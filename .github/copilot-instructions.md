Repository overview

- Purpose: Contains a JSON Schema (systems.schema.json) describing a system record and a large daily data dump (systems_neutron.json) holding the actual records.
- Data shape: Each record follows the schema in systems.schema.json: id64 (integer), name (string), coords {x,y,z} (numbers), needsPermit (boolean), updateTime (RFC3339 UTC string). The schema sets additionalProperties: false (do not expect extra fields).

Build / test / lint commands

- No build/test/lint scripts or CI workflows detected in this repository.
- Working with large JSON files: prefer streaming tools (jq, python -ijson) rather than loading into memory.

Useful commands

- View schema:  jq . systems.schema.json
- Inspect first record: jq '.[0]' systems_neutron.json
- Stream each item compacted (memory-friendly): jq -c '.[]' systems_neutron.json | head -n 5
- Find system by name (case-insensitive): jq -c '.[] | select(.name | test("(?i)NAME"))' systems_neutron.json
- Find system by id64: jq -c '.[] | select(.id64==1234567890)' systems_neutron.json
- Count records: jq length systems_neutron.json
- Validate a JSON file against the schema (requires ajv-cli): ajv validate -s systems.schema.json -d systems_neutron.json

High-level architecture

- This repository is primarily a data repo, not an application:
  - systems.schema.json — authoritative JSON Schema describing one system record
  - systems_neutron.json — a large JSON array (dump) of system records. The dump is pretty-printed; each system appears on its own lines for readability.

Key conventions & patterns

- Single authoritative schema: All tooling and downstream consumers should use systems.schema.json as the source of truth for fields and types.
- Strict schema: additionalProperties is false. If adding fields, update systems.schema.json first.
- Coordinate object required: coords.x, coords.y, coords.z must exist for each record.
- updateTime is stored in UTC RFC3339 date-time format.
- Data size considerations: systems_neutron.json may be large (>10MB). Prefer streaming queries and line-oriented processing (jq -c '.[]') or use ndjson variants for incremental ingestion.

Copilot guidance

- When asked to modify or analyze records, recommend streaming solutions and sample commands (jq, python ijson) rather than in-memory edits.
- For schema changes, propose the minimal schema edit and show an ajv-cli validation command to run locally.
- If proposing transforms on systems_1day.json, include an approach that supports processing a subset (filter by name or id64) and a memory-safe, incremental approach.

Notes for future AI assistants

- No language-specific build/test tooling detected; focus on data-processing guidance.
- If adding code (scripts, tests, CI), update this file with exact commands and examples so future assistants can surface them.

Indexing, meta file, and prefix compression

This project includes a prefix-compressed SQLite index builder and reader to reduce DB size and speed queries. Key points:
- Meta file: a JSON map (default: systems_meta.json) that stores two mappings:
  - prefixes: { "0": "", "1": "Sol", ... } — integer key -> string prefix. Use "0" for empty prefix.
  - starTypes: { "0": "", "1": "G (White-Yellow) Star", ... } — integer key -> star type string.
- Prefix extraction rule: if a dash (`-`) exists, take everything up to the first dash as prefix; otherwise take everything up to the first space. The remainder is stored as name_suffix so full name = prefix + name_suffix.
- systems with needsPermit == true are omitted from the index.

Building meta and index (stdin support)

- Build meta (writes systems_meta.json):
  scripts/distance_cli_sqlite_prefix.py --build-meta --file systems_neutron.json
  or with compressed input on stdin: zcat systems_neutron.json.gz | scripts/distance_cli_sqlite_prefix.py --build-meta --file -
- Build index (reads JSON from file or stdin and creates sqlite DB):
  scripts/distance_cli_sqlite_prefix.py --build-index --file systems_neutron.json --meta systems_meta.json --out systems_neutron.sqlite
  or using stdin (recommended when data is compressed): zcat systems_neutron.json.gz | scripts/distance_cli_sqlite_prefix.py --build-index --file - --meta systems_meta.json --out systems_neutron.sqlite
- The special token "-" for --file means read JSON from stdin; this enables piping decompressed data directly into the builder so large compressed dumps need not be stored uncompressed on disk.

SQLite schema (prefix-compressed index)

The prefix-compressed DB schema (columns used by the scripts) is:
- id64 INTEGER PRIMARY KEY
- prefix_id INTEGER      -- index into meta.prefixes
- name_suffix TEXT       -- remainder of the name after the prefix (includes separator if present)
- x REAL, y REAL, z REAL -- coordinates
- bx INTEGER, by INTEGER, bz INTEGER -- bucket grid coordinates for spatial indexing
- star_type_id INTEGER   -- index into meta.starTypes
- updateTime TEXT        -- RFC3339 timestamp (kept for reference)

Note: older DBs created before name_suffix existed will be migrated by adding the column on first use. A small backfill helper can be added if you already have a DB without suffixes.

Using the index and reconstructing names

- Query tools reconstruct full names at runtime by loading the meta JSON and concatenating meta.prefixes[str(prefix_id)] + name_suffix.
- Neighbor queries only load nearby buckets from SQLite into memory to keep RAM usage low.
- Star type strings are reconstructed via meta.starTypes[str(star_type_id)].

Tips

- Tune --bucket-size when building the DB to balance DB size vs candidate counts for neighbor queries.
- Use --max-neighbors and --max-hop carefully for pathfinding to avoid wide searches.
- The prefix heuristic works for the majority of names but may mis-segment some edge cases; verify if important names appear truncated.

Commands for quick inspection

- Show top prefixes (simple count example):
  sqlite3 systems_neutron.sqlite "SELECT prefix_id, count(*) FROM systems GROUP BY prefix_id ORDER BY count(*) DESC LIMIT 20;"
- Reconstruct a single name using Python and meta JSON:
  python -c "import json; m=json.load(open('systems_meta.json')); p=m['prefixes']['1']; print(p + 'Suffix')"


