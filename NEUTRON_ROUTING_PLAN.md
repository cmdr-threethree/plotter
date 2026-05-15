# Plan: Neutron Star Routing (Neutron Highway)

This plan outlines the steps to add a new "Neutron Star Routing" feature. This feature allows users to plan routes that primarily use neutron stars, significantly increasing jump range in Elite Dangerous.

## Objective
- Add an `is_neutron` flag to the systems database.
- Provide a way to mark systems as neutron stars from a specific JSON import.
- Implement a routing algorithm that finds the nearest neutron star to the start and then routes through neutron stars to the destination.
- Add a "Neutron Highway" option to the web interface.

## 1. Database Schema & Indexing (`scripts/distance_cli_sqlite_prefix.py`)

### 1.1 Update Schema
- Modify `ensure_schema_prefix` to add an `is_neutron` column to the `systems` table.
- **Changes**:
    - `systems` table: Add `is_neutron INTEGER DEFAULT 0`.
    - Create index: `CREATE INDEX IF NOT EXISTS idx_systems_neutron ON systems(is_neutron) WHERE is_neutron = 1`.

### 1.2 Update Indexer
- Add a new CLI flag: `--mark-neutron`.
- Update `build_index_prefix` to handle the `is_neutron` flag during insertion.
- Use `INSERT INTO systems (...) ON CONFLICT(id64) DO UPDATE SET is_neutron = MAX(is_neutron, excluded.is_neutron)` to ensure existing systems can be marked as neutron stars without being reset during regular imports.

## 2. Pathfinding Logic (`scripts/distance_cli_sqlite_prefix.py`)

### 2.1 Nearest Neutron Lookup
- Add a new helper function `nearest_neutron(conn, coords, coord_scale, id_to_prefix, id_to_star)` that performs an R-Tree search restricted to `is_neutron = 1`.

### 2.2 Neutron-Aware Neighbor Search
- Update `neighbors_for_center_prefix` to accept an `only_neutron` boolean parameter.
- When `only_neutron` is true, the SQL query will include `AND is_neutron = 1`.

### 2.3 Neutron Routing Strategy
- Add `find_path_neutron_highway(conn, source, target, max_hop, ...)`:
    1.  Find `NearestNeutron(source["coords"])`.
    2.  If not found, return `None`.
    3.  Call `find_path_robust(NearestNeutron, target, max_hop, ..., only_neutron=True)`.
    4.  The `find_path_directional` (called by `robust`) naturally handles the non-neutron destination as the final hop because it checks for the "goal" within reach regardless of star type filters.
    5.  Prepend the original `source` to the result if it's not the same as `NearestNeutron`.

## 3. Web Application Integration

### 3.1 Backend (`webapp/app.py`)
- Update `/api/path/stream` to accept a `neutron_highway` boolean parameter.
- If `neutron_highway` is true, invoke the new `find_path_neutron_highway` logic.
- Ensure progress streaming still works (the new logic should emit progress messages).

### 3.2 Frontend (`webapp/static/index.html` & `app.js`)
- **UI**: Add a checkbox "Neutron Highway" near the "Max hop" setting.
- **JS**:
    - Capture the state of the checkbox.
    - Include `neutron_highway=true` in the SSE connection URL to `/api/path/stream`.
    - Ensure the UI correctly displays the multi-segment path.

## 4. Verification & Testing
- **Unit Test**: Add a test case in `tests/test_distance_cli_sqlite_prefix.py` that:
    1.  Marks a subset of systems as neutron stars.
    2.  Verifies `find_path_neutron_highway` correctly uses those systems.
- **Manual Test**: Run the indexer with `--mark-neutron` on a sample file and verify the `is_neutron` column in the DB.
- **Integration Test**: Use the web UI to plan a neutron route and verify the hops are indeed neutron stars (except the start and end).

## Alternatives Considered
- **Using `star_type_id` only**: We could just filter by `star_type_id` for "Neutron Star". However, the requirement specifically mentions a "special json data import", which suggests that the source of truth for "routing-capable neutron stars" might be different from the main star type (e.g., specific lists like the Spansh Neutron Highway data). Using a dedicated `is_neutron` flag is more flexible.
