import os
import sys
import json
from flask import Flask, request, jsonify, send_from_directory, stream_with_context, Response
import threading
import queue

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

# Load meta (best-effort)
try:
    with open(META_PATH, 'r', encoding='utf-8') as mf:
        META = json.load(mf)
except Exception:
    META = {}

app = Flask(__name__, static_folder='static', static_url_path='')

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    db = request.args.get('db', DB_PATH)
    meta_path = request.args.get('meta', META_PATH)
    # load meta if different
    meta_local = META
    if meta_path != META_PATH:
        try:
            with open(meta_path, 'r', encoding='utf-8') as mf:
                meta_local = json.load(mf)
        except Exception:
            meta_local = META
    conn = distance.open_db(db)
    try:
        results = distance.get_system_by_query_prefix(conn, q, meta_local, limit=20)
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
    db = body.get('db', DB_PATH)
    meta_path = body.get('meta', META_PATH)
    max_hop = float(body.get('max_hop', 40.0))
    bucket_size = float(body.get('bucket_size', BUCKET_SIZE_DEFAULT))
    step_threshold = float(body.get('step_threshold', 1.0))
    step_expand_factor = float(body.get('step_expand_factor', 2.0))

    # load meta
    meta_local = META
    if meta_path != META_PATH:
        try:
            with open(meta_path, 'r', encoding='utf-8') as mf:
                meta_local = json.load(mf)
        except Exception:
            meta_local = META

    conn = distance.open_db(db)
    try:
        s_list = distance.get_system_by_query_prefix(conn, source_q, meta_local, limit=10)
        t_list = distance.get_system_by_query_prefix(conn, target_q, meta_local, limit=10)
        if not s_list:
            return jsonify({'error': f'source not found: {source_q}'}), 404
        if not t_list:
            return jsonify({'error': f'target not found: {target_q}'}), 404
        # choose first match for now
        s = s_list[0]
        t = t_list[0]
        # silent progress callback for the HTTP API (no streaming)
        def noop_progress(msg: str):
            return
        path = distance.find_path_directional(conn, s, t, max_hop, bucket_size, meta_local, step_threshold=step_threshold, expand_factor=step_expand_factor, on_progress=noop_progress)
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
        return jsonify({'path': out, 'total': round(total, 1)})
    finally:
        conn.close()


@app.route('/api/path/stream')
def api_path_stream():
    # stream path progress using Server-Sent Events (SSE). Accepts query params: source, target, max_hop, bucket_size
    source_q = request.args.get('source')
    target_q = request.args.get('target')
    if not source_q or not target_q:
        return jsonify({'error': 'source and target required'}), 400
    db = request.args.get('db', DB_PATH)
    meta_path = request.args.get('meta', META_PATH)
    max_hop = float(request.args.get('max_hop', 40.0))
    bucket_size = float(request.args.get('bucket_size', BUCKET_SIZE_DEFAULT))
    step_threshold = float(request.args.get('step_threshold', 1.0))
    step_expand_factor = float(request.args.get('step_expand_factor', 2.0))

    # load meta
    meta_local = META
    if meta_path != META_PATH:
        try:
            with open(meta_path, 'r', encoding='utf-8') as mf:
                meta_local = json.load(mf)
        except Exception:
            meta_local = META

    progress_q = queue.Queue()
    result_q = queue.Queue()

    class Writer:
        def write(self, s):
            if s is None:
                return
            try:
                progress_q.put(s)
            except Exception:
                pass
        def flush(self):
            pass

    def worker():
        # open DB in this thread
        conn = distance.open_db(db)
        try:
            s_list = distance.get_system_by_query_prefix(conn, source_q, meta_local, limit=10)
            t_list = distance.get_system_by_query_prefix(conn, target_q, meta_local, limit=10)
            if not s_list or not t_list:
                result_q.put({'error': 'source or target not found'})
                return
            s = s_list[0]; t = t_list[0]

            # define on_progress callback that pushes to progress_q (non-blocking, drop if full)
            def on_progress(msg: str):
                try:
                    # normalize newline-only
                    if msg == '\n' or (isinstance(msg, str) and msg.endswith('\n')):
                        progress_q.put_nowait(msg.strip())
                    else:
                        progress_q.put_nowait(str(msg))
                except Exception:
                    # drop if queue is full or other errors
                    pass

            try:
                path = distance.find_path_directional(conn, s, t, max_hop, bucket_size, meta_local, step_threshold=step_threshold, expand_factor=step_expand_factor, on_progress=on_progress)
            except Exception as e:
                result_q.put({'error': str(e)})
                return
            if path is None:
                result_q.put({'error': 'No path found'})
                return
            # compute path output
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
            result_q.put({'path': out, 'total': round(total, 1)})
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
    app.run(host='0.0.0.0', port=port, debug=True)
