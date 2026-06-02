"""Tests for the composable seam-matching subsystem (ADR 0007, design D6/D7/D8).

A *seam mask* is the per-pixel occupancy of one tile-side's contact line:
a sequence of bools, painted (True) vs empty (False). Masks are pre-oriented
by the caller so that index ``i`` of one side faces index ``i`` of the side it
abuts; the matchers here are orientation-agnostic and purely positional.
"""

import unittest

from seam_matching import (
    MatchPolicy,
    complement_score,
    equality_score,
)


class EqualityScoreTests(unittest.TestCase):
    def test_identical_masks_score_one(self):
        self.assertEqual(equality_score((True, False, True), (True, False, True)), 1.0)

    def test_fully_opposite_masks_score_zero(self):
        self.assertEqual(equality_score((True, True), (False, False)), 0.0)

    def test_partial_agreement_is_fractional(self):
        # 3 of 4 positions agree
        self.assertEqual(
            equality_score((True, True, True, False), (True, True, False, False)),
            0.75,
        )

    def test_null_equals_null(self):
        # two finished/empty edges abut with no break (D1/D6)
        self.assertEqual(equality_score((False, False, False), (False, False, False)), 1.0)

    def test_painted_versus_null_is_a_break(self):
        self.assertEqual(equality_score((True, True), (False, False)), 0.0)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            equality_score((True, False), (True, False, True))


class ComplementScoreTests(unittest.TestCase):
    def test_complementary_masks_score_one(self):
        self.assertEqual(complement_score((True, False, True), (False, True, False)), 1.0)

    def test_identical_masks_score_zero(self):
        self.assertEqual(complement_score((True, False), (True, False)), 0.0)

    def test_null_versus_full_is_complementary(self):
        self.assertEqual(complement_score((False, False), (True, True)), 1.0)

    def test_null_versus_null_is_not_complementary(self):
        self.assertEqual(complement_score((False, False), (False, False)), 0.0)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            complement_score((True,), (True, False))


class MatchPolicyTests(unittest.TestCase):
    def test_default_policy_accepts_equal_masks(self):
        policy = MatchPolicy()
        self.assertTrue(policy.fits((True, False, True), (True, False, True)))

    def test_default_policy_accepts_complementary_masks(self):
        policy = MatchPolicy()
        self.assertTrue(policy.fits((True, False, True), (False, True, False)))

    def test_default_policy_rejects_misaligned_masks(self):
        # neither equal nor complementary: agree 1/3, oppose 2/3
        policy = MatchPolicy()
        self.assertFalse(policy.fits((True, True, False), (True, False, False)))

    def test_null_versus_null_fits(self):
        self.assertTrue(MatchPolicy().fits((False, False), (False, False)))

    def test_combined_is_max_over_enabled_matchers(self):
        policy = MatchPolicy()
        # complementary pair: equality 0.0, complement 1.0 -> max 1.0
        self.assertEqual(policy.combined((True, False), (False, True)), 1.0)

    def test_relaxed_threshold_accepts_near_match(self):
        policy = MatchPolicy(threshold=0.75)
        # 3/4 agree -> equality 0.75 -> fits under relaxed threshold, not under exact
        self.assertTrue(policy.fits((True, True, True, False), (True, True, False, False)))
        self.assertFalse(MatchPolicy().fits((True, True, True, False), (True, True, False, False)))

    def test_disabling_complement_rejects_interlocking(self):
        policy = MatchPolicy(enabled=("equality",))
        self.assertFalse(policy.fits((True, False), (False, True)))

    def test_scores_reports_each_enabled_matcher(self):
        scores = MatchPolicy().scores((True, False), (True, False))
        self.assertEqual(set(scores), {"equality", "complement"})
        self.assertEqual(scores["equality"], 1.0)
        self.assertEqual(scores["complement"], 0.0)

    def test_unknown_matcher_name_raises(self):
        with self.assertRaises(ValueError):
            MatchPolicy(enabled=("equality", "nonsense"))

    def test_empty_matcher_set_raises(self):
        with self.assertRaises(ValueError):
            MatchPolicy(enabled=())


if __name__ == "__main__":
    unittest.main()
