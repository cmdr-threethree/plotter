import math
import random
import copy
from typing import Dict, List, Optional, Set, Tuple, Callable
from plotter.models import Coordinates, System
from plotter.database import DatabaseManager

def find_path_directional(
    db: DatabaseManager,
    source: System,
    target: System,
    max_hop: float,
    max_nodes: int = 5000,
    max_neighbors: int = 500,
    allowed_star_ids: Optional[Set[int]] = None,
    step_threshold: float = 1.0,
    expand_factor: float = 2.0,
    in_memory_buckets: Optional[Dict[Tuple[int, int, int], List[Dict]]] = None,
    relax_factor: float = 1.1,
    allow_relaxation: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
    only_neutron: bool = False,
) -> Optional[List[System]]:
    """Directional stepping pathfinder with bidirectional search.
    If allow_relaxation is True, relaxes max_hop for a single step if stuck.
    """

    def _emit(msg: str):
        if on_progress:
            on_progress(msg)
        else:
            if msg == "\n":
                print()
            else:
                print(msg, end="\r", flush=True)

    def _step(
        current: System,
        goal: System,
        current_max_hop: float,
        visited_self: Set[int],
        visited_other: Dict[int, System],
    ) -> Optional[System]:
        cx, cy, cz = current.coords.x, current.coords.y, current.coords.z
        gx, gy, gz = goal.coords.x, goal.coords.y, goal.coords.z
        dx, dy, dz = gx - cx, gy - cy, gz - cz
        d2 = dx * dx + dy * dy + dz * dz

        if d2 <= current_max_hop * current_max_hop:
            res = copy.copy(goal)
            if d2 > max_hop * max_hop:
                res._relaxed_hop = math.sqrt(d2)
            return res

        mag = math.sqrt(d2)
        tx, ty, tz = (
            cx + (dx / mag) * current_max_hop,
            cy + (dy / mag) * current_max_hop,
            cz + (dz / mag) * current_max_hop,
        )

        radius = step_threshold
        while radius <= current_max_hop:
            fake_center = System(
                id64=-1,
                name="fake",
                coords=Coordinates(tx, ty, tz)
            )
            cands = db.neighbors_for_center(
                fake_center,
                radius,
                set(),
                max_neighbors=max_neighbors,
                allowed_star_ids=allowed_star_ids,
                in_memory_buckets=in_memory_buckets,
                only_neutron=only_neutron,
            )
            if cands:
                valid = []
                for c in cands:
                    if c.id64 in visited_self:
                        continue
                    dcx, dcy, dcz = (
                        c.coords.x - cx,
                        c.coords.y - cy,
                        c.coords.z - cz,
                    )
                    dist2 = dcx * dcx + dcy * dcy + dcz * dcz
                    if dist2 <= current_max_hop * current_max_hop:
                        if c.id64 in visited_other:
                            res = copy.copy(visited_other[c.id64])
                            if dist2 > max_hop * max_hop:
                                res._relaxed_hop = math.sqrt(dist2)
                            return res
                        valid.append((dist2, c))
                if valid:
                    dist2, best_c = min(
                        valid,
                        key=lambda t: (t[1].coords.x - tx) ** 2
                        + (t[1].coords.y - ty) ** 2
                        + (t[1].coords.z - tz) ** 2,
                    )
                    best = copy.copy(best_c)
                    if dist2 > max_hop * max_hop:
                        best._relaxed_hop = math.sqrt(dist2)
                    return best
            radius *= expand_factor
        return None

    path_f, path_r = [source], [target]
    visited_f, visited_r = {source.id64: source}, {target.id64: target}
    curr_f, curr_r = source, target

    for nodes in range(max_nodes):
        if nodes % 10 == 0:
            dx, dy, dz = (
                curr_r.coords.x - curr_f.coords.x,
                curr_r.coords.y - curr_f.coords.y,
                curr_r.coords.z - curr_f.coords.z,
            )
            gap = math.sqrt(dx * dx + dy * dy + dz * dz)
            _emit(f"Search step {nodes}: gap={gap:.1f} nodes={len(path_f)+len(path_r)}")

        nxt_f = _step(curr_f, curr_r, max_hop, set(visited_f.keys()), visited_r)
        if nxt_f:
            if nxt_f.id64 in visited_r:
                idx = next(
                    i for i, n in enumerate(path_r) if n.id64 == nxt_f.id64
                )
                path_f.append(nxt_f)
                return path_f + path_r[:idx][::-1]
            path_f.append(nxt_f)
            visited_f[nxt_f.id64] = nxt_f
            curr_f = nxt_f
            continue

        nxt_r = _step(curr_r, curr_f, max_hop, set(visited_r.keys()), visited_f)
        if nxt_r:
            if nxt_r.id64 in visited_f:
                idx = next(
                    i for i, n in enumerate(path_f) if n.id64 == nxt_r.id64
                )
                path_r.append(nxt_r)
                return path_f[: idx + 1] + path_r[::-1][1:]
            path_r.append(nxt_r)
            visited_r[nxt_r.id64] = nxt_r
            curr_r = nxt_r
            continue

        if allow_relaxation:
            _emit("Pathfinding: Stuck, trying relaxation...")
            current_relax = relax_factor
            while current_relax <= 3.0:
                relaxed_hop = max_hop * current_relax
                nxt_f = _step(
                    curr_f, curr_r, relaxed_hop, set(visited_f.keys()), visited_r
                )
                if nxt_f:
                    if nxt_f.id64 in visited_r:
                        idx = next(
                            i
                            for i, n in enumerate(path_r)
                            if n.id64 == nxt_f.id64
                        )
                        path_f.append(nxt_f)
                        return path_f + path_r[:idx][::-1]
                    path_f.append(nxt_f)
                    visited_f[nxt_f.id64] = nxt_f
                    curr_f = nxt_f
                    break
                nxt_r = _step(
                    curr_r, curr_f, relaxed_hop, set(visited_r.keys()), visited_f
                )
                if nxt_r:
                    if nxt_r.id64 in visited_f:
                        idx = next(
                            i
                            for i, n in enumerate(path_f)
                            if n.id64 == nxt_r.id64
                        )
                        path_r.append(nxt_r)
                        return path_f[: idx + 1] + path_r[::-1][1:]
                    path_r.append(nxt_r)
                    visited_r[nxt_r.id64] = nxt_r
                    curr_r = nxt_r
                    break
                current_relax *= relax_factor
            else:
                return None
            continue
        return None
    return None

def _find_path_robust_single(
    db: DatabaseManager,
    source: System,
    target: System,
    max_hop: float,
    max_nodes: int = 5000,
    max_neighbors: int = 500,
    allowed_star_ids: Optional[Set[int]] = None,
    step_threshold: float = 1.0,
    expand_factor: float = 2.0,
    in_memory_buckets: Optional[Dict[Tuple[int, int, int], List[Dict]]] = None,
    relax_factor: float = 1.1,
    waypoint_tries: int = 50,
    on_progress: Optional[Callable[[str], None]] = None,
    only_neutron: bool = False,
) -> Optional[List[System]]:
    """Internal single-direction robust search logic."""

    def _emit(msg: str):
        if on_progress:
            on_progress(msg)

    # 1. Direct search (no relaxation)
    _emit("Pathfinding: Starting direct search...")
    res = find_path_directional(
        db,
        source,
        target,
        max_hop,
        max_nodes=max_nodes,
        max_neighbors=max_neighbors,
        allowed_star_ids=allowed_star_ids,
        step_threshold=step_threshold,
        expand_factor=expand_factor,
        in_memory_buckets=in_memory_buckets,
        relax_factor=relax_factor,
        allow_relaxation=False,
        on_progress=on_progress,
        only_neutron=only_neutron,
    )
    if res:
        return res

    # 2. Waypoint search
    _emit(f"Pathfinding: Direct failed, trying {waypoint_tries} waypoints...")
    ax, ay, az = source.coords.x, source.coords.y, source.coords.z
    bx, by, bz = target.coords.x, target.coords.y, target.coords.z
    vx, vy, vz = bx - ax, by - ay, bz - az
    dist = math.sqrt(vx * vx + vy * vy + vz * vz)
    if dist > 0:
        mx, my, mz = (ax + bx) / 2, (ay + by) / 2, (az + bz) / 2
        if abs(vx) < abs(vy):
            n = (1.0, 0.0, 0.0)
        else:
            n = (0.0, 1.0, 0.0)
        p1x, p1y, p1z = (
            vy * n[2] - vz * n[1],
            vz * n[0] - vx * n[2],
            vx * n[1] - vy * n[0],
        )
        p1_mag = math.sqrt(p1x * p1x + p1y * p1y + p1z * p1z)
        p1x, p1y, p1z = p1x / p1_mag, p1y / p1_mag, p1z / p1_mag
        p2x, p2y, p2z = vy * p1z - vz * p1y, vz * p1x - vx * p1z, vx * p1y - vy * p1x
        p2_mag = math.sqrt(p2x * p2x + p2y * p2y + p2z * p2z)
        p2x, p2y, p2z = p2x / p2_mag, p2y / p2_mag, p2z / p2_mag

        for i in range(waypoint_tries):
            radius = ((i + 1) / waypoint_tries) * 0.5 * dist
            angle = random.uniform(0, 2 * math.pi)
            wx, wy, wz = (
                mx + radius * (math.cos(angle) * p1x + math.sin(angle) * p2x),
                my + radius * (math.cos(angle) * p1y + math.sin(angle) * p2y),
                mz + radius * (math.cos(angle) * p1z + math.sin(angle) * p2z),
            )

            _emit(f"Waypoint try {i+1}/{waypoint_tries} (radius={radius:.1f})...")
            mid_sys = db.nearest_system(Coordinates(wx, wy, wz))
            if (
                not mid_sys
                or mid_sys.id64 == source.id64
                or mid_sys.id64 == target.id64
            ):
                continue

            path1 = find_path_directional(
                db,
                source,
                mid_sys,
                max_hop,
                max_nodes=max_nodes,
                max_neighbors=max_neighbors,
                allowed_star_ids=allowed_star_ids,
                step_threshold=step_threshold,
                expand_factor=expand_factor,
                in_memory_buckets=in_memory_buckets,
                relax_factor=relax_factor,
                allow_relaxation=False,
                on_progress=on_progress,
                only_neutron=only_neutron,
            )
            if path1:
                path2 = find_path_directional(
                    db,
                    mid_sys,
                    target,
                    max_hop,
                    max_nodes=max_nodes,
                    max_neighbors=max_neighbors,
                    allowed_star_ids=allowed_star_ids,
                    step_threshold=step_threshold,
                    expand_factor=expand_factor,
                    in_memory_buckets=in_memory_buckets,
                    relax_factor=relax_factor,
                    allow_relaxation=False,
                    on_progress=on_progress,
                    only_neutron=only_neutron,
                )
                if path2:
                    return path1 + path2[1:]

    # 3. Relaxation search
    _emit("Pathfinding: Waypoints failed, resorting to relaxation...")
    return find_path_directional(
        db,
        source,
        target,
        max_hop,
        max_nodes=max_nodes,
        max_neighbors=max_neighbors,
        allowed_star_ids=allowed_star_ids,
        step_threshold=step_threshold,
        expand_factor=expand_factor,
        in_memory_buckets=in_memory_buckets,
        relax_factor=relax_factor,
        allow_relaxation=True,
        on_progress=on_progress,
        only_neutron=only_neutron,
    )

def find_path_robust(
    db: DatabaseManager,
    source: System,
    target: System,
    max_hop: float,
    max_nodes: int = 5000,
    max_neighbors: int = 500,
    allowed_star_ids: Optional[Set[int]] = None,
    step_threshold: float = 1.0,
    expand_factor: float = 2.0,
    in_memory_buckets: Optional[Dict[Tuple[int, int, int], List[Dict]]] = None,
    relax_factor: float = 1.1,
    waypoint_tries: int = 50,
    on_progress: Optional[Callable[[str], None]] = None,
    only_neutron: bool = False,
) -> Optional[List[System]]:
    """Directional stepping pathfinder that searches both directions and picks the best."""

    def _emit(msg: str):
        if on_progress:
            on_progress(msg)
        else:
            if msg == "\n":
                print()
            else:
                print(msg, end="\r", flush=True)

    def _get_path_metrics(path: List[System]) -> Tuple[float, int]:
        if not path:
            return (float("inf"), float("inf"))
        dist = 0.0
        relaxed = 0
        for i in range(1, len(path)):
            c1, c2 = path[i - 1].coords, path[i].coords
            dist += math.sqrt(
                (c2.x - c1.x) ** 2
                + (c2.y - c1.y) ** 2
                + (c2.z - c1.z) ** 2
            )
            if path[i]._relaxed_hop is not None:
                relaxed += 1
        return (dist, relaxed)

    _emit("Pathfinding: Searching A -> B...")
    p1 = _find_path_robust_single(
        db,
        source,
        target,
        max_hop,
        max_nodes=max_nodes,
        max_neighbors=max_neighbors,
        allowed_star_ids=allowed_star_ids,
        step_threshold=step_threshold,
        expand_factor=expand_factor,
        in_memory_buckets=in_memory_buckets,
        relax_factor=relax_factor,
        waypoint_tries=waypoint_tries,
        on_progress=on_progress,
        only_neutron=only_neutron,
    )

    _emit("Pathfinding: Searching B -> A...")
    p2_rev = _find_path_robust_single(
        db,
        target,
        source,
        max_hop,
        max_nodes=max_nodes,
        max_neighbors=max_neighbors,
        allowed_star_ids=allowed_star_ids,
        step_threshold=step_threshold,
        expand_factor=expand_factor,
        in_memory_buckets=in_memory_buckets,
        relax_factor=relax_factor,
        waypoint_tries=waypoint_tries,
        on_progress=on_progress,
        only_neutron=only_neutron,
    )
    p2 = p2_rev[::-1] if p2_rev else None

    m1 = _get_path_metrics(p1) if p1 else (float("inf"), float("inf"))
    m2 = _get_path_metrics(p2) if p2 else (float("inf"), float("inf"))

    if p1 and p2:
        if m1[1] < m2[1]:
            return p1
        if m2[1] < m1[1]:
            return p2
        return p1 if m1[0] <= m2[0] else p2
    return p1 or p2
