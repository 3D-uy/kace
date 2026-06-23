import unittest
from core.probe_offset_visualizer import _offset_to_cell, _render_bed

class TestProbeOffsetVisualizer(unittest.TestCase):

    def test_offset_to_cell_calculations(self):
        # Center cell for X (total 14 cells, index 6)
        # Should remain 6 for 0.0 offset
        self.assertEqual(_offset_to_cell(0.0, 100.0, 14, 6), 6)
        
        # -20mm offset in X (scale = 7 / 50 = 0.14 -> 6 / 50 = 0.12)
        # 6 + round(-20 * 0.12) = 6 - 2 = 4
        self.assertEqual(_offset_to_cell(-20.0, 100.0, 14, 6), 4)

        # Center cell for Y (total 7 cells, index 3)
        self.assertEqual(_offset_to_cell(0.0, 100.0, 7, 3), 3)

        # -10mm in Y offset (which translates to positive Y after negation in visualization)
        self.assertEqual(_offset_to_cell(-10.0, 100.0, 7, 3), 2)

    def test_overlap_detection(self):
        # Overlap (both offsets are 0.0) -> center cell should show 'X'
        lines = _render_bed(0.0, 0.0, 235.0, 235.0)
        # Verify the legend shows X is the overlap symbol
        # The grid row 3 (which represents nozzle row) contains the overlap character
        nozzle_row = lines[4] # lines[0] is top border, lines[1..7] are rows
        grid_part = nozzle_row.split("|")[1]
        self.assertIn("X", grid_part)
        self.assertNotIn("N", grid_part) # N should be replaced by X
        self.assertNotIn("P", grid_part) # P should be replaced by X

    def test_non_overlap_rendering(self):
        # Large enough offset so there is no overlap
        lines = _render_bed(-20.0, 10.0, 235.0, 235.0)
        
        # Verify nozzle row has N
        nozzle_row = lines[4]
        grid_part_nozzle = nozzle_row.split("|")[1]
        self.assertIn("N", grid_part_nozzle)
        self.assertNotIn("X", grid_part_nozzle)
        
        # Verify probe row (row 2) has P
        probe_row = lines[3]
        grid_part_probe = probe_row.split("|")[1]
        self.assertIn("P", grid_part_probe)
        self.assertNotIn("N", grid_part_probe)

if __name__ == '__main__':
    unittest.main()

