import unittest

import numpy as np

from flappy.vision import Box, PillarGap, analyze, select_active_gap


class VisionTests(unittest.TestCase):
    def test_plain_sky_has_no_pillar_or_scooter(self):
        image = np.full((900, 405, 3), (57, 167, 242), dtype=np.uint8)
        observation = analyze(image)
        self.assertIsNone(observation.scooter)
        self.assertEqual(observation.gaps, ())

    def test_tan_background_without_dark_pillar_rims_is_rejected(self):
        image = np.full((900, 405, 3), (57, 167, 242), dtype=np.uint8)
        image[90:300, 245:325] = (223, 175, 111)
        image[510:730, 245:325] = (223, 175, 111)
        self.assertEqual(analyze(image).gaps, ())

    def test_nearest_pillar_remains_selected_through_scooter_overlap(self):
        current = PillarGap(39, 103, 300, 550)
        upcoming = PillarGap(250, 314, 300, 550)
        gaps = (current, upcoming)
        self.assertEqual(select_active_gap(gaps, Box(82, 425, 137, 475), 405), current)
        self.assertEqual(select_active_gap(gaps, Box(108, 425, 163, 475), 405), upcoming)


if __name__ == "__main__":
    unittest.main()
