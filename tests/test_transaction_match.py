import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, datetime  # noqa: E402

from config import ACCOUNT_TO_PAYMENT_METHOD, NEW_AMOUNT_TOLERANCE  # noqa: E402
from match import (LoggedTxn, link_to_otps, match,  # noqa: E402
                   reconcile_pending)
from parse import OTP  # noqa: E402
from sheets import PendingRow  # noqa: E402


def _conf(last4, amount, ts, merchant="X"):
    return OTP(amount=amount, merchant_raw=merchant, card_last4=last4,
               ts=ts, raw="")


def _match(otps, logged):
    return match(otps, logged, tolerance=NEW_AMOUNT_TOLERANCE,
                 payment_method_map=ACCOUNT_TO_PAYMENT_METHOD)


def test_no_retry_dedup_two_identical_debits_are_two_txns():
    # Same rail + amount + day: with the OTP source these were retries; with
    # confirmations they are two real settled transactions and must not merge.
    c1 = _conf("0978", 82.0, datetime(2026, 7, 18, 17, 0))
    c2 = _conf("0978", 82.0, datetime(2026, 7, 18, 18, 0))
    _, pending = _match([c1, c2], [])
    assert len(pending) == 2

    # One logged row consumes exactly one of them (rows are one-to-one).
    logged = [LoggedTxn("H", date(2026, 7, 18), "X", 82.0,
                        "Cashbook - Kabeer and Pallavi", 2)]
    added, pending = _match([c1, c2], logged)
    assert len(added) == 1 and len(pending) == 1


def test_amount_tolerance_is_one_rupee():
    within = _conf("9005", 100.0, datetime(2026, 7, 18, 12, 0))
    ok = [LoggedTxn("H", date(2026, 7, 18), "P", 101.0, "ICICI 9005", 2)]  # +1
    added, _ = _match([within], ok)
    assert len(added) == 1

    outside = _conf("9005", 100.0, datetime(2026, 7, 18, 12, 0))
    no = [LoggedTxn("H", date(2026, 7, 18), "P", 102.0, "ICICI 9005", 3)]   # +2
    _, pending = _match([outside], no)
    assert len(pending) == 1


def test_cashbook_rail_matches_on_upi_last4():
    c = _conf("6679", 1497.0, datetime(2026, 7, 15, 9, 0))
    logged = [LoggedTxn("H", date(2026, 7, 15), "P", 1497.0,
                        "Cashbook - Ishita and Harsh", 4)]
    added, _ = _match([c], logged)
    assert len(added) == 1


def test_link_card_confirmation_inherits_exclusion_and_comments():
    conf = _conf("9005", 540.0, datetime(2026, 7, 19, 22, 43))
    otp = _conf("9005", 540.0, datetime(2026, 7, 19, 22, 40))
    otp.excluded = True
    otp.exclude_reason = "refund"
    otp.comments = "Dhara household"
    link_to_otps([conf], [otp], tolerance=NEW_AMOUNT_TOLERANCE)
    assert conf.excluded
    assert conf.exclude_reason == "refund"
    assert conf.comments == "Dhara household"


def test_link_picks_nearest_otp_one_to_one():
    conf = _conf("9005", 200.0, datetime(2026, 7, 19, 12, 0))
    near = _conf("9005", 200.0, datetime(2026, 7, 19, 12, 5))
    near.comments = "near"
    far = _conf("9005", 200.0, datetime(2026, 7, 19, 20, 0))
    far.comments = "far"
    link_to_otps([conf], [near, far], tolerance=NEW_AMOUNT_TOLERANCE)
    assert conf.comments == "near"


def test_upi_rail_never_links_to_an_otp():
    # Cashbook last-4 isn't an OTP-linked card, so it inherits nothing even if a
    # (hypothetical) matching OTP exists.
    upi = _conf("0978", 82.0, datetime(2026, 7, 18, 17, 33))
    otp = _conf("0978", 82.0, datetime(2026, 7, 18, 17, 30))
    otp.comments = "should not link"
    link_to_otps([upi], [otp], tolerance=NEW_AMOUNT_TOLERANCE)
    assert upi.comments == "" and not upi.excluded


def _prow(d, amount, pm):
    return PendingRow(date=d, time="10:00", amount=amount, platform="P",
                      payment_method=pm, comments="", source_cell="src")


def test_reconcile_drops_now_logged_keeps_unlogged():
    logged_row = _prow(date(2026, 7, 15), 100.0, "ICICI 9005")   # now logged
    still_row = _prow(date(2026, 7, 16), 250.0, "K&D 6547")      # not logged
    logged = [LoggedTxn("H", date(2026, 7, 15), "P", 100.0, "ICICI 9005", 2)]
    still = reconcile_pending([logged_row, still_row], logged,
                              tolerance=NEW_AMOUNT_TOLERANCE)
    assert [r.amount for r in still] == [250.0]
