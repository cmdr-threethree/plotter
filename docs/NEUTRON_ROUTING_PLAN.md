# Neutron Star Routing (Neutron Highway) — IMPLEMENTED

This document outlines the architecture and implementation of the "Neutron Star Routing" feature, which allows users to plan routes that primarily use neutron stars to significantly increase jump range.

## Objective
- Add an `is_neutron` flag to the systems database.
- Provide a way to mark systems as neutron stars from a specific JSON import.
- Implement a routing algorithm that finds the nearest neutron star to the start and then routes through neutron stars to the destination.
- Integrated "Neutron Highway" option in the web interface and API.

## 1. Database Schema & Indexing (`scripts/distance_cli_sqlite_prefix.py`)

### 1.1 Schema Implementation
- Added an `is_neutron` column to the `systems` table.
- Created a filtered index: `CREATE INDEX IF NOT EXISTS idx_systems_neutron ON systems(is_neutron) WHERE is_neutron = 1`.
- Spatial lookups for neutron stars leverage the `rtree_systems` virtual table combined with the `is_neutron` flag for $O(\log N)$ performance.

### 1.2 Indexer Updates
- Added CLI flag: `--mark-neutron`.
- The indexer handles the `is_neutron` flag during insertion using `ON CONFLICT(id64) DO UPDATE SET is_neutron = MAX(is_neutron, excluded.is_neutron)`. This ensures systems can be marked as neutron stars without overwriting other metadata.

## 2. Pathfinding Logic (`scripts/distance_cli_sqlite_prefix.py`)

### 2.1 Nearest Neutron Lookup
- Implemented `nearest_of_type` (and specific neutron helpers) to perform R-Tree searches restricted to specific star type IDs or the `is_neutron` flag.

### 2.2 Neutron-Aware Neighbor Search
- `neighbors_for_center_prefix` accepts star type filters.
- When routing for the highway, the search is restricted to systems where `is_neutron = 1`.

### 2.3 Neutron Routing Strategy
- Implemented `find_path_neutron_highway(conn, source, target, max_hop, ...)`:
    1.  Resolves `NearestNeutron(source["coords"])`.
    2.  Calculates a route through the neutron network using `find_path_robust` with `only_neutron=True`.
    3.  Naturally handles the non-neutron destination as the final hop.
    4.  Ensures the path is valid and efficient compared to direct jumping.

## 3. Web Application Integration

### 3.1 Backend (`webapp/app.py`)
- The `/api/path/stream` endpoint accepts a `neutron_highway=true` parameter.
- Worker threads invoke `find_path_neutron_highway` for these requests.
- Progress streaming (SSE) provides real-time feedback during the more intensive neutron search.

### 3.2 Frontend (`webapp/static/app.js`)
- Added "Neutron Highway" checkbox to the UI.
- Updates the SSE request URL to include the `neutron_highway` flag.
- Displays the resulting high-range hops in the route table.

## 4. Verification
- **Unit Tests**: `tests/test_distance_cli_sqlite_prefix.py` includes cases for marking neutron stars and verifying highway pathfinding logic.
- **Data Integration**: Successfully tested with Spansh neutron dumps using the `--mark-neutron` flag.
