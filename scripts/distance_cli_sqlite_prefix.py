#!/usr/bin/env python3
"""
SQLite-backed distance/path tool with prefix compression and stdin input support.

Features:
- build-meta: scan systems (from file or stdin) and systems.schema.json to produce a meta JSON with:
    {"prefixes": {"0": "" , "1": "Sol", ...}, "starTypes": {"0":"", "1":"G (White-Yellow) Star", ...}}
  Prefix extraction rule: if name contains '-' use everything up to the first dash, otherwise use everything up to the first space; if neither, the whole name. Reserve id 0 for empty prefix.
- build-index: read systems from file or stdin, skip systems needing a permit, and store prefix_id, name_suffix and star_type_id (integers) along with coordinates and bucket coords. Index is resumable (INSERT OR IGNORE) and shows progress.
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
import random
import sqlite3
import sys
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple, Callable

DEFAULT_JSON = "systems_neutron.json"
DEFAULT_DB = "systems_index.db"
DEFAULT_META = "systems_meta.json"

BATCH_SIZE = 1000
PROGRESS_INTERVAL = 10


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
    processed = 0
    for line in iter_lines_from_source(json_path):
        processed += 1
        if processed % PROGRESS_INTERVAL == 0:
            print(f"Processed {processed} lines, prefixes {len(prefixes_counter)}", end='\r', flush=True)
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

    # end progress line
    if processed >= PROGRESS_INTERVAL:
        print()

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
    conn.execute('PRAGMA cache_size = -65536;')   # 64 MB page cache
    conn.execute('PRAGMA mmap_size = 2147483648;') # 2 GB memory-mapped reads
    return conn


def ensure_schema_prefix(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Create systems table with INTEGER coordinates
    cur.execute('''
        CREATE TABLE IF NOT EXISTS systems (
            id64 INTEGER PRIMARY KEY,
            prefix_id INTEGER,
            x INTEGER,
            y INTEGER,
            z INTEGER,
            star_type_id INTEGER,
            name_suffix TEXT
        )
    ''')
    # Create R-tree for spatial queries
    cur.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS rtree_systems USING rtree(
            id64,
            min_x, max_x,
            min_y, max_y,
            min_z, max_z
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_prefix ON systems(prefix_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_star_type ON systems(star_type_id)')
    
    # Meta table for DB parameters
    cur.execute('''
        CREATE TABLE IF NOT EXISTS db_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()


def build_index_prefix(json_path: str, db_path: str, bucket_size: float, meta_path: str, coord_scale: int = 32, force: bool = False) -> None:
    if json_path != '-' and not os.path.exists(json_path):
        print(f"JSON file not found: {json_path}")
        sys.exit(1)
    if not os.path.exists(meta_path):
        print(f"Meta file not found: {meta_path}. Run --build-meta first.")
        sys.exit(1)

    # If DB doesn't exist, we can set page_size
    is_new_db = not os.path.exists(db_path) or force
    if force and os.path.exists(db_path):
        print(f"--force given: removing existing DB {db_path}")
        os.remove(db_path)

    with open(meta_path, 'r', encoding='utf-8') as mf:
        meta = json.load(mf)
    prefixes = meta.get('prefixes', {})
    prefix_to_id = {v: int(k) for k, v in prefixes.items()}
    starTypes = meta.get('starTypes', {})
    star_to_id = {v: int(k) for k, v in starTypes.items()}

    conn = sqlite3.connect(db_path)
    if is_new_db:
        conn.execute('PRAGMA page_size = 8192;')
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=OFF;')
    conn.execute('PRAGMA temp_store=MEMORY;')
    
    ensure_schema_prefix(conn)
    cur = conn.cursor()

    # Store DB parameters
    cur.execute('INSERT OR REPLACE INTO db_meta (key, value) VALUES (?, ?)', ('coord_scale', str(coord_scale)))
    cur.execute('INSERT OR REPLACE INTO db_meta (key, value) VALUES (?, ?)', ('bucket_size', str(bucket_size)))
    conn.commit()

    insert_sql = 'INSERT OR IGNORE INTO systems (id64,prefix_id,x,y,z,star_type_id,name_suffix) VALUES (?,?,?,?,?,?,?)'
    rtree_sql = 'INSERT OR IGNORE INTO rtree_systems (id64,min_x,max_x,min_y,max_y,min_z,max_z) VALUES (?,?,?,?,?,?,?)'
    
    batch: List[Tuple] = []
    rtree_batch: List[Tuple] = []
    inserted = 0
    processed = 0

    print(f'Starting index build (scale={coord_scale}, resumable). Systems requiring permits are skipped.')
    for line in iter_lines_from_source(json_path):
        processed += 1
        if processed % PROGRESS_INTERVAL == 0:
            print(f"Processed {processed} lines, inserted {inserted} rows...", end='\r', flush=True)
        if '{' not in line:
            continue
        obj = parse_line_object(line)
        if obj is None:
            continue
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
            suffix = name[len(prefix):]
            
            # Scaled coordinates
            ix = int(round(float(coords['x']) * coord_scale))
            iy = int(round(float(coords['y']) * coord_scale))
            iz = int(round(float(coords['z']) * coord_scale))
            
            batch.append((sid, prefix_id, ix, iy, iz, star_id, suffix))
            rtree_batch.append((sid, ix, ix, iy, iy, iz, iz))
        except Exception:
            continue
        if len(batch) >= BATCH_SIZE:
            cur.executemany(insert_sql, batch)
            cur.executemany(rtree_sql, rtree_batch)
            conn.commit()
            inserted += len(batch)
            batch.clear()
            rtree_batch.clear()
    if batch:
        cur.executemany(insert_sql, batch)
        cur.executemany(rtree_sql, rtree_batch)
        conn.commit()
        inserted += len(batch)
        batch.clear()
        rtree_batch.clear()

    print('\nFinalizing: ANALYZE and VACUUM...')
    cur.execute('ANALYZE;')
    conn.commit()
    cur.execute('VACUUM;')
    conn.close()
    print(f"Index build complete. Processed {processed} lines; inserted {inserted} rows into {db_path}.")


def get_system_by_query_prefix(conn: sqlite3.Connection, query: str, meta: Dict, id_to_prefix: Dict[int, str], id_to_star: Dict[int, str], coord_scale: int, limit: int = 10) -> List[Dict]:
    """Find systems by id64 or exact full-name match (prefix + name_suffix).

    Assumes the current prefix-compressed DB schema (prefix_id + name_suffix). Exact matches only — no LIKE or partial matching.
    """
    prefixes = meta.get('prefixes', {})

    # Try id lookup first
    try:
        q_int = int(query)
        cur = conn.execute('SELECT id64,prefix_id,name_suffix,x,y,z,star_type_id FROM systems WHERE id64=?', (q_int,))
        row = cur.fetchone()
        if row:
            name = id_to_prefix.get(row[1], '') + (row[2] or '')
            star = id_to_star.get(row[6], '') if len(row) > 6 else ''
            # Unscale coordinates
            x, y, z = row[3] / coord_scale, row[4] / coord_scale, row[5] / coord_scale
            return [{'id64': row[0], 'name': name, 'coords': {'x': x, 'y': y, 'z': z}, 'mainStar': star}]
    except ValueError:
        pass

    # Exact full-name match: try prefixes that are a prefix of the query, longest first
    items = sorted(prefixes.items(), key=lambda kv: len(kv[1] or ''), reverse=True)
    out: List[Dict] = []
    for pid_str, prefix in items:
        pid = int(pid_str)
        if not query.startswith(prefix):
            continue
        suffix = query[len(prefix):]
        cur = conn.execute('SELECT id64,prefix_id,name_suffix,x,y,z,star_type_id FROM systems WHERE prefix_id=? AND name_suffix=? LIMIT ?', (pid, suffix, limit))
        for r in cur:
            name = prefix + (r[2] or '')
            star = id_to_star.get(r[6], '')
            # Unscale coordinates
            x, y, z = r[3] / coord_scale, r[4] / coord_scale, r[5] / coord_scale
            out.append({'id64': r[0], 'name': name, 'coords': {'x': x, 'y': y, 'z': z}, 'mainStar': star})
            if len(out) >= limit:
                return out
    return out


def neighbors_for_center_prefix(conn: sqlite3.Connection, center: Dict, max_distance: float, visited: Set[int], coord_scale: int, id_to_prefix: Dict[int, str], id_to_star: Dict[int, str], max_neighbors: int = 500, allowed_star_ids: Optional[Set[int]] = None, in_memory_buckets: Optional[Dict[Tuple[int,int,int], List[Dict]]] = None) -> List[Dict]:
    """Return nearby neighbors within max_distance for center using R-tree or in-memory buckets.

    visited filtering is applied after retrieving candidates.
    allowed_star_ids: if provided, only return neighbors whose star_type_id is in this set.
    """
    cx, cy, cz = center['coords']['x'], center['coords']['y'], center['coords']['z']
    
    # Scale search bounds
    s_dist = max_distance * coord_scale
    s_cx, s_cy, s_cz = cx * coord_scale, cy * coord_scale, cz * coord_scale
    
    min_x, max_x = s_cx - s_dist, s_cx + s_dist
    min_y, max_y = s_cy - s_dist, s_cy + s_dist
    min_z, max_z = s_cz - s_dist, s_cz + s_dist

    max_d2 = max_distance * max_distance

    if in_memory_buckets is not None:
        # Fallback for preloaded data
        out: List[Tuple[float, Dict]] = []
        for bucket_list in in_memory_buckets.values():
            for r in bucket_list:
                sid = r['id64']
                star_id = r.get('star_type_id')
                if allowed_star_ids and star_id not in allowed_star_ids:
                    continue
                x, y, z = r['x'] / coord_scale, r['y'] / coord_scale, r['z'] / coord_scale
                dx = x - cx
                dy = y - cy
                dz = z - cz
                d2 = dx*dx + dy*dy + dz*dz
                if d2 <= max_d2:
                    name = id_to_prefix.get(r.get('prefix_id'), '') + (r.get('name_suffix') or '')
                    star = id_to_star.get(star_id, '')
                    out.append((d2, {'id64': sid, 'name': name, 'coords': {'x': x, 'y': y, 'z': z}, 'mainStar': star, 'star_type_id': star_id}))
        out.sort(key=lambda t: t[0])
        candidates = [t[1] for t in out[:max_neighbors]]
    else:
        # R-tree range query
        sql = '''
            SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, s.star_type_id
            FROM rtree_systems r
            JOIN systems s ON s.id64 = r.id64
            WHERE r.min_x BETWEEN ? AND ?
              AND r.min_y BETWEEN ? AND ?
              AND r.min_z BETWEEN ? AND ?
        '''
        cur = conn.execute(sql, (min_x, max_x, min_y, max_y, min_z, max_z))
        out: List[Tuple[float, Dict]] = []
        for r in cur:
            sid = r[0]
            star_id = r[6]
            if allowed_star_ids and star_id not in allowed_star_ids:
                continue
            # Unscale coordinates
            x, y, z = r[3] / coord_scale, r[4] / coord_scale, r[5] / coord_scale
            dx = x - cx
            dy = y - cy
            dz = z - cz
            d2 = dx*dx + dy*dy + dz*dz
            if d2 <= max_d2:
                name = id_to_prefix.get(r[1], '') + (r[2] or '')
                star = id_to_star.get(star_id, '')
                out.append((d2, {'id64': sid, 'name': name, 'coords': {'x': x, 'y': y, 'z': z}, 'mainStar': star, 'star_type_id': star_id}))
        
        out.sort(key=lambda t: t[0])
        candidates = [t[1] for t in out[:max_neighbors]]

    # Filter out visited and self
    res = []
    for c in candidates:
        sid = c['id64']
        if sid == center['id64'] or sid in visited:
            continue
        res.append(c)
        if len(res) >= max_neighbors:
            break
    return res


def find_path_directional(conn: sqlite3.Connection, source: Dict, target: Dict, max_hop: float, coord_scale: int, id_to_prefix: Dict[int, str], id_to_star: Dict[int, str], max_nodes: int = 5000, max_neighbors: int = 500, allowed_star_ids: Optional[Set[int]] = None, step_threshold: float = 1.0, expand_factor: float = 2.0, in_memory_buckets: Optional[Dict[Tuple[int,int,int], List[Dict]]] = None, relax_factor: float = 1.1, allow_relaxation: bool = False, on_progress: Optional[Callable[[str], None]] = None) -> Optional[List[Dict]]:
    """Directional stepping pathfinder with bidirectional search.
    If allow_relaxation is True, relaxes max_hop for a single step if stuck.
    """
    def _emit(msg: str):
        if on_progress: on_progress(msg)
        else:
            if msg == '\n': print()
            else: print(msg, end='\r', flush=True)

    def _step(current: Dict, goal: Dict, current_max_hop: float, visited_self: Set[int], visited_other: Dict[int, Dict]) -> Optional[Dict]:
        cx, cy, cz = current['coords']['x'], current['coords']['y'], current['coords']['z']
        gx, gy, gz = goal['coords']['x'], goal['coords']['y'], goal['coords']['z']
        dx, dy, dz = gx - cx, gy - cy, gz - cz
        d2 = dx*dx + dy*dy + dz*dz
        
        if d2 <= current_max_hop*current_max_hop:
            res = goal.copy()
            if d2 > max_hop*max_hop: res['_relaxed_hop'] = math.sqrt(d2)
            return res

        mag = math.sqrt(d2)
        tx, ty, tz = cx + (dx / mag) * current_max_hop, cy + (dy / mag) * current_max_hop, cz + (dz / mag) * current_max_hop

        radius = step_threshold
        while radius <= current_max_hop:
            fake_center = {'id64': -1, 'coords': {'x': tx, 'y': ty, 'z': tz}}
            cands = neighbors_for_center_prefix(conn, fake_center, radius, set(), coord_scale, id_to_prefix, id_to_star, max_neighbors=max_neighbors, allowed_star_ids=allowed_star_ids, in_memory_buckets=in_memory_buckets)
            if cands:
                valid = []
                for c in cands:
                    if c['id64'] in visited_self: continue
                    dcx, dcy, dcz = c['coords']['x'] - cx, c['coords']['y'] - cy, c['coords']['z'] - cz
                    dist2 = dcx*dcx + dcy*dcy + dcz*dcz
                    if dist2 <= current_max_hop*current_max_hop:
                        if c['id64'] in visited_other:
                            res = visited_other[c['id64']].copy()
                            if dist2 > max_hop*max_hop: res['_relaxed_hop'] = math.sqrt(dist2)
                            return res
                        valid.append((dist2, c))
                if valid:
                    dist2, best_c = min(valid, key=lambda t: (t[1]['coords']['x']-tx)**2 + (t[1]['coords']['y']-ty)**2 + (t[1]['coords']['z']-tz)**2)
                    best = best_c.copy()
                    if dist2 > max_hop*max_hop: best['_relaxed_hop'] = math.sqrt(dist2)
                    return best
            radius *= expand_factor
        return None

    path_f, path_r = [source], [target]
    visited_f, visited_r = {source['id64']: source}, {target['id64']: target}
    curr_f, curr_r = source, target

    for nodes in range(max_nodes):
        if nodes % 10 == 0:
            dx, dy, dz = curr_r['coords']['x']-curr_f['coords']['x'], curr_r['coords']['y']-curr_f['coords']['y'], curr_r['coords']['z']-curr_f['coords']['z']
            gap = math.sqrt(dx*dx + dy*dy + dz*dz)
            _emit(f"Search step {nodes}: gap={gap:.1f} nodes={len(path_f)+len(path_r)}")

        nxt_f = _step(curr_f, curr_r, max_hop, set(visited_f.keys()), visited_r)
        if nxt_f:
            if nxt_f['id64'] in visited_r:
                idx = next(i for i, n in enumerate(path_r) if n['id64'] == nxt_f['id64'])
                path_f.append(nxt_f); return path_f + path_r[:idx][::-1]
            path_f.append(nxt_f); visited_f[nxt_f['id64']] = nxt_f; curr_f = nxt_f; continue

        nxt_r = _step(curr_r, curr_f, max_hop, set(visited_r.keys()), visited_f)
        if nxt_r:
            if nxt_r['id64'] in visited_f:
                idx = next(i for i, n in enumerate(path_f) if n['id64'] == nxt_r['id64'])
                path_r.append(nxt_r); return path_f[:idx+1] + path_r[::-1][1:]
            path_r.append(nxt_r); visited_r[nxt_r['id64']] = nxt_r; curr_r = nxt_r; continue

        if allow_relaxation:
            _emit("Pathfinding: Stuck, trying relaxation...")
            current_relax = relax_factor
            while current_relax <= 3.0:
                relaxed_hop = max_hop * current_relax
                nxt_f = _step(curr_f, curr_r, relaxed_hop, set(visited_f.keys()), visited_r)
                if nxt_f:
                    if nxt_f['id64'] in visited_r:
                        idx = next(i for i, n in enumerate(path_r) if n['id64'] == nxt_f['id64'])
                        path_f.append(nxt_f); return path_f + path_r[:idx][::-1]
                    path_f.append(nxt_f); visited_f[nxt_f['id64']] = nxt_f; curr_f = nxt_f; break
                nxt_r = _step(curr_r, curr_f, relaxed_hop, set(visited_r.keys()), visited_f)
                if nxt_r:
                    if nxt_r['id64'] in visited_f:
                        idx = next(i for i, n in enumerate(path_f) if n['id64'] == nxt_r['id64'])
                        path_r.append(nxt_r); return path_f[:idx+1] + path_r[::-1][1:]
                    path_r.append(nxt_r); visited_r[nxt_r['id64']] = nxt_r; curr_r = nxt_r; break
                current_relax *= relax_factor
            else: return None
            continue
        return None
    return None


def find_path_robust(conn: sqlite3.Connection, source: Dict, target: Dict, max_hop: float, coord_scale: int, id_to_prefix: Dict[int, str], id_to_star: Dict[int, str], max_nodes: int = 5000, max_neighbors: int = 500, allowed_star_ids: Optional[Set[int]] = None, step_threshold: float = 1.0, expand_factor: float = 2.0, in_memory_buckets: Optional[Dict[Tuple[int,int,int], List[Dict]]] = None, relax_factor: float = 1.1, waypoint_tries: int = 50, on_progress: Optional[Callable[[str], None]] = None) -> Optional[List[Dict]]:
    """Directional stepping pathfinder with waypoint fallback and relaxation."""
    def _emit(msg: str):
        if on_progress: on_progress(msg)
        else:
            if msg == '\n': print()
            else: print(msg, end='\r', flush=True)

    # 1. Direct search (no relaxation)
    _emit("Pathfinding: Starting direct search...")
    res = find_path_directional(conn, source, target, max_hop, coord_scale, id_to_prefix, id_to_star, max_nodes, max_neighbors, allowed_star_ids, step_threshold, expand_factor, in_memory_buckets, relax_factor, allow_relaxation=False, on_progress=on_progress)
    if res: return res

    # 2. Waypoint search
    _emit(f"Pathfinding: Direct failed, trying {waypoint_tries} waypoints...")
    ax, ay, az = source['coords']['x'], source['coords']['y'], source['coords']['z']
    bx, by, bz = target['coords']['x'], target['coords']['y'], target['coords']['z']
    vx, vy, vz = bx - ax, by - ay, bz - az
    dist = math.sqrt(vx*vx + vy*vy + vz*vz)
    if dist > 0:
        # Midpoint
        mx, my, mz = (ax + bx) / 2, (ay + by) / 2, (az + bz) / 2
        # Find arbitrary perp vectors
        if abs(vx) < abs(vy): n = (1.0, 0.0, 0.0)
        else: n = (0.0, 1.0, 0.0)
        # Cross product P1 = V x N
        p1x, p1y, p1z = vy*n[2] - vz*n[1], vz*n[0] - vx*n[2], vx*n[1] - vy*n[0]
        p1_mag = math.sqrt(p1x*p1x + p1y*p1y + p1z*p1z)
        p1x, p1y, p1z = p1x/p1_mag, p1y/p1_mag, p1z/p1_mag
        # P2 = V x P1
        p2x, p2y, p2z = vy*p1z - vz*p1y, vz*p1x - vx*p1z, vx*p1y - vy*p1x
        p2_mag = math.sqrt(p2x*p2x + p2y*p2y + p2z*p2z)
        p2x, p2y, p2z = p2x/p2_mag, p2y/p2_mag, p2z/p2_mag

        for i in range(waypoint_tries):
            radius = ((i + 1) / waypoint_tries) * 0.5 * dist
            angle = random.uniform(0, 2 * math.pi)
            wx, wy, wz = mx + radius * (math.cos(angle)*p1x + math.sin(angle)*p2x), my + radius * (math.cos(angle)*p1y + math.sin(angle)*p2y), mz + radius * (math.cos(angle)*p1z + math.sin(angle)*p2z)
            
            _emit(f"Waypoint try {i+1}/{waypoint_tries} (radius={radius:.1f})...")
            mid_sys = nearest_system(conn, {'x': wx, 'y': wy, 'z': wz}, coord_scale, id_to_prefix, id_to_star)
            if not mid_sys or mid_sys['id64'] == source['id64'] or mid_sys['id64'] == target['id64']: continue
            
            # source -> mid
            path1 = find_path_directional(conn, source, mid_sys, max_hop, coord_scale, id_to_prefix, id_to_star, max_nodes, max_neighbors, allowed_star_ids, step_threshold, expand_factor, in_memory_buckets, relax_factor, allow_relaxation=False, on_progress=None)
            if path1:
                # mid -> target
                path2 = find_path_directional(conn, mid_sys, target, max_hop, coord_scale, id_to_prefix, id_to_star, max_nodes, max_neighbors, allowed_star_ids, step_threshold, expand_factor, in_memory_buckets, relax_factor, allow_relaxation=False, on_progress=None)
                if path2:
                    _emit('\n')
                    return path1 + path2[1:]

    # 3. Relaxation search
    _emit("Pathfinding: Waypoints failed, resorting to relaxation...")
    return find_path_directional(conn, source, target, max_hop, coord_scale, id_to_prefix, id_to_star, max_nodes, max_neighbors, allowed_star_ids, step_threshold, expand_factor, in_memory_buckets, relax_factor, allow_relaxation=True, on_progress=on_progress)


def nearest_system(conn: sqlite3.Connection, near_coords: Dict, coord_scale: int, id_to_prefix: Dict[int, str], id_to_star: Dict[int, str], initial_radius: float = 50.0) -> Optional[Dict]:
    """Find the nearest system to given coordinates using expanding radius R-tree search."""
    radius = initial_radius
    cx, cy, cz = near_coords['x'], near_coords['y'], near_coords['z']
    while True:
        s_dist = radius * coord_scale
        s_cx, s_cy, s_cz = cx * coord_scale, cy * coord_scale, cz * coord_scale
        min_x, max_x = s_cx - s_dist, s_cx + s_dist
        min_y, max_y = s_cy - s_dist, s_cy + s_dist
        min_z, max_z = s_cz - s_dist, s_cz + s_dist
        sql = '''
            SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, s.star_type_id
            FROM rtree_systems r
            JOIN systems s ON s.id64 = r.id64
            WHERE r.min_x BETWEEN ? AND ?
              AND r.min_y BETWEEN ? AND ?
              AND r.min_z BETWEEN ? AND ?
            LIMIT 1
        '''
        row = conn.execute(sql, (min_x, max_x, min_y, max_y, min_z, max_z)).fetchone()
        if row:
            rx, ry, rz = row[3] / coord_scale, row[4] / coord_scale, row[5] / coord_scale
            name = id_to_prefix.get(row[1], '') + (row[2] or '')
            star = id_to_star.get(row[6], '')
            return {'id64': row[0], 'name': name, 'coords': {'x': rx, 'y': ry, 'z': rz}, 'mainStar': star}
        if radius > 10000: return None
        radius *= 2


def nearest_of_type(conn: sqlite3.Connection, near_coords: Dict, type_ids: List[int], coord_scale: int, initial_radius: float = 50.0) -> Optional[Dict]:
    """Find the nearest system of matching star type using expanding radius R-tree search."""
    radius = initial_radius
    cx, cy, cz = near_coords['x'], near_coords['y'], near_coords['z']
    
    while True:
        # Scale search bounds
        s_dist = radius * coord_scale
        s_cx, s_cy, s_cz = cx * coord_scale, cy * coord_scale, cz * coord_scale
        
        min_x, max_x = s_cx - s_dist, s_cx + s_dist
        min_y, max_y = s_cy - s_dist, s_cy + s_dist
        min_z, max_z = s_cz - s_dist, s_cz + s_dist
        
        placeholders = ','.join('?' for _ in type_ids)
        sql = f'''
            SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, s.star_type_id
            FROM rtree_systems r
            JOIN systems s ON s.id64 = r.id64
            WHERE r.min_x BETWEEN ? AND ?
              AND r.min_y BETWEEN ? AND ?
              AND r.min_z BETWEEN ? AND ?
              AND s.star_type_id IN ({placeholders})
        '''
        rows = conn.execute(sql, (min_x, max_x, min_y, max_y, min_z, max_z, *type_ids)).fetchall()
        
        best = None
        best_d2 = None
        
        for r in rows:
            # Unscale
            rx, ry, rz = r[3] / coord_scale, r[4] / coord_scale, r[5] / coord_scale
            d2 = (rx-cx)**2 + (ry-cy)**2 + (rz-cz)**2
            if d2 <= radius**2:
                if best is None or d2 < best_d2:
                    best = r
                    best_d2 = d2
        
        if best:
            return {'id64': best[0], 'prefix_id': best[1], 'name_suffix': best[2], 'x': best[3], 'y': best[4], 'z': best[5], 'star_type_id': best[6], 'dist': math.sqrt(best_d2)}
        
        if radius > 100000: # Galaxy diameter fallback
            return None
        radius *= 2


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
    parser.add_argument('--coord-scale', type=int, default=32, help='Scale factor for storing coordinates as integers (default 32)')
    parser.add_argument('--build-meta', action='store_true')
    parser.add_argument('--build-index', action='store_true')
    parser.add_argument('--force', action='store_true', help='Force rebuild index from scratch')
    parser.add_argument('--max-hop', type=float, help='If provided, find path where each hop <= this')
    parser.add_argument('--max-nodes', type=int, default=5000)
    parser.add_argument('--max-neighbors', type=int, default=500)
    parser.add_argument('--only-star-types', help='Comma-separated star type names to restrict nodes used in pathfinding')
    parser.add_argument('--nearest-type', help='Find nearest system of given star type name (comma-separated supported)')
    parser.add_argument('--near', help='Reference point for --nearest-type: either "id64"/name or coordinates "x,y,z"')
    parser.add_argument('--directional', action='store_true', help='Use directional stepping approximate pathfinder')
    parser.add_argument('--step-threshold', type=float, default=1.0, help='Initial threshold distance when searching near the step point')
    parser.add_argument('--step-expand-factor', type=float, default=2.0, help='Multiplier to expand search radius when no candidate found')
    parser.add_argument('--waypoint-tries', type=int, default=50, help='Number of random waypoints to try if direct path fails')
    parser.add_argument('--preload', action='store_true', help='Preload buckets between source and target into memory to avoid SQL roundtrips')
    parser.add_argument('--preload-margin-buckets', type=int, default=1, help='Extra bucket margin when preloading')
    parser.add_argument('--from', dest='from_sys', help='Source system name or id64')
    parser.add_argument('--to', dest='to_sys', help='Target system name or id64')
    args = parser.parse_args()
    # Default behavior: if user didn't request --fast or --directional explicitly, use directional stepping by default for speed
    if not getattr(args, 'fast', False) and not getattr(args, 'directional', False):
        args.directional = True

    if args.build_meta:
        # attempt to use local schema file
        schema_path = os.path.join(os.path.dirname(__file__), '..', 'systems.schema.json') if os.path.exists(os.path.join(os.path.dirname(__file__), '..', 'systems.schema.json')) else 'systems.schema.json'
        build_meta(args.file, schema_path, args.meta_file)
        return

    if args.build_index:
        build_index_prefix(args.file, args.db, args.bucket_size, args.meta_file, coord_scale=args.coord_scale, force=args.force)
        return

    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}. Run --build-index first.")
        sys.exit(1)
    if not os.path.exists(args.meta_file):
        print(f"Meta file {args.meta_file} not found; required.")
        sys.exit(1)

    with open(args.meta_file, 'r', encoding='utf-8') as mf:
        meta = json.load(mf)

    # Pre-build lookup maps to avoid rebuilding in hot loops
    prefixes = meta.get('prefixes', {})
    id_to_prefix = {int(k): v for k, v in prefixes.items()}
    star_map = meta.get('starTypes', {})
    id_to_star = {int(k): v for k, v in star_map.items()} if star_map else {}

    # build star name -> id map
    star_name_to_id = {v: int(k) for k, v in star_map.items()}

    conn = open_db(args.db)
    
    # Load DB parameters
    try:
        coord_scale = int(conn.execute('SELECT value FROM db_meta WHERE key="coord_scale"').fetchone()[0])
        bucket_size = float(conn.execute('SELECT value FROM db_meta WHERE key="bucket_size"').fetchone()[0])
    except Exception:
        # Fallback for old DBs if they haven't been rebuilt yet
        coord_scale = 1
        bucket_size = args.bucket_size

    # If nearest-type requested, perform nearest search and exit
    if args.nearest_type:
        if not args.near:
            print('--near is required when using --nearest-type')
            return
        # resolve star type ids
        types = [s.strip() for s in args.nearest_type.split(',') if s.strip()]
        type_ids = [star_name_to_id.get(t) for t in types if t in star_name_to_id]
        if not type_ids:
            print('No matching star types found in meta for:', types)
            return
        # resolve near point
        near = args.near.strip()
        near_coords = None
        # coordinate format x,y,z
        if ',' in near:
            parts = near.split(',')
            if len(parts) != 3:
                print('Invalid coordinates for --near. Use: x,y,z')
                return
            try:
                near_coords = {'x': float(parts[0]), 'y': float(parts[1]), 'z': float(parts[2])}
            except ValueError:
                print('Invalid numeric coordinates')
                return
        else:
            # treat as system query
            cand = get_system_by_query_prefix(conn, near, meta, id_to_prefix, id_to_star, coord_scale)
            if not cand:
                print('Could not resolve --near to a system:', near)
                return
            near_coords = cand[0]['coords']
        
        # Use expanding R-tree search
        result = nearest_of_type(conn, near_coords, type_ids, coord_scale)
        if not result:
            print('No matching systems found')
            return
        
        name = id_to_prefix.get(result['prefix_id'], '') + (result['name_suffix'] or '')
        print(f"Nearest: {name} id64={result['id64']} dist={result['dist']:.1f}")
        return

    # interactive prompts for pathfinding
    q1 = args.from_sys or input('Enter first system name or id64: ').strip()
    cand1 = get_system_by_query_prefix(conn, q1, meta, id_to_prefix, id_to_star, coord_scale)
    s1 = choose_candidate_list(cand1, 'first')
    if s1 is None:
        print('Cancelled')
        return

    q2 = args.to_sys or input('Enter second system name or id64: ').strip()
    cand2 = get_system_by_query_prefix(conn, q2, meta, id_to_prefix, id_to_star, coord_scale)
    s2 = choose_candidate_list(cand2, 'second')
    if s2 is None:
        print('Cancelled')
        return

    dx = s1['coords']['x'] - s2['coords']['x']
    dy = s1['coords']['y'] - s2['coords']['y']
    dz = s1['coords']['z'] - s2['coords']['z']
    direct = math.sqrt(dx*dx + dy*dy + dz*dz)
    print(f"Direct distance: {direct:.1f}")
    if args.max_hop is None:
        return
    if direct <= args.max_hop:
        print('Within max hop; direct')
        return

    print('Searching for path...')
    # prepare allowed star ids from --only-star-types
    allowed_star_ids = None
    if args.only_star_types:
        parts = [p.strip() for p in args.only_star_types.split(',') if p.strip()]
        allowed_star_ids = set()
        for p in parts:
            sid = star_name_to_id.get(p)
            if sid is not None:
                allowed_star_ids.add(sid)
        if not allowed_star_ids:
            print('No matching star types for --only-star-types:', parts)
            return

    # Optionally preload buckets between source and target
    in_memory_buckets = None
    if args.preload:
        # compute bucket bounding box between source and target
        def bucket_coords_of(c):
            return (math.floor(c['x'] / bucket_size), math.floor(c['y'] / bucket_size), math.floor(c['z'] / bucket_size))
        b1 = bucket_coords_of(s1['coords'])
        b2 = bucket_coords_of(s2['coords'])
        min_bx = min(b1[0], b2[0]) - args.preload_margin_buckets
        max_bx = max(b1[0], b2[0]) + args.preload_margin_buckets
        min_by = min(b1[1], b2[1]) - args.preload_margin_buckets
        max_by = max(b1[1], b2[1]) + args.preload_margin_buckets
        min_bz = min(b1[2], b2[2]) - args.preload_margin_buckets
        max_bz = max(b1[2], b2[2]) + args.preload_margin_buckets
        print(f"Preloading buckets bx[{min_bx}..{max_bx}] by[{min_by}..{max_by}] bz[{min_bz}..{max_bz}]")
        in_memory_buckets = {}
        # Preload currently still uses buckets for the "in-memory" structure, but reads from systems table
        # We need to unscale coords if we store them in in_memory_buckets, or handle it in neighbors_for_center_prefix
        # Let's keep the scaled values in the bucket list and have neighbors_for_center_prefix unscale them.
        sql = '''
            SELECT id64,prefix_id,name_suffix,x,y,z,star_type_id 
            FROM systems 
            WHERE (x/?) BETWEEN ? AND ? 
              AND (y/?) BETWEEN ? AND ? 
              AND (z/?) BETWEEN ? AND ?
        '''
        # (x/scale) / bucket_size = x / (scale * bucket_size)
        s_bs = coord_scale * bucket_size
        cur = conn.execute(sql, (s_bs, min_bx, max_bx, s_bs, min_by, max_by, s_bs, min_bz, max_bz))
        for r in cur:
            # To maintain compatibility with the existing in_memory_buckets structure in neighbors_for_center_prefix
            # we'll use the scaled coordinates and the bucket coords as keys.
            bx_i = math.floor(r[3] / s_bs)
            by_i = math.floor(r[4] / s_bs)
            bz_i = math.floor(r[5] / s_bs)
            rec = {'id64': r[0], 'prefix_id': r[1], 'name_suffix': r[2], 'x': r[3], 'y': r[4], 'z': r[5], 'star_type_id': r[6]}
            in_memory_buckets.setdefault((bx_i, by_i, bz_i), []).append(rec)

    def cli_progress(msg: str):
        if msg is None:
            return
        if msg == '\n':
            print()
        else:
            print(msg, end='\r', flush=True)

    path = find_path_robust(conn, s1, s2, args.max_hop, coord_scale, id_to_prefix, id_to_star, max_nodes=args.max_nodes, max_neighbors=args.max_neighbors, allowed_star_ids=allowed_star_ids, step_threshold=args.step_threshold, expand_factor=args.step_expand_factor, in_memory_buckets=in_memory_buckets, waypoint_tries=args.waypoint_tries, on_progress=cli_progress)
    if path is None:
        print('No path found')
        return
    # Print path with per-hop distances and total distance
    total = 0.0
    print('Path:')
    prev = None
    for i, p in enumerate(path, start=1):
        c = p['coords']
        if prev is None:
            hop_dist = 0.0
        else:
            dx = c['x'] - prev['x']
            dy = c['y'] - prev['y']
            dz = c['z'] - prev['z']
            hop_dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            total += hop_dist
        print(f" {i}) {p['name']} id64={p['id64']} coords=({c['x']},{c['y']},{c['z']}) mainStar={p.get('mainStar')} hop_dist={hop_dist:.1f}", end='')
        if '_relaxed_hop' in p:
            print(f" [RELAXED: {p['_relaxed_hop']:.1f}]", end='')
        print()
        prev = c
    print(f'Total path distance: {total:.1f}')
    
    # Calculate straight line distance
    s_coords = s1['coords']
    t_coords = s2['coords']
    direct_dist = math.sqrt((t_coords['x']-s_coords['x'])**2 + (t_coords['y']-s_coords['y'])**2 + (t_coords['z']-s_coords['z'])**2)
    print(f'Straight line distance: {direct_dist:.1f}')
    
    if direct_dist > 0:
        diff_pct = ((total / direct_dist) - 1) * 100
        print(f'Path is {diff_pct:.1f}% longer than straight line')
    
    print('Done')

if __name__ == '__main__':
    main()
