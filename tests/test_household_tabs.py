import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sheets import _filter_household_tabs  # noqa: E402

_HH = ["Date (double click)", "Platform", "Amount paid (₹)", "Payment method",
       "Remark", "Billed to Family (₹)"]
_NOT_HH = ["Something", "Else"]


def test_keeps_real_households_sorted_alphabetically():
    items = [
        ("Kabeer and Pallavi", _HH),
        ("Ishita and Harsh", _HH),
        ("Legend", _NOT_HH),
    ]
    assert _filter_household_tabs(items) == ["Ishita and Harsh",
                                             "Kabeer and Pallavi"]


def test_excludes_duplicate_me_even_though_it_has_household_headers():
    # "Duplicate me" is the template tab: it DOES carry the household markers
    # (that's why clones do), but it must never be a logging destination.
    items = [("Duplicate me", _HH), ("Real Household", _HH)]
    assert _filter_household_tabs(items) == ["Real Household"]


def test_excludes_all_named_non_household_tabs():
    items = [(t, _HH) for t in (
        "To fix", "Legend", "Unrecorded transactions", "Duplicate me",
        "Wallet updates", "Master Tracker",
        "transactions-2026-06-01-to-2026-06-09")]
    items.append(("Only Real One", _HH))
    assert _filter_household_tabs(items) == ["Only Real One"]


def test_drops_tabs_without_household_markers():
    items = [("Master Tracker", _NOT_HH), ("Exports", _NOT_HH)]
    assert _filter_household_tabs(items) == []
