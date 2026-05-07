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
        # Build meta
        mod.build_meta(self.json_path, self.schema_path, self.meta_path)
        self.assertTrue(os.path.exists(self.meta_path))
        with open(self.meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertIn("prefixes", meta)
        self.assertIn("starTypes", meta)
        # prefixes should include 'Sol' and 'FarAway' (FarAway may be full name prefix)
        prefixes = set(meta["prefixes"].values())
        self.assertIn("Sol", prefixes)

        # Build index (force to ensure clean DB)
        mod.build_index_prefix(
            self.json_path,
            self.db_path,
            bucket_size=50.0,
            meta_path=self.meta_path,
            force=True,
            coord_scale=32,
        )
        self.assertTrue(os.path.exists(self.db_path))

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM systems")
        count = cur.fetchone()[0]

        # load DB parameters
        coord_scale = int(
            conn.execute(
                'SELECT value FROM db_meta WHERE key="coord_scale"'
            ).fetchone()[0]
        )

        # Pre-build maps as mod.main does
        id_to_prefix = {int(k): v for k, v in meta.get("prefixes", {}).items()}
        id_to_star = {int(k): v for k, v in meta.get("starTypes", {}).items()}

        # compute expected rows by reading the json and counting non-permit entries
        with open(self.json_path, "r", encoding="utf-8") as f:
            systems = json.load(f)
        expected_rows = sum(1 for s in systems if not s.get("needsPermit"))
        self.assertEqual(count, expected_rows)

        # Choose two non-permit systems from the JSON for lookup/path tests
        non_permit = [s for s in systems if not s.get("needsPermit")]
        self.assertTrue(len(non_permit) >= 2)
        first_sys = non_permit[0]
        # pick another a few steps away (prefer index+5 if exists)
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

        # Pathfinding between the two chosen systems using max_hop=40 (nodes are spaced 30 apart in sample_large)
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
        # path should have at least 2 nodes
        self.assertTrue(len(ids) >= 2)

        # Test nearest_of_type
        # Find nearest system of the same type as first_sys
        star_name_to_id = {v: int(k) for k, v in meta.get("starTypes", {}).items()}
        first_star_type = first_sys.get("mainStar")
        type_id = star_name_to_id.get(first_star_type)
        if type_id is not None:
            near_coords = first_sys["coords"]
            res_nearest = mod.nearest_of_type(conn, near_coords, [type_id], coord_scale)
            self.assertIsNotNone(res_nearest)
            # It should find first_sys itself as it's at the exact coordinates
            self.assertEqual(res_nearest["id64"], first_sys["id64"])

        conn.close()


if __name__ == "__main__":
    unittest.main()
