from dataclasses import dataclass
from typing import Dict, Any, Union, Optional

@dataclass(frozen=True)
class Coordinates:
    x: float
    y: float
    z: float

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def from_dict(cls, d: Dict[str, Union[float, int]]) -> "Coordinates":
        return cls(x=float(d["x"]), y=float(d["y"]), z=float(d["z"]))


@dataclass
class System:
    id64: int
    name: str
    coords: Coordinates
    mainStar: str = ""
    needs_permit: bool = False
    is_neutron: bool = False
    dist: Optional[float] = None
    _relaxed_hop: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "id64": self.id64,
            "name": self.name,
            "coords": self.coords.to_dict(),
            "mainStar": self.mainStar,
            "needs_permit": self.needs_permit,
            "is_neutron": self.is_neutron,
        }
        if self.dist is not None:
            res["dist"] = self.dist
        if self._relaxed_hop is not None:
            res["_relaxed_hop"] = self._relaxed_hop
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "System":
        coords_data = d["coords"]
        if isinstance(coords_data, dict):
            coords = Coordinates.from_dict(coords_data)
        elif isinstance(coords_data, (list, tuple)) and len(coords_data) == 3:
            coords = Coordinates(x=float(coords_data[0]), y=float(coords_data[1]), z=float(coords_data[2]))
        elif isinstance(coords_data, Coordinates):
            coords = coords_data
        else:
            raise TypeError(f"Invalid coordinate format: {coords_data}")

        needs_permit = bool(d.get("needs_permit", d.get("needsPermit", False)))
        main_star = d.get("mainStar") or d.get("main_star") or d.get("star_type") or ""

        return cls(
            id64=int(d["id64"]),
            name=d["name"],
            coords=coords,
            mainStar=main_star,
            needs_permit=needs_permit,
            is_neutron=bool(d.get("is_neutron", False)),
            dist=d.get("dist"),
            _relaxed_hop=d.get("_relaxed_hop"),
        )


