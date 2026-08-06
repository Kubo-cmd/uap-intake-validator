"""Tests for the clean-room conditioning module."""

import math
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from uap_conditioning import assess_conditioning  # noqa: E402


class ConditioningTests(unittest.TestCase):
    def test_straight_line_geometry_is_poor(self):
        frames = 12
        sensors = []
        bearings = []
        for index in range(frames):
            sensors.extend((float(index), 0.0, 0.0))
            bearings.extend((1.0, 0.0, 0.0))
        result = assess_conditioning(sensors, bearings, fps=30.0)
        self.assertEqual(result["conditioning"], "poor")
        self.assertLess(result["effectiveRank"], 6)
        self.assertNotIn("error", result)

    def test_orbit_parallax_is_not_poor(self):
        frames = 40
        sensors = []
        bearings = []
        for index in range(frames):
            angle = 2.0 * math.pi * index / frames
            x = 100.0 * math.cos(angle)
            y = 100.0 * math.sin(angle)
            z = 25.0 * math.sin(2.0 * angle + 0.3)
            sensors.extend((x, y, z))
            bearings.extend((-x, -y, -z))
        result = assess_conditioning(sensors, bearings, fps=20.0)
        self.assertIn(result["conditioning"], ("marginal", "good"))
        self.assertEqual(result["effectiveRank"], 6)
        self.assertNotIn("error", result)

    def test_nonfinite_input_fails_closed(self):
        result = assess_conditioning([0.0, 0.0, 0.0], [math.nan, 0.0, 1.0])
        self.assertEqual(result["conditioning"], "poor")
        self.assertEqual(result["rcond"], 0.0)
        self.assertIn("error", result)

    def test_non_numeric_and_boolean_inputs_fail_closed(self):
        for bad in ("1.0", True):
            result = assess_conditioning([0.0, 0.0, 0.0], [bad, 0.0, 1.0])
            self.assertEqual(result["conditioning"], "poor")
            self.assertIn("error", result)

    def test_mismatched_frames_fail_closed(self):
        result = assess_conditioning(
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        )
        self.assertEqual(result["conditioning"], "poor")
        self.assertIn("error", result)

    def test_duplicate_times_are_degenerate_not_exceptional(self):
        sensors = [0.0, 0.0, 0.0] * 4
        bearings = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
        result = assess_conditioning(sensors, bearings, times=[2.0] * 4)
        self.assertEqual(result["conditioning"], "poor")
        self.assertLessEqual(result["effectiveRank"], 3)
        self.assertNotIn("error", result)

    def test_zero_bearing_fails_closed(self):
        result = assess_conditioning([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        self.assertEqual(result["conditioning"], "poor")
        self.assertIn("error", result)

    def test_oversized_input_fails_closed(self):
        frames = 10001
        result = assess_conditioning([0.0] * (3 * frames), [1.0, 0.0, 0.0] * frames)
        self.assertEqual(result["conditioning"], "poor")
        self.assertIn("10000", result["error"])

    def test_collapse_diagnostics(self):
        sensors = [0.0, 0.0, 0.0] * 3
        bearings = [1.0, 0.0, 0.0] * 3
        positions = [0.0, 0.0, 0.0, -2.0, 0.0, 0.0, -4.0, 0.0, 0.0]
        result = assess_conditioning(
            sensors, bearings, times=[0.0, 1.0, 2.0], positions=positions
        )
        self.assertAlmostEqual(result["onSensorFraction"], 1.0 / 3.0)
        self.assertAlmostEqual(result["behindSensorFraction"], 2.0 / 3.0)
        self.assertEqual(result["medianSignedRangeM"], -2.0)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["collapseReason"], "position_on_sensor")


if __name__ == "__main__":
    unittest.main(verbosity=2)
