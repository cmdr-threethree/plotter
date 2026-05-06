# Performance Analysis & Optimization Roadmap — IMPLEMENTED

Analyzed: `scripts/distance_cli_sqlite_prefix.py`  
Context: systems dataset with very large row counts (target: 10 M+ systems).

---

## 1. Database Schema — Storage Size (IMPLEMENTED)

### 1.1 Coordinates stored as 4-byte scaled integers (INT32)
**Status:** IMPLEMENTED.  
Elite Dangerous coordinates are stored as `ix, iy, iz` (INTEGER).  
`COORD_SCALE` (default 32) is used for scaling.  
**Impact:** ~12 bytes/row saved.

### 1.2 Replace bx/by/bz with SQLite R-tree
**Status:** IMPLEMENTED.  
`rtree_systems` virtual table used for spatial range queries.  
**Impact:** $O(\log n)$ range queries; removed redundant bucket columns.

### 1.3 SQLite build-time PRAGMA — set page_size=8192
**Status:** IMPLEMENTED.  
Sets `page_size = 8192` on new database creation.

### 1.4 Run VACUUM after build
**Status:** IMPLEMENTED.  
Reclaims fragmentation and optimizes file layout.

---

## 2. Query Performance — Pathfinding (IMPLEMENTED)

### 2.1 Directional pathfinder: single DB query per hop
**Status:** IMPLEMENTED.  
Queries once for all candidates within `max_hop`, then picks the best. No more doubling radius loops.

### 2.2 id_to_prefix / id_to_star dicts pre-built
**Status:** IMPLEMENTED.  
Built once in `main()` or webapp startup and passed as arguments.

### 2.3 LRU-limited cache
**Status:** IMPLEMENTED.  
`_manual_cache` uses `collections.OrderedDict` with a 2048-item LRU limit.

### 2.4 nearest-type with R-tree expanding radius
**Status:** IMPLEMENTED.  
Uses $O(\log n)$ R-tree search instead of $O(n)$ full table scan.

---

## 3. SQLite Connection PRAGMAs (IMPLEMENTED)
**Status:** IMPLEMENTED.  
Added `cache_size`, `mmap_size`, `journal_mode=WAL`, etc., to `open_db()`.

---

## 4. Priority Order for Implementation

All items from the roadmap have been implemented, including the structural changes (R-tree, scaled coordinates).

---

## 5. Optional: NumPy for bulk distance computation
**Status:** DEFERRED.  
Optional optimization for very high-volume preloaded datasets. Not required for current performance targets.
