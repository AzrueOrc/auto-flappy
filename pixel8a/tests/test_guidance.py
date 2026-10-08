import unittest

from flappy.guidance import GapContinuity, ManualGuidance
from flappy.vision import Box, Observation, PillarGap


class GuidanceTests(unittest.TestCase):
    def test_user_point_selects_the_marked_gap_and_waits_for_next_mark(self):
        guide = ManualGuidance()
        scooter = Box(82, 425, 137, 475)
        background = PillarGap(230, 294, 100, 340)
        pillar = PillarGap(240, 304, 300, 550)
        observation = Observation("GAMEPLAY_CANDIDATE", scooter,
                                  (background, pillar), background)
        guide.mark_scooter(110)
        guide.mark_gap(270, 425)
        selected = guide.guide(observation, 1.0, 405, 900)
        self.assertEqual(selected.active_gap, pillar)
        moved = PillarGap(237, 301, 300, 550)
        selected = guide.guide(Observation("GAMEPLAY_CANDIDATE", scooter,
                                           (background, moved), background),
                               1.02, 405, 900)
        self.assertEqual(selected.active_gap, moved)
        passed = PillarGap(0, 70, 300, 550)
        guide._tracked = passed
        selected = guide.guide(Observation("GAMEPLAY_CANDIDATE", scooter,
                                           (passed, pillar), passed),
                               1.04, 405, 900)
        self.assertIsNone(selected.active_gap)
        self.assertIsNone(guide.gap_point)
        self.assertIsNone(guide.guide(observation, 1.06, 405, 900).active_gap)

    def test_short_detector_dropout_uses_only_recent_stable_gap(self):
        continuity = GapContinuity()
        scooter = Box(82, 425, 137, 475)
        for index, left in enumerate((240, 237, 234)):
            gap = PillarGap(left, left + 64, 300, 550)
            observation = Observation("GAMEPLAY_CANDIDATE", scooter, (gap,), gap)
            self.assertEqual(continuity.guide(observation, 1 + index * .02, 405).active_gap,
                             gap)
        missing = Observation("GAMEPLAY_CANDIDATE", scooter, (), None)
        inferred = continuity.guide(missing, 1.10, 405)
        self.assertTrue(continuity.estimated)
        self.assertEqual(inferred.active_gap.left, 225)
        self.assertIsNone(continuity.guide(missing, 1.30, 405).active_gap)
        self.assertFalse(continuity.estimated)


if __name__ == "__main__":
    unittest.main()
