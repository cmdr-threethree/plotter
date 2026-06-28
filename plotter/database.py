import sqlite3
import math
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from plotter.models import Coordinates, System

class DatabaseManager:
    """Manages SQLite connections, database schemas, and all system search and spatial queries."""

    def __init__(self, db_path: str, immutable: bool = False, check_same_thread: bool = True):
        self.db_path = db_path
        self.immutable = immutable
        self.check_same_thread = check_same_thread
        self.conn = self._open_db()

        self.id_to_prefix: Dict[int, str] = {}
        self.id_to_star: Dict[int, str] = {}
        self.star_to_id: Dict[str, int] = {}
        self.coord_scale: int = 1
        self.bucket_size: float = 50.0

        self._load_meta()

    def _open_db(self) -> sqlite3.Connection:
        if self.immutable:
            # Immutable mode using URI
            conn = sqlite3.connect(
                f"file:{self.db_path}?immutable=1", uri=True, check_same_thread=self.check_same_thread
            )
        else:
            conn = sqlite3.connect(self.db_path, check_same_thread=self.check_same_thread)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=OFF;")

        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size = -65536;")  # 64 MB page cache
        conn.execute("PRAGMA mmap_size = 2147483648;")  # 2 GB memory-mapped reads
        return conn

    def _load_meta(self) -> None:
        try:
            meta = self.load_meta_from_db()
            self.id_to_prefix = {int(k): v for k, v in meta.get("prefixes", {}).items()}
            self.id_to_star = {int(k): v for k, v in meta.get("starTypes", {}).items()}
            self.star_to_id = {v: k for k, v in self.id_to_star.items()}

            coord_scale_row = self.conn.execute(
                'SELECT value FROM db_meta WHERE key="coord_scale"'
            ).fetchone()
            if coord_scale_row:
                self.coord_scale = int(coord_scale_row[0])

            bucket_size_row = self.conn.execute(
                'SELECT value FROM db_meta WHERE key="bucket_size"'
            ).fetchone()
            if bucket_size_row:
                self.bucket_size = float(bucket_size_row[0])
        except sqlite3.OperationalError:
            pass

    def load_meta_from_db(self) -> Dict[str, Dict[str, str]]:
        cur = self.conn.cursor()
        prefixes = {}
        try:
            cur.execute("SELECT id, prefix FROM prefixes")
            for pid, prefix in cur:
                prefixes[str(pid)] = prefix
        except sqlite3.OperationalError:
            pass

        star_types = {}
        try:
            cur.execute("SELECT id, type_name FROM star_types")
            for sid, name in cur:
                star_types[str(sid)] = name
        except sqlite3.OperationalError:
            pass

        return {"prefixes": prefixes, "starTypes": star_types}

    def close(self) -> None:
        if self.conn:
            self.conn.close()

    def ensure_schema(self) -> None:
        """Create the database tables and indexes if they do not exist."""
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS systems (
                id64 INTEGER PRIMARY KEY,
                prefix_id INTEGER,
                x INTEGER,
                y INTEGER,
                z INTEGER,
                star_type_id INTEGER,
                name_suffix TEXT,
                is_neutron INTEGER DEFAULT 0,
                needs_permit INTEGER DEFAULT 0
            )
            """
        )
        try:
            cur.execute("ALTER TABLE systems ADD COLUMN is_neutron INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cur.execute("ALTER TABLE systems ADD COLUMN needs_permit INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        cur.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS rtree_systems USING rtree(
                id64,
                min_x, max_x,
                min_y, max_y,
                min_z, max_z
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_prefix ON systems(prefix_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_star_type ON systems(star_type_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_systems_neutron ON systems(is_neutron) WHERE is_neutron = 1")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_systems_permit ON systems(needs_permit) WHERE needs_permit = 1")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS prefixes (
                id INTEGER PRIMARY KEY,
                prefix TEXT UNIQUE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS star_types (
                id INTEGER PRIMARY KEY,
                type_name TEXT UNIQUE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS db_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self.conn.commit()

    def get_system_by_query(self, query: str, limit: int = 10) -> List[System]:
        """Find systems by id64 or exact full-name match (prefix + name_suffix)."""
        if query.isdigit():
            q_int = int(query)
            cur = self.conn.execute(
                """
                SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, st.type_name, p.prefix, s.needs_permit, s.is_neutron
                FROM systems s
                LEFT JOIN star_types st ON st.id = s.star_type_id
                LEFT JOIN prefixes p ON p.id = s.prefix_id
                WHERE s.id64=?
                """,
                (q_int,),
            )
            row = cur.fetchone()
            if row:
                name = (row[7] or "") + (row[2] or "")
                star = row[6] or ""
                x, y, z = row[3] / self.coord_scale, row[4] / self.coord_scale, row[5] / self.coord_scale
                return [
                    System(
                        id64=row[0],
                        name=name,
                        coords=Coordinates(x, y, z),
                        mainStar=star,
                        needs_permit=bool(row[8]),
                        is_neutron=bool(row[9]),
                    )
                ]

        candidates = [query[:i] for i in range(len(query), 0, -1)]
        if not candidates:
            return []

        placeholders = ",".join("?" for _ in candidates)
        prefix_rows = self.conn.execute(
            f"SELECT id, prefix FROM prefixes WHERE prefix IN ({placeholders})",
            tuple(candidates),
        ).fetchall()

        prefix_rows.sort(key=lambda r: len(r[1]), reverse=True)

        out: List[System] = []
        for pid, prefix_str in prefix_rows:
            suffix = query[len(prefix_str) :]
            cur = self.conn.execute(
                """
                SELECT s.id64, s.x, s.y, s.z, st.type_name, s.needs_permit, s.is_neutron
                FROM systems s
                LEFT JOIN star_types st ON st.id = s.star_type_id
                WHERE s.prefix_id=? AND s.name_suffix=?
                LIMIT ?
                """,
                (pid, suffix, limit - len(out)),
            )
            for r in cur:
                x, y, z = r[1] / self.coord_scale, r[2] / self.coord_scale, r[3] / self.coord_scale
                out.append(
                    System(
                        id64=r[0],
                        name=query,
                        coords=Coordinates(x, y, z),
                        mainStar=r[4] or "",
                        needs_permit=bool(r[5]),
                        is_neutron=bool(r[6]),
                    )
                )
                if len(out) >= limit:
                    return out

        return out

    def nearest_neutron(self, near_coords: Union[Coordinates, Dict[str, float]], initial_radius: float = 50.0) -> Optional[System]:
        """Find the nearest neutron star to given coordinates using expanding radius R-tree search."""
        if isinstance(near_coords, dict):
            cx, cy, cz = near_coords["x"], near_coords["y"], near_coords["z"]
        else:
            cx, cy, cz = near_coords.x, near_coords.y, near_coords.z

        radius = initial_radius
        while True:
            s_dist = radius * self.coord_scale
            s_cx, s_cy, s_cz = cx * self.coord_scale, cy * self.coord_scale, cz * self.coord_scale
            min_x, max_x = s_cx - s_dist, s_cx + s_dist
            min_y, max_y = s_cy - s_dist, s_cy + s_dist
            min_z, max_z = s_cz - s_dist, s_cz + s_dist

            sql = """
                SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, st.type_name, p.prefix, s.needs_permit, s.is_neutron
                FROM rtree_systems r
                JOIN systems s ON s.id64 = r.id64
                LEFT JOIN star_types st ON st.id = s.star_type_id
                LEFT JOIN prefixes p ON p.id = s.prefix_id
                WHERE r.min_x BETWEEN ? AND ?
                  AND r.min_y BETWEEN ? AND ?
                  AND r.min_z BETWEEN ? AND ?
                  AND s.is_neutron = 1
                LIMIT 1
            """
            row = self.conn.execute(sql, (min_x, max_x, min_y, max_y, min_z, max_z)).fetchone()
            if row:
                rx, ry, rz = (
                    row[3] / self.coord_scale,
                    row[4] / self.coord_scale,
                    row[5] / self.coord_scale,
                )
                name = (row[7] or "") + (row[2] or "")
                star = row[6] or ""
                return System(
                    id64=row[0],
                    name=name,
                    coords=Coordinates(rx, ry, rz),
                    mainStar=star,
                    needs_permit=bool(row[8]),
                    is_neutron=bool(row[9]),
                )
            if radius > 10000:
                return None
            radius *= 2

    def nearest_system(self, near_coords: Union[Coordinates, Dict[str, float]], initial_radius: float = 50.0) -> Optional[System]:
        """Find the nearest system to given coordinates using expanding radius R-tree search."""
        if isinstance(near_coords, dict):
            cx, cy, cz = near_coords["x"], near_coords["y"], near_coords["z"]
        else:
            cx, cy, cz = near_coords.x, near_coords.y, near_coords.z

        radius = initial_radius
        while True:
            s_dist = radius * self.coord_scale
            s_cx, s_cy, s_cz = cx * self.coord_scale, cy * self.coord_scale, cz * self.coord_scale
            min_x, max_x = s_cx - s_dist, s_cx + s_dist
            min_y, max_y = s_cy - s_dist, s_cy + s_dist
            min_z, max_z = s_cz - s_dist, s_cz + s_dist
            sql = """
                SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, st.type_name, p.prefix, s.needs_permit, s.is_neutron
                FROM rtree_systems r
                JOIN systems s ON s.id64 = r.id64
                LEFT JOIN star_types st ON st.id = s.star_type_id
                LEFT JOIN prefixes p ON p.id = s.prefix_id
                WHERE r.min_x BETWEEN ? AND ?
                  AND r.min_y BETWEEN ? AND ?
                  AND r.min_z BETWEEN ? AND ?
                LIMIT 1
            """
            row = self.conn.execute(sql, (min_x, max_x, min_y, max_y, min_z, max_z)).fetchone()
            if row:
                rx, ry, rz = (
                    row[3] / self.coord_scale,
                    row[4] / self.coord_scale,
                    row[5] / self.coord_scale,
                )
                name = (row[7] or "") + (row[2] or "")
                star = row[6] or ""
                return System(
                    id64=row[0],
                    name=name,
                    coords=Coordinates(rx, ry, rz),
                    mainStar=star,
                    needs_permit=bool(row[8]),
                    is_neutron=bool(row[9]),
                )
            if radius > 10000:
                return None
            radius *= 2

    def nearest_of_type(
        self,
        near_coords: Union[Coordinates, Dict[str, float]],
        type_ids: Optional[List[int]],
        initial_radius: float = 50.0,
        exclude_id64: Optional[int] = None,
    ) -> Optional[System]:
        """Find nearest system of matching star type, excluding self and systems at identical coordinates."""
        if isinstance(near_coords, dict):
            cx, cy, cz = near_coords["x"], near_coords["y"], near_coords["z"]
        else:
            cx, cy, cz = near_coords.x, near_coords.y, near_coords.z

        radius = initial_radius
        while True:
            s_dist = radius * self.coord_scale
            s_cx, s_cy, s_cz = cx * self.coord_scale, cy * self.coord_scale, cz * self.coord_scale
            min_x, max_x = s_cx - s_dist, s_cx + s_dist
            min_y, max_y = s_cy - s_dist, s_cy + s_dist
            min_z, max_z = s_cz - s_dist, s_cz + s_dist

            sql = """
                SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, st.type_name, p.prefix, s.needs_permit, s.is_neutron
                FROM rtree_systems r
                JOIN systems s ON s.id64 = r.id64
                LEFT JOIN star_types st ON st.id = s.star_type_id
                LEFT JOIN prefixes p ON p.id = s.prefix_id
                WHERE r.min_x BETWEEN ? AND ?
                  AND r.min_y BETWEEN ? AND ?
                  AND r.min_z BETWEEN ? AND ?
            """
            params = [min_x, max_x, min_y, max_y, min_z, max_z]
            if type_ids:
                placeholders = ",".join("?" for _ in type_ids)
                sql += f" AND s.star_type_id IN ({placeholders})"
                params.extend(type_ids)

            rows = self.conn.execute(sql, tuple(params)).fetchall()
            best = None
            best_d2 = None

            for r in rows:
                if exclude_id64 is not None and r[0] == exclude_id64:
                    continue
                rx, ry, rz = r[3] / self.coord_scale, r[4] / self.coord_scale, r[5] / self.coord_scale
                if rx == cx and ry == cy and rz == cz:
                    continue
                d2 = (rx - cx) ** 2 + (ry - cy) ** 2 + (rz - cz) ** 2
                if d2 <= radius**2:
                    if best is None or d2 < best_d2:
                        best = r
                        best_d2 = d2

            if best:
                rx, ry, rz = best[3] / self.coord_scale, best[4] / self.coord_scale, best[5] / self.coord_scale
                name = (best[7] or "") + (best[2] or "")
                star = best[6] or ""
                return System(
                    id64=best[0],
                    name=name,
                    coords=Coordinates(rx, ry, rz),
                    mainStar=star,
                    needs_permit=bool(best[8]),
                    is_neutron=bool(best[9]),
                    dist=math.sqrt(best_d2),
                )

            if radius > 100000:
                return None
            radius *= 2

    def neighbors_for_center(
        self,
        center: System,
        max_distance: float,
        visited: Set[int],
        max_neighbors: int = 500,
        allowed_star_ids: Optional[Set[int]] = None,
        in_memory_buckets: Optional[Dict[Tuple[int, int, int], List[Dict[str, Any]]]] = None,
        only_neutron: bool = False,
    ) -> List[System]:
        cx, cy, cz = center.coords.x, center.coords.y, center.coords.z
        s_dist = max_distance * self.coord_scale
        s_cx, s_cy, s_cz = cx * self.coord_scale, cy * self.coord_scale, cz * self.coord_scale

        min_x, max_x = s_cx - s_dist, s_cx + s_dist
        min_y, max_y = s_cy - s_dist, s_cy + s_dist
        min_z, max_z = s_cz - s_dist, s_cz + s_dist
        max_d2 = max_distance * max_distance

        if in_memory_buckets is not None:
            out: List[Tuple[float, System]] = []
            for bucket_list in in_memory_buckets.values():
                for r in bucket_list:
                    sid = r["id64"]
                    star_id = r.get("star_type_id")
                    if allowed_star_ids and star_id not in allowed_star_ids:
                        continue
                    if only_neutron and not r.get("is_neutron"):
                        continue
                    if r.get("needs_permit"):
                        continue
                    x, y, z = (
                        r["x"] / self.coord_scale,
                        r["y"] / self.coord_scale,
                        r["z"] / self.coord_scale,
                    )
                    dx = x - cx
                    dy = y - cy
                    dz = z - cz
                    d2 = dx * dx + dy * dy + dz * dz
                    if d2 <= max_d2:
                        name = self.id_to_prefix.get(r.get("prefix_id"), "") + (r.get("name_suffix") or "")
                        star = self.id_to_star.get(star_id, "")
                        out.append(
                            (
                                d2,
                                System(
                                    id64=sid,
                                    name=name,
                                    coords=Coordinates(x, y, z),
                                    mainStar=star,
                                    needs_permit=bool(r.get("needs_permit")),
                                    is_neutron=bool(r.get("is_neutron")),
                                ),
                            )
                        )
            out.sort(key=lambda t: t[0])
            candidates = [t[1] for t in out[:max_neighbors]]
        else:
            sql = """
                SELECT s.id64, s.prefix_id, s.name_suffix, s.x, s.y, s.z, s.star_type_id, s.needs_permit, s.is_neutron
                FROM rtree_systems r
                JOIN systems s ON s.id64 = r.id64
                WHERE r.min_x BETWEEN ? AND ?
                  AND r.min_y BETWEEN ? AND ?
                  AND r.min_z BETWEEN ? AND ?
                  AND s.needs_permit = 0
            """
            if only_neutron:
                sql += " AND s.is_neutron = 1"

            cur = self.conn.execute(sql, (min_x, max_x, min_y, max_y, min_z, max_z))
            out: List[Tuple[float, System]] = []
            for r in cur:
                sid = r[0]
                star_id = r[6]
                needs_permit = bool(r[7])
                name = self.id_to_prefix.get(r[1], "") + (r[2] or "")
                star = self.id_to_star.get(star_id, "")

                if allowed_star_ids and star_id not in allowed_star_ids:
                    continue
                x, y, z = r[3] / self.coord_scale, r[4] / self.coord_scale, r[5] / self.coord_scale
                dx = x - cx
                dy = y - cy
                dz = z - cz
                d2 = dx * dx + dy * dy + dz * dz
                if d2 <= max_d2:
                    out.append(
                        (
                            d2,
                            System(
                                id64=sid,
                                name=name,
                                coords=Coordinates(x, y, z),
                                mainStar=star,
                                needs_permit=needs_permit,
                                is_neutron=bool(r[8]),
                            ),
                        )
                    )

            out.sort(key=lambda t: t[0])
            candidates = [t[1] for t in out[:max_neighbors]]

        res = []
        for c in candidates:
            sid = c.id64
            if sid == center.id64 or sid in visited:
                continue
            res.append(c)
            if len(res) >= max_neighbors:
                break
        return res
