"""Regression tests for the stated robust-statistics methodology."""

import unittest

from src.analysis import analyse_groups, analyse_price_levels
from src.cleaning import clean_observations
from src.mad import median_absolute_deviation, modified_z_score


class MadTests(unittest.TestCase):
    def test_manual_mad_example(self) -> None:
        # median = 12; absolute deviations = [2, 0, 8, 10, 88]; MAD = 8.
        values = [10.0, 12.0, 20.0, 22.0, 100.0]
        self.assertEqual(median_absolute_deviation(values), 8.0)
        self.assertAlmostEqual(modified_z_score(100.0, 12.0, 8.0), 7.4195)

    def test_zero_mad_has_no_misleading_score(self) -> None:
        self.assertIsNone(modified_z_score(12.0, 10.0, 0.0))

    def test_group_marks_clear_outlier(self) -> None:
        observations = [
            {
                "item_id": str(index), "title": "phone", "price_numeric": price,
                "snapshot_timestamp": "2026-01-01T00-00-00Z", "model": "iPhone test",
                "storage_gb": "128", "condition_category": "used",
            }
            for index, price in enumerate([100.0, 102.0, 1000.0])
        ]
        result = analyse_groups(
            observations,
            min_sample_size=3,
            z_threshold=3.5,
            group_fields=("model", "storage_gb", "condition_category"),
        )[0]
        self.assertEqual(result["median_price"], 102.0)
        self.assertEqual(result["mad"], 2.0)
        self.assertEqual(result["outlier_count"], 1)
        self.assertEqual(result["market_price_estimate"], 101.0)

    def test_market_estimate_is_mean_after_outlier_removal(self) -> None:
        observations = [
            {
                "item_id": str(index), "title": "phone", "price_numeric": price,
                "snapshot_timestamp": "2026-01-01T00-00-00Z", "model": "iPhone test",
                "storage_gb": "128", "condition_category": "used",
            }
            for index, price in enumerate([100.0, 100.0, 104.0, 1000.0])
        ]
        result = analyse_groups(
            observations, 4, 3.5, ("model", "storage_gb", "condition_category")
        )[0]
        self.assertAlmostEqual(result["market_price_estimate"], 101.33333333333333)

    def test_price_levels_use_requested_dimensions(self) -> None:
        observations = [
            {
                "item_id": str(index), "title": "phone", "price_numeric": price,
                "snapshot_timestamp": "2026-01-01T00-00-00Z", "model": "iPhone test",
                "storage_gb": storage, "colour": colour, "condition_category": "used",
            }
            for index, (price, storage, colour) in enumerate(
                [(100.0, "64", "black"), (120.0, "128", "black"), (130.0, "128", "white")]
            )
        ]
        levels = analyse_price_levels(observations, min_sample_size=1, z_threshold=3.5)
        self.assertEqual(len(levels["model"]), 1)
        self.assertEqual(len(levels["model_storage"]), 2)
        self.assertEqual(len(levels["model_storage_colour"]), 3)

    def test_model_casing_variations_are_normalised(self) -> None:
        source = {
            "item_id": "1", "price_numeric": 100.0, "price_eligible": True,
            "is_actual_iphone": True, "bundle": False, "title": "phone",
            "model": "iPhone SE (2nd Generation)", "storage_gb": 64,
            "snapshot_timestamp": "2026-01-01T00-00-00Z",
        }
        first, _ = clean_observations([source])
        second_source = dict(source, item_id="2", model="iPhone SE (2nd generation)")
        second, _ = clean_observations([second_source])
        self.assertEqual(first[0]["model"], second[0]["model"])


if __name__ == "__main__":
    unittest.main()
