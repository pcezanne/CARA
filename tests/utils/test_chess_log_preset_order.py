"""Tests for chess_log_preset_order.order_categories."""

from __future__ import annotations

import unittest

from app.utils.chess_log_preset_order import (
    CLAMP_ORDER,
    CCT_ORDER,
    order_categories,
)


class TestClampOrder(unittest.TestCase):

    def test_clamp_order_constant(self):
        self.assertEqual(CLAMP_ORDER, ("C", "L", "A", "M", "P"))

    def test_clamp_full_set_canonical_order(self):
        self.assertEqual(
            order_categories("CLAMP", ["P", "A", "C", "M", "L"]),
            ["C", "L", "A", "M", "P"],
        )

    def test_clamp_subset_preserves_canonical_order(self):
        self.assertEqual(
            order_categories("CLAMP", ["M", "C"]),
            ["C", "M"],
        )

    def test_clamp_uncategorized_last(self):
        result = order_categories("CLAMP", ["P", "", "C"])
        self.assertEqual(result[-1], "")
        self.assertEqual(result[0], "C")

    def test_clamp_unknown_cat_after_known_alphabetical(self):
        result = order_categories("CLAMP", ["Z", "C", "L"])
        self.assertEqual(result[:2], ["C", "L"])
        self.assertIn("Z", result)
        self.assertGreater(result.index("Z"), result.index("L"))

    def test_clamp_only_uncategorized(self):
        self.assertEqual(order_categories("CLAMP", [""]), [""])

    def test_clamp_empty_present(self):
        self.assertEqual(order_categories("CLAMP", []), [])


class TestCCTOrder(unittest.TestCase):

    def test_cct_order_constant(self):
        self.assertEqual(CCT_ORDER, ("Checks", "Captures", "Threats"))

    def test_cct_full_set_canonical_order(self):
        self.assertEqual(
            order_categories("CCT", ["Threats", "Checks", "Captures"]),
            ["Checks", "Captures", "Threats"],
        )

    def test_cct_subset(self):
        self.assertEqual(
            order_categories("CCT", ["Threats", "Checks"]),
            ["Checks", "Threats"],
        )

    def test_cct_uncategorized_last(self):
        result = order_categories("CCT", ["", "Captures"])
        self.assertEqual(result[-1], "")
        self.assertEqual(result[0], "Captures")


class TestCustomOrder(unittest.TestCase):

    def test_custom_with_order_respected(self):
        self.assertEqual(
            order_categories("Custom", ["Foo", "Bar", "Baz"],
                             custom_order=["Baz", "Foo", "Bar"]),
            ["Baz", "Foo", "Bar"],
        )

    def test_custom_without_order_alphabetical(self):
        result = order_categories("Custom", ["Zebra", "Alpha", "Mango"])
        self.assertEqual(result, ["Alpha", "Mango", "Zebra"])

    def test_custom_with_order_unknown_cats_appended(self):
        result = order_categories("Custom", ["Foo", "Bar", "Extra"],
                                  custom_order=["Foo", "Bar"])
        self.assertEqual(result[:2], ["Foo", "Bar"])
        self.assertIn("Extra", result)
        self.assertGreater(result.index("Extra"), 1)

    def test_custom_uncategorized_always_last(self):
        result = order_categories("Custom", ["Foo", "", "Bar"],
                                  custom_order=["Bar", "Foo"])
        self.assertEqual(result[-1], "")


class TestUnknownPreset(unittest.TestCase):

    def test_unknown_preset_alphabetical_named_then_uncategorized(self):
        result = order_categories("ZPRESET", ["C", "A", "B", ""])
        self.assertEqual(result, ["A", "B", "C", ""])

    def test_unknown_preset_empty_input(self):
        self.assertEqual(order_categories("ZPRESET", []), [])


if __name__ == "__main__":
    unittest.main()
