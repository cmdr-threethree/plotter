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
import sqlite3
import sys
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple, Callable

DEFAULT_JSON = "systems_neutron.json"
DEFAULT_DB = "systems_index.db"
DEFAULT_META = "systems_meta.json"

BATCH_SIZE = 1000
PROGRESS_INTERVAL = 10

# global bucket cache for lazy loading: (bx,by,bz) -> list of records
global_bucket_cache = {}


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
            bz INTEGER,
            name_suffix TEXT
        )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_buckets ON systems(bx,by,bz)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_prefix ON systems(prefix_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_star_type ON systems(star_type_id)')
    # Ensure name_suffix column exists for older DBs
    cur.execute("PRAGMA table_info(systems)")
    cols = [r[1] for r in cur.fetchall()]
    if 'name_suffix' not in cols:
        cur.execute('ALTER TABLE systems ADD COLUMN name_suffix TEXT')
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

    insert_sql = 'INSERT OR IGNORE INTO systems (id64,prefix_id,x,y,z,star_type_id,bx,by,bz,name_suffix) VALUES (?,?,?,?,?,?,?,?,?,?)'
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
            # store suffix including separator so prefix + suffix == original name
            suffix = name[len(prefix):]
            x = float(coords['x']); y = float(coords['y']); z = float(coords['z'])
            bx,by,bz = bucket_coords(x,y,z)
            batch.append((sid, prefix_id, x, y, z, star_id, bx, by, bz, suffix))
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
    """Find systems by id64 or exact full-name match (prefix + name_suffix).

    Assumes the current prefix-compressed DB schema (prefix_id + name_suffix). Exact matches only — no LIKE or partial matching.
    """
    prefixes = meta.get('prefixes', {})
    id_to_prefix = {int(k): v for k, v in prefixes.items()}
    star_map = meta.get('starTypes', {})
    id_to_star = {int(k): v for k, v in star_map.items()} if star_map else {}

    # Try id lookup first
    try:
        q_int = int(query)
        cur = conn.execute('SELECT id64,prefix_id,name_suffix,x,y,z,star_type_id FROM systems WHERE id64=?', (q_int,))
        row = cur.fetchone()
        if row:
            name = id_to_prefix.get(row[1], '') + (row[2] or '')
            star = id_to_star.get(row[6], '') if len(row) > 6 else ''
            return [{'id64': row[0], 'name': name, 'coords': {'x': row[3], 'y': row[4], 'z': row[5]}, 'mainStar': star}]
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
            out.append({'id64': r[0], 'name': name, 'coords': {'x': r[3], 'y': r[4], 'z': r[5]}, 'mainStar': star})
            if len(out) >= limit:
                return out
    return out


def neighbors_for_center_prefix(conn: sqlite3.Connection, center: Dict, max_distance: float, visited: Set[int], bucket_size: float, max_neighbors: int = 500, meta: Optional[Dict] = None, allowed_star_ids: Optional[Set[int]] = None, in_memory_buckets: Optional[Dict[Tuple[int,int,int], List[Dict]]] = None) -> List[Dict]:
    """Return cached nearby neighbors within max_distance for center.

    Cache key ignores visited; visited filtering is applied after retrieving candidates.
    allowed_star_ids: if provided, only return neighbors whose star_type_id is in this set.
    """
    bx = math.floor(center['coords']['x'] / bucket_size)
    by = math.floor(center['coords']['y'] / bucket_size)
    bz = math.floor(center['coords']['z'] / bucket_size)
    rb = int(math.ceil(max_distance / bucket_size))

    min_bx, max_bx = bx - rb, bx + rb
    min_by, max_by = by - rb, by + rb
    min_bz, max_bz = bz - rb, bz + rb

    max_d2 = max_distance * max_distance
    prefixes = meta.get('prefixes', {}) if meta else {}
    id_to_prefix = {int(k): v for k, v in prefixes.items()}
    star_types = meta.get('starTypes', {}) if meta else {}
    id_to_star = {int(k): v for k, v in star_types.items()}

    cache_key = (center['id64'], int(max_distance), int(bucket_size), int(max_neighbors), bx, by, bz, tuple(sorted(allowed_star_ids)) if allowed_star_ids else None)
    manual_cache = getattr(neighbors_for_center_prefix, '_manual_cache', None)
    if manual_cache is None:
        neighbors_for_center_prefix._manual_cache = {}
        manual_cache = neighbors_for_center_prefix._manual_cache

    if in_memory_buckets is not None:
        # gather candidates from preloaded buckets
        out: List[Tuple[float, Dict]] = []
        for bx_i in range(min_bx, max_bx+1):
            for by_i in range(min_by, max_by+1):
                for bz_i in range(min_bz, max_bz+1):
                    bucket_list = in_memory_buckets.get((bx_i, by_i, bz_i), [])
                    for r in bucket_list:
                        sid = r['id64']
                        star_id = r.get('star_type_id')
                        if allowed_star_ids and star_id not in allowed_star_ids:
                            continue
                        x, y, z = r['x'], r['y'], r['z']
                        dx = x - center['coords']['x']
                        dy = y - center['coords']['y']
                        dz = z - center['coords']['z']
                        d2 = dx*dx + dy*dy + dz*dz
                        if d2 <= max_d2:
                            name = id_to_prefix.get(r.get('prefix_id'), '') + (r.get('name_suffix') or '')
                            star = id_to_star.get(star_id, '')
                            out.append((d2, {'id64': sid, 'name': name, 'coords': {'x': x, 'y': y, 'z': z}, 'mainStar': star, 'star_type_id': star_id}))
        out.sort(key=lambda t: t[0])
        candidates = [t[1] for t in out[:max_neighbors]]
    elif cache_key in manual_cache:
        candidates = manual_cache[cache_key]
    else:
        # Lazy load buckets one at a time and cache them globally
        out: List[Tuple[float, Dict]] = []
        for bx_i in range(min_bx, max_bx + 1):
            for by_i in range(min_by, max_by + 1):
                for bz_i in range(min_bz, max_bz + 1):
                    key = (bx_i, by_i, bz_i)
                    bucket_list = global_bucket_cache.get(key)
                    if bucket_list is None:
                        # load this bucket from sqlite
                        cur = conn.execute('SELECT id64,prefix_id,name_suffix,x,y,z,star_type_id FROM systems WHERE bx=? AND by=? AND bz=?', key)
                        bucket_list = []
                        for r in cur:
                            bucket_list.append({'id64': r[0], 'prefix_id': r[1], 'name_suffix': r[2], 'x': r[3], 'y': r[4], 'z': r[5], 'star_type_id': r[6]})
                        global_bucket_cache[key] = bucket_list
                    # process bucket_list
                    for r in bucket_list:
                        sid = r['id64']
                        star_id = r.get('star_type_id')
                        if allowed_star_ids and star_id not in allowed_star_ids:
                            continue
                        x, y, z = r['x'], r['y'], r['z']
                        dx = x - center['coords']['x']
                        dy = y - center['coords']['y']
                        dz = z - center['coords']['z']
                        d2 = dx*dx + dy*dy + dz*dz
                        if d2 <= max_d2:
                            name = id_to_prefix.get(r.get('prefix_id'), '') + (r.get('name_suffix') or '')
                            star = id_to_star.get(star_id, '')
                            out.append((d2, {'id64': sid, 'name': name, 'coords': {'x': x, 'y': y, 'z': z}, 'mainStar': star, 'star_type_id': star_id}))
        out.sort(key=lambda t: t[0])
        candidates = [t[1] for t in out[:max_neighbors]]
        # store in manual cache to speed repeated identical queries
        manual_cache[cache_key] = candidates

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


def find_path_greedy(conn: sqlite3.Connection, source: Dict, target: Dict, max_hop: float, bucket_size: float, meta: Dict, max_nodes: int = 500, max_neighbors: int = 200, allowed_star_ids: Optional[Set[int]] = None, in_memory_buckets: Optional[Dict[Tuple[int,int,int], List[Dict]]] = None, on_progress: Optional[Callable[[str], None]] = None) -> Optional[List[Dict]]:
    """Greedy approximate walk: quick fallback that moves to the neighbor closest to the target.

    This is a lightweight replacement for the old 'fast' branch. It returns a path (including source and target)
    or None if it gets stuck or cannot reach the target within max_nodes.
    on_progress: optional callback(msg) for progress updates.
    """
    def _emit(msg: str):
        try:
            if on_progress:
                on_progress(msg)
            else:
                if msg == '\n':
                    print()
                else:
                    print(msg, end='\r', flush=True)
        except Exception:
            pass

    cur = source
    visited = set([cur['id64']])
    path = [cur]
    nodes_examined = 0
    stalls = 0
    while nodes_examined < max_nodes:
        nodes_examined += 1
        if nodes_examined % PROGRESS_INTERVAL == 0:
            _emit(f"Greedy progress: examined {nodes_examined} nodes; path_len={len(path)}")
        # if target within one hop, finish
        dx = cur['coords']['x'] - target['coords']['x']
        dy = cur['coords']['y'] - target['coords']['y']
        dz = cur['coords']['z'] - target['coords']['z']
        if dx*dx + dy*dy + dz*dz <= max_hop*max_hop:
            path.append(target)
            if nodes_examined >= PROGRESS_INTERVAL:
                _emit('\n')
            return path
        neighbors = neighbors_for_center_prefix(conn, cur, max_hop, visited, bucket_size, max_neighbors=max_neighbors, meta=meta, allowed_star_ids=allowed_star_ids, in_memory_buckets=in_memory_buckets)
        if not neighbors:
            break
        # pick neighbor minimizing distance to target
        best = None
        best_d2 = None
        cur_dx = cur['coords']['x'] - target['coords']['x']
        cur_d2 = cur_dx*cur_dx + (cur['coords']['y'] - target['coords']['y'])**2 + (cur['coords']['z'] - target['coords']['z'])**2
        for n in neighbors:
            if n['id64'] in visited:
                continue
            dx = n['coords']['x'] - target['coords']['x']
            dy = n['coords']['y'] - target['coords']['y']
            dz = n['coords']['z'] - target['coords']['z']
            d2 = dx*dx + dy*dy + dz*dz
            if best is None or d2 < best_d2:
                best = n
                best_d2 = d2
        if best is None:
            break
        # if no progress (best not closer than current), allow a few stalls then give up
        if best_d2 >= cur_d2:
            stalls += 1
            if stalls > 5:
                break
        else:
            stalls = 0
        visited.add(best['id64'])
        path.append(best)
        cur = best
    if nodes_examined >= PROGRESS_INTERVAL:
        _emit('\n')
    return None


def find_path_directional(conn: sqlite3.Connection, source: Dict, target: Dict, max_hop: float, bucket_size: float, meta: Dict, max_nodes: int = 5000, max_neighbors: int = 500, allowed_star_ids: Optional[Set[int]] = None, step_threshold: float = 1.0, expand_factor: float = 2.0, in_memory_buckets: Optional[Dict[Tuple[int,int,int], List[Dict]]] = None, relax_factor: float = 1.05, fallback_to_greedy: bool = True, greedy_nodes: int = 500, greedy_neighbors: int = 200, on_progress: Optional[Callable[[str], None]] = None) -> Optional[List[Dict]]:
    """Directional stepping pathfinder (approximate, fast).

    From current system, compute a point max_hop towards target and search for a system near that point within an expanding radius starting at step_threshold.
    Repeat until target is within max_hop. Returns a list of systems (including source and target) or None.
    Progress is printed every PROGRESS_INTERVAL steps.

    Improvements to increase success rate while keeping speed:
    - If no candidate within max_hop found, try a slightly relaxed hop distance (relax_factor).
    - If that still fails and fallback_to_greedy is True, run a short greedy search from the current point to reach target.
    """
    cur = source
    path = [cur]
    visited = set([cur['id64']])
    nodes = 0
    def _emit(msg: str):
        try:
            if on_progress:
                on_progress(msg)
            else:
                # CLI fallback: mimic previous behavior (carriage-return updates)
                if msg == '\n':
                    print()
                else:
                    print(msg, end='\r', flush=True)
        except Exception:
            pass

    while nodes < max_nodes:
        nodes += 1
        # progress indicator per step
        if nodes % 2 == 0:
            try:
                dx_t = target['coords']['x'] - cur['coords']['x']
                dy_t = target['coords']['y'] - cur['coords']['y']
                dz_t = target['coords']['z'] - cur['coords']['z']
                dist_to_target = math.sqrt(dx_t*dx_t + dy_t*dy_t + dz_t*dz_t)
                _emit(f"Directional step {nodes}: at id={cur['id64']} dist_to_target={dist_to_target:.1f} path_len={len(path)}")
            except Exception:
                pass

        # check if target within a single hop
        dx = cur['coords']['x'] - target['coords']['x']
        dy = cur['coords']['y'] - target['coords']['y']
        dz = cur['coords']['z'] - target['coords']['z']
        if dx*dx + dy*dy + dz*dz <= max_hop*max_hop:
            path.append(target)
            if nodes >= PROGRESS_INTERVAL:
                _emit('\n')
            return path

        # compute step point max_hop away from cur towards target
        vx = target['coords']['x'] - cur['coords']['x']
        vy = target['coords']['y'] - cur['coords']['y']
        vz = target['coords']['z'] - cur['coords']['z']
        mag = math.sqrt(vx*vx + vy*vy + vz*vz)
        if mag == 0:
            return None
        tx = cur['coords']['x'] + (vx / mag) * max_hop
        ty = cur['coords']['y'] + (vy / mag) * max_hop
        tz = cur['coords']['z'] + (vz / mag) * max_hop

        # search for candidate near (tx,ty,tz) with expanding radius
        radius = step_threshold
        found = None
        while radius <= max_hop:
            # progress on radius
            if nodes % PROGRESS_INTERVAL == 0:
                try:
                    _emit(f"  trying radius={radius:.3f}")
                except Exception:
                    pass
            fake_center = {'id64': -1, 'coords': {'x': tx, 'y': ty, 'z': tz}}
            cands = neighbors_for_center_prefix(conn, fake_center, radius, set(), bucket_size, max_neighbors=max_neighbors, meta=meta, allowed_star_ids=allowed_star_ids, in_memory_buckets=in_memory_buckets)
            if cands:
                # sort by closeness to the step point
                cands_sorted = sorted(cands, key=lambda c: (c['coords']['x']-tx)**2 + (c['coords']['y']-ty)**2 + (c['coords']['z']-tz)**2)
                for cand in cands_sorted:
                    if cand['id64'] in visited:
                        continue
                    # enforce hop distance <= max_hop from current
                    dx_c = cand['coords']['x'] - cur['coords']['x']
                    dy_c = cand['coords']['y'] - cur['coords']['y']
                    dz_c = cand['coords']['z'] - cur['coords']['z']
                    d2_c = dx_c*dx_c + dy_c*dy_c + dz_c*dz_c
                    if d2_c <= max_hop*max_hop:
                        found = cand
                        break
                if found:
                    break
            radius *= expand_factor

        if not found:
            # try a slightly relaxed hop distance before giving up
            relaxed_max = max_hop * relax_factor
            radius = step_threshold
            while radius <= relaxed_max:
                if nodes % PROGRESS_INTERVAL == 0:
                    try:
                        _emit(f"  trying relaxed radius={radius:.3f} (relaxed max {relaxed_max:.3f})")
                    except Exception:
                        pass
                fake_center = {'id64': -1, 'coords': {'x': tx, 'y': ty, 'z': tz}}
                cands = neighbors_for_center_prefix(conn, fake_center, radius, set(), bucket_size, max_neighbors=max_neighbors, meta=meta, allowed_star_ids=allowed_star_ids, in_memory_buckets=in_memory_buckets)
                if cands:
                    cands_sorted = sorted(cands, key=lambda c: (c['coords']['x']-tx)**2 + (c['coords']['y']-ty)**2 + (c['coords']['z']-tz)**2)
                    for cand in cands_sorted:
                        if cand['id64'] in visited:
                            continue
                        dx_c = cand['coords']['x'] - cur['coords']['x']
                        dy_c = cand['coords']['y'] - cur['coords']['y']
                        dz_c = cand['coords']['z'] - cur['coords']['z']
                        d2_c = dx_c*dx_c + dy_c*dy_c + dz_c*dz_c
                        if d2_c <= relaxed_max*relaxed_max:
                            found = cand
                            break
                    if found:
                        break
                radius *= expand_factor

        if not found:
            # fallback to a short greedy search from current point to attempt to reach target
            if fallback_to_greedy:
                if nodes >= PROGRESS_INTERVAL:
                    _emit('\n')
                try:
                    _emit('Directional: falling back to short greedy search...')
                except Exception:
                    pass
                greedy_path = find_path_greedy(conn, cur, target, max_hop, bucket_size, meta, max_nodes=greedy_nodes, max_neighbors=greedy_neighbors, allowed_star_ids=allowed_star_ids, in_memory_buckets=in_memory_buckets, on_progress=_emit)
                if greedy_path:
                    # attach greedy path (skip duplicate current)
                    path.extend(greedy_path[1:])
                    if nodes >= PROGRESS_INTERVAL:
                        _emit('\n')
                    return path
            if nodes >= PROGRESS_INTERVAL:
                _emit('\n')
            return None

        # append found and continue
        visited.add(found['id64'])
        path.append(found)
        cur = found
    if nodes >= PROGRESS_INTERVAL:
        _emit('\n')
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
    parser.add_argument('--preload', action='store_true', help='Preload buckets between source and target into memory to avoid SQL roundtrips')
    parser.add_argument('--preload-margin-buckets', type=int, default=1, help='Extra bucket margin when preloading')
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
        build_index_prefix(args.file, args.db, args.bucket_size, args.meta_file, force=args.force)
        return

    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}. Run --build-index first.")
        sys.exit(1)
    if not os.path.exists(args.meta_file):
        print(f"Meta file {args.meta_file} not found; required.")
        sys.exit(1)

    with open(args.meta_file, 'r', encoding='utf-8') as mf:
        meta = json.load(mf)

    # build star name -> id map
    star_name_to_id = {v: int(k) for k, v in meta.get('starTypes', {}).items()}

    conn = open_db(args.db)

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
            cand = get_system_by_query_prefix(conn, near, meta)
            if not cand:
                print('Could not resolve --near to a system:', near)
                return
            near_coords = cand[0]['coords']
        # perform SQL nearest search among matching star_type_ids
        placeholders = ','.join('?' for _ in type_ids)
        sql = f"SELECT id64,prefix_id,name_suffix,x,y,z,star_type_id,((x-?)*(x-?)+(y-?)*(y-?)+(z-?)*(z-?)) as d2 FROM systems WHERE star_type_id IN ({placeholders}) ORDER BY d2 LIMIT 1"
        params = [near_coords['x'], near_coords['x'], near_coords['y'], near_coords['y'], near_coords['z'], near_coords['z']] + type_ids
        cur = conn.execute(sql, tuple(params))
        row = cur.fetchone()
        if not row:
            print('No matching systems found')
            return
        name = meta.get('prefixes', {}).get(str(row[1]), '') + (row[2] or '')
        dx = row[3] - near_coords['x']
        dy = row[4] - near_coords['y']
        dz = row[5] - near_coords['z']
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        print(f"Nearest: {name} id64={row[0]} dist={dist:.1f}")
        return

    # interactive prompts for pathfinding
    q1 = input('Enter first system name or id64: ').strip()
    cand1 = get_system_by_query_prefix(conn, q1, meta)
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
            return (math.floor(c['x'] / args.bucket_size), math.floor(c['y'] / args.bucket_size), math.floor(c['z'] / args.bucket_size))
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
        prefixes = meta.get('prefixes', {})
        id_to_prefix = {int(k): v for k, v in prefixes.items()}
        star_types = meta.get('starTypes', {})
        id_to_star = {int(k): v for k, v in star_types.items()}
        sql = 'SELECT id64,prefix_id,name_suffix,x,y,z,star_type_id,bx,by,bz FROM systems WHERE bx BETWEEN ? AND ? AND by BETWEEN ? AND ? AND bz BETWEEN ? AND ?'
        cur = conn.execute(sql, (min_bx, max_bx, min_by, max_by, min_bz, max_bz))
        for r in cur:
            bx_i, by_i, bz_i = r[7], r[8], r[9]
            rec = {'id64': r[0], 'prefix_id': r[1], 'name_suffix': r[2], 'x': r[3], 'y': r[4], 'z': r[5], 'star_type_id': r[6]}
            in_memory_buckets.setdefault((bx_i, by_i, bz_i), []).append(rec)

    def cli_progress(msg: str):
        if msg is None:
            return
        if msg == '\n':
            print()
        else:
            print(msg, end='\r', flush=True)

    path = find_path_directional(conn, s1, s2, args.max_hop, args.bucket_size, meta, max_nodes=args.max_nodes, max_neighbors=args.max_neighbors, allowed_star_ids=allowed_star_ids, step_threshold=args.step_threshold, expand_factor=args.step_expand_factor, in_memory_buckets=in_memory_buckets, on_progress=cli_progress)
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
        print(f" {i}) {p['name']} id64={p['id64']} coords=({c['x']},{c['y']},{c['z']}) mainStar={p.get('mainStar')} hop_dist={hop_dist:.1f}")
        prev = c
    print(f'Total path distance: {total:.1f}')
    print('Done')

if __name__ == '__main__':
    main()
