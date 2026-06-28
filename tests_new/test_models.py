import unittest
from plotter.models import Coordinates, System

class TestModels(unittest.TestCase):
    def test_coordinates_to_from_dict(self):
        c = Coordinates(1.2, -3.4, 5.6)
        d = c.to_dict()
        self.assertEqual(d, {"x": 1.2, "y": -3.4, "z": 5.6})
        
        c2 = Coordinates.from_dict(d)
        self.assertEqual(c2, c)

    def test_system_to_from_dict(self):
        data = {
            "id64": 12345,
            "name": "Colonia",
            "coords": {"x": 0.0, "y": 1.0, "z": 2.0},
            "mainStar": "G Star",
            "needsPermit": True,
            "is_neutron": True
        }
        sys = System.from_dict(data)
        self.assertEqual(sys.id64, 12345)
        self.assertEqual(sys.name, "Colonia")
        self.assertEqual(sys.coords.x, 0.0)
        self.assertEqual(sys.coords.y, 1.0)
        self.assertEqual(sys.coords.z, 2.0)
        self.assertEqual(sys.mainStar, "G Star")
        self.assertTrue(sys.needs_permit)
        self.assertTrue(sys.is_neutron)

        d = sys.to_dict()
        self.assertEqual(d["id64"], 12345)
        self.assertEqual(d["name"], "Colonia")
        self.assertEqual(d["coords"], {"x": 0.0, "y": 1.0, "z": 2.0})
        self.assertEqual(d["mainStar"], "G Star")
        self.assertTrue(d["needs_permit"])
        self.assertTrue(d["is_neutron"])

    def test_system_from_dict_tuple_coords(self):
        data = {
            "id64": 999,
            "name": "Test",
            "coords": (10.0, 20.0, 30.0),
            "needs_permit": False
        }
        sys = System.from_dict(data)
        self.assertEqual(sys.coords, Coordinates(10.0, 20.0, 30.0))
        self.assertFalse(sys.needs_permit)
