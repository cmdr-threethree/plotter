# Master Refactoring Plan: Modular Plotter

This document outlines the strategy for refactoring the Plotter project from a monolithic script into a modular, maintainable Python package.

## 1. Objective
The goal is to decouple the core logic (database, routing, indexing) while maintaining the existing database schema and external API contracts. This will allow for better testing, easier maintenance, and clearer separation of concerns.

## 2. Target Architecture
The code will be reorganized into a `plotter/` package with the following structure:

- `plotter/`
  - `__init__.py`: Package entry point.
  - `models.py`: Pydantic/Dataclass models for `System`, `Coordinates`, etc.
  - `database.py`: `DatabaseManager` for SQLite interactions, R-Tree, and search.
  - `routing/`:
    - `__init__.py`: Router interface.
    - `astar.py`: Core A* and Robust logic.
    - `neutron.py`: Neutron Highway logic.
  - `indexer.py`: Logic for building the database from raw JSON.

## 3. Specifications Reference
This plan is governed by the following detailed specifications:
- **Database Schema**: [database.md](database.md)
- **Data Ingestion**: [ingestion.md](ingestion.md)
- **Web API**: [api.md](api.md)
- **Routing Algorithms**: [routing.md](routing.md)
- **Search & Spatial Logic**: [search.md](search.md)

## 4. Implementation Phases

### Phase 1: Foundation & Models
- Create the `plotter/` directory.
- Implement `plotter/models.py` to define the data structures used across all modules.

### Phase 2: Database & Search Extraction
- Implement `plotter/database.py` based on the [Database](database.md) and [Search](search.md) specifications.
- Ensure all SQLite PRAGMAs and R-Tree query logic are encapsulated here.

### Phase 3: Routing Extraction
- Implement the routing algorithms in `plotter/routing/` as specified in [Routing Logic](routing.md).
- The router should depend on `DatabaseManager` for system lookups.

### Phase 4: Indexer Extraction
- Move the `build-index` logic to `plotter/indexer.py` as specified in [Data Ingestion](ingestion.md).
- Create a standalone CLI entry point that uses this module.

### Phase 5: Webapp Integration
- Update `webapp/app.py` to use the `plotter` package.
- Remove the `sys.path` hack and direct imports from `scripts/`.
- Verify compliance with the [Web API](api.md) specification.

### Phase 6: Cleanup & Validation
- Update existing tests to point to the new package.
- Remove redundant logic from `scripts/distance_cli_sqlite_prefix.py`.
- Final validation against Spansh data and existing pathfinding results.

## 5. Constraints
- **Zero Schema Change**: The SQLite table structure MUST NOT be modified.
- **API Compatibility**: The `/api/` endpoints MUST return the exact same JSON structures.
- **Performance**: Modularization MUST NOT introduce significant latency in spatial queries or routing.
