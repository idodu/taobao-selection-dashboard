from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_dashboard.py"
SPEC = importlib.util.spec_from_file_location("validate_dashboard", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ValidateDashboardTest(unittest.TestCase):
    def test_margin_range_allows_negative_profit_for_risk_visibility(self) -> None:
        self.assertTrue(MODULE.is_percent_range([-18.5, 12.0]))
        self.assertTrue(MODULE.is_percent_range([22.0, 22.1]))

    def test_margin_range_rejects_invalid_values(self) -> None:
        self.assertFalse(MODULE.is_percent_range([12.0]))
        self.assertFalse(MODULE.is_percent_range([12.0, 101.0]))
        self.assertFalse(MODULE.is_percent_range([20.0, -5.0]))


if __name__ == "__main__":
    unittest.main()
