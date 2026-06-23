import unittest
from core.scraper import parse_config, detect_driver_info, is_socketed_board, get_reusable_driver_sockets

class TestDriverDetection(unittest.TestCase):

    def test_detect_tmc2209_uart(self):
        """Verify that TMC2209 in UART mode is correctly detected."""
        cfg = """
        [stepper_x]
        step_pin: PC2
        
        [tmc2209 stepper_x]
        uart_pin: PC11
        tx_pin: PC10
        run_current: 0.580
        """
        parsed = parse_config(cfg)
        info = detect_driver_info(parsed)
        
        self.assertTrue(info["integrated"])
        self.assertEqual(info["driver_type"], "TMC2209")
        self.assertEqual(info["driver_mode"], "UART")

    def test_detect_tmc5160_spi(self):
        """Verify that TMC5160 in SPI mode is correctly detected."""
        cfg = """
        [tmc5160 stepper_y]
        cs_pin: PD3
        spi_bus: spi1
        run_current: 0.800
        """
        parsed = parse_config(cfg)
        info = detect_driver_info(parsed)
        
        self.assertTrue(info["integrated"])
        self.assertEqual(info["driver_type"], "TMC5160")
        self.assertEqual(info["driver_mode"], "SPI")

    def test_detect_standalone_tmc(self):
        """Verify that a TMC configuration without communication pins defaults to Standalone."""
        cfg = """
        [tmc2208 stepper_z]
        run_current: 0.650
        """
        parsed = parse_config(cfg)
        info = detect_driver_info(parsed)
        
        self.assertTrue(info["integrated"])
        self.assertEqual(info["driver_type"], "TMC2208")
        self.assertEqual(info["driver_mode"], "Standalone")

    def test_no_driver_data(self):
        """Verify that boards with no stepper driver data return integrated=False."""
        cfg = """
        [stepper_x]
        step_pin: P2.2
        dir_pin: !P2.6
        """
        parsed = parse_config(cfg)
        info = detect_driver_info(parsed)
        
        self.assertFalse(info["integrated"])
        self.assertIsNone(info["driver_type"])
        self.assertIsNone(info["driver_mode"])

    def test_detect_driver_info_with_socketed_board(self):
        """Verify that a socketed board disables integrated driver flag."""
        cfg = """
        [tmc2209 stepper_x]
        uart_pin: PC11
        run_current: 0.580
        """
        parsed = parse_config(cfg)
        # Without board_name (defaults to non-socketed)
        info_default = detect_driver_info(parsed)
        self.assertTrue(info_default["integrated"])
        
        # With socketed board_name
        info_socketed = detect_driver_info(parsed, "generic-bigtreetech-skr-v1.4.cfg")
        self.assertFalse(info_socketed["integrated"])
        self.assertTrue(info_socketed["is_socketed"])

    def test_socketed_board_classification(self):
        """Verify socketed board checks correctly flag replaceable vs integrated driver boards."""
        self.assertTrue(is_socketed_board("generic-bigtreetech-skr-v1.4.cfg"))
        self.assertTrue(is_socketed_board("generic-bigtreetech-octopus-v1.1.cfg"))
        self.assertTrue(is_socketed_board("generic-mks-sgen-l.cfg"))
        
        # Integrated driver boards should be classified as NOT socketed
        self.assertFalse(is_socketed_board("generic-creality-v4.2.2.cfg"))
        self.assertFalse(is_socketed_board("generic-bigtreetech-skr-mini-e3-v3.0.cfg"))
        self.assertFalse(is_socketed_board("generic-bigtreetech-skr-pico.cfg"))
        self.assertFalse(is_socketed_board(None))
        self.assertFalse(is_socketed_board(""))


class TestReusableDriverSockets(unittest.TestCase):
    """Tests for get_reusable_driver_sockets() — the multi-Z alias derivation layer.

    The regression was that the wizard scanned the already-parsed dict (which
    silently drops commented-out section headers) instead of the raw config
    string, causing an empty driver choice list on Octopus-class boards.
    """

    def test_commented_extruder_headers_octopus_pattern(self):
        """Commented #[extruder1] headers must be discovered — core Octopus regression path."""
        raw = """
[stepper_z]
step_pin: PF11
dir_pin: PG3
enable_pin: !PG5

#[extruder1]
#step_pin: PE6
#dir_pin: PA14
#enable_pin: !PE0

#[extruder2]
#step_pin: PF9
#dir_pin: PF10
#enable_pin: !PG2
"""
        sockets = get_reusable_driver_sockets(raw, "generic-bigtreetech-octopus-v1.1.cfg")
        keys = [k for k, _ in sockets]
        labels = [l for _, l in sockets]
        self.assertIn("extruder1", keys)
        self.assertIn("extruder2", keys)
        self.assertIn("E1", labels)
        self.assertIn("E2", labels)

    def test_active_extruder_sections(self):
        """Active (uncommented) [extruderN] sections must also be discovered."""
        raw = """
[extruder]
step_pin: PE2

[extruder1]
step_pin: PE6

[extruder2]
step_pin: PF9
"""
        sockets = get_reusable_driver_sockets(raw)
        keys = [k for k, _ in sockets]
        # extruder (primary) must NOT appear — only extruder1, extruder2
        self.assertNotIn("extruder", keys)
        self.assertIn("extruder1", keys)
        self.assertIn("extruder2", keys)

    def test_extruder_stepper_klipper_0_11(self):
        """[extruder_stepper <name>] sections (Klipper 0.11+ naming) are discovered."""
        raw = """
[extruder_stepper stepper_e1]
step_pin: PA6

[extruder_stepper stepper_e2]
step_pin: PA7
"""
        sockets = get_reusable_driver_sockets(raw)
        keys = [k for k, _ in sockets]
        labels = [l for _, l in sockets]
        self.assertIn("extruder_stepper stepper_e1", keys)
        self.assertIn("extruder_stepper stepper_e2", keys)
        self.assertIn("STEPPER_E1", labels)
        self.assertIn("STEPPER_E2", labels)

    def test_deduplication_mixed_patterns(self):
        """A board config that mixes commented and active headers must not produce duplicates."""
        raw = """
[extruder1]
step_pin: PE6

#[extruder1]
#step_pin: PE6
"""
        sockets = get_reusable_driver_sockets(raw)
        keys = [k for k, _ in sockets]
        self.assertEqual(keys.count("extruder1"), 1, "extruder1 should appear exactly once")

    def test_empty_board_returns_empty_list(self):
        """A board with no extra extruder sockets returns an empty list — no crash."""
        raw = """
[stepper_x]
step_pin: PA0

[extruder]
step_pin: PE2
"""
        sockets = get_reusable_driver_sockets(raw)
        self.assertEqual(sockets, [],
                         "Boards with only a primary extruder should return no reusable sockets")

    def test_sorted_stable_order(self):
        """Returned sockets must be in stable sorted order (extruder1 < extruder2 < …)."""
        raw = """
#[extruder3]
#step_pin: PA3

#[extruder1]
#step_pin: PA1

#[extruder2]
#step_pin: PA2
"""
        sockets = get_reusable_driver_sockets(raw)
        keys = [k for k, _ in sockets]
        self.assertEqual(keys, sorted(keys))


if __name__ == '__main__':
    unittest.main()
