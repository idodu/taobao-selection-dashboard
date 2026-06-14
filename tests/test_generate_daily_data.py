from __future__ import annotations

import importlib.util
import unittest
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_daily_data.py"
SPEC = importlib.util.spec_from_file_location("generate_daily_data", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class GenerateDailyDataTest(unittest.TestCase):
    def test_catalog_is_large_enough_for_rotation(self) -> None:
        catalog = MODULE.load_catalog()
        self.assertGreaterEqual(len(catalog["products"]), 40)
        self.assertEqual(len({item["id"] for item in catalog["products"]}), len(catalog["products"]))

    def test_daily_selection_respects_quality_and_diversity_constraints(self) -> None:
        data, _ = MODULE.generate(
            now=datetime(2026, 6, 14, 10, tzinfo=MODULE.BEIJING),
            history={"dates": {}},
        )
        products = data["products"]
        self.assertEqual(len(products), 10)
        self.assertEqual(Counter(item["type"] for item in products), MODULE.TYPE_TARGETS)
        self.assertLessEqual(max(Counter(item["brand"] for item in products).values()), 2)
        self.assertLessEqual(max(Counter(item["category"] for item in products).values()), 3)
        self.assertTrue(all(len(item["platforms"]) >= 2 for item in products))
        self.assertTrue(all(item["sourceUrl"] and item["image"] for item in products))

    def test_seven_day_rotation_changes_the_board(self) -> None:
        history = {"dates": {}}
        previous_ids: set[str] | None = None
        unique_ids: set[str] = set()
        adjacent_overlaps: list[int] = []
        start = datetime(2026, 6, 14, 10, tzinfo=MODULE.BEIJING)

        for offset in range(7):
            data, history = MODULE.generate(
                now=start + timedelta(days=offset),
                history=history,
            )
            ids = {item["id"] for item in data["products"]}
            unique_ids.update(ids)
            if previous_ids is not None:
                adjacent_overlaps.append(len(ids & previous_ids))
            previous_ids = ids

        self.assertGreaterEqual(len(unique_ids), 30)
        self.assertTrue(all(overlap <= 4 for overlap in adjacent_overlaps))
        self.assertTrue(any(overlap <= 2 for overlap in adjacent_overlaps))


if __name__ == "__main__":
    unittest.main()
