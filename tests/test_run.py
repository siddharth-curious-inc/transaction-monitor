import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import IST  # noqa: E402
from match import as_results  # noqa: E402
from parse import parse_message  # noqa: E402
from run import compose  # noqa: E402
from slack_io import _blocks_to_text  # noqa: E402

WHEN = datetime(2026, 6, 23, 17, 0, tzinfo=IST)


def _excluded(reason=""):
    o = parse_message(
        "Time: 2026-06-23 09:37:01\nx is OTP for INR 155.00 transaction "
        "towards BLINK COMME using ICICI Bank Credit Card XX9005.")
    o.excluded = True
    o.exclude_reason = reason
    return o


def test_summary_shows_excluded_count():
    excluded = as_results([_excluded("refund")])
    main, _ = compose(3, [], [], [], excluded, WHEN)
    text = _blocks_to_text(main[0])
    assert "🚫 Excluded by ops: *1*" in text


def test_reply_has_excluded_table_with_reason():
    excluded = as_results([_excluded("double charge refunded")])
    _, reply = compose(1, [], [], [], excluded, WHEN)
    assert reply is not None
    text = _blocks_to_text(reply[0])
    assert "Excluded by ops" in text
    assert "Reason" in text  # header column present
    assert "double charge refunded" in text


def test_reply_reason_blank_when_no_note():
    excluded = as_results([_excluded("")])
    _, reply = compose(1, [], [], [], excluded, WHEN)
    text = _blocks_to_text(reply[0])
    # row renders with an empty reason cell rather than a placeholder
    assert "Blinkit" in text


def test_no_reply_when_nothing_logged_or_excluded():
    main, reply = compose(0, [], [], [], [], WHEN)
    assert reply is None


def test_pending_table_shows_comments_column():
    o = parse_message(
        "Time: 2026-06-23 09:37:01\nx is OTP for INR 155.00 transaction "
        "towards BLINK COMME using ICICI Bank Credit Card XX9005.")
    o.comments = "Prachii household"
    pending = as_results([o])
    main, _ = compose(1, [], pending, [], [], WHEN)
    text = _blocks_to_text(main[0])
    assert "Comments" in text  # header column present
    assert "Prachii household" in text


def test_pending_table_comments_blank_shows_double_hyphen():
    o = parse_message(
        "Time: 2026-06-23 09:37:01\nx is OTP for INR 155.00 transaction "
        "towards BLINK COMME using ICICI Bank Credit Card XX9005.")
    pending = as_results([o])
    main, _ = compose(1, [], pending, [], [], WHEN)
    text = _blocks_to_text(main[0])
    assert "--" in text


def test_reply_logged_header_includes_today_date():
    o = parse_message(
        "Time: 2026-06-23 09:37:01\nx is OTP for INR 155.00 transaction "
        "towards BLINK COMME using ICICI Bank Credit Card XX9005.")
    from match import match, LoggedTxn
    from datetime import date
    logged = [LoggedTxn("Prachii", date(2026, 6, 23), "Blinkit", 155.0,
                        "ICICI 9005", 1)]
    added, _ = match([o], logged)
    _, reply = compose(1, added, [], [], [], WHEN)
    text = _blocks_to_text(reply[0])
    assert "✅ Logged today (23 Jun 2026)" in text
