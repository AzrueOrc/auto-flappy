import unittest

from flappy.autopilot import (FlapPlanner, MIN_TAP_INTERVAL, aim_height,
                              clearance_bounds, click_zone, safe_height_band,
                              scan_lines)
from flappy.vision import Box, Observation, PillarGap


def frame(left: int, y: int = 500, scene: str = "GAMEPLAY_CANDIDATE") -> Observation:
    gap = PillarGap(left, left + 64, 300, 550)
    return Observation(scene, Box(82, y - 25, 137, y + 25), (gap,), gap)


class PlannerTests(unittest.TestCase):
    def test_requires_moving_stable_target_and_throttles_taps(self):
        self.assertEqual(MIN_TAP_INTERVAL, .11)
        planner = FlapPlanner()
        self.assertFalse(planner.observe(frame(300), 1.00, 1.01, 405, 900))
        self.assertFalse(planner.observe(frame(297), 1.02, 1.03, 405, 900))
        self.assertTrue(planner.observe(frame(294), 1.04, 1.05, 405, 900))
        self.assertFalse(planner.observe(frame(291), 1.06, 1.07, 405, 900))
        self.assertFalse(planner.observe(frame(275), 1.16, 1.17, 405, 900))

    def test_red_zone_taps_once_until_scooter_returns_to_green(self):
        planner = FlapPlanner()
        for index, left in enumerate((186, 183)):
            timestamp = 1.0 + index * .02
            self.assertFalse(planner.observe(frame(left, 450), timestamp,
                                             timestamp + .01, 405, 900))
        self.assertTrue(planner.observe(frame(180, 450), 1.04, 1.05, 405, 900))
        self.assertFalse(planner.observe(frame(170, 470), 1.16, 1.17, 405, 900))
        self.assertFalse(planner.observe(frame(160, 470), 1.30, 1.31, 405, 900))
        self.assertFalse(planner.observe(frame(155, 425), 1.32, 1.33, 405, 900))
        self.assertTrue(planner.observe(frame(150, 450), 1.34, 1.35, 405, 900))

    def test_withholds_tap_for_stale_missing_or_stationary_target(self):
        planner = FlapPlanner()
        for timestamp in (1.00, 1.02, 1.04):
            self.assertFalse(planner.observe(frame(300), timestamp, timestamp + .01,
                                             405, 900))
        self.assertFalse(planner.observe(frame(290), 1.06, 1.30, 405, 900))
        missing = Observation("GAMEPLAY_CANDIDATE", Box(82, 475, 137, 525), (), None)
        self.assertFalse(planner.observe(missing, 1.32, 1.33, 405, 900))
        self.assertFalse(planner.observe(frame(280), 1.34, 1.35, 405, 900))

    def test_does_not_tap_when_above_target(self):
        planner = FlapPlanner()
        for index, left in enumerate((300, 297, 294)):
            timestamp = 1.0 + index * .02
            self.assertFalse(planner.observe(frame(left, 360), timestamp, timestamp + .01,
                                             405, 900))

    def test_opening_flight_holds_height_before_first_pillar(self):
        planner = FlapPlanner()
        def open_sky(y: int) -> Observation:
            return Observation("GAMEPLAY_CANDIDATE", Box(82, y - 25, 137, y + 25),
                               (), None)

        self.assertFalse(planner.observe(open_sky(330), 1.00, 1.01, 405, 900))
        self.assertFalse(planner.observe(open_sky(360), 1.02, 1.03, 405, 900))
        self.assertTrue(planner.observe(open_sky(390), 1.04, 1.05, 405, 900))
        self.assertFalse(planner.observe(open_sky(395), 1.06, 1.07, 405, 900))

    def test_brief_missing_gap_does_not_immediately_use_open_sky_rule(self):
        planner = FlapPlanner()
        for index, left in enumerate((300, 297, 294)):
            timestamp = 1.0 + index * .02
            planner.observe(frame(left, 350), timestamp, timestamp + .01, 405, 900)
        missing = Observation("GAMEPLAY_CANDIDATE", Box(82, 430, 137, 480), (), None)
        self.assertFalse(planner.observe(missing, 1.06, 1.07, 405, 900))
        self.assertTrue(planner.observe(missing, 1.34, 1.35, 405, 900))

    def test_near_pillar_waits_until_flap_has_upper_clearance(self):
        planner = FlapPlanner()
        gap = PillarGap(180, 244, 300, 550)
        self.assertEqual(clearance_bounds(gap), (337.5, 512.5))
        upper, lower = safe_height_band(gap, 50, 900)
        self.assertEqual((upper, lower), (434.5, 487.5))
        self.assertEqual(aim_height(gap), 425)
        self.assertEqual(click_zone(gap, 50), (450.0, 487.5))
        self.assertEqual(scan_lines(110, 405), (45, 110, 236))
        for index, left in enumerate((186, 183, 180)):
            timestamp = 1.0 + index * .02
            self.assertFalse(planner.observe(frame(left, 390), timestamp,
                                             timestamp + .01, 405, 900))
        self.assertTrue(planner.observe(frame(177, 450), 1.06, 1.07, 405, 900))

    def test_coasts_above_lower_click_zone_even_after_center(self):
        planner = FlapPlanner()
        for index, left in enumerate((186, 183, 180)):
            timestamp = 1.0 + index * .02
            self.assertFalse(planner.observe(frame(left, 440), timestamp,
                                             timestamp + .01, 405, 900))

    def test_continues_flapping_until_trailing_edge_clears_pillar(self):
        planner = FlapPlanner()
        for index, left in enumerate((45, 42)):
            timestamp = 1.0 + index * .02
            self.assertFalse(planner.observe(frame(left, 450), timestamp,
                                             timestamp + .01, 405, 900))
        self.assertTrue(planner.observe(frame(39, 450), 1.04, 1.05, 405, 900))
        self.assertFalse(planner.observe(frame(30, 450), 1.29, 1.30, 405, 900))
        self.assertFalse(planner.observe(frame(28, 425), 1.31, 1.32, 405, 900))
        self.assertTrue(planner.observe(frame(26, 450), 1.33, 1.34, 405, 900))
        self.assertFalse(planner.observe(frame(14, 450), 1.54, 1.55, 405, 900))

    def test_near_pillar_does_not_flap_into_upper_cap(self):
        planner = FlapPlanner()
        for index, left in enumerate((186, 183, 180)):
            timestamp = 1.0 + index * .02
            self.assertFalse(planner.observe(frame(left, 350), timestamp,
                                             timestamp + .01, 405, 900))


if __name__ == "__main__":
    unittest.main()
