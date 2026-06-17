# Specification: Data Ingestion (Indexer)

This document describes the logic for transforming raw system data into the optimized SQLite database structure.

## 1. Input Format
The indexer consumes a stream of JSON objects (JSONL or a JSON array). Each object MUST contain:
- `id64`: 64-bit integer.
- `name`: String.
- `coords`: Object with `x`, `y`, `z` (floats).
- `mainStar`: String (optional).
- `needsPermit`: Boolean (optional).

## 2. Prefix Extraction Algorithm
To support prefix compression, the `prefix` is extracted from the system `name` using the following rules:
1. If the name contains a dash (`-`), the prefix is everything **before** the first dash.
2. If the name contains no dash but contains a space (` `), the prefix is everything **before** the first space.
3. Otherwise, the entire name is considered the prefix (the `name_suffix` becomes an empty string).

**Example:**
- `Colonia 4` -> Prefix: `Colonia`, Suffix: ` 4`
- `Eol Prou AB-C d1-2` -> Prefix: `Eol Prou AB`, Suffix: `-C d1-2`
- `Sol` -> Prefix: `Sol`, Suffix: ``

## 3. Transformation Steps (Per System)
1. **Coordinate Scaling**: Multiply `x`, `y`, `z` by `coord_scale` (default 32) and round to the nearest integer.
2. **Prefix Mapping**:
   - Check if the extracted prefix exists in the `prefixes` table.
   - If not, insert it and generate a new `prefix_id`.
3. **Star Type Mapping**:
   - Check if `mainStar` exists in the `star_types` table.
   - If not, insert it and generate a new `star_type_id`.
4. **Neutron Flagging**: Determine `is_neutron` based on the `mainStar` type or external metadata.

## 4. Ingestion Performance & Batching
To maintain high throughput (e.g., >10,000 systems/sec), the indexer MUST:
1. **Use Transactions**: Group inserts into batches (default size: 1000).
2. **Prepared Statements**: Use `INSERT INTO ... ON CONFLICT(id64) DO UPDATE` to handle resumable builds or updates.
3. **R-Tree Population**: Populating the `rtree_systems` table MUST happen in the same transaction as the `systems` table insert.
4. **Metadata Caching**: Maintain an in-memory cache of `prefix -> prefix_id` and `star_type -> star_type_id` to avoid redundant database lookups during a single ingestion run.

## 5. Post-Processing
After all systems are processed, the following commands MUST be executed:
1. `ANALYZE;`: Update SQLite query planner statistics.
2. `VACUUM;`: (Optional) Rebuild the database file for maximum fragmentation reduction.
3. Ensure all indexes defined in the [Database Specification](database.md) are present.
