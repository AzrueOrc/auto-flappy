import unittest

import numpy as np

from flappy.vision import Box, PillarGap, analyze, select_active_gap


class VisionTests(unittest.TestCase):
    @staticmethod
    def _candidate(width: int, lower_start: int) -> np.ndarray:
        image = np.full((900, 405, 3), (57, 167, 242), dtype=np.uint8)
        image[65:85, 180:210] = (255, 255, 255)
        image[415:463, 90:138] = (18, 170, 79)
        image[90:290, 180:180 + width] = (223, 175, 111)
        image[lower_start:750, 180:180 + width] = (223, 175, 111)
        image[290:295, 176:184 + width] = (60, 43, 30)
        image[lower_start - 6:lower_start - 1, 176:184 + width] = (60, 43, 30)
        image[90:290, 178:181] = (60, 43, 30)
        image[90:290, 179 + width:182 + width] = (60, 43, 30)
        image[lower_start:750, 178:181] = (60, 43, 30)
        image[lower_start:750, 179 + width:182 + width] = (60, 43, 30)
        return image

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

    def test_oversized_skyline_pair_is_not_a_gap(self):
        self.assertTrue(analyze(self._candidate(68, 520)).gaps)
        self.assertEqual(analyze(self._candidate(130, 520)).gaps, ())
        self.assertEqual(analyze(self._candidate(68, 650)).gaps, ())

    def test_nearest_pillar_remains_selected_through_scooter_overlap(self):
        current = PillarGap(39, 103, 300, 550)
        upcoming = PillarGap(250, 314, 300, 550)
        gaps = (current, upcoming)
        self.assertEqual(select_active_gap(gaps, Box(82, 425, 137, 475), 405), current)
        self.assertEqual(select_active_gap(gaps, Box(108, 425, 163, 475), 405), upcoming)


if __name__ == "__main__":
    unittest.main()
