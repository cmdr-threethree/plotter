#!/usr/bin/env python3
"""
SQLite-backed distance and pathfinder with resumable index build, progress indicator,
and storage of mainStar type. Systems requiring a permit are ignored when building the index.

Build index (resumable):
  python3 scripts/distance_cli_sqlite.py --build-index --file systems_1day.json --db systems_index.db --bucket-size 50

Pass --force to rebuild from scratch.

Query / interactive pathfinding:
  python3 scripts/distance_cli_sqlite.py --db systems_index.db --max-hop 40 --bucket-size 50

Index schema: systems(id64 PRIMARY KEY, name, x, y, z, mainStar, bx, by, bz)
"""

import argparse
import json
import math
import os
import sqlite3
import sys
from typing import Dict, List, Optional, Set, Tuple

DEFAULT_JSON = "systems_neutron.json"
DEFAULT_DB = "systems_index.db"

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


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=OFF;')
    conn.execute('PRAGMA temp_store=MEMORY;')
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS systems (
            id64 INTEGER PRIMARY KEY,
            name TEXT,
            x REAL,
            y REAL,
            z REAL,
            mainStar TEXT,
            bx INTEGER,
            by INTEGER,
            bz INTEGER
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_buckets ON systems(bx,by,bz)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_name_lower ON systems(name)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mainstar ON systems(mainStar)')
    conn.commit()


def build_index(json_path: str, db_path: str, bucket_size: float, force: bool = False) -> None:
    if not os.path.exists(json_path):
        print(f"JSON file not found: {json_path}")
        sys.exit(1)
    if force and os.path.exists(db_path):
        print(f"--force given: removing existing DB {db_path}")
        os.remove(db_path)

    conn = open_db(db_path)
    ensure_schema(conn)
    cur = conn.cursor()

    def bucket_coords(x: float, y: float, z: float) -> Tuple[int,int,int]:
        return (math.floor(x / bucket_size), math.floor(y / bucket_size), math.floor(z / bucket_size))

    insert_sql = 'INSERT OR IGNORE INTO systems (id64,name,x,y,z,mainStar,bx,by,bz) VALUES (?,?,?,?,?,?,?,?,?)'
    batch: List[Tuple] = []
    inserted = 0
    processed = 0

    print('Starting index build (resumable). Press Ctrl-C to stop; you can re-run with same DB to resume.')
    with open(json_path, 'r', encoding='utf-8') as fh:
        for line in fh:
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
                x = float(coords['x']); y = float(coords['y']); z = float(coords['z'])
                bx,by,bz = bucket_coords(x,y,z)
                batch.append((sid, name, x, y, z, main_star, bx, by, bz))
            except Exception:
                continue
            if len(batch) >= BATCH_SIZE:
                cur.executemany(insert_sql, batch)
                conn.commit()
                inserted += len(batch)
                batch.clear()
        # final flush
        if batch:
            cur.executemany(insert_sql, batch)
            conn.commit()
            inserted += len(batch)
            batch.clear()

    cur.execute('ANALYZE;')
    conn.commit()
    conn.close()
    print(f"\nIndex build complete. Processed {processed} lines; inserted {inserted} rows into {db_path}.")


def get_system_by_query(conn: sqlite3.Connection, query: str, limit: int = 10) -> List[Dict]:
    try:
        q_int = int(query)
        cur = conn.execute('SELECT id64,name,x,y,z,mainStar FROM systems WHERE id64=?', (q_int,))
        row = cur.fetchone()
        return ([{'id64': row[0], 'name': row[1], 'coords': {'x': row[2],'y': row[3],'z': row[4]}, 'mainStar': row[5]}] if row else [])
    except Exception:
        cur = conn.execute('SELECT id64,name,x,y,z,mainStar FROM systems WHERE lower(name) LIKE ? LIMIT ?', (f"%{query.lower()}%", limit))
        out = []
        for r in cur:
            out.append({'id64': r[0], 'name': r[1], 'coords': {'x': r[2],'y': r[3],'z': r[4]}, 'mainStar': r[5]})
        return out


def neighbors_for_center(conn: sqlite3.Connection, center: Dict, max_distance: float, visited: Set[int], bucket_size: float, max_neighbors: int = 500) -> List[Dict]:
    bx = math.floor(center['coords']['x'] / bucket_size)
    by = math.floor(center['coords']['y'] / bucket_size)
    bz = math.floor(center['coords']['z'] / bucket_size)
    rb = int(math.ceil(max_distance / bucket_size))

    min_bx, max_bx = bx - rb, bx + rb
    min_by, max_by = by - rb, by + rb
    min_bz, max_bz = bz - rb, bz + rb

    sql = '''SELECT id64,name,x,y,z,mainStar FROM systems
             WHERE bx BETWEEN ? AND ? AND by BETWEEN ? AND ? AND bz BETWEEN ? AND ?'''
    cur = conn.execute(sql, (min_bx, max_bx, min_by, max_by, min_bz, max_bz))

    max_d2 = max_distance * max_distance
    out: List[Tuple[float, Dict]] = []
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
            out.append((d2, {'id64': sid, 'name': r[1], 'coords': {'x': x,'y': y,'z': z}, 'mainStar': r[5]}))
    out.sort(key=lambda t: t[0])
    return [t[1] for t in out[:max_neighbors]]


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


def find_path_bfs_db(conn: sqlite3.Connection, source: Dict, target: Dict, max_hop: float, bucket_size: float, max_nodes: int = 5000, max_neighbors: int = 500) -> Optional[List[Dict]]:
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
        neighbors = neighbors_for_center(conn, center, max_hop, visited, bucket_size, max_neighbors=max_neighbors)
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


def main():
    parser = argparse.ArgumentParser(description='SQLite-backed distance/path tool with resumable index build')
    parser.add_argument('--file', '-f', default=DEFAULT_JSON)
    parser.add_argument('--db', default=DEFAULT_DB)
    parser.add_argument('--bucket-size', type=float, default=50.0)
    parser.add_argument('--build-index', action='store_true')
    parser.add_argument('--force', action='store_true', help='Force rebuild index from scratch')
    parser.add_argument('--max-hop', type=float, help='If provided, find path where each hop <= this')
    parser.add_argument('--max-nodes', type=int, default=5000)
    parser.add_argument('--max-neighbors', type=int, default=500)
    args = parser.parse_args()

    if args.build_index:
        build_index(args.file, args.db, args.bucket_size, force=args.force)
        return

    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}. Run --build-index first.")
        sys.exit(1)

    conn = open_db(args.db)

    q1 = input('Enter first system name or id64: ').strip()
    cand1 = get_system_by_query(conn, q1)
    s1 = choose_candidate_list(cand1, 'first')
    if s1 is None:
        print('Cancelled')
        return
    q2 = input('Enter second system name or id64: ').strip()
    cand2 = get_system_by_query(conn, q2)
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
    path = find_path_bfs_db(conn, s1, s2, args.max_hop, args.bucket_size, max_nodes=args.max_nodes, max_neighbors=args.max_neighbors)
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
