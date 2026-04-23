#!/usr/bin/env python3
"""
Interactive distance calculator for systems stored in a large JSON array (systems_1day.json).
Searches the data file line-by-line (streaming) so it never loads the whole file into memory.

Added: path-finding mode that finds a chain of systems between two systems where each hop is
no longer than --max-hop. The search is BFS and streams the data file for neighbor discovery,
so it doesn't build an in-memory graph (may be slower but memory-safe).

Usage examples:
  python3 scripts/distance_cli_path.py                          # interactive prompts (distance only)
  python3 scripts/distance_cli_path.py --max-hop 40            # find path with max hop 40
  python3 scripts/distance_cli_path.py --file data.json --max-hop 40 --max-nodes 2000

Notes:
- BFS node exploration is capped by --max-nodes to avoid very long runs.
- You can tune --max-neighbors to limit neighbors considered per node (speed vs completeness).

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


def find_candidates(file_path: str, query: str, max_results: int = MAX_CANDIDATES) -> List[Dict]:
    is_id = False
    try:
        q_int = int(query)
        is_id = True
    except Exception:
        is_id = False

    matches: List[Dict] = []
    lower_q = query.lower()

    with open(file_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            if is_id:
                if '"id64"' not in line:
                    continue
                if str(q_int) not in line:
                    continue
                obj = parse_line_object(line)
                if obj is None:
                    continue
                if obj.get('id64') == q_int:
                    matches.append(obj)
            else:
                if '"name"' not in line:
                    continue
                if lower_q not in line.lower():
                    continue
                obj = parse_line_object(line)
                if obj is None:
                    continue
                name = obj.get('name', '')
                if lower_q in name.lower():
                    matches.append(obj)

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


def distance(a: Dict, b: Dict) -> float:
    ax, ay, az = a['coords']['x'], a['coords']['y'], a['coords']['z']
    bx, by, bz = b['coords']['x'], b['coords']['y'], b['coords']['z']
    dx = ax - bx
    dy = ay - by
    dz = az - bz
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def find_neighbors(file_path: str, center: Dict, max_distance: float, visited: Set[int], max_neighbors: int = 500) -> List[Dict]:
    """Stream the file and return systems within max_distance of center, excluding visited id64s.
    Stops after collecting max_neighbors results to limit work per node.
    """
    neighbors: List[Dict] = []
    cx = center['coords']['x']
    cy = center['coords']['y']
    cz = center['coords']['z']

    with open(file_path, 'r', encoding='utf-8') as fh:
        for line in fh:
            if '"coords"' not in line:
                continue
            obj = parse_line_object(line)
            if obj is None:
                continue
            try:
                sid = obj.get('id64')
                if sid is None or sid in visited:
                    continue
                coords = obj.get('coords')
                if not coords:
                    continue
                dx = coords['x'] - cx
                dy = coords['y'] - cy
                dz = coords['z'] - cz
                d2 = dx * dx + dy * dy + dz * dz
                if d2 <= max_distance * max_distance:
                    neighbors.append(obj)
            except Exception:
                continue
            if len(neighbors) >= max_neighbors:
                break
    return neighbors


def find_path_bfs(file_path: str, source: Dict, target: Dict, max_hop: float, max_nodes: int = 1000, max_neighbors: int = 500) -> Optional[List[Dict]]:
    """BFS search for a path from source to target where each hop <= max_hop.
    Returns list of system objects from source to target or None if not found.
    """
    from collections import deque

    src_id = source.get('id64')
    tgt_id = target.get('id64')
    if src_id == tgt_id:
        return [source]

    visited: Set[int] = set([src_id])
    parent: Dict[int, int] = {}
    node_obj: Dict[int, Dict] = {src_id: source}

    q = deque([src_id])
    nodes_examined = 0

    while q:
        current_id = q.popleft()
        current_obj = node_obj[current_id]
        nodes_examined += 1
        if nodes_examined > max_nodes:
            print(f"Reached max node limit ({max_nodes}). Aborting search.")
            return None
        # find neighbors streaming
        neighbors = find_neighbors(file_path, current_obj, max_hop, visited, max_neighbors=max_neighbors)
        for n in neighbors:
            nid = n.get('id64')
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


def prompt_for_system(file_path: str, which: str) -> Optional[Dict]:
    while True:
        user = input(f"Enter {which} system name or id64 (or 'q' to quit): ")
        if not user:
            continue
        if user.strip().lower() in ('q', 'quit', 'exit'):
            return None
        candidates = find_candidates(file_path, user.strip())
        chosen = choose_candidate(candidates, which)
        if chosen is not None:
            return chosen


def main():
    parser = argparse.ArgumentParser(description='Interactive system distance calculator (streaming).')
    parser.add_argument('--file', '-f', default=DEFAULT_FILE, help='Path to systems JSON file (default: systems_1day.json)')
    parser.add_argument('--max-hop', type=float, help='If provided, find a path where each hop is <= this distance')
    parser.add_argument('--max-nodes', type=int, default=1000, help='Max nodes to explore during BFS (default: 1000)')
    parser.add_argument('--max-neighbors', type=int, default=500, help='Max neighbors to consider per node (default: 500)')
    args = parser.parse_args()

    file_path = args.file
    if not os.path.exists(file_path):
        print(f"Data file not found: {file_path}")
        sys.exit(1)

    print("Streaming distance/path calculator. Matches are found by scanning the file line-by-line.")
    s1 = prompt_for_system(file_path, 'first')
    if s1 is None:
        print("Cancelled.")
        return
    s2 = prompt_for_system(file_path, 'second')
    if s2 is None:
        print("Cancelled.")
        return

    try:
        total_dist = distance(s1, s2)
        print('\nDirect Euclidean distance: {:.6f}'.format(total_dist))
        if args.max_hop is None:
            print('No --max-hop provided; done.')
            return

        max_hop = args.max_hop
        if total_dist <= max_hop:
            print(f"Systems are within max-hop ({max_hop}); direct hop is sufficient.")
            return

        print(f"Searching for path with max hop {max_hop} (this may be slow).")
        path = find_path_bfs(file_path, s1, s2, max_hop, max_nodes=args.max_nodes, max_neighbors=args.max_neighbors)
        if path is None:
            print("No path found within the given constraints.")
            return

        print("Path found (sequence of systems):")
        for i, p in enumerate(path):
            coords = p.get('coords', {})
            print(f" {i+1}) {p.get('name')} id64={p.get('id64')} coords=({coords.get('x')},{coords.get('y')},{coords.get('z')})")
        # also show hop distances
        print('\nHop distances:')
        for i in range(len(path)-1):
            d = distance(path[i], path[i+1])
            print(f" {i+1}) {path[i].get('name')} -> {path[i+1].get('name')}: {d:.6f}")
        print(f"Total legs: {len(path)-1}")

    except Exception as e:
        print(f"Failed to compute: {e}")


if __name__ == '__main__':
    main()
