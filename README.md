# Plotter — Elite Dangerous Pathfinding Tool

A high-performance, SQLite-backed pathfinding and system search tool for Elite Dangerous. Plotter provides both a powerful CLI and a modern, offline-capable Web Application (PWA).

## Features

- **Robust Bidirectional Search**: Approximate pathfinding using directional stepping from both ends to ensure high connectivity and speed.
- **Waypoint Fallbacks**: Automatically attempts to bypass "dead ends" using orthogonal waypoints when a direct route fails.
- **Star Type Filtering**: Restrict pathfinding to specific star types (e.g., fuel stars or neutron stars).
- **Nearest System Search**: Quickly find the nearest Neutron Star, White Dwarf, or any other star type from your current location or specific coordinates.
- **Modern Web Interface**:
    - **PWA / Offline Support**: Full Service Worker integration allows the app to load and display saved routes even without an internet connection.
    - **Route Persistence**: Save results to browser local storage for instant retrieval.
    - **Import/Export**: Share routes or back them up as JSON files.
    - **Efficiency Metrics**: Calculates total distance, direct distance, and path overhead percentage.

## Prerequisites

- **Python 3.8+**
- **Flask** (for the web application)

```bash
pip install -r webapp/requirements.txt
```

### Updating Dependencies
To update dependencies to their latest versions and ensure they are pinned:

```bash
# Generate a report of the latest versions
pip install -r webapp/requirements.txt --upgrade --dry-run --report report.json --ignore-installed

# Manually update webapp/requirements.txt with the versions found in report.json
# or use a tool like pip-compile if available.
```

---

## Initial Setup (Database Creation)

Before using Plotter, you must initialize the SQLite database from a source JSON file (e.g., `systems.json` from EDDN/EDSM).

### Build Search Index (Single Pass)
Parses the source JSON and populates a SQLite database with integrated metadata and R-Tree spatial indexing in a single pass.

```bash
python3 scripts/distance_cli_sqlite_prefix.py \
  --file systems.json \
  --db data/systems.db \
  --build-index
```
*This dynamically populates prefix and star type metadata directly into the database.*

---

## CLI Usage

### Find a Path
```bash
python3 scripts/distance_cli_sqlite_prefix.py \
  --from "Sol" \
  --to "Colonia" \
  --max-hop 400
```

### Find Nearest Star Type
```bash
python3 scripts/distance_cli_sqlite_prefix.py \
  --near "Sol" \
  --nearest-type "Neutron Star"
```

---

## Web Application

The web app provides a user-friendly interface for pathfinding and route management.

### Starting the Server
```bash
# Set environment variables if needed
export PLOTTER_DB="data/systems.db"


python3 webapp/app.py
```
Access the UI at `http://localhost:5000`.

### Development Notes
If you modify the static assets (`app.js`, `styles.css`, etc.), remember to increment the `CACHE_NAME` in `webapp/static/sw.js` to ensure the Service Worker triggers an update for users.

---

## Architecture

- **SQLite + R-Tree**: Uses SQLite's spatial indexing for fast $O(\log N)$ neighbor lookups.
- **Prefix Compression**: Reduces database size and memory footprint by compressing common system name prefixes.
- **Directional Stepping**: An optimized A*-like algorithm that steps towards the target from both the source and the target simultaneously.

## License
Public Domain
