import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from match import LoggedTxn, dedup_retries, match  # noqa: E402
from parse import parse_message  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "messages.txt")
TODAY = date(2026, 6, 23)


def load_otps():
    with open(FIX, encoding="utf-8") as f:
        blocks = [b.strip() for b in f.read().split("===")]
    return [parse_message(b) for b in blocks]


def test_dedup_collapses_retry():
    otps = load_otps()  # last two are the same card+amount 2 min apart
    deduped = dedup_retries(otps, window_seconds=600)
    assert len(otps) == 4
    assert len(deduped) == 3  # the 09:39 retry of 09:37 is dropped


def test_dedup_keeps_far_apart_same_amount():
    otps = load_otps()
    deduped = dedup_retries(otps, window_seconds=60)  # 2 min > 1 min window
    assert len(deduped) == 4


def test_match_added_and_pending():
    otps = dedup_retries(load_otps())  # 3 expected txns: 554/6547, 581/6570, 155/9005
    logged = [
        # exact for the Swiggy one
        LoggedTxn("Prachii", TODAY, "Swiggy - Food", 554.0, "K&D 6547", 2),
        # within +/-5 for the Instamart one, platform differs (still matches on key)
        LoggedTxn("Shonik", TODAY, "Zepto", 583.0, "K&P 6570", 5),
        # 155/9005 intentionally NOT logged -> should be pending
    ]
    added, pending = match(otps, logged)
    assert len(added) == 2
    assert len(pending) == 1
    assert pending[0].otp.amount == 155.0
    assert pending[0].platform == "Blinkit"  # alias applied for display


def test_one_row_cannot_satisfy_two_otps():
    # two distinct ~150 OTPs same card same day, only one logged row
    o = parse_message(
        "Time: 2026-06-23 11:00:00\nx is OTP for INR 150.00 transaction "
        "towards BLINK COMME using ICICI Bank Credit Card XX9005.")
    o2 = parse_message(
        "Time: 2026-06-23 15:00:00\nx is OTP for INR 152.00 transaction "
        "towards BLINK COMME using ICICI Bank Credit Card XX9005.")
    logged = [LoggedTxn("Kel", TODAY, "Blinkit", 151.0, "ICICI 9005", 3)]
    added, pending = match([o, o2], logged)
    assert len(added) == 1
    assert len(pending) == 1


def test_wrong_date_does_not_match():
    otps = dedup_retries(load_otps())
    logged = [LoggedTxn("Prachii", date(2026, 6, 22), "Swiggy - Food", 554.0, "K&D 6547", 2)]
    added, pending = match(otps, logged)
    assert len(added) == 0
    assert len(pending) == 3
