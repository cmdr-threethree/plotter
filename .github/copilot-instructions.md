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

