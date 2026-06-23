import unittest
from core.motion_model import PrinterMotionSpace
from core.bed_mesh import generate_bed_mesh_config
from core.leveling import validate_probe_reachability, filter_reachable_points, derive_probing_points

class TestBedMeshAndLeveling(unittest.TestCase):

    def test_bed_mesh_sizing_and_algorithm(self):
        """Test bed mesh count sizing and algorithm selection based on bed size."""
        # 0. Very small bed (<100mm) -> 3x3, lagrange
        user_data = {
            "x_size": "80",
            "y_size": "80",
            "probe": "Inductive",
            "probe_x_offset": "0",
            "probe_y_offset": "0",
        }
        space = PrinterMotionSpace(user_data)
        res = generate_bed_mesh_config(space, user_data, {})
        self.assertEqual(res["probe_count"], "3, 3")
        self.assertEqual(res["algorithm"], "lagrange")
        self.assertNotIn("bicubic_tension", res)

        # 1. Small bed (120mm, ≥100mm) -> 4x4, bicubic
        user_data = {
            "x_size": "120",
            "y_size": "120",
            "probe": "BLTouch",
            "probe_x_offset": "-20",
            "probe_y_offset": "10",
        }
        space = PrinterMotionSpace(user_data)
        res = generate_bed_mesh_config(space, user_data, {})
        self.assertEqual(res["probe_count"], "4, 4")
        self.assertEqual(res["algorithm"], "bicubic")

        # 2. Medium bed (235mm) -> 5x5, bicubic
        user_data = {
            "x_size": "235",
            "y_size": "235",
            "probe": "BLTouch",
            "probe_x_offset": "-38",
            "probe_y_offset": "2",
        }
        space = PrinterMotionSpace(user_data)
        res = generate_bed_mesh_config(space, user_data, {})
        self.assertEqual(res["probe_count"], "5, 5")
        self.assertEqual(res["algorithm"], "bicubic")
        self.assertEqual(res["bicubic_tension"], "0.2")

        # 3. Large bed (350mm) -> 7x7, bicubic
        user_data = {
            "x_size": "350",
            "y_size": "350",
            "probe": "Inductive",
            "probe_x_offset": "0",
            "probe_y_offset": "25",
        }
        space = PrinterMotionSpace(user_data)
        res = generate_bed_mesh_config(space, user_data, {})
        self.assertEqual(res["probe_count"], "7, 7")

    def test_bed_mesh_horizontal_move_z(self):
        """Test Z hop defaults for different probe types and overrides."""
        # 1. BLTouch -> 5
        user_data = {"x_size": "235", "y_size": "235", "probe": "BLTouch"}
        space = PrinterMotionSpace(user_data)
        res = generate_bed_mesh_config(space, user_data, {})
        self.assertEqual(res["horizontal_move_z"], "5")

        # 2. Inductive -> 3
        user_data = {"x_size": "235", "y_size": "235", "probe": "Inductive"}
        space = PrinterMotionSpace(user_data)
        res = generate_bed_mesh_config(space, user_data, {})
        self.assertEqual(res["horizontal_move_z"], "3")

        # 3. Profile override -> 12
        parsed_data = {"bed_mesh": {"horizontal_move_z": "12"}}
        res = generate_bed_mesh_config(space, user_data, parsed_data)
        self.assertEqual(res["horizontal_move_z"], "12")

    def test_bed_mesh_bounds_derivation(self):
        """Test mesh bounds derivation and clamping inside probeable bed area."""
        user_data = {
            "x_size": "235",
            "y_size": "235",
            "x_position_min": "-10",
            "x_position_max": "240",
            "y_position_min": "0",
            "y_position_max": "235",
            "probe_x_offset": "-35",
            "probe_y_offset": "-5",
            "probe": "BLTouch"
        }
        # probeable range X: [max(0, -10 + (-35)), min(235, 240 + (-35))] -> [0.0, 205.0]
        # probeable range Y: [max(0, 0 + (-5)), min(235, 235 + (-5))] -> [0.0, 230.0]
        # mesh_min = probeable_min + 10 -> X=10, Y=10
        # mesh_max = probeable_max - 10 -> X=195, Y=220
        space = PrinterMotionSpace(user_data)
        res = generate_bed_mesh_config(space, user_data, {})
        self.assertEqual(res["mesh_min"], "10.0, 10.0")
        self.assertEqual(res["mesh_max"], "195.0, 220.0")

    def test_leveling_reachability_and_clamping(self):
        """Test Z-tilt / quad-gantry level reachability checks and clamped point derivation."""
        user_data = {
            "x_size": "300",
            "y_size": "300",
            "x_position_min": "-10",
            "x_position_max": "310",
            "y_position_min": "-10",
            "y_position_max": "310",
            "probe_x_offset": "-40",
            "probe_y_offset": "-10",
            "probe": "Inductive"
        }
        # Probe reachable area:
        # X: [-10 - 40, 310 - 40] -> [-50.0, 270.0]
        # Y: [-10 - 10, 310 - 10] -> [-20.0, 300.0]
        # Probeable bed area: X: [0.0, 270.0], Y: [0.0, 300.0]
        space = PrinterMotionSpace(user_data)

        # Test point reachability
        points = [
            (10, 10),      # Reachable
            (290, 10),     # Unreachable (X=290 > max probe X 270)
            (150, 150),    # Reachable
            (200, 310),    # Unreachable (Y=310 > max probe Y 300)
        ]
        
        reachability = validate_probe_reachability(space, points)
        self.assertTrue(reachability[(10, 10)])
        self.assertFalse(reachability[(290, 10)])
        self.assertTrue(reachability[(150, 150)])
        self.assertFalse(reachability[(200, 310)])

        # Test filtering
        filtered = filter_reachable_points(space, points)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0], (10, 10))
        self.assertEqual(filtered[1], (150, 150))

        # Test clamping / derivation
        target_points = [
            (5, 5),
            (295, 295),
        ]
        clamped = derive_probing_points(space, target_points, margin=5)
        # For (5, 5): X=max(0+5, 5) -> 5, Y=max(0+5, 5) -> 5
        # For (295, 295): X=min(270-5, 295) -> 265, Y=min(300-5, 295) -> 295
        self.assertEqual(clamped[0], (5.0, 5.0))
        self.assertEqual(clamped[1], (265.0, 295.0))

if __name__ == '__main__':
    unittest.main()
