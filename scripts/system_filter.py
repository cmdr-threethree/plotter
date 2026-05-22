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
• Shows progress periodically (10k lines, or 500k in CI).

Created by: Microsoft Copilot
"""

import sys
import time
import os

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

CUBE_SIDE = int(os.environ.get("CUBE_SIDE",25))

PROGRESS_INTERVAL = 10000
if os.environ.get("CI") == "true":
    PROGRESS_INTERVAL *= 50

output_count = 0
line_count = 0
last_count = 0
last_time = time.time()

print(f"Starting, cube side {CUBE_SIDE}", file=sys.stderr)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    if line[-1] == ',':
        line = line[:-1]

    line_count += 1

    # Progress every PROGRESS_INTERVAL lines
    if line_count % PROGRESS_INTERVAL == 0:
        now = time.time()
        dt = now - last_time
        dl = line_count - last_count
        lps = dl / dt if dt > 0 else 0.0
        print(f"Processed {line_count:,} lines, output {output_count:,}...  {lps:,.0f} lines/s",
              end="\r", file=sys.stderr)
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
        output_count += 1
        continue

    # RULE 2A: Non-common star types → always output
    if star not in COMMON:
        print(json_dumps(obj))
        output_count += 1
        continue

    # RULE 2B: Common star types → one per CUBE_SIDE^3 cube
    coords = obj.get("coords") or obj.get("coordsLocked") or obj.get("coordsLockedApprox")
    if not coords:
        continue

    x = coords.get("x")
    y = coords.get("y")
    z = coords.get("z")
    if x is None or y is None or z is None:
        continue

    xc = int(x // CUBE_SIDE)
    yc = int(y // CUBE_SIDE)
    zc = int(z // CUBE_SIDE)

    h = hash((xc, yc, zc))

    if h not in seen_cubes:
        seen_cubes.add(h)
        print(json_dumps(obj))
        output_count += 1

print(f"\nFinished. Total lines processed: {line_count:,}, output: {output_count:,}", file=sys.stderr)
