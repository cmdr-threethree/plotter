# Specification: Webapp API

This document describes the HTTP API provided by the Plotter web application. All API responses MUST be JSON-encoded unless otherwise specified.

## 1. Global Configurations
- **Prefix**: `/api`
- **Default Limit**: 20 (for search)
- **Max Route Length**: 26,000 ly (for pathfinding)

## 2. Endpoints

### 2.1 Health Check
- **Path**: `/health`
- **Method**: `GET`
- **Response**:
  ```json
  { "status": "ok" }
  ```

### 2.2 System Search
Search for systems by name prefix or ID.
- **Path**: `/search`
- **Method**: `GET`
- **Query Parameters**:
  - `q` (string, required): The search query (ID64 or name prefix).
- **Response**: An array of system objects.
  ```json
  [
    {
      "id64": 12345,
      "name": "Colonia",
      "coords": { "x": 0.0, "y": 0.0, "z": 0.0 },
      "mainStar": "G (White-Yellow) Star",
      "needs_permit": false
    }
  ]
  ```

### 2.3 Nearest Star Search
Find the nearest system of specific star types relative to a reference point.
- **Path**: `/nearest`
- **Method**: `GET`
- **Query Parameters**:
  - `near` (string, required): A system name OR coordinates in `x,y,z` format.
  - `types` (string, optional): Comma-separated list of star type names (e.g., `Neutron Star,White Dwarf`).
- **Response**: A single system object (see Search response format).
- **Errors**:
  - `400`: `near` is missing or `types` doesn't match any known stars.
  - `404`: Could not resolve reference point or no matching systems found.

### 2.4 Streaming Pathfinding
Calculate a route between two systems with real-time progress updates.
- **Path**: `/path/stream`
- **Method**: `GET`
- **Query Parameters**:
  - `source` (string, required): Source system name.
  - `target` (string, required): Target system name.
  - `max_hop` (float, optional): Maximum jump range (default: 40.0).
  - `neutron_highway` (boolean, optional): If `true`, prioritize Neutron Stars for routing.
- **Response Type**: `text/event-stream` (SSE)

#### Event: `progress`
Sent during pathfinding to provide status updates to the user.
- **Data**: A string message (e.g., "Exploring node 500...").

#### Event: `result` (Success)
Sent once the path is found.
- **Data**:
  ```json
  {
    "path": [
      {
        "id64": 1,
        "name": "Source",
        "coords": { "x": 0, "y": 0, "z": 0 },
        "hop_dist": 0.0,
        "mainStar": "...",
        "needs_permit": false
      },
      ...
    ],
    "total": 123.4,
    "direct": 120.0,
    "diff_pct": 2.8
  }
  ```

#### Event: `result` (Error)
Sent if pathfinding fails or hits a limit.
- **Data (Limit Exceeded)**:
  ```json
  {
    "error": "limit_exceeded",
    "limit": 26000.0,
    "dist": 30000.0,
    "suggestion": { ...nearest neutron star at 25k ly... },
    "is_neutron": true
  }
  ```
- **Data (Generic Error)**:
  ```json
  { "error": "No path found" }
  ```

## 3. Error Handling
Standard error responses MUST use the following JSON format:
```json
{ "error": "Descriptive error message" }
```
- `400 Bad Request`: Missing or malformed parameters.
- `404 Not Found`: Resource or system not found.
- `500 Internal Server Error`: Unexpected server-side failure.
