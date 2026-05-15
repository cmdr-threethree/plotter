#!/usr/bin/env python3
"""
Elite Dangerous System Filter Script
------------------------------------

This script processes the massive Spansh "systems.jsonl" data dump in a
streaming, memory‑efficient way. It was created by Microsoft Copilot to help
extract a meaningful subset of systems for exploration, mapping, or custom
galaxy analysis.

WHY THIS SCRIPT EXISTS
----------------------
The full Spansh systems dump contains ~140 million systems. Most of them
are common star types (M, K, G, F, A, etc.) and densely packed. Keeping
all of them is unnecessary for many use cases, so this script applies
three filtering rules to dramatically reduce the dataset size while
preserving interesting or unique systems.

FILTERING RULES
---------------
1. If the system name does NOT contain a "-" character:
       → ALWAYS output it.
   These are usually hand‑placed, lore, or special systems.

2. If the system name DOES contain "-":
   2A. If the star type is NON‑COMMON:
           → ALWAYS output it.
       These include neutron stars, black holes, white dwarfs,
       Wolf‑Rayet stars, carbon stars, etc.

   2B. If the star type IS COMMON:
           → Output ONLY ONE system per 5×5×5 ly cube.
       This down‑samples the dense regions of the galaxy while keeping
       spatial coverage.

PERFORMANCE FEATURES
--------------------
• Uses orjson automatically if installed (5× faster JSON parsing).
• Falls back to Python's json module with a warning.
• Uses Python's built‑in tuple hashing for cube tracking (fast, low‑memory).
• Streams input line‑by‑line (safe for multi‑GB files).
• Shows progress every 10k lines, including lines/second throughput.

Created by: Microsoft Copilot
"""

import sys
import time

# Try to import orjson for speed
try:
    import orjson
    def json_loads(s):
        return orjson.loads(s)
    def json_dumps(obj):
        return orjson.dumps(obj).decode()
    print("Using orjson for fast parsing", file=sys.stderr)
except ImportError:
    import json
    def json_loads(s):
        return json.loads(s)
    def json_dumps(obj):
        return json.dumps(obj)
    print("Warning: orjson not installed. Install it for 3–5× faster parsing: pip install orjson",
          file=sys.stderr)

COMMON = {
    "M (Red dwarf) Star",
    "K (Yellow-Orange) Star",
    "F (White) Star",
    "G (White-Yellow) Star",
    "A (Blue-White) Star",
    "T (Brown dwarf) Star",
    "L (Brown dwarf) Star",
    "Y (Brown dwarf) Star",
    "B (Blue-White) Star",
    "T Tauri Star",
}

seen_cubes = set()

line_count = 0
last_count = 0
last_time = time.time()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    if line[-1] == ',':
        line = line[:-1]

    line_count += 1

    # Progress every 10k lines
    if line_count % 10000 == 0:
        now = time.time()
        dt = now - last_time
        dl = line_count - last_count
        lps = dl / dt if dt > 0 else 0.0
        print(f"\rProcessed {line_count:,} lines...  {lps:,.0f} lines/s",
              end="", file=sys.stderr)
        last_time = now
        last_count = line_count

    try:
        obj = json_loads(line)
    except Exception:
        continue

    name = obj.get("name")
    star = obj.get("mainStar")
    if not name or not star:
        continue

    # RULE 1: If name does NOT contain "-", always output
    if "-" not in name:
        print(json_dumps(obj))
        continue

    # RULE 2A: Non-common star types → always output
    if star not in COMMON:
        print(json_dumps(obj))
        continue

    # RULE 2B: Common star types → one per 5x5x5 cube
    coords = obj.get("coords") or obj.get("coordsLocked") or obj.get("coordsLockedApprox")
    if not coords:
        continue

    x = coords.get("x")
    y = coords.get("y")
    z = coords.get("z")
    if x is None or y is None or z is None:
        continue

    xc = int(x // 5)
    yc = int(y // 5)
    zc = int(z // 5)

    h = hash((xc, yc, zc))

    if h not in seen_cubes:
        seen_cubes.add(h)
        print(json_dumps(obj))

print(f"\rFinished. Total lines processed: {line_count:,}", file=sys.stderr)
