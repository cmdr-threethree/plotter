#!/usr/bin/env python3
"""
Interactive fast distance and path finder using spatial bucketing index.
Loads systems into memory once, builds a 3D grid index (buckets) of coordinates to reduce neighbor search.

Usage:
  python3 scripts/distance_cli_indexed.py --file systems_1day.json --max-hop 40 --bucket-size 50

Options:
  --bucket-size FLOAT   Size of spatial buckets (default: 50). Smaller buckets -> finer index -> faster neighbor queries but more buckets.
  --max-hop FLOAT       Maximum allowed hop length for pathfinding (required for path mode).
  --max-nodes INT       Max BFS nodes (default: 5000)
  --max-neighbors INT   Max neighbors per node to consider (default: 500)

This trades memory for speed: build index once and perform neighbor queries by scanning only nearby buckets.
"""

import argparse
import json
import math
import os
import sys
from typing import Optional, Dict, List, Set, Tuple

DEFAULT_FILE = "systems_neutron.json"
MAX_CANDIDATES = 10


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


def load_systems_and_index(file_path: str, bucket_size: float) -> Tuple[List[Dict], Dict[int, Dict], Dict[Tuple[int,int,int], List[int]]]:
    systems: List[Dict] = []
    id_map: Dict[int, Dict] = {}
    index: Dict[Tuple[int,int,int], List[int]] = {}

    def bucket_coords(x: float, y: float, z: float) -> Tuple[int,int,int]:
        return (math.floor(x / bucket_size), math.floor(y / bucket_size), math.floor(z / bucket_size))

    with open(file_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            if '{' not in line:
                continue
            obj = parse_line_object(line)
            if obj is None:
                continue
            try:
                sid = int(obj.get('id64'))
                name = obj.get('name')
                coords = obj.get('coords')
                if name is None or coords is None:
                    continue
                sx = float(coords['x']); sy = float(coords['y']); sz = float(coords['z'])
                s = {'id64': sid, 'name': name, 'coords': {'x': sx, 'y': sy, 'z': sz}}
                systems.append(s)
                id_map[sid] = s
                b = bucket_coords(sx, sy, sz)
                index.setdefault(b, []).append(sid)
            except Exception:
                continue
    return systems, id_map, index


def find_candidates_in_memory(systems: List[Dict], id_map: Dict[int, Dict], query: str, max_results: int = MAX_CANDIDATES) -> List[Dict]:
    try:
        q_int = int(query)
        obj = id_map.get(q_int)
        return [obj] if obj is not None else []
    except Exception:
        q = query.lower()
        matches: List[Dict] = []
        for s in systems:
            if q in s['name'].lower():
                matches.append(s)
                if len(matches) >= max_results:
                    break
        return matches


def choose_candidate(candidates: List[Dict], prompt_name: str) -> Optional[Dict]:
    if not candidates:
        print(f"No matches found for {prompt_name}.")
        return None
    if len(candidates) == 1:
        obj = candidates[0]
        print(f"Selected: {obj.get('name')} (id64={obj.get('id64')}) coords={obj.get('coords')}")
        return obj
    print(f"Multiple matches for {prompt_name}. Choose one:")
    for i, c in enumerate(candidates, start=1):
        coords = c.get('coords') or {}
        print(f" {i}) {c.get('name')}  id64={c.get('id64')}  coords=({coords.get('x')},{coords.get('y')},{coords.get('z')})")
    while True:
        choice = input(f"Enter selection [1-{len(candidates)}] or 0 to cancel: ")
        if not choice.isdigit():
            print("Please enter a number.")
            continue
        idx = int(choice)
        if idx == 0:
            return None
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1]
        print("Out of range.")


def euclid_dist_sq(a: Dict, b: Dict) -> float:
    dx = a['coords']['x'] - b['coords']['x']
    dy = a['coords']['y'] - b['coords']['y']
    dz = a['coords']['z'] - b['coords']['z']
    return dx * dx + dy * dy + dz * dz


class NeighborCache:
    def __init__(self):
        self.cache: Dict[Tuple[int,int], List[int]] = {}
    @staticmethod
    def hop_key(hop: float) -> int:
        return int(round(hop * 1000))
    def get(self, node_id: int, hop: float) -> Optional[List[int]]:
        return self.cache.get((node_id, self.hop_key(hop)))
    def set(self, node_id: int, hop: float, neighbors: List[int]):
        self.cache[(node_id, self.hop_key(hop))] = neighbors


def find_neighbors_indexed(systems: List[Dict], id_map: Dict[int, Dict], index: Dict[Tuple[int,int,int], List[int]], center: Dict, max_distance: float, visited: Set[int], bucket_size: float, max_neighbors: int = 500, cache: Optional[NeighborCache] = None) -> List[Dict]:
    if cache is not None:
        cached = cache.get(center['id64'], max_distance)
        if cached is not None:
            return [id_map[i] for i in cached if i not in visited][:max_neighbors]

    bx = math.floor(center['coords']['x'] / bucket_size)
    by = math.floor(center['coords']['y'] / bucket_size)
    bz = math.floor(center['coords']['z'] / bucket_size)
    radius_buckets = int(math.ceil(max_distance / bucket_size))
    max_d2 = max_distance * max_distance

    neighbor_ids: List[int] = []
    seen: Set[int] = set()
    # iterate nearby buckets only
    for dx in range(-radius_buckets, radius_buckets+1):
        for dy in range(-radius_buckets, radius_buckets+1):
            for dz in range(-radius_buckets, radius_buckets+1):
                key = (bx+dx, by+dy, bz+dz)
                bucket_list = index.get(key)
                if not bucket_list:
                    continue
                for sid in bucket_list:
                    if sid == center['id64'] or sid in visited or sid in seen:
                        continue
                    seen.add(sid)
                    s = id_map.get(sid)
                    if s is None:
                        continue
                    if euclid_dist_sq(center, s) <= max_d2:
                        neighbor_ids.append(sid)
                        if len(neighbor_ids) >= max_neighbors:
                            break
                if len(neighbor_ids) >= max_neighbors:
                    break
            if len(neighbor_ids) >= max_neighbors:
                break
        if len(neighbor_ids) >= max_neighbors:
            break

    if cache is not None:
        cache.set(center['id64'], max_distance, neighbor_ids)
    return [id_map[i] for i in neighbor_ids]


def find_path_bfs_indexed(systems: List[Dict], id_map: Dict[int, Dict], index: Dict[Tuple[int,int,int], List[int]], source: Dict, target: Dict, max_hop: float, bucket_size: float, max_nodes: int = 5000, max_neighbors: int = 500) -> Optional[List[Dict]]:
    from collections import deque
    src_id = source['id64']
    tgt_id = target['id64']
    if src_id == tgt_id:
        return [source]

    visited: Set[int] = set([src_id])
    parent: Dict[int, int] = {}
    node_obj: Dict[int, Dict] = {src_id: source}
    q = deque([src_id])
    cache = NeighborCache()
    nodes_examined = 0

    while q:
        current_id = q.popleft()
        current_obj = node_obj[current_id]
        nodes_examined += 1
        if nodes_examined > max_nodes:
            print(f"Reached max node limit ({max_nodes}). Aborting search.")
            return None
        neighbors = find_neighbors_indexed(systems, id_map, index, current_obj, max_hop, visited, bucket_size, max_neighbors=max_neighbors, cache=cache)
        for n in neighbors:
            nid = n['id64']
            if nid in visited:
                continue
            visited.add(nid)
            parent[nid] = current_id
            node_obj[nid] = n
            if nid == tgt_id:
                path_ids = [tgt_id]
                while path_ids[-1] != src_id:
                    path_ids.append(parent[path_ids[-1]])
                path_ids.reverse()
                return [node_obj[i] for i in path_ids]
            q.append(nid)
    return None


def prompt_for_system(systems: List[Dict], id_map: Dict[int, Dict], which: str) -> Optional[Dict]:
    while True:
        user = input(f"Enter {which} system name or id64 (or 'q' to quit): ")
        if not user:
            continue
        if user.strip().lower() in ('q', 'quit', 'exit'):
            return None
        candidates = find_candidates_in_memory(systems, id_map, user.strip())
        chosen = choose_candidate(candidates, which)
        if chosen is not None:
            return chosen


def main():
    parser = argparse.ArgumentParser(description='Interactive distance/path calculator using spatial index.')
    parser.add_argument('--file', '-f', default=DEFAULT_FILE, help='Path to systems JSON file (default: systems_1day.json)')
    parser.add_argument('--bucket-size', type=float, default=50.0, help='Bucket size for spatial index (default 50)')
    parser.add_argument('--max-hop', type=float, help='If provided, find a path where each hop is <= this distance')
    parser.add_argument('--max-nodes', type=int, default=5000, help='Max nodes to explore during BFS (default: 5000)')
    parser.add_argument('--max-neighbors', type=int, default=500, help='Max neighbors to consider per node (default: 500)')
    args = parser.parse_args()

    file_path = args.file
    if not os.path.exists(file_path):
        print(f"Data file not found: {file_path}")
        sys.exit(1)

    print("Loading systems into memory and building spatial index...")
    systems, id_map, index = load_systems_and_index(file_path, args.bucket_size)
    print(f"Loaded {len(systems)} systems, index has {len(index)} buckets.")

    s1 = prompt_for_system(systems, id_map, 'first')
    if s1 is None:
        print("Cancelled.")
        return
    s2 = prompt_for_system(systems, id_map, 'second')
    if s2 is None:
        print("Cancelled.")
        return

    try:
        total_d = math.sqrt(euclid_dist_sq(s1, s2))
        print('\nDirect Euclidean distance: {:.6f}'.format(total_d))
        if args.max_hop is None:
            print('No --max-hop provided; done.')
            return
        max_hop = args.max_hop
        if total_d <= max_hop:
            print(f"Systems are within max-hop ({max_hop}); direct hop is sufficient.")
            return

        print(f"Searching for path with max hop {max_hop} using bucket size {args.bucket_size} (BFS indexed).")
        path = find_path_bfs_indexed(systems, id_map, index, s1, s2, max_hop, args.bucket_size, max_nodes=args.max_nodes, max_neighbors=args.max_neighbors)
        if path is None:
            print("No path found within the given constraints.")
            return

        print("Path found (sequence of systems):")
        for i, p in enumerate(path):
            coords = p.get('coords', {})
            print(f" {i+1}) {p.get('name')} id64={p.get('id64')} coords=({coords.get('x')},{coords.get('y')},{coords.get('z')})")
        print('\nHop distances:')
        total = 0.0
        for i in range(len(path)-1):
            d = math.sqrt(euclid_dist_sq(path[i], path[i+1]))
            total += d
            print(f" {i+1}) {path[i].get('name')} -> {path[i+1].get('name')}: {d:.6f}")
        print(f"Total legs: {len(path)-1}, total path distance: {total:.6f}")

    except Exception as e:
        print(f"Failed to compute: {e}")


if __name__ == '__main__':
    main()
