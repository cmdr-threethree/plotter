import unittest
import tempfile
import os
from plotter.models import Coordinates, System
from plotter.database import DatabaseManager
from plotter.routing import find_path_robust, find_path_neutron_highway

class TestRouting(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_routing.db")
        self.db = DatabaseManager(self.db_path)
        self.db.ensure_schema()

        # Seed metadata and scales
        cur = self.db.conn.cursor()
        cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('coord_scale', '32')")
        cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('bucket_size', '50.0')")
        cur.execute("INSERT OR REPLACE INTO prefixes (id, prefix) VALUES (1, 'Sys')")
        cur.execute("INSERT OR REPLACE INTO star_types (id, type_name) VALUES (1, 'G-Type')")
        cur.execute("INSERT OR REPLACE INTO star_types (id, type_name) VALUES (2, 'Neutron Star')")
        self.db.conn.commit()
        self.db._load_meta()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_robust_pathfinding_basic(self):
        # Create a line of systems:
        # A(0,0,0) -> B(30,0,0) -> C(60,0,0)
        # Max hop = 40.0. A -> C should work via B.
        cur = self.db.conn.cursor()
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (1, 1, ' A', 0, 0, 0, 1, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (1, 0, 0, 0, 0, 0, 0)")
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (2, 1, ' B', 960, 0, 0, 1, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (2, 960, 960, 0, 0, 0, 0)")
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (3, 1, ' C', 1920, 0, 0, 1, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (3, 1920, 1920, 0, 0, 0, 0)")
        self.db.conn.commit()

        sys_a = self.db.get_system_by_query("1")[0]
        sys_c = self.db.get_system_by_query("3")[0]

        path = find_path_robust(self.db, sys_a, sys_c, max_hop=40.0)
        self.assertIsNotNone(path)
        self.assertEqual(len(path), 3)
        self.assertEqual(path[0].id64, 1)
        self.assertEqual(path[1].id64, 2)
        self.assertEqual(path[2].id64, 3)

    def test_neutron_highway_routing(self):
        # Create a highway setup:
        # Source A(0,0,0), Neutron B(100,0,0), Target C(200,0,0)
        # Max hop = 120.0
        cur = self.db.conn.cursor()
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (1, 1, ' A', 0, 0, 0, 1, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (1, 0, 0, 0, 0, 0, 0)")
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (2, 1, ' B', 3200, 0, 0, 2, 1, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (2, 3200, 3200, 0, 0, 0, 0)")
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (3, 1, ' C', 6400, 0, 0, 1, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (3, 6400, 6400, 0, 0, 0, 0)")
        self.db.conn.commit()

        sys_a = self.db.get_system_by_query("1")[0]
        sys_c = self.db.get_system_by_query("3")[0]

        path = find_path_neutron_highway(self.db, sys_a, sys_c, max_hop=120.0)
        self.assertIsNotNone(path)
        self.assertEqual(len(path), 3)
        self.assertEqual(path[0].id64, 1)
        self.assertEqual(path[1].id64, 2)
        self.assertEqual(path[2].id64, 3)
        self.assertTrue(path[1].is_neutron)
