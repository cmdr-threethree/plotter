#!/usr/bin/env python3
"""
SQLite-backed distance/path tool with prefix compression and stdin input support.

Features:
- build-meta: scan systems (from file or stdin) and systems.schema.json to produce a meta JSON with:
    {"prefixes": {"0": "" , "1": "Sol", ...}, "starTypes": {"0":"", "1":"G (White-Yellow) Star", ...}}
  Prefix extraction rule: if name contains '-' use everything up to the first dash, otherwise use everything up to the first space; if neither, the whole name. Reserve id 0 for empty prefix.
- build-index: read systems from file or stdin, skip systems needing a permit, and store prefix_id and star_type_id (integers) along with coordinates and bucket coords. Index is resumable (INSERT OR IGNORE) and shows progress.
- query/pathfinding: loads the meta JSON to display prefix labels and star types. Pathfinding uses bucketed neighbor queries that only load nearby rows from sqlite.

I/O: pass --file - to read systems from stdin (useful with compressed files, e.g. zcat systems_neutron.json.gz | python ... --file - --build-index ...)

Usage examples:
  # generate meta from file:
  python3 scripts/distance_cli_sqlite_prefix.py --build-meta --file systems_neutron.json --meta-file systems_meta.json

  # or from stdin (compressed):
  zcat systems_neutron.json.gz | python3 scripts/distance_cli_sqlite_prefix.py --build-meta --file - --meta-file systems_meta.json

  # build index using stdin and meta
  zcat systems_neutron.json.gz | python3 scripts/distance_cli_sqlite_prefix.py --build-index --use-prefix --meta-file systems_meta.json --db systems_index.db --bucket-size 50 --file -

  # query
  python3 scripts/distance_cli_sqlite_prefix.py --db systems_index.db --meta-file systems_meta.json --use-prefix --max-hop 40

"""

import argparse
import json
import math
import os
import sqlite3
import sys
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

DEFAULT_JSON = "systems_neutron.json"
DEFAULT_DB = "systems_index.db"
DEFAULT_META = "systems_meta.json"

BATCH_SIZE = 1000
PROGRESS_INTERVAL = 5000


def clean_json_line(line: str) -> Optional[str]:
    s = line.strip()
    if not s or s in ("[", "]"):
        return None
    if s.endswith(','):
        s = s[:-1]
    if not s.startswith('{'):
        return None
    return s


def parse_line_object(line: str) -> Optional[Dict]:
    s = clean_json_line(line)
    if s is None:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def iter_lines_from_source(path: str):
    """Yield lines from path or stdin if path == '-'."""
    if path == '-' or path is None:
        for line in sys.stdin:
            yield line
    else:
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                yield line


def extract_prefix(name: str) -> str:
    # If name contains a dash, use everything up to the first dash
    if '-' in name:
        return name.split('-', 1)[0]
    if ' ' in name:
        return name.split(' ', 1)[0]
    return name


def build_meta(json_path: str, schema_path: str, out_path: str) -> None:
    if json_path != '-' and not os.path.exists(json_path):
        print(f"JSON file not found: {json_path}")
        sys.exit(1)

    prefixes_counter = Counter()
    total = 0
    for line in iter_lines_from_source(json_path):
        total += 1
        if '{' not in line:
            continue
        obj = parse_line_object(line)
        if obj is None:
            continue
        name = obj.get('name')
        if not name:
            continue
        prefix = extract_prefix(name)
        prefixes_counter[prefix] += 1

    prefixes = [p for p, _ in prefixes_counter.most_common()]
    prefix_map = {p: i+1 for i, p in enumerate(prefixes)}
    inv_prefix_map = {str(i+1): p for p, i in prefix_map.items()}
    inv_prefix_map['0'] = ''

    # extract star types from schema file if present
    star_types: List[str] = []
    if os.path.exists(schema_path):
        try:
            with open(schema_path, 'r', encoding='utf-8') as sf:
                schema = json.load(sf)
                enum = None
                if isinstance(schema, dict):
                    items = schema.get('items')
                    if isinstance(items, dict):
                        props = items.get('properties')
                        if isinstance(props, dict):
                            mainStar = props.get('mainStar')
                            if isinstance(mainStar, dict):
                                enum = mainStar.get('enum')
                if isinstance(enum, list):
                    star_types = enum
        except Exception:
            star_types = []
    star_map = {s: i+1 for i, s in enumerate(star_types)}
    inv_star_map = {str(i+1): s for s, i in star_map.items()}
    inv_star_map['0'] = ''

    meta = {'prefixes': inv_prefix_map, 'starTypes': inv_star_map}
    with open(out_path, 'w', encoding='utf-8') as out:
        json.dump(meta, out, indent=2, ensure_ascii=False)
    print(f"Meta written to {out_path}. Prefixes: {len(inv_prefix_map)-1}, starTypes: {len(inv_star_map)-1}")


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=OFF;')
    conn.execute('PRAGMA temp_store=MEMORY;')
    return conn


def ensure_schema_prefix(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS systems (
            id64 INTEGER PRIMARY KEY,
            prefix_id INTEGER,
            x REAL,
            y REAL,
            z REAL,
            star_type_id INTEGER,
            bx INTEGER,
            by INTEGER,
            bz INTEGER
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_buckets ON systems(bx,by,bz)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_prefix ON systems(prefix_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_star_type ON systems(star_type_id)')
    conn.commit()


def build_index_prefix(json_path: str, db_path: str, bucket_size: float, meta_path: str, force: bool = False) -> None:
    if json_path != '-' and not os.path.exists(json_path):
        print(f"JSON file not found: {json_path}")
        sys.exit(1)
    if not os.path.exists(meta_path):
        print(f"Meta file not found: {meta_path}. Run --build-meta first.")
        sys.exit(1)
    if force and os.path.exists(db_path):
        print(f"--force given: removing existing DB {db_path}")
        os.remove(db_path)

    with open(meta_path, 'r', encoding='utf-8') as mf:
        meta = json.load(mf)
    prefixes = meta.get('prefixes', {})
    prefix_to_id = {v: int(k) for k, v in prefixes.items()}
    starTypes = meta.get('starTypes', {})
    star_to_id = {v: int(k) for k, v in starTypes.items()}

    conn = open_db(db_path)
    ensure_schema_prefix(conn)
    cur = conn.cursor()

    def bucket_coords(x: float, y: float, z: float) -> Tuple[int,int,int]:
        return (math.floor(x / bucket_size), math.floor(y / bucket_size), math.floor(z / bucket_size))

    insert_sql = 'INSERT OR IGNORE INTO systems (id64,prefix_id,x,y,z,star_type_id,bx,by,bz) VALUES (?,?,?,?,?,?,?,?,?)'
    batch: List[Tuple] = []
    inserted = 0
    processed = 0

    print('Starting prefix-compressed index build (resumable). Systems requiring permits are skipped.')
    for line in iter_lines_from_source(json_path):
        processed += 1
        if processed % PROGRESS_INTERVAL == 0:
            print(f"Processed {processed} lines, inserted {inserted} rows...", end='\r', flush=True)
        if '{' not in line:
            continue
        obj = parse_line_object(line)
        if obj is None:
            continue
        # Skip systems that require a permit
        if obj.get('needsPermit'):
            continue
        try:
            sid = int(obj['id64'])
            name = obj.get('name')
            coords = obj.get('coords')
            main_star = obj.get('mainStar')
            if name is None or coords is None:
                continue
            prefix = extract_prefix(name)
            prefix_id = prefix_to_id.get(prefix, 0)
            star_id = star_to_id.get(main_star, 0)
            x = float(coords['x']); y = float(coords['y']); z = float(coords['z'])
            bx,by,bz = bucket_coords(x,y,z)
            batch.append((sid, prefix_id, x, y, z, star_id, bx, by, bz))
        except Exception:
            continue
        if len(batch) >= BATCH_SIZE:
            cur.executemany(insert_sql, batch)
            conn.commit()
            inserted += len(batch)
            batch.clear()
    if batch:
        cur.executemany(insert_sql, batch)
        conn.commit()
        inserted += len(batch)
        batch.clear()

    cur.execute('ANALYZE;')
    conn.commit()
    conn.close()
    print(f"\nPrefix-compressed index build complete. Processed {processed} lines; inserted {inserted} rows into {db_path}.")


def get_system_by_query_prefix(conn: sqlite3.Connection, query: str, meta: Dict, limit: int = 10) -> List[Dict]:
    prefixes = meta.get('prefixes', {})
    id_to_prefix = {int(k): v for k,v in prefixes.items()}
    try:
        q_int = int(query)
        cur = conn.execute('SELECT id64,prefix_id,x,y,z,star_type_id FROM systems WHERE id64=?', (q_int,))
        row = cur.fetchone()
        return ([{'id64': row[0], 'name': id_to_prefix.get(row[1], '') + ' ...', 'coords': {'x': row[2],'y': row[3],'z': row[4]}, 'starTypeId': row[5]}] if row else [])
    except Exception:
        matched_prefix_ids = [int(k) for k,v in prefixes.items() if query.lower() in v.lower()]
        if not matched_prefix_ids:
            return []
        placeholders = ','.join('?' for _ in matched_prefix_ids)
        sql = f'SELECT id64,prefix_id,x,y,z,star_type_id FROM systems WHERE prefix_id IN ({placeholders}) LIMIT ?'
        cur = conn.execute(sql, (*matched_prefix_ids, limit))
        out = []
        for r in cur:
            out.append({'id64': r[0], 'name': id_to_prefix.get(r[1], '') + ' ...', 'coords': {'x': r[2],'y': r[3],'z': r[4]}, 'starTypeId': r[5]})
        return out


def neighbors_for_center_prefix(conn: sqlite3.Connection, center: Dict, max_distance: float, visited: Set[int], bucket_size: float, max_neighbors: int = 500, meta: Optional[Dict] = None) -> List[Dict]:
    bx = math.floor(center['coords']['x'] / bucket_size)
    by = math.floor(center['coords']['y'] / bucket_size)
    bz = math.floor(center['coords']['z'] / bucket_size)
    rb = int(math.ceil(max_distance / bucket_size))

    min_bx, max_bx = bx - rb, bx + rb
    min_by, max_by = by - rb, by + rb
    min_bz, max_bz = bz - rb, bz + rb

    sql = '''SELECT id64,prefix_id,x,y,z,star_type_id FROM systems
             WHERE bx BETWEEN ? AND ? AND by BETWEEN ? AND ? AND bz BETWEEN ? AND ?'''
    cur = conn.execute(sql, (min_bx, max_bx, min_by, max_by, min_bz, max_bz))

    max_d2 = max_distance * max_distance
    out: List[Tuple[float, Dict]] = []
    prefixes = meta.get('prefixes', {}) if meta else {}
    id_to_prefix = {int(k): v for k,v in prefixes.items()}
    star_types = meta.get('starTypes', {}) if meta else {}
    id_to_star = {int(k): v for k,v in star_types.items()}

    for r in cur:
        sid = r[0]
        if sid == center['id64'] or sid in visited:
            continue
        x,y,z = r[2], r[3], r[4]
        dx = x - center['coords']['x']
        dy = y - center['coords']['y']
        dz = z - center['coords']['z']
        d2 = dx*dx + dy*dy + dz*dz
        if d2 <= max_d2:
            name = id_to_prefix.get(r[1], '') + ' ...'
            star = id_to_star.get(r[5], '')
            out.append((d2, {'id64': sid, 'name': name, 'coords': {'x': x,'y': y,'z': z}, 'mainStar': star}))
    out.sort(key=lambda t: t[0])
    return [t[1] for t in out[:max_neighbors]]


def find_path_bfs_db_prefix(conn: sqlite3.Connection, source: Dict, target: Dict, max_hop: float, bucket_size: float, meta: Dict, max_nodes: int = 5000, max_neighbors: int = 500) -> Optional[List[Dict]]:
    from collections import deque
    src = source['id64']; tgt = target['id64']
    if src == tgt:
        return [source]
    visited: Set[int] = set([src])
    parent: Dict[int, int] = {}
    node_map: Dict[int, Dict] = {src: source}
    q = deque([src])
    nodes_examined = 0

    while q:
        cid = q.popleft()
        nodes_examined += 1
        if nodes_examined > max_nodes:
            print(f"Reached max nodes ({max_nodes})")
            return None
        center = node_map[cid]
        neighbors = neighbors_for_center_prefix(conn, center, max_hop, visited, bucket_size, max_neighbors=max_neighbors, meta=meta)
        for n in neighbors:
            nid = n['id64']
            if nid in visited:
                continue
            visited.add(nid)
            parent[nid] = cid
            node_map[nid] = n
            if nid == tgt:
                path_ids = [tgt]
                while path_ids[-1] != src:
                    path_ids.append(parent[path_ids[-1]])
                path_ids.reverse()
                return [node_map[i] for i in path_ids]
            q.append(nid)
    return None


def choose_candidate_list(lst: List[Dict], which: str) -> Optional[Dict]:
    if not lst:
        print(f"No matches for {which}")
        return None
    if len(lst) == 1:
        s = lst[0]
        print(f"Selected: {s['name']} (id64={s['id64']}) coords={s['coords']} mainStar={s.get('mainStar')}")
        return s
    print(f"Multiple matches for {which}:")
    for i, s in enumerate(lst, start=1):
        c = s['coords']
        print(f" {i}) {s['name']} id64={s['id64']} coords=({c['x']},{c['y']},{c['z']}) mainStar={s.get('mainStar')}")
    while True:
        choice = input(f"Choose [1-{len(lst)}] or 0 to cancel: ")
        if not choice.isdigit():
            print("Enter a number")
            continue
        v = int(choice)
        if v == 0:
            return None
        if 1 <= v <= len(lst):
            return lst[v-1]
        print("Out of range")


def main():
    parser = argparse.ArgumentParser(description='SQLite-backed distance/path tool with optional prefix compression')
    parser.add_argument('--file', '-f', default=DEFAULT_JSON)
    parser.add_argument('--db', default=DEFAULT_DB)
    parser.add_argument('--meta-file', default=DEFAULT_META)
    parser.add_argument('--bucket-size', type=float, default=50.0)
    parser.add_argument('--build-meta', action='store_true')
    parser.add_argument('--build-index', action='store_true')
    parser.add_argument('--use-prefix', action='store_true', help='Store prefix_id (integer) and star_type_id instead of full name')
    parser.add_argument('--force', action='store_true', help='Force rebuild index from scratch')
    parser.add_argument('--max-hop', type=float, help='If provided, find path where each hop <= this')
    parser.add_argument('--max-nodes', type=int, default=5000)
    parser.add_argument('--max-neighbors', type=int, default=500)
    args = parser.parse_args()

    if args.build_meta:
        # attempt to use local schema file
        schema_path = os.path.join(os.path.dirname(__file__), '..', 'systems.schema.json') if os.path.exists(os.path.join(os.path.dirname(__file__), '..', 'systems.schema.json')) else 'systems.schema.json'
        build_meta(args.file, schema_path, args.meta_file)
        return

    if args.build_index:
        if args.use_prefix:
            build_index_prefix(args.file, args.db, args.bucket_size, args.meta_file, force=args.force)
        else:
            print('Non-prefix DB build not implemented in this script. Use distance_cli_sqlite.py for that mode.')
        return

    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}. Run --build-index first.")
        sys.exit(1)
    if args.use_prefix and not os.path.exists(args.meta_file):
        print(f"Meta file {args.meta_file} not found; required when --use-prefix")
        sys.exit(1)

    meta = None
    if args.use_prefix:
        with open(args.meta_file, 'r', encoding='utf-8') as mf:
            meta = json.load(mf)

    conn = open_db(args.db)

    # interactive prompts
    q1 = input('Enter first system name or id64: ').strip()
    if args.use_prefix:
        cand1 = get_system_by_query_prefix(conn, q1, meta)
    else:
        print('Only --use-prefix query supported in this tool')
        return
    s1 = choose_candidate_list(cand1, 'first')
    if s1 is None:
        print('Cancelled')
        return

    q2 = input('Enter second system name or id64: ').strip()
    cand2 = get_system_by_query_prefix(conn, q2, meta)
    s2 = choose_candidate_list(cand2, 'second')
    if s2 is None:
        print('Cancelled')
        return

    dx = s1['coords']['x'] - s2['coords']['x']
    dy = s1['coords']['y'] - s2['coords']['y']
    dz = s1['coords']['z'] - s2['coords']['z']
    direct = math.sqrt(dx*dx + dy*dy + dz*dz)
    print(f"Direct distance: {direct:.6f}")
    if args.max_hop is None:
        return
    if direct <= args.max_hop:
        print('Within max hop; direct')
        return

    print('Searching for path...')
    path = find_path_bfs_db_prefix(conn, s1, s2, args.max_hop, args.bucket_size, meta, max_nodes=args.max_nodes, max_neighbors=args.max_neighbors)
    if path is None:
        print('No path found')
        return
    print('Path:')
    for i,p in enumerate(path, start=1):
        c = p['coords']
        print(f" {i}) {p['name']} id64={p['id64']} coords=({c['x']},{c['y']},{c['z']}) mainStar={p.get('mainStar')}")
    print('Done')

if __name__ == '__main__':
    main()
