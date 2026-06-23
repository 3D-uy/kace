import unittest
from core.motion_model import PrinterMotionSpace

class TestMotionModel(unittest.TestCase):

    def test_default_values(self):
        """Test motion model default values when no custom limits are provided."""
        user_data = {
            "x_size": "235",
            "y_size": "235",
            "z_size": "250",
            "probe_x_offset": "-38",
            "probe_y_offset": "2",
            "probe": "BLTouch"
        }
        
        space = PrinterMotionSpace(user_data)
        
        # Test basic dimensions
        self.assertEqual(space.x_size, 235.0)
        self.assertEqual(space.y_size, 235.0)
        self.assertEqual(space.z_size, 250.0)
        
        # Test fallback travel limits
        self.assertEqual(space.x_min, 0.0)
        self.assertEqual(space.x_max, 235.0)
        self.assertEqual(space.x_endstop, 0.0)
        self.assertEqual(space.y_min, 0.0)
        self.assertEqual(space.y_max, 235.0)
        self.assertEqual(space.y_endstop, 0.0)
        self.assertEqual(space.z_min, 0.0)
        self.assertEqual(space.z_max, 250.0)
        self.assertEqual(space.z_endstop, 0.0)
        
        # Test areas
        self.assertEqual(space.printable_bed_area()["x"], (0.0, 235.0))
        self.assertEqual(space.nozzle_reachable_area()["x"], (0.0, 235.0))
        
        # Test probe reachable area: [min + offset, max + offset] -> [0 - 38, 235 - 38] -> [-38.0, 197.0]
        self.assertEqual(space.probe_reachable_area()["x"], (-38.0, 197.0))
        self.assertEqual(space.probe_reachable_area()["y"], (2.0, 237.0))
        
        # Test probeable bed area (intersection of bed [0, 235] and probe reachable):
        # X: [0.0, 197.0]
        # Y: [2.0, 235.0]
        self.assertEqual(space.probeable_bed_area()["x"], (0.0, 197.0))
        self.assertEqual(space.probeable_bed_area()["y"], (2.0, 235.0))

    def test_custom_negative_coordinates(self):
        """Test motion model with custom negative limits (e.g. Voron/CoreXY style configs)."""
        user_data = {
            "x_size": "250",
            "y_size": "250",
            "z_size": "250",
            "x_position_min": "-10",
            "x_position_max": "260",
            "x_position_endstop": "-5",
            "y_position_min": "-15",
            "y_position_max": "255",
            "y_position_endstop": "-10",
            "probe_x_offset": "-40",
            "probe_y_offset": "-10",
            "probe": "Inductive"
        }
        
        space = PrinterMotionSpace(user_data)
        
        # Test parsed travel limits
        self.assertEqual(space.x_min, -10.0)
        self.assertEqual(space.x_max, 260.0)
        self.assertEqual(space.x_endstop, -5.0)
        self.assertEqual(space.y_min, -15.0)
        self.assertEqual(space.y_max, 255.0)
        self.assertEqual(space.y_endstop, -10.0)
        
        # Nozzle Reachable Area
        self.assertEqual(space.nozzle_reachable_area()["x"], (-10.0, 260.0))
        self.assertEqual(space.nozzle_reachable_area()["y"], (-15.0, 255.0))
        
        # Probe Reachable Area:
        # X: [-10 + (-40), 260 + (-40)] -> [-50.0, 220.0]
        # Y: [-15 + (-10), 255 + (-10)] -> [-25.0, 245.0]
        self.assertEqual(space.probe_reachable_area()["x"], (-50.0, 220.0))
        self.assertEqual(space.probe_reachable_area()["y"], (-25.0, 245.0))
        
        # Probeable Bed Area (intersection with printable bed [0, 250]):
        # X: [max(0, -50), min(250, 220)] -> [0.0, 220.0]
        # Y: [max(0, -25), min(250, 245)] -> [0.0, 245.0]
        self.assertEqual(space.probeable_bed_area()["x"], (0.0, 220.0))
        self.assertEqual(space.probeable_bed_area()["y"], (0.0, 245.0))
        
        # Homed origin
        self.assertEqual(space.homed_origin()["x"], -5.0)
        self.assertEqual(space.homed_origin()["y"], -10.0)

    def test_invalid_data_graceful_fallbacks(self):
        """Test motion model behaves gracefully with malformed user data input."""
        user_data = {
            "x_size": "invalid",
            "y_size": None,
            "x_position_min": "abc",
            "probe_x_offset": "foo",
        }
        
        space = PrinterMotionSpace(user_data)
        
        self.assertEqual(space.x_size, 235.0)
        self.assertEqual(space.y_size, 235.0)
        self.assertEqual(space.x_min, 0.0)
        self.assertEqual(space.probe_x_offset, 0.0)
        
        # Checking that dict serialization does not fail
        d = space.to_dict()
        self.assertIn("printable_bed_area", d)
        self.assertIn("nozzle_reachable_area", d)

if __name__ == '__main__':
    unittest.main()
