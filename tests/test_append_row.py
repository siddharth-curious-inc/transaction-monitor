import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, datetime  # noqa: E402

import pytest  # noqa: E402

from config import ACCOUNT_TO_PAYMENT_METHOD, NEW_AMOUNT_TOLERANCE  # noqa: E402
from match import LoggedTxn, match  # noqa: E402
from parse import OTP  # noqa: E402
from sheets import _household_row_values, _parse_amount, _parse_date  # noqa: E402

# A deliberately scattered header: the columns the bot writes are NOT contiguous
# and NOT in A-B-C order, so this exercises index-based alignment.
HEADER = ["", "Date (double click)", "", "Platform", "Amount paid (₹)",
          "Payment method", "foo", "Remark", "Billed to Family (₹)"]


def test_row_aligns_values_to_their_columns():
    row = _household_row_values(HEADER, date(2026, 7, 19), "Blinkit", 155.0,
                                "ICICI 9005", "a note")
    assert row[1] == "19-Jul-2026"     # Date, DD-Mon-YYYY
    assert row[3] == "Blinkit"         # Platform
    assert row[4] == 155.0             # Amount (numeric)
    assert row[5] == "ICICI 9005"      # Payment method
    assert row[7] == "a note"          # Remark
    assert row[0] == "" and row[2] == "" and row[6] == ""  # left for ops


def test_remark_omitted_when_empty():
    # With no remark the row stops at the Payment-method column (index 5); the
    # Remark cell (index 7) is simply not written, so append leaves it blank.
    row = _household_row_values(HEADER, date(2026, 7, 19), "Blinkit", 155.0,
                                "ICICI 9005", "")
    assert len(row) == 6
    assert row[5] == "ICICI 9005"


def test_missing_required_column_raises():
    bad = ["Platform", "Amount paid (₹)", "Payment method"]  # no Date column
    with pytest.raises(RuntimeError):
        _household_row_values(bad, date(2026, 7, 19), "X", 1.0, "ICICI 9005")


def test_written_row_is_recognised_by_the_matcher():
    # The whole point of the write format: a row the bot appends must be seen as
    # "logged" by the next scheduled run, or the item stays pending forever.
    row = _household_row_values(HEADER, date(2026, 7, 19), "Blinkit", 155.0,
                                "ICICI 9005", "")
    logged = [LoggedTxn(
        household="H",
        date=_parse_date(row[1]),
        platform=row[3],
        amount=_parse_amount(str(row[4])),
        payment_method=row[5],
        row=2)]
    conf = OTP(amount=155.0, merchant_raw="BLINK COMME", card_last4="9005",
               ts=datetime(2026, 7, 19, 10, 0), raw="")
    added, pending = match([conf], logged, tolerance=NEW_AMOUNT_TOLERANCE,
                           payment_method_map=ACCOUNT_TO_PAYMENT_METHOD)
    assert len(added) == 1 and not pending
