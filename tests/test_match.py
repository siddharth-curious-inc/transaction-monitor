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


def test_row_goes_to_best_platform_claimant_not_earliest_otp():
    # Real-world regression: an earlier ZZ73 FirstClub OTP (no row of its own)
    # must NOT steal the Zomato 71 row that is a near-exact same-platform match
    # for the later Zomato 71.26 OTP.
    firstclub = parse_message(
        "Time: 2026-06-26 06:54:01\nx is OTP for INR 73.00 transaction "
        "towards FirstClub using ICICI Bank INR Prepaid Card XX6547.")
    zomato = parse_message(
        "Time: 2026-06-26 08:15:15\nx is OTP for INR 71.26 transaction "
        "towards ZOMATO LTD using ICICI Bank INR Prepaid Card XX6547.")
    logged = [LoggedTxn("Prachii", date(2026, 6, 26), "Zomato", 71.0, "K&D 6547", 10)]
    added, pending = match([firstclub, zomato], logged)
    assert len(added) == 1
    assert added[0].otp is zomato
    assert added[0].logged.row == 10
    assert len(pending) == 1
    assert pending[0].otp is firstclub


def test_wrong_date_does_not_match():
    otps = dedup_retries(load_otps())
    logged = [LoggedTxn("Prachii", date(2026, 6, 22), "Swiggy - Food", 554.0, "K&D 6547", 2)]
    added, pending = match(otps, logged)
    assert len(added) == 0
    assert len(pending) == 3


def _otp(ts, amount=155.0, card="9005", merchant="BLINK COMME"):
    o = parse_message(
        f"Time: {ts}\nx is OTP for INR {amount:.2f} transaction "
        f"towards {merchant} using ICICI Bank Credit Card XX{card}.")
    return o


def test_x_on_retry_excludes_whole_cluster():
    # same card+amount 2 min apart = one retry cluster. Ops X the later retry
    # (the one dedup discards); the surviving anchor must inherit the exclusion
    # and the reply reason.
    anchor = _otp("2026-06-23 09:37:01")
    retry = _otp("2026-06-23 09:39:30")
    retry.excluded = True
    retry.exclude_reason = "refund issued"

    deduped = dedup_retries([anchor, retry], window_seconds=600)
    assert len(deduped) == 1
    assert deduped[0].excluded is True
    assert deduped[0].exclude_reason == "refund issued"


def test_x_does_not_leak_across_separate_clusters():
    early = _otp("2026-06-23 09:00:00")
    late = _otp("2026-06-23 10:00:00")  # 1h later -> its own anchor
    late.excluded = True

    deduped = sorted(dedup_retries([early, late], window_seconds=600),
                     key=lambda x: x.ts)
    assert len(deduped) == 2
    assert deduped[0].excluded is False
    assert deduped[1].excluded is True


def test_comment_on_retry_propagates_to_anchor():
    # ops reply "Prachii" on whichever retry they happen to see; the surviving
    # anchor must inherit that note even if it landed on the discarded retry.
    anchor = _otp("2026-06-23 09:37:01")
    retry = _otp("2026-06-23 09:39:30")
    retry.comments = "Prachii"

    deduped = dedup_retries([anchor, retry], window_seconds=600)
    assert len(deduped) == 1
    assert deduped[0].comments == "Prachii"


def test_comment_does_not_leak_across_separate_clusters():
    early = _otp("2026-06-23 09:00:00")
    late = _otp("2026-06-23 10:00:00")  # 1h later -> its own anchor
    late.comments = "Shonik"

    deduped = sorted(dedup_retries([early, late], window_seconds=600),
                     key=lambda x: x.ts)
    assert len(deduped) == 2
    assert deduped[0].comments == ""
    assert deduped[1].comments == "Shonik"


def test_excluded_otp_is_not_pending():
    excluded = _otp("2026-06-23 11:00:00")
    excluded.excluded = True
    active = _otp("2026-06-23 12:00:00", amount=200.0)
    otps = dedup_retries([excluded, active])
    # mirror run.main(): excluded OTPs never enter matching
    to_match = [o for o in otps if not o.excluded]
    added, pending = match(to_match, [])
    assert len(added) == 0
    assert len(pending) == 1
    assert pending[0].otp.amount == 200.0
