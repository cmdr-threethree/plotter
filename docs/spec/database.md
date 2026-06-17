# Specification: Database Structure & Persistence

This document describes the SQLite-based storage layer for the Plotter project. The database is designed for high-performance spatial lookups and efficient name-based searches using prefix compression.

## 1. SQLite Configuration
The database MUST be optimized with the following PRAGMAs for performance:
- `journal_mode = WAL` (Write-Ahead Logging)
- `synchronous = OFF` (During index builds) or `NORMAL` (Production)
- `temp_store = MEMORY`
- `mmap_size = 2147483648` (2GB memory map for fast reads)
- `page_size = 8192` (Set at creation)

## 2. Table Schemas

### 2.1 `systems` Table
The primary table storing system attributes.
- `id64` (INTEGER PRIMARY KEY): The unique Spansh/EDDN 64-bit ID.
- `prefix_id` (INTEGER): Foreign key to `prefixes.id`.
- `x`, `y`, `z` (INTEGER): Coordinates scaled by `coord_scale` (default 32) and rounded to the nearest integer.
- `star_type_id` (INTEGER): Foreign key to `star_types.id`.
- `name_suffix` (TEXT): The part of the system name remaining after the prefix is removed.
- `is_neutron` (INTEGER): Boolean flag (0/1) indicating a Neutron Star.
- `needs_permit` (INTEGER): Boolean flag (0/1) indicating a permit-locked system.

### 2.2 `rtree_systems` Virtual Table
An R-Tree index for spatial range and nearest-neighbor queries.
- `id64` (INTEGER PRIMARY KEY)
- `min_x`, `max_x`, `min_y`, `max_y`, `min_z`, `max_z` (FLOAT/INT): The bounding box of the system (typically min=max for a point).

### 2.3 `prefixes` Table
Normalized lookup for system name prefixes.
- `id` (INTEGER PRIMARY KEY)
- `prefix` (TEXT UNIQUE): The prefix string (e.g., "Colonia", "Eol Prou").

### 2.4 `star_types` Table
Normalized lookup for star types.
- `id` (INTEGER PRIMARY KEY)
- `type_name` (TEXT UNIQUE): The full star type name (e.g., "Neutron Star").

### 2.5 `db_meta` Table
Key-value store for database configuration.
- `key` (TEXT PRIMARY KEY)
- `value` (TEXT)
Required keys:
- `coord_scale`: The multiplier used for integer coordinate storage (e.g., "32").
- `bucket_size`: Used for spatial partitioning logic (e.g., "50.0").

## 3. Core Logic: Name Resolution (Prefix Compression)
To reconstruct a system's full name:
1. Fetch `prefix_id` and `name_suffix` from `systems`.
2. Lookup `prefix` in the `prefixes` table using `prefix_id`.
3. `full_name = prefix + name_suffix`.

## 4. Core Logic: Coordinate Scaling
- **Storage**: `stored_x = round(actual_x * coord_scale)`
- **Retrieval**: `actual_x = stored_x / coord_scale`

## 5. Indexes
- `idx_prefix` on `systems(prefix_id)`
- `idx_star_type` on `systems(star_type_id)`
- `idx_systems_neutron` on `systems(is_neutron) WHERE is_neutron = 1`
- `idx_systems_permit` on `systems(needs_permit) WHERE needs_permit = 1`
