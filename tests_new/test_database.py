import unittest
import tempfile
import os
import sqlite3
from plotter.models import Coordinates, System
from plotter.database import DatabaseManager

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_systems.db")
        self.db = DatabaseManager(self.db_path)
        self.db.ensure_schema()
        # Seed default scale and bucket size meta
        cur = self.db.conn.cursor()
        cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('coord_scale', '32')")
        cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('bucket_size', '50.0')")
        self.db.conn.commit()
        self.db._load_meta()

    def tearDown(self):
        self.db.close()
        self.tmpdir.cleanup()

    def test_ensure_schema_and_meta(self):
        # Reload metadata and verify it loaded the values from setUp
        self.db._load_meta()
        self.assertEqual(self.db.coord_scale, 32)
        self.assertEqual(self.db.bucket_size, 50.0)

    def test_get_system_by_query_id(self):
        cur = self.db.conn.cursor()
        cur.execute("INSERT OR IGNORE INTO prefixes (id, prefix) VALUES (1, 'Colonia')")
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (12345, 1, ' 4', 0, 32, 64, 0, 0, 0)"
        )
        self.db.conn.commit()
        self.db._load_meta()

        res = self.db.get_system_by_query("12345")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].id64, 12345)
        self.assertEqual(res[0].name, "Colonia 4")
        self.assertEqual(res[0].coords, Coordinates(0.0, 1.0, 2.0))
        self.assertFalse(res[0].needs_permit)
        self.assertFalse(res[0].is_neutron)

    def test_get_system_by_query_name(self):
        cur = self.db.conn.cursor()
        cur.execute("INSERT OR IGNORE INTO prefixes (id, prefix) VALUES (1, 'Colonia')")
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (12345, 1, ' 4', 0, 32, 64, 0, 0, 0)"
        )
        self.db.conn.commit()
        self.db._load_meta()

        res = self.db.get_system_by_query("Colonia 4")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].id64, 12345)
        self.assertEqual(res[0].name, "Colonia 4")

    def test_nearest_system_and_neutron(self):
        cur = self.db.conn.cursor()
        cur.execute("INSERT OR IGNORE INTO prefixes (id, prefix) VALUES (1, 'Colonia')")
        cur.execute("INSERT OR IGNORE INTO prefixes (id, prefix) VALUES (2, 'Neutron')")
        # System 1: Colonia 1 at (10, 0, 0)
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (1, 1, ' 1', 320, 0, 0, 0, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (1, 320, 320, 0, 0, 0, 0)")
        # System 2: Neutron 1 at (20, 0, 0) - is_neutron = 1
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (2, 2, ' 1', 640, 0, 0, 0, 1, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (2, 640, 640, 0, 0, 0, 0)")
        self.db.conn.commit()
        self.db._load_meta()

        # Query near (0, 0, 0)
        near = self.db.nearest_system(Coordinates(0, 0, 0))
        self.assertIsNotNone(near)
        self.assertEqual(near.id64, 1)

        # Query near neutron
        neutron = self.db.nearest_neutron(Coordinates(0, 0, 0))
        self.assertIsNotNone(neutron)
        self.assertEqual(neutron.id64, 2)

    def test_nearest_of_type(self):
        cur = self.db.conn.cursor()
        cur.execute("INSERT OR IGNORE INTO prefixes (id, prefix) VALUES (1, 'System')")
        cur.execute("INSERT OR IGNORE INTO star_types (id, type_name) VALUES (10, 'O-Type')")
        cur.execute("INSERT OR IGNORE INTO star_types (id, type_name) VALUES (11, 'B-Type')")
        
        # System 1: O-Type at (10,0,0)
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (1, 1, ' A', 320, 0, 0, 10, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (1, 320, 320, 0, 0, 0, 0)")
        
        # System 2: B-Type at (15,0,0)
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (2, 1, ' B', 480, 0, 0, 11, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (2, 480, 480, 0, 0, 0, 0)")
        self.db.conn.commit()
        self.db._load_meta()

        # Search for type 11 (B-Type) near (0,0,0)
        res = self.db.nearest_of_type(Coordinates(0,0,0), type_ids=[11])
        self.assertIsNotNone(res)
        self.assertEqual(res.id64, 2)
        self.assertEqual(res.dist, 15.0)

    def test_neighbors_for_center(self):
        cur = self.db.conn.cursor()
        cur.execute("INSERT OR IGNORE INTO prefixes (id, prefix) VALUES (1, 'System')")
        # Center: System A at (0,0,0)
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (1, 1, ' A', 0, 0, 0, 0, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (1, 0, 0, 0, 0, 0, 0)")
        # Neighbor: System B at (30,0,0) -> within 40 max distance
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (2, 1, ' B', 960, 0, 0, 0, 0, 0)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (2, 960, 960, 0, 0, 0, 0)")
        # Permitted neighbor: System C at (20,0,0) -> needs_permit = 1 (should be skipped)
        cur.execute(
            "INSERT INTO systems (id64, prefix_id, name_suffix, x, y, z, star_type_id, is_neutron, needs_permit) "
            "VALUES (3, 1, ' C', 640, 0, 0, 0, 0, 1)"
        )
        cur.execute("INSERT INTO rtree_systems VALUES (3, 640, 640, 0, 0, 0, 0)")
        self.db.conn.commit()
        self.db._load_meta()

        center = self.db.get_system_by_query("1")[0]
        neighbors = self.db.neighbors_for_center(center, max_distance=40.0, visited=set())
        
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].id64, 2)
