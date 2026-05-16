import os
import sys
import json
import sqlite3
import tempfile
import unittest

# Ensure scripts directory is importable
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

import distance_cli_sqlite_prefix as mod


class TestDistanceCliSqlitePrefix(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        sample_large = os.path.join(os.path.dirname(__file__), "sample_large.json")
        # If a larger sample exists in tests/, use it; otherwise create a small sample
        if os.path.exists(sample_large):
            self.json_path = sample_large
        else:
            self.json_path = os.path.join(self.tmpdir.name, "sample.json")

        self.schema_path = os.path.join(self.tmpdir.name, "schema.json")
        self.meta_path = os.path.join(self.tmpdir.name, "meta.json")
        self.db_path = os.path.join(self.tmpdir.name, "systems.db")

        # sample schema with mainStar enum
        schema = {"items": {"properties": {"mainStar": {"enum": ["G", "K", "M"]}}}}
        with open(self.schema_path, "w", encoding="utf-8") as sf:
            json.dump(schema, sf)

        # If no large sample, create a small pretty-printed JSON array
        if not os.path.exists(sample_large):
            systems = [
                {
                    "id64": 1,
                    "name": "Sol-Alpha",
                    "coords": {"x": 0, "y": 0, "z": 0},
                    "needsPermit": False,
                    "mainStar": "G",
                },
                {
                    "id64": 2,
                    "name": "Sol-Beta",
                    "coords": {"x": 30, "y": 0, "z": 0},
                    "needsPermit": False,
                    "mainStar": "K",
                },
                {
                    "id64": 3,
                    "name": "FarAway",
                    "coords": {"x": 1000, "y": 0, "z": 0},
                    "needsPermit": True,
                    "mainStar": "M",
                },
                {
                    "id64": 4,
                    "name": "Sol-Gamma",
                    "coords": {"x": 60, "y": 0, "z": 0},
                    "needsPermit": False,
                    "mainStar": "G",
                },
            ]
            with open(self.json_path, "w", encoding="utf-8") as jf:
                jf.write("[\n")
                for i, obj in enumerate(systems):
                    s = json.dumps(obj, ensure_ascii=False)
                    if i != len(systems) - 1:
                        jf.write(s + ",\n")
                    else:
                        jf.write(s + "\n")
                jf.write("]\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_extract_prefix_and_clean_parse(self):
        # extract_prefix
        self.assertEqual(mod.extract_prefix("Ab-Cd"), "Ab")
        self.assertEqual(mod.extract_prefix("Hello World"), "Hello")
        self.assertEqual(mod.extract_prefix("NoSep"), "NoSep")
        # clean_json_line and parse_line_object
        line = '  {"id64":1, "name":"X"},\n'
        cleaned = mod.clean_json_line(line)
        self.assertTrue(cleaned.startswith("{"))
        obj = mod.parse_line_object(line)
        self.assertIsInstance(obj, dict)
        self.assertEqual(obj["id64"], 1)

    def test_build_meta_and_index_and_query_and_path(self):
        # 1. Test classic two-pass for backward compatibility of the tool
        mod.build_meta(self.json_path, self.schema_path, self.meta_path)
        self.assertTrue(os.path.exists(self.meta_path))
        with open(self.meta_path, "r", encoding="utf-8") as f:
            meta_json = json.load(f)
        self.assertIn("prefixes", meta_json)
        self.assertIn("starTypes", meta_json)

        # 2. Test single-pass build (preferred)
        mod.build_index_prefix(
            self.json_path,
            self.db_path,
            bucket_size=50.0,
            schema_path=self.schema_path,
            force=True,
            coord_scale=32,
        )
        self.assertTrue(os.path.exists(self.db_path))

        conn = mod.open_db(self.db_path)
        
        # load meta from DB
        meta = mod.load_meta_from_db(conn)
        self.assertTrue(len(meta["prefixes"]) > 0)
        self.assertTrue(len(meta["starTypes"]) > 0)

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM systems")
        count = cur.fetchone()[0]

        # load DB parameters
        coord_scale = int(
            conn.execute(
                'SELECT value FROM db_meta WHERE key="coord_scale"'
            ).fetchone()[0]
        )

        # Pre-build maps
        id_to_prefix = {int(k): v for k, v in meta.get("prefixes", {}).items()}
        id_to_star = {int(k): v for k, v in meta.get("starTypes", {}).items()}

        # compute expected rows by reading the json
        with open(self.json_path, "r", encoding="utf-8") as f:
            systems = json.load(f)
        expected_rows = len(systems)
        self.assertEqual(count, expected_rows)

        # Choose two non-permit systems from the JSON for lookup/path tests
        non_permit = [s for s in systems if not s.get("needsPermit")]
        self.assertTrue(len(non_permit) >= 2)
        first_sys = non_permit[0]
        second_idx = min(5, len(non_permit) - 1)
        second_sys = non_permit[second_idx]

        # Test id lookup via get_system_by_query_prefix
        res = mod.get_system_by_query_prefix(
            conn, str(first_sys["id64"]), meta, id_to_prefix, id_to_star, coord_scale
        )
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id64"], first_sys["id64"])

        # Test exact name lookup: full name must match prefix+suffix
        res2 = mod.get_system_by_query_prefix(
            conn, first_sys["name"], meta, id_to_prefix, id_to_star, coord_scale
        )
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["id64"], first_sys["id64"])

        # Non-existing exact name should return empty
        res3 = mod.get_system_by_query_prefix(
            conn, "Nonexistent-System", meta, id_to_prefix, id_to_star, coord_scale
        )
        self.assertEqual(len(res3), 0)

        # Pathfinding between the two chosen systems using max_hop=40
        s1 = res2[0]
        s2 = mod.get_system_by_query_prefix(
            conn, second_sys["name"], meta, id_to_prefix, id_to_star, coord_scale
        )[0]
        path = mod.find_path_robust(
            conn,
            s1,
            s2,
            max_hop=40.0,
            coord_scale=coord_scale,
            id_to_prefix=id_to_prefix,
            id_to_star=id_to_star,
            max_nodes=1000,
            max_neighbors=200,
        )
        self.assertIsNotNone(path)
        ids = [p["id64"] for p in path]
        self.assertEqual(ids[0], first_sys["id64"])
        self.assertEqual(ids[-1], second_sys["id64"])
        self.assertTrue(len(ids) >= 2)

        # Test nearest_of_type
        star_name_to_id = {v: int(k) for k, v in meta.get("starTypes", {}).items()}
        first_star_type = first_sys.get("mainStar")
        type_id = star_name_to_id.get(first_star_type)
        if type_id is not None:
            near_coords = first_sys["coords"]
            # With self-exclusion, it should find another system of the same type (or return None if only one exists)
            res_nearest = mod.nearest_of_type(conn, near_coords, [type_id], coord_scale, exclude_id64=first_sys["id64"])
            if res_nearest:
                self.assertNotEqual(res_nearest["id64"], first_sys["id64"])
                self.assertTrue(res_nearest["dist"] >= 0)

        conn.close()

    def test_neutron_highway_routing(self):
        # 1. Create a line of systems
        # A(0,0,0), B(100,0,0), C(200,0,0), D(300,0,0), E(400,0,0)
        systems = [
            {"id64": 10, "name": "A", "coords": {"x": 0, "y": 0, "z": 0}, "mainStar": "G"},
            {"id64": 11, "name": "B", "coords": {"x": 100, "y": 0, "z": 0}, "mainStar": "N"},
            {"id64": 12, "name": "C", "coords": {"x": 200, "y": 0, "z": 0}, "mainStar": "N"},
            {"id64": 13, "name": "D", "coords": {"x": 300, "y": 0, "z": 0}, "mainStar": "N"},
            {"id64": 14, "name": "E", "coords": {"x": 400, "y": 0, "z": 0}, "mainStar": "G"},
        ]
        base_json = os.path.join(self.tmpdir.name, "neutron_test_base.json")
        with open(base_json, "w") as f:
            f.write("[\n")
            for i, s in enumerate(systems):
                f.write(json.dumps(s))
                if i < len(systems) - 1:
                    f.write(",\n")
                else:
                    f.write("\n")
            f.write("]\n")

        # Build initial index
        mod.build_index_prefix(base_json, self.db_path, bucket_size=50.0, force=True, coord_scale=32)

        # Mark B, C, D as neutrons
        neutron_systems = [systems[1], systems[2], systems[3]]
        neutron_json = os.path.join(self.tmpdir.name, "neutron_test_only.json")
        with open(neutron_json, "w") as f:
            f.write("[\n")
            for i, s in enumerate(neutron_systems):
                f.write(json.dumps(s))
                if i < len(neutron_systems) - 1:
                    f.write(",\n")
                else:
                    f.write("\n")
            f.write("]\n")

        mod.build_index_prefix(neutron_json, self.db_path, bucket_size=50.0, mark_neutron=True, coord_scale=32)

        conn = mod.open_db(self.db_path)
        meta = mod.load_meta_from_db(conn)
        id_to_prefix = {int(k): v for k, v in meta["prefixes"].items()}
        id_to_star = {int(k): v for k, v in meta["starTypes"].items()}
        coord_scale = 32

        # Get source and target
        s1 = mod.get_system_by_query_prefix(conn, "A", meta, id_to_prefix, id_to_star, coord_scale)[0]
        s2 = mod.get_system_by_query_prefix(conn, "E", meta, id_to_prefix, id_to_star, coord_scale)[0]

        # Test routing with max_hop = 150
        # A -> B (100), B -> C (100), C -> D (100), D -> E (100)
        path = mod.find_path_neutron_highway(
            conn, s1, s2, max_hop=150.0, coord_scale=coord_scale,
            id_to_prefix=id_to_prefix, id_to_star=id_to_star
        )

        self.assertIsNotNone(path)
        self.assertEqual(len(path), 5)
        self.assertEqual(path[0]["name"], "A")
        self.assertEqual(path[-1]["name"], "E")
        self.assertEqual(path[1]["name"], "B")
        self.assertEqual(path[2]["name"], "C")
        self.assertEqual(path[3]["name"], "D")

        # Verify intermediate hops are neutrons (B, C, D)
        # Check in DB
        for hop in path[1:-1]:
            cur = conn.execute("SELECT is_neutron FROM systems WHERE id64=?", (hop["id64"],))
            self.assertEqual(cur.fetchone()[0], 1)

        # Test if no neutron is found near source (radius expansion limit is 10000)
        s_far = {"id64": 99, "name": "Far", "coords": {"x": 20000, "y": 0, "z": 0}, "mainStar": "G"}
        path_far = mod.find_path_neutron_highway(
            conn, s_far, s2, max_hop=150.0, coord_scale=coord_scale,
            id_to_prefix=id_to_prefix, id_to_star=id_to_star
        )
        self.assertIsNone(path_far)

        conn.close()

    def test_immutable_mode(self):
        mod.build_index_prefix(self.json_path, self.db_path, bucket_size=50.0, force=True)
        self.assertTrue(os.path.exists(self.db_path))

        # Open in immutable mode
        conn = mod.open_db(self.db_path, immutable=True)
        try:
            # Reads should work
            cur = conn.execute("SELECT COUNT(*) FROM systems")
            self.assertTrue(cur.fetchone()[0] > 0)

            # Writes should fail
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO systems (id64) VALUES (999999)")
        finally:
            conn.close()

    def test_permit_system_routing(self):
        # Setup systems:
        # A(0,0,0) - No permit
        # P(50,0,0) - NEEDS permit
        # C(50,10,0) - No permit
        # B(100,0,0) - No permit
        # Max hop 60.
        # A -> B should use C, not P.
        # A -> P should work.
        # P -> B should work.
        systems = [
            {"id64": 100, "name": "A", "coords": {"x": 0, "y": 0, "z": 0}, "needsPermit": False},
            {"id64": 101, "name": "P", "coords": {"x": 50, "y": 0, "z": 0}, "needsPermit": True},
            {"id64": 102, "name": "C", "coords": {"x": 50, "y": 10, "z": 0}, "needsPermit": False},
            {"id64": 103, "name": "B", "coords": {"x": 100, "y": 0, "z": 0}, "needsPermit": False},
        ]
        json_path = os.path.join(self.tmpdir.name, "permit_test.json")
        with open(json_path, "w") as f:
            f.write("[\n")
            for i, s in enumerate(systems):
                f.write(json.dumps(s))
                if i < len(systems) - 1:
                    f.write(",\n")
                else:
                    f.write("\n")
            f.write("]\n")

        mod.build_index_prefix(json_path, self.db_path, bucket_size=50.0, force=True, coord_scale=32)
        conn = mod.open_db(self.db_path)
        meta = mod.load_meta_from_db(conn)
        id_to_prefix = {int(k): v for k, v in meta["prefixes"].items()}
        id_to_star = {int(k): v for k, v in meta["starTypes"].items()}
        coord_scale = 32

        def get_sys(name):
            return mod.get_system_by_query_prefix(conn, name, meta, id_to_prefix, id_to_star, coord_scale)[0]

        sA = get_sys("A")
        sP = get_sys("P")
        sC = get_sys("C")
        sB = get_sys("B")

        # 1. A -> B should avoid P and use C
        path = mod.find_path_robust(conn, sA, sB, max_hop=60.0, coord_scale=coord_scale,
                                   id_to_prefix=id_to_prefix, id_to_star=id_to_star)
        self.assertIsNotNone(path)
        ids = [p["id64"] for p in path]
        self.assertIn(102, ids) # Should use C
        self.assertNotIn(101, ids[1:-1]) # Should NOT use P as intermediate

        # 2. A -> P should work (Target is permit system)
        path_to_p = mod.find_path_robust(conn, sA, sP, max_hop=60.0, coord_scale=coord_scale,
                                        id_to_prefix=id_to_prefix, id_to_star=id_to_star)
        self.assertIsNotNone(path_to_p)
        self.assertEqual(path_to_p[-1]["id64"], 101)

        # 3. P -> B should work (Source is permit system)
        path_from_p = mod.find_path_robust(conn, sP, sB, max_hop=60.0, coord_scale=coord_scale,
                                          id_to_prefix=id_to_prefix, id_to_star=id_to_star)
        self.assertIsNotNone(path_from_p)
        self.assertEqual(path_from_p[0]["id64"], 101)

        conn.close()


if __name__ == "__main__":
    unittest.main()
