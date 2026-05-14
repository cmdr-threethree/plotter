# Design Document: Optimized SQLite Indexing & Integrated Metadata

## 1. Problem Statement
The current database creation process requires two full passes over the source JSON data:
1.  **Build Meta**: Scans all system names to build a frequency-sorted prefix map.
2.  **Build Index**: Re-scans the JSON to populate the SQLite database using the generated `meta.json`.

This approach doubles the I/O cost and complicates deployment by requiring two linked files (`systems.db` and `meta.json`) to be managed together.

## 2. Proposed Solution
Transition to a **single-pass build process** where metadata is dynamically discovered and stored directly within the SQLite database.

### 2.1 Single-Pass Indexing
- The indexer will maintain an in-memory cache of prefixes encountered so far.
- When a new prefix is found, it is assigned the next available integer ID and inserted into the `prefixes` table.
- This eliminates the need for a preliminary scan of the source JSON.

### 2.2 Integrated Metadata Schema
The SQLite database will become self-describing by including dedicated metadata tables.

#### New Tables:
- **`prefixes`**:
    - `id`: INTEGER PRIMARY KEY
    - `prefix`: TEXT UNIQUE
- **`star_types`**:
    - `id`: INTEGER PRIMARY KEY
    - `type_name`: TEXT UNIQUE

#### Updated `db_meta`:
- Stores `coord_scale`, `bucket_size`, and a `schema_version` to identify the integrated format.

### 2.3 Web Application Simplification
- Remove `PLOTTER_META` environment variable requirement.
- On startup, the web application will query the `prefixes` and `star_types` tables to build its internal lookup maps.
- **Note**: Backward compatibility for `meta.json` will not be maintained in the web layer to keep the code clean and focused.

## 3. Implementation Plan [COMPLETED]

### Phase 1: Core Script Refactoring (`scripts/distance_cli_sqlite_prefix.py`) [DONE]
- **Schema Update**: Update `ensure_schema_prefix` to include the new metadata tables and indexes.
- **Dynamic Meta Resolution**: Implement a helper class/logic within `build_index_prefix` to handle `GET_OR_CREATE` logic for prefixes and star types during the main loop.
- **Schema Loading**: Update `build_index_prefix` to load star types from `systems.schema.json` (if available) into the DB at the start.
- **Cleanup**: Deprecate or remove the `--build-meta` flag if it's no longer useful for the primary workflow.

### Phase 2: Web App Update (`webapp/app.py`) [DONE]
- Remove `META_PATH` and related JSON loading logic.
- Implement a `load_metadata_from_db(conn)` function that populates `ID_TO_PREFIX` and `ID_TO_STAR`.
- Update initialization to ensure the DB is reachable and metadata is loaded before accepting requests.

### Phase 3: Testing & Validation [DONE]
- **Unit Tests**: Update `tests/test_distance_cli_sqlite_prefix.py` to use the single-pass flow.
- **Integration Test**: Verify the web app starts and searches correctly using only a `.sqlite` file.
- **Performance Check**: Confirm the single-pass build time is significantly lower than the combined two-pass time.

## 4. Benefits
- **Speed**: Build time reduced by approximately 50%.
- **Simplicity**: Deployment involves moving a single file.
- **Robustness**: No risk of metadata/database mismatch.
- **SQL-Friendly**: Allows for easier debugging and reporting via standard SQLite clients.
