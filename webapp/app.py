import os
import sys
import json
import logging
from functools import lru_cache
from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    stream_with_context,
    Response,
)
import threading
import queue
import sqlite3

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure scripts dir is importable so we can reuse logic without modifying it
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import distance_cli_sqlite_prefix as distance

# Config via env or fall back to defaults in the imported module
DB_PATH = os.environ.get("PLOTTER_DB", distance.DEFAULT_DB)
DB_IMMUTABLE = os.environ.get("PLOTTER_DB_IMMUTABLE", "false").lower() == "true"
BUCKET_SIZE_DEFAULT = 50.0


def get_db_conn(check_same_thread=True):
    return distance.open_db(DB_PATH, immutable=DB_IMMUTABLE, check_same_thread=check_same_thread)


def get_db_params(conn: sqlite3.Connection):
    """Load coord_scale and bucket_size from db_meta table."""
    try:
        coord_scale = int(
            conn.execute(
                'SELECT value FROM db_meta WHERE key="coord_scale"'
            ).fetchone()[0]
        )
        bucket_size = float(
            conn.execute(
                'SELECT value FROM db_meta WHERE key="bucket_size"'
            ).fetchone()[0]
        )
        return coord_scale, bucket_size
    except Exception:
        # Fallback for old/uninitialized DBs
        return 1, BUCKET_SIZE_DEFAULT


# Load meta and pre-build lookup maps from DB
try:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    # Persistent global connection for fast queries (search, nearest)
    # Using check_same_thread=False because Flask is multi-threaded
    DB_CONN = get_db_conn(check_same_thread=False)

    META = distance.load_meta_from_db(DB_CONN)
    # We ONLY keep starTypes in memory as they are few. Prefixes are resolved on-demand.
    ID_TO_STAR = {int(k): v for k, v in META.get("starTypes", {}).items()}
    STAR_NAME_TO_ID = {v: k for k, v in ID_TO_STAR.items()}

    COORD_SCALE, BUCKET_SIZE = get_db_params(DB_CONN)

    if not ID_TO_STAR:
        raise ValueError(f"No star types found in database: {DB_PATH}")
except Exception as e:
    logger.error(f"FATAL: Error loading metadata from {DB_PATH}: {e}")
    sys.exit(1)


@lru_cache(maxsize=1000)
def get_cached_search(q, limit=20):
    """Cached wrapper for system search."""
    return distance.get_system_by_query_prefix(
        DB_CONN, q, coord_scale=COORD_SCALE, limit=limit
    )


app = Flask(__name__, static_folder="static", static_url_path="")

# If running under Gunicorn, bridge logs
if "gunicorn" in os.environ.get("SERVER_SOFTWARE", ""):
    gunicorn_logger = logging.getLogger("gunicorn.error")
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    # Also redirect the module logger
    logger.handlers = gunicorn_logger.handlers
    logger.setLevel(gunicorn_logger.level)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    # Use cached search with global connection
    results = get_cached_search(q, limit=20)
    return jsonify(results)


@app.route("/api/nearest")
def api_nearest():
    near_q = request.args.get("near", "").strip()
    types_q = request.args.get("types", "").strip()
    if not near_q:
        return jsonify({"error": "near required"}), 400

    # 1. Resolve near point
    near_coords = None
    exclude_id64 = None
    if "," in near_q:
        parts = near_q.split(",")
        if len(parts) == 3:
            try:
                near_coords = {
                    "x": float(parts[0]),
                    "y": float(parts[1]),
                    "z": float(parts[2]),
                }
            except ValueError:
                pass

    if not near_coords:
        cands = get_cached_search(near_q, limit=1)
        if cands:
            near_coords = cands[0]["coords"]
            exclude_id64 = cands[0]["id64"]

    if not near_coords:
        return (
            jsonify({"error": f"could not resolve reference point: {near_q}"}),
            404,
        )

    # 2. Resolve star type ids
    type_ids = None
    if types_q:
        type_parts = [t.strip() for t in types_q.split(",") if t.strip()]
        type_ids = [STAR_NAME_TO_ID.get(t) for t in type_parts if t in STAR_NAME_TO_ID]
        if not type_ids:
            return (
                jsonify({"error": f"no matching star types found for: {types_q}"}),
                400,
            )

    # 3. Search using global connection
    res = distance.nearest_of_type(
        DB_CONN, near_coords, type_ids, COORD_SCALE, exclude_id64=exclude_id64
    )
    if not res:
        return jsonify({"error": "no matching systems found"}), 404

    return jsonify(res)


@app.route("/api/path", methods=["POST"])
def api_path():
    body = request.get_json() or {}
    source_q = body.get("source")
    target_q = body.get("target")
    if not source_q or not target_q:
        return jsonify({"error": "source and target required"}), 400
    max_hop = float(body.get("max_hop", 40.0))

    s_list = get_cached_search(source_q, limit=1)
    t_list = get_cached_search(target_q, limit=1)
    if not s_list:
        return jsonify({"error": f"source not found: {source_q}"}), 404
    if not t_list:
        return jsonify({"error": f"target not found: {target_q}"}), 404
    s = s_list[0]
    t = t_list[0]

    def noop_progress(msg: str):
        return

    # Use global connection for pathfinding
    path = distance.find_path_robust(
        DB_CONN,
        s,
        t,
        max_hop,
        COORD_SCALE,
        on_progress=noop_progress,
    )
    if path is None:
        return jsonify({"error": "No path found"}), 404

    # compute hop distances and total
    total = 0.0
    out = []
    prev = None
    for p in path:
        coords = p.get("coords", {})
        hop_dist = 0.0
        if prev is not None:
            dx = coords["x"] - prev["x"]
            dy = coords["y"] - prev["y"]
            dz = coords["z"] - prev["z"]
            hop_dist = (dx * dx + dy * dy + dz * dz) ** 0.5
            total += hop_dist
        out.append(
            {
                "id64": p.get("id64"),
                "name": p.get("name"),
                "coords": coords,
                "mainStar": p.get("mainStar"),
                "hop_dist": round(hop_dist, 1),
                "needs_permit": p.get("needs_permit", False),
            }
        )
        prev = coords

    # Efficiency metrics
    s_coords = s["coords"]
    t_coords = t["coords"]
    direct_dist = (
        (t_coords["x"] - s_coords["x"]) ** 2
        + (t_coords["y"] - s_coords["y"]) ** 2
        + (t_coords["z"] - s_coords["z"]) ** 2
    ) ** 0.5
    diff_pct = ((total / direct_dist) - 1) * 100 if direct_dist > 0 else 0

    return jsonify(
        {
            "path": out,
            "total": round(total, 1),
            "direct": round(direct_dist, 1),
            "diff_pct": round(diff_pct, 1),
        }
    )


@app.route("/api/path/stream")
def api_path_stream():
    source_q = request.args.get("source")
    target_q = request.args.get("target")
    if not source_q or not target_q:
        return jsonify({"error": "source and target required"}), 400
    max_hop = float(request.args.get("max_hop", 40.0))
    neutron_highway = request.args.get("neutron_highway", "false").lower() == "true"

    progress_q = queue.Queue(maxsize=256)
    result_q = queue.Queue(maxsize=2)

    def worker():
        # Worker thread uses its OWN connection for long-running task
        conn = get_db_conn()
        try:
            s_list = distance.get_system_by_query_prefix(
                conn, source_q, coord_scale=COORD_SCALE, limit=1
            )
            t_list = distance.get_system_by_query_prefix(
                conn, target_q, coord_scale=COORD_SCALE, limit=1
            )
            if not s_list or not t_list:
                result_q.put({"error": "source or target not found"})
                return
            s = s_list[0]
            t = t_list[0]

            def on_progress(msg: str):
                try:
                    text = "\n".join(str(msg).splitlines())
                    progress_q.put_nowait(text)
                except Exception:
                    pass

            try:
                if neutron_highway:
                    path = distance.find_path_neutron_highway(
                        conn,
                        s,
                        t,
                        max_hop,
                        COORD_SCALE,
                        on_progress=on_progress,
                    )
                else:
                    path = distance.find_path_robust(
                        conn,
                        s,
                        t,
                        max_hop,
                        COORD_SCALE,
                        on_progress=on_progress,
                    )
            except Exception as e:
                result_q.put({"error": str(e)})
                return
            if path is None:
                result_q.put({"error": "No path found"})
                return
            total = 0.0
            out = []
            prev = None
            for p in path:
                coords = p.get("coords", {})
                hop_dist = 0.0
                if prev is not None:
                    dx = coords["x"] - prev["x"]
                    dy = coords["y"] - prev["y"]
                    dz = coords["z"] - prev["z"]
                    hop_dist = (dx * dx + dy * dy + dz * dz) ** 0.5
                    total += hop_dist
                out.append(
                    {
                        "id64": p.get("id64"),
                        "name": p.get("name"),
                        "coords": coords,
                        "mainStar": p.get("mainStar"),
                        "hop_dist": round(hop_dist, 1),
                        "needs_permit": p.get("needs_permit", False),
                    }
                )
                prev = coords

            # Efficiency metrics
            s_coords = s["coords"]
            t_coords = t["coords"]
            direct_dist = (
                (t_coords["x"] - s_coords["x"]) ** 2
                + (t_coords["y"] - s_coords["y"]) ** 2
                + (t_coords["z"] - s_coords["z"]) ** 2
            ) ** 0.5
            diff_pct = ((total / direct_dist) - 1) * 100 if direct_dist > 0 else 0

            result_q.put(
                {
                    "path": out,
                    "total": round(total, 1),
                    "direct": round(direct_dist, 1),
                    "diff_pct": round(diff_pct, 1),
                }
            )
        except Exception as e:
            result_q.put({"error": str(e)})
        finally:
            try:
                conn.close()
            except Exception:
                pass

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def event_stream():
        # stream progress lines and finally the result as a JSON payload
        while thread.is_alive() or not progress_q.empty() or not result_q.empty():
            try:
                item = progress_q.get(timeout=0.2)
                # send as progress event
                # ensure single-line
                line = item.strip().replace("\r", "")
                if not line:
                    continue
                yield "event: progress\n"
                # escape data lines
                for chunk in line.split("\n"):
                    yield f"data: {chunk}\n"
                yield "\n"
            except queue.Empty:
                # check for result
                try:
                    res = result_q.get_nowait()
                except queue.Empty:
                    continue
                # send final result event
                import json as _json

                yield "event: result\n"
                yield f"data: {_json.dumps(res)}\n\n"
                return
        # if we exit loop without result, send error
        if not result_q.qsize():
            yield "event: result\n"
            yield 'data: {"error": "No result"}\n\n'

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")


# Serve other static assets
@app.route("/<path:path>")
def static_proxy(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
