import os
import sys
import json
from flask import Flask, request, jsonify, send_from_directory, stream_with_context, Response
import threading
import queue
import sqlite3

# Ensure scripts dir is importable so we can reuse logic without modifying it
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SCRIPTS = os.path.join(ROOT, 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import distance_cli_sqlite_prefix as distance

# Config via env or fall back to defaults in the imported module
DB_PATH = os.environ.get('PLOTTER_DB', distance.DEFAULT_DB)
META_PATH = os.environ.get('PLOTTER_META', distance.DEFAULT_META)
BUCKET_SIZE_DEFAULT = 50.0

# Load meta and pre-build lookup maps
try:
    with open(META_PATH, 'r', encoding='utf-8') as mf:
        META = json.load(mf)
    ID_TO_PREFIX = {int(k): v for k, v in META.get('prefixes', {}).items()}
    ID_TO_STAR = {int(k): v for k, v in META.get('starTypes', {}).items()}
except Exception:
    META = {}
    ID_TO_PREFIX = {}
    ID_TO_STAR = {}

def get_db_params(conn: sqlite3.Connection):
    """Load coord_scale and bucket_size from db_meta table."""
    try:
        coord_scale = int(conn.execute('SELECT value FROM db_meta WHERE key="coord_scale"').fetchone()[0])
        bucket_size = float(conn.execute('SELECT value FROM db_meta WHERE key="bucket_size"').fetchone()[0])
        return coord_scale, bucket_size
    except Exception:
        # Fallback for old/uninitialized DBs
        return 1, BUCKET_SIZE_DEFAULT

app = Flask(__name__, static_folder='static', static_url_path='')

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    db = DB_PATH
    conn = distance.open_db(db)
    try:
        coord_scale, _ = get_db_params(conn)
        results = distance.get_system_by_query_prefix(conn, q, META, ID_TO_PREFIX, ID_TO_STAR, coord_scale, limit=20)
    finally:
        conn.close()
    return jsonify(results)

@app.route('/api/path', methods=['POST'])
def api_path():
    body = request.get_json() or {}
    source_q = body.get('source')
    target_q = body.get('target')
    if not source_q or not target_q:
        return jsonify({'error': 'source and target required'}), 400
    db = DB_PATH
    max_hop = float(body.get('max_hop', 40.0))

    conn = distance.open_db(db)
    try:
        coord_scale, _ = get_db_params(conn)
        s_list = distance.get_system_by_query_prefix(conn, source_q, META, ID_TO_PREFIX, ID_TO_STAR, coord_scale, limit=10)
        t_list = distance.get_system_by_query_prefix(conn, target_q, META, ID_TO_PREFIX, ID_TO_STAR, coord_scale, limit=10)
        if not s_list:
            return jsonify({'error': f'source not found: {source_q}'}), 404
        if not t_list:
            return jsonify({'error': f'target not found: {target_q}'}), 404
        s = s_list[0]
        t = t_list[0]
        def noop_progress(msg: str):
            return
        # find_path_directional now takes coord_scale, ID_TO_PREFIX, ID_TO_STAR instead of meta, bucket_size
        path = distance.find_path_robust(conn, s, t, max_hop, coord_scale, ID_TO_PREFIX, ID_TO_STAR, on_progress=noop_progress)
        if path is None:
            return jsonify({'error': 'No path found'}), 404
        # compute hop distances and total
        total = 0.0
        out = []
        prev = None
        for p in path:
            coords = p.get('coords', {})
            hop_dist = 0.0
            if prev is not None:
                dx = coords['x'] - prev['x']
                dy = coords['y'] - prev['y']
                dz = coords['z'] - prev['z']
                hop_dist = (dx*dx + dy*dy + dz*dz) ** 0.5
                total += hop_dist
            out.append({
                'id64': p.get('id64'),
                'name': p.get('name'),
                'coords': coords,
                'mainStar': p.get('mainStar'),
                'hop_dist': round(hop_dist, 1)
            })
            prev = coords

        # Efficiency metrics
        s_coords = s['coords']
        t_coords = t['coords']
        direct_dist = ((t_coords['x']-s_coords['x'])**2 + (t_coords['y']-s_coords['y'])**2 + (t_coords['z']-s_coords['z'])**2) ** 0.5
        diff_pct = ((total / direct_dist) - 1) * 100 if direct_dist > 0 else 0
        
        return jsonify({
            'path': out, 
            'total': round(total, 1), 
            'direct': round(direct_dist, 1),
            'diff_pct': round(diff_pct, 1)
        })
    finally:
        conn.close()


@app.route('/api/path/stream')
def api_path_stream():
    source_q = request.args.get('source')
    target_q = request.args.get('target')
    if not source_q or not target_q:
        return jsonify({'error': 'source and target required'}), 400
    db = DB_PATH
    max_hop = float(request.args.get('max_hop', 40.0))

    progress_q = queue.Queue(maxsize=256)
    result_q = queue.Queue(maxsize=2)

    def worker():
        conn = distance.open_db(db)
        try:
            coord_scale, _ = get_db_params(conn)
            s_list = distance.get_system_by_query_prefix(conn, source_q, META, ID_TO_PREFIX, ID_TO_STAR, coord_scale, limit=10)
            t_list = distance.get_system_by_query_prefix(conn, target_q, META, ID_TO_PREFIX, ID_TO_STAR, coord_scale, limit=10)
            if not s_list or not t_list:
                result_q.put({'error': 'source or target not found'})
                return
            s = s_list[0]; t = t_list[0]

            def on_progress(msg: str):
                try:
                    text = '\n'.join(str(msg).splitlines())
                    progress_q.put_nowait(text)
                except Exception:
                    pass

            try:
                path = distance.find_path_robust(conn, s, t, max_hop, coord_scale, ID_TO_PREFIX, ID_TO_STAR, on_progress=on_progress)
            except Exception as e:
                result_q.put({'error': str(e)})
                return
            if path is None:
                result_q.put({'error': 'No path found'})
                return
            total = 0.0
            out = []
            prev = None
            for p in path:
                coords = p.get('coords', {})
                hop_dist = 0.0
                if prev is not None:
                    dx = coords['x'] - prev['x']
                    dy = coords['y'] - prev['y']
                    dz = coords['z'] - prev['z']
                    hop_dist = (dx*dx + dy*dy + dz*dz) ** 0.5
                    total += hop_dist
                out.append({
                    'id64': p.get('id64'),
                    'name': p.get('name'),
                    'coords': coords,
                    'mainStar': p.get('mainStar'),
                    'hop_dist': round(hop_dist, 1)
                })
                prev = coords
            
            # Efficiency metrics
            s_coords = s['coords']
            t_coords = t['coords']
            direct_dist = ((t_coords['x']-s_coords['x'])**2 + (t_coords['y']-s_coords['y'])**2 + (t_coords['z']-s_coords['z'])**2) ** 0.5
            diff_pct = ((total / direct_dist) - 1) * 100 if direct_dist > 0 else 0

            result_q.put({
                'path': out, 
                'total': round(total, 1),
                'direct': round(direct_dist, 1),
                'diff_pct': round(diff_pct, 1)
            })
        except Exception as e:
            result_q.put({'error': str(e)})
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
                line = item.strip().replace('\r','')
                if not line:
                    continue
                yield "event: progress\n"
                # escape data lines
                for chunk in line.split('\n'):
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
            yield "data: {\"error\": \"No result\"}\n\n"

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')

# Serve other static assets
@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory(app.static_folder, path)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
