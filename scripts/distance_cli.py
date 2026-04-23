#!/usr/bin/env python3
"""
Interactive distance calculator for systems stored in a large JSON array (systems_1day.json).
Searches the data file line-by-line (streaming) so it never loads the whole file into memory.

Usage examples:
  python3 scripts/distance_cli.py            # interactive prompts
  python3 scripts/distance_cli.py --file path/to/systems_1day.json

Search behaviour:
- Enter either an id64 (integer) or a partial/full name. Partial name matches are case-insensitive.
- If multiple candidates are found, the tool shows up to 10 matches and lets you choose.

"""

import argparse
import json
import math
import os
import re
import sys
from typing import Optional, Dict, List

DEFAULT_FILE = "systems_neutron.json"
MAX_CANDIDATES = 10


def clean_json_line(line: str) -> Optional[str]:
    """Strip trailing commas and whitespace and ensure the line looks like a JSON object.
    Returns cleaned JSON string or None if line is not an object.
    """
    s = line.strip()
    # Skip array markers
    if not s:
        return None
    if s in ("[", "]"):
        return None
    # Remove trailing comma
    if s.endswith(','):
        s = s[:-1]
    # Only parse if it starts with '{'
    if not s.startswith('{'):
        return None
    return s


def parse_line_object(line: str) -> Optional[Dict]:
    s = clean_json_line(line)
    if s is None:
        return None
    try:
        obj = json.loads(s)
        return obj
    except json.JSONDecodeError:
        # If parsing fails, skip this line
        return None


def find_candidates(file_path: str, query: str, max_results: int = MAX_CANDIDATES) -> List[Dict]:
    """Stream the file and return up to max_results candidate objects matching query.
    If query is all digits, treat it as an id64 search.
    Otherwise perform a case-insensitive substring match on the name field.
    """
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
            # Fast-path checks to avoid JSON parsing
            if is_id:
                if '"id64"' not in line:
                    continue
                # quick substring check
                if str(q_int) not in line:
                    continue
                obj = parse_line_object(line)
                if obj is None:
                    continue
                if obj.get('id64') == q_int:
                    matches.append(obj)
            else:
                # name search
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
        # else loop again


def main():
    parser = argparse.ArgumentParser(description='Interactive system distance calculator (streaming).')
    parser.add_argument('--file', '-f', default=DEFAULT_FILE, help='Path to systems JSON file (default: systems_1day.json)')
    args = parser.parse_args()

    file_path = args.file
    if not os.path.exists(file_path):
        print(f"Data file not found: {file_path}")
        sys.exit(1)

    print("Streaming distance calculator. Matches are found by scanning the file line-by-line.")
    s1 = prompt_for_system(file_path, 'first')
    if s1 is None:
        print("Cancelled.")
        return
    s2 = prompt_for_system(file_path, 'second')
    if s2 is None:
        print("Cancelled.")
        return

    try:
        dist = distance(s1, s2)
        print('\nResult:')
        print(f" {s1.get('name')} (id64={s1.get('id64')})")
        print(f" {s2.get('name')} (id64={s2.get('id64')})")
        print(f" Euclidean distance: {dist:.6f}")
    except Exception as e:
        print(f"Failed to compute distance: {e}")


if __name__ == '__main__':
    main()
