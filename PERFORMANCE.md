# Performance Analysis & Optimization Roadmap

Analyzed: `scripts/distance_cli_sqlite_prefix.py`  
Context: systems dataset with very large row counts (target: 10 M+ systems).

---

## 1. Database Schema — Storage Size

### 1.1 Coordinates stored as 8-byte doubles (REAL) — save ~12 bytes/row

Elite Dangerous coordinates have a fixed precision of 1/32 ly (0.03125). The full galaxy
range is ±65 000 ly. Multiplying by 32 yields a maximum integer value of ~2 100 000, which
fits in a signed INT32 (4 bytes). Storing `x`, `y`, `z` as scaled INT32 instead of REAL
cuts coordinate storage from 24 → 12 bytes per row.

**Impact:** ~120 MB saved per 10 M rows on the table alone (before indexes).

**Implementation:**
- Add `--coord-scale` argument (default 32) to the build step.
- Change column types: `x INTEGER, y INTEGER, z INTEGER` (SQLite stores them in 3–4 bytes).
- All coordinate arithmetic must divide by the scale factor after reading:
  ```python
  COORD_SCALE = 32
  # on insert:  ix = round(float(coords['x']) * COORD_SCALE)
  # on read:    x_float = row['x'] / COORD_SCALE
  ```
- The bucket formula changes to:
  `bx = floor(ix / (bucket_size * COORD_SCALE))`
- Store `COORD_SCALE` in the meta JSON so readers always know the factor.

---

### 1.2 bx/by/bz columns are redundant — replace with SQLite R-tree

`bx`, `by`, `bz` exist solely to support `idx_buckets ON systems(bx,by,bz)`.  
They cost ~7 bytes/row on the table; the index itself adds further overhead.

**Better alternative: SQLite R-tree virtual table**

```sql
CREATE VIRTUAL TABLE rtree_systems USING rtree(
    id64,
    min_x, max_x,
    min_y, max_y,
    min_z, max_z
);
```

For point data `min_x = max_x = x` etc. R-tree provides O(log n) range queries on 3D data
and removes the need for bx/by/bz entirely.

**Impact:**
- Removes 3 columns (~7 bytes/row on the main table).
- R-tree internal storage is compact and avoids the large B-tree overhead of idx_buckets.
- Spatial range queries become a single indexed scan instead of iterating bucket cells.

**Implementation:**
- Drop `bx`, `by`, `bz` columns and `idx_prefix` on systems.
- Create the R-tree table alongside the main table.
- On insert: populate both `systems` and `rtree_systems`.
- Replace all `WHERE bx=? AND by=? AND bz=?` queries with:
  ```sql
  SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, s.star_type_id
  FROM rtree_systems r
  JOIN systems s ON s.id64 = r.id64
  WHERE r.min_x BETWEEN ? AND ?
    AND r.min_y BETWEEN ? AND ?
    AND r.min_z BETWEEN ? AND ?
  ```
  Range bounds: `(center - max_distance, center + max_distance)` on each axis.

---

### 1.3 SQLite build-time PRAGMA — set page_size before any schema

Must be the very first command on a new database (before `CREATE TABLE`):

```python
conn.execute('PRAGMA page_size = 8192;')
```

A page size of 8192 reduces B-tree depth for large tables and can trim 5–10% from the file.
Has no effect if set after the schema already exists.

---

### 1.4 Run VACUUM after build

After `build-index` completes:
```python
conn.execute('VACUUM;')
```
Reclaims fragmented pages caused by the batch-insert pattern and can reduce file size by
several percent.

---

## 2. Query Performance — Pathfinding

### 2.1 Directional pathfinder makes multiple DB queries per hop (critical)

**Location:** `find_path_directional`, lines ~512–565

**Problem:** For each hop, the code loops with an expanding radius, calling
`neighbors_for_center_prefix` multiple times:

```python
radius = step_threshold        # default 1.0
while radius <= max_hop:       # up to log2(40) ≈ 6 iterations
    cands = neighbors_for_center_prefix(conn, fake_center, radius, ...)
    radius *= expand_factor    # doubles each time
```

Worse: the fake center uses `id64 = -1`, which **never hits the manual_cache**, so each
iteration goes all the way to SQLite or the bucket cache.

**Fix:** Query once for all candidates within `max_hop`, then pick the best by proximity to
the step point. If no candidate found within the initial threshold, still fall back to a
single broader query rather than repeated doubling.

```python
# Single query: all candidates within max_hop of the step point
cands = neighbors_for_center_prefix(conn, fake_center, max_hop, visited, ...)
if cands:
    # sort by closeness to step point, pick first that is within max_hop of cur
    found = min((c for c in cands if dist(c, cur) <= max_hop),
                key=lambda c: dist(c, fake_center), default=None)
```

---

### 2.2 id_to_prefix / id_to_star dicts rebuilt on every neighbor call

**Location:** `neighbors_for_center_prefix`, lines ~318–321

```python
id_to_prefix = {int(k): v for k, v in prefixes.items()}   # rebuilt every call
id_to_star   = {int(k): v for k, v in star_types.items()}
```

These are constant for the lifetime of a query session. Rebuilding them inside a hot loop
that is called hundreds of times per pathfinding run wastes CPU.

**Fix:** Build them once in `main()` after loading the meta file and pass them as
pre-computed dicts into the neighbor/pathfinding functions, or cache them as module-level
attributes set once.

---

### 2.3 global_bucket_cache has no size limit

**Location:** module-level `global_bucket_cache = {}`, used in `neighbors_for_center_prefix`

For very large datasets with diverse paths, this dict grows without bound and can exhaust
RAM.

**Fix:** Replace with an LRU cache:

```python
from functools import lru_cache
# or use collections.OrderedDict with a max size

MAX_BUCKET_CACHE = 4096   # tune based on available RAM and bucket_size
```

Alternatively, rely on `--preload` (which already loads all relevant buckets into a local
dict) and disable the global cache when preloading is active — the global cache is already
bypassed when `in_memory_buckets is not None`.

---

### 2.4 nearest-type does a full table scan sorted by distance (critical)

**Location:** `main()`, lines ~705–717

```python
sql = "SELECT ... ((x-?)*(x-?)+(y-?)*(y-?)+(z-?)*(z-?)) as d2
       FROM systems WHERE star_type_id IN (...)
       ORDER BY d2 LIMIT 1"
```

This computes a Euclidean distance for **every row** of the matching star type and sorts
the entire result — O(n) with no spatial pruning. For 10 M systems with a common type this
is catastrophically slow.

**Fix:** Use an expanding-radius R-tree search:

```python
def nearest_of_type(conn, near_coords, type_ids, bucket_size, meta):
    """Find the nearest system of matching star type using expanding radius."""
    radius = bucket_size
    while True:
        cx, cy, cz = near_coords['x'], near_coords['y'], near_coords['z']
        rows = conn.execute('''
            SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, s.star_type_id
            FROM rtree_systems r
            JOIN systems s ON s.id64 = r.id64
            WHERE r.min_x BETWEEN ? AND ?
              AND r.min_y BETWEEN ? AND ?
              AND r.min_z BETWEEN ? AND ?
              AND s.star_type_id IN ({})
        '''.format(','.join('?' * len(type_ids))),
            (cx-radius, cx+radius, cy-radius, cy+radius, cz-radius, cz+radius, *type_ids)
        ).fetchall()
        # filter exact sphere and find minimum
        best = min(
            (r for r in rows if (r[3]-cx)**2 + (r[4]-cy)**2 + (r[5]-cz)**2 <= radius**2),
            key=lambda r: (r[3]-cx)**2 + (r[4]-cy)**2 + (r[5]-cz)**2,
            default=None
        )
        if best or radius > 200_000:  # give up if past galaxy diameter
            return best
        radius *= 2
```

---

## 3. SQLite Connection PRAGMAs — easy wins for query sessions

Add to `open_db()`:

```python
def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=OFF;')
    conn.execute('PRAGMA temp_store=MEMORY;')
    conn.execute('PRAGMA cache_size = -65536;')   # 64 MB page cache (was ~2 MB default)
    conn.execute('PRAGMA mmap_size = 2147483648;') # 2 GB memory-mapped reads
    return conn
```

`cache_size = -65536` means 65 536 KiB (negative sign = KiB units). Adjust to available RAM.  
`mmap_size` avoids repeated syscalls for read-heavy workloads.

---

## 4. Priority Order for Implementation

| Priority | Change | Effort | Impact |
|---|---|---|---|
| 1 | Add PRAGMA cache_size + mmap_size to open_db | trivial | moderate query speed |
| 2 | Fix directional pathfinder: single neighbor query per hop | low | major speed improvement |
| 3 | Pre-build id_to_prefix / id_to_star outside hot loop | low | moderate speed |
| 4 | LRU-limit global_bucket_cache | low | prevents OOM on large datasets |
| 5 | Fix nearest-type with R-tree expanding radius | medium | critical for large data |
| 6 | Replace bx/by/bz + idx_buckets with R-tree virtual table | medium | large size + speed |
| 7 | Store x/y/z as scaled INT32 (scale=32) | medium | ~12 bytes/row size saving |
| 8 | Set page_size=8192 at build time | trivial (rebuild required) | 5–10% size |
| 9 | Run VACUUM after build | trivial | reclaims fragmentation |

Items 6 and 7 require a **full index rebuild** and are not backwards-compatible with
existing DB files. Implement together as a new DB version with a schema version marker
stored in a `meta` table.

---

## 5. Optional: NumPy for bulk distance computation

When `--preload` is active and large buckets are loaded into memory, replacing the Python
distance loop with NumPy vectorized operations can give a 10–50× speedup on the candidate
filtering step:

```python
import numpy as np

coords = np.array([[r['x'], r['y'], r['z']] for r in all_candidates])
center = np.array([cx, cy, cz])
d2 = np.sum((coords - center) ** 2, axis=1)
mask = d2 <= max_distance ** 2
filtered = [all_candidates[i] for i in np.where(mask)[0]]
```

NumPy is an optional dependency; guard with `try: import numpy`.
