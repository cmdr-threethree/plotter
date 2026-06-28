from typing import Dict, List, Optional, Set, Tuple, Callable
from plotter.models import Coordinates, System
from plotter.database import DatabaseManager
from plotter.routing.astar import find_path_robust

def find_path_neutron_highway(
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
) -> Optional[List[System]]:
    """Neutron highway strategy:
    1. Find nearest neutron to source.
    2. Route from that neutron to target using ONLY neutron stars for intermediate hops.
    3. The destination target is allowed even if not a neutron star.
    """

    def _emit(msg: str):
        if on_progress:
            on_progress(msg)

    _emit("Neutron Highway: Finding nearest neutron to source...")
    near_neutron = db.nearest_neutron(source.coords)
    if not near_neutron:
        _emit("Neutron Highway: No neutron star found near source.")
        return None

    _emit(f"Neutron Highway: Nearest neutron is {near_neutron.name}. Routing...")

    path = find_path_robust(
        db,
        near_neutron,
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
        only_neutron=True,
    )

    if not path:
        return None

    if path[0].id64 != source.id64:
        path = [source] + path

    return path
