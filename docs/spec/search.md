# Specification: Search & Spatial Logic

This document describes the logic for searching star systems by name/ID and performing spatial queries (nearest neighbor) using the SQLite R-Tree index.

## 1. System Search (`get_system_by_query_prefix`)

The search logic MUST support both 64-bit IDs and partial name strings.

### 1.1 ID Search
If the query string consists only of digits:
1. Perform a direct lookup on `systems.id64`.
2. JOIN with `prefixes` and `star_types` to reconstruct the full name and star type.

### 1.2 Name Search
For text-based queries:
1. **Prefix Matching**: Perform a `LIKE 'query%'` search on the `prefixes` table.
2. **System Retrieval**: Using the matching `prefix_id`s, query the `systems` table.
3. **Refinement**: If the query is longer than the prefix (e.g., query is "Colonia 4"), the remainder MUST match the `name_suffix` using `LIKE`.
4. **Ordering**: Results SHOULD be ordered by `id64` (as a stable secondary sort) or by name length to prioritize exact matches.

## 2. Spatial Queries (`nearest_of_type`)

This logic finds the closest system to a given point, optionally filtered by star types.

### 2.1 Nearest Neighbor Algorithm
Since SQLite's R-Tree provides bounding box lookups but not direct "nearest" sorting, the following "expanding window" strategy MUST be used:

1. **Initial Search**: Define a small bounding box (e.g., +/- 100ly) around the target coordinates `(x, y, z)`.
2. **Query**:
   ```sql
   SELECT s.id64, ... 
   FROM rtree_systems r
   JOIN systems s ON s.id64 = r.id64
   WHERE r.min_x >= :min_x AND r.max_x <= :max_x 
     AND r.min_y >= :min_y AND r.max_y <= :max_y
     AND r.min_z >= :min_z AND r.max_z <= :max_z
     AND s.star_type_id IN (:type_ids) -- Optional
   ```
3. **Expansion**: If no results are found, double the window size and retry.
4. **Final Sort**: Once candidates are found, calculate the exact Euclidean distance in memory and return the closest one.

### 2.2 Exclusions
Spatial queries MUST support an `exclude_id64` parameter to prevent a system from being its own "nearest" neighbor (useful for finding the next hop in a route).

## 3. Coordinate Handling in Queries
- **Inputs**: All query coordinates (from API or routing logic) are provided as actual floats.
- **Scaling**: Before querying `rtree_systems` or `systems`, these floats MUST be multiplied by `coord_scale` and converted to integers.
- **Outputs**: All coordinates returned to the user MUST be unscaled (divided by `coord_scale`).

## 4. Performance Considerations
- **LIMIT**: All search queries SHOULD have a reasonable `LIMIT` (default 20) to prevent oversized responses.
- **Index Usage**: Ensure the SQL queries are structured to utilize `idx_prefix` and `idx_star_type` for maximum efficiency.
