# Specification: Routing Logic

This document describes the algorithms used to calculate optimal and efficient routes between star systems.

## 1. Core A* Search (`find_path_directional`)
The fundamental pathfinding algorithm is a modified A* search.

### 1.1 Heuristic & Cost
- **Heuristic**: Euclidean distance to the target system.
- **Cost**: Actual distance traveled (sum of hop distances).
- **Goal**: Minimize `f(n) = g(n) + h(n)`.

### 1.2 Node Expansion
For each node `n`, neighbors are found using the following constraints:
1. **Distance**: `dist(n, neighbor) <= max_hop`.
2. **Directional Bias**: Neighbors MUST be closer to the target than the current node, or within a small threshold of deviation, to prevent backtracking.
3. **Neighbor Limit**: To ensure performance, only the top `K` (e.g., 500) nearest neighbors within the `max_hop` radius are considered.
4. **Visited Check**: Prevent cycles by tracking visited `id64` IDs.

### 1.3 Progress Reporting
The algorithm MUST support a callback function (`on_progress`) that is invoked periodically (e.g., every 100 nodes explored) with a string describing the current state.

## 2. Robust Routing Strategy (`find_path_robust`)
Real-world galaxy data often contains "gaps" where no systems exist within a fixed `max_hop`. The robust strategy handles this through multiple attempts:

1. **Forward Search**: standard A* from Source to Target.
2. **Backward Search**: standard A* from Target to Source (if forward fails).
3. **Relaxation**: If both fail, increase the `max_hop` by a `relax_factor` (e.g., 1.1x) and retry. 
4. **Waypoint Strategy**: If the distance is large, calculate a midpoint (waypoint) and attempt to route `Source -> Waypoint -> Target`.

## 3. Neutron Highway Logic (`find_path_neutron_highway`)
Specialized routing for long-range travel using Neutron Star jump boosts.

### 3.1 Prioritization
- The search space is filtered to prioritize systems with `is_neutron = 1`.
- **Search Pattern**:
  1. From the current system, find the nearest Neutron Star that is "roughly" in the direction of the target.
  2. If a Neutron Star is found, jump to it.
  3. If no Neutron Star is within range, perform a standard A* search to the next "Neutron Cluster" or the final target.

### 3.2 Constraints
- **Neutron Range**: While Neutron Stars provide a 4x boost in the game, this routing logic typically treats them as "waypoints" to stay on the highway.
- **Exit Logic**: When within `max_hop * 2` of the target, switch to standard A* to finalize the approach.

## 4. Distance Calculations
All distance calculations MUST use the standard 3D Euclidean distance formula:
`sqrt((x2-x1)^2 + (y2-y1)^2 + (z2-z1)^2)`

Note: Use unscaled (actual) coordinates for all routing math.
