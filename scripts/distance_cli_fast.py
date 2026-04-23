#!/usr/bin/env python3
"""
Faster interactive distance and path finder.
Loads the system list once into memory and caches neighbor searches to avoid repeated file scans.

Usage:
  python3 scripts/distance_cli_fast.py --file systems_1day.json --max-hop 40

Notes:
- This trades memory for speed: systems are read into memory once. For very large dumps this may use significant RAM.
- Neighbor results are cached per-node per-hop (rounded) to speed BFS.
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


def load_systems(file_path: str) -> Tuple[List[Dict], Dict[int, Dict]]:
    """Read the file once and return a list of system objects and an id->obj map.
    Each object contains only id64, name, coords for memory compactness.
    """
    systems: List[Dict] = []
    id_map: Dict[int, Dict] = {}
    with open(file_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            if '{' not in line:
                continue
            obj = parse_line_object(line)
            if obj is None:
                continue
            try:
                sid = obj.get('id64')
                name = obj.get('name')
                coords = obj.get('coords')
                if sid is None or name is None or coords is None:
                    continue
                # Keep minimal representation
                s = {'id64': int(sid), 'name': name, 'coords': {'x': float(coords['x']), 'y': float(coords['y']), 'z': float(coords['z'])}}
                systems.append(s)
                id_map[s['id64']] = s
            except Exception:
                continue
    return systems, id_map


def find_candidates_in_memory(systems: List[Dict], id_map: Dict[int, Dict], query: str, max_results: int = MAX_CANDIDATES) -> List[Dict]:
    try:
        q_int = int(query)
        # direct id lookup
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
        # key: (node_id, hop_key) -> list of neighbor ids
        self.cache: Dict[Tuple[int, int], List[int]] = {}

    @staticmethod
    def hop_key(hop: float) -> int:
        # quantize hop to millesimal to make stable keys
        return int(round(hop * 1000))

    def get(self, node_id: int, hop: float) -> Optional[List[int]]:
        return self.cache.get((node_id, self.hop_key(hop)))

    def set(self, node_id: int, hop: float, neighbors: List[int]):
        self.cache[(node_id, self.hop_key(hop))] = neighbors


def find_neighbors_in_memory(systems: List[Dict], id_map: Dict[int, Dict], center: Dict, max_distance: float, visited: Set[int], max_neighbors: int = 500, cache: Optional[NeighborCache] = None) -> List[Dict]:
    # use cache if available
    if cache is not None:
        cached = cache.get(center['id64'], max_distance)
        if cached is not None:
            # return objects excluding visited
            out = [id_map[i] for i in cached if i not in visited]
            return out[:max_neighbors]

    max_d2 = max_distance * max_distance
    neighbors_ids: List[int] = []
    # iterate all systems and collect neighbor ids; this is in-memory so fast
    for s in systems:
        sid = s['id64']
        if sid == center['id64'] or sid in visited:
            continue
        d2 = euclid_dist_sq(center, s)
        if d2 <= max_d2:
            neighbors_ids.append(sid)
            if len(neighbors_ids) >= max_neighbors:
                break

    if cache is not None:
        cache.set(center['id64'], max_distance, neighbors_ids)
    return [id_map[i] for i in neighbors_ids]


def find_path_bfs_in_memory(systems: List[Dict], id_map: Dict[int, Dict], source: Dict, target: Dict, max_hop: float, max_nodes: int = 5000, max_neighbors: int = 500) -> Optional[List[Dict]]:
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
        neighbors = find_neighbors_in_memory(systems, id_map, current_obj, max_hop, visited, max_neighbors=max_neighbors, cache=cache)
        for n in neighbors:
            nid = n['id64']
            if nid in visited:
                continue
            visited.add(nid)
            parent[nid] = current_id
            node_obj[nid] = n
            if nid == tgt_id:
                # reconstruct path
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
    parser = argparse.ArgumentParser(description='Interactive system distance/path calculator (fast, in-memory).')
    parser.add_argument('--file', '-f', default=DEFAULT_FILE, help='Path to systems JSON file (default: systems_1day.json)')
    parser.add_argument('--max-hop', type=float, help='If provided, find a path where each hop is <= this distance')
    parser.add_argument('--max-nodes', type=int, default=5000, help='Max nodes to explore during BFS (default: 5000)')
    parser.add_argument('--max-neighbors', type=int, default=500, help='Max neighbors to consider per node (default: 500)')
    args = parser.parse_args()

    file_path = args.file
    if not os.path.exists(file_path):
        print(f"Data file not found: {file_path}")
        sys.exit(1)

    print("Loading systems into memory (one-time). This speeds up pathfinding but uses more RAM.")
    systems, id_map = load_systems(file_path)
    print(f"Loaded {len(systems)} systems.")

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

        print(f"Searching for path with max hop {max_hop} (BFS in-memory).")
        path = find_path_bfs_in_memory(systems, id_map, s1, s2, max_hop, max_nodes=args.max_nodes, max_neighbors=args.max_neighbors)
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
