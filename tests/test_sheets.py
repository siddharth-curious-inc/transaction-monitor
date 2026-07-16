import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from match import as_results  # noqa: E402
from parse import parse_message  # noqa: E402
from sheets import PENDING_SHEET_HEADER, build_pending_sheet_rows  # noqa: E402
from slack_io import permalink  # noqa: E402


def _otp(time_str, amount, merchant, card, comments="", slack_ts=""):
    o = parse_message(
        f"Time: {time_str}\nx is OTP for INR {amount} transaction "
        f"towards {merchant} using ICICI Bank Credit Card XX{card}.")
    o.comments = comments
    o.slack_ts = slack_ts
    return o


def test_permalink_format():
    link = permalink("https://curious.slack.com/", "1719135421.000200")
    assert link.startswith("https://curious.slack.com/archives/")
    assert link.endswith("/p1719135421000200")  # dot stripped, 'p' prefix


def test_permalink_empty_without_ts_or_base():
    assert permalink("", "1719135421.000200") == ""
    assert permalink("https://x.slack.com/", "") == ""


def test_build_pending_rows_header_and_columns():
    o = _otp("2026-06-23 09:37:01", "155.00", "BLINK COMME", "9005",
             comments="Prachii household", slack_ts="1719135421.000200")
    rows = build_pending_sheet_rows(as_results([o]), "https://curious.slack.com/")
    assert rows[0] == PENDING_SHEET_HEADER
    date, time, amount, platform, card, comments, source = rows[1]
    assert date == "23-Jun-2026"
    assert time == "09:37"
    assert amount == "₹155.00"
    assert platform == "Blinkit"
    assert card == "ICICI 9005"
    assert comments == "Prachii household"
    assert source.startswith('=HYPERLINK("https://curious.slack.com/archives/')
    assert 'p1719135421000200"' in source
    assert source.endswith('"OTP message")')


def test_build_pending_rows_sorted_oldest_first():
    late = _otp("2026-06-25 12:00:00", "200.00", "ZEPTO MARKE", "6547")
    early = _otp("2026-06-23 08:00:00", "100.00", "SWIGGY", "6547")
    rows = build_pending_sheet_rows(as_results([late, early]),
                                    "https://curious.slack.com/")
    # header, then oldest (23-Jun) before newest (25-Jun)
    assert rows[1][0] == "23-Jun-2026"
    assert rows[2][0] == "25-Jun-2026"


def test_build_pending_rows_no_link_when_ts_missing():
    o = _otp("2026-06-23 09:37:01", "155.00", "SWIGGY", "6547", slack_ts="")
    rows = build_pending_sheet_rows(as_results([o]), "https://curious.slack.com/")
    # falls back to a plain label rather than a broken HYPERLINK formula
    assert rows[1][6] == "OTP message"
