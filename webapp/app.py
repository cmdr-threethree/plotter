import os
import sys
import json
from flask import Flask, request, jsonify, send_from_directory

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
        path = distance.find_path_directional(conn, s, t, max_hop, bucket_size, meta_local, step_threshold=step_threshold, expand_factor=step_expand_factor)
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

# Serve other static assets
@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory(app.static_folder, path)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
