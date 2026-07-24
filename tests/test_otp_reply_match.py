import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "interactivity"))

from datetime import datetime  # noqa: E402

from otp_match import find_otp_reply_target  # noqa: E402
from parse import OTP  # noqa: E402


def _otp(last4, amount, ts, slack_ts):
    return OTP(amount=amount, merchant_raw="X", card_last4=last4, ts=ts,
               raw="", slack_ts=slack_ts)


def _conf(last4, amount, ts):
    return OTP(amount=amount, merchant_raw="X", card_last4=last4, ts=ts, raw="")


def test_picks_closest_otp_before_confirmation():
    conf = _conf("9005", 500.0, datetime(2026, 7, 20, 12, 0, 0))
    far = _otp("9005", 500.0, datetime(2026, 7, 20, 11, 45, 0), "ts_far")
    near = _otp("9005", 500.0, datetime(2026, 7, 20, 11, 58, 0), "ts_near")
    assert find_otp_reply_target(conf, [far, near]) == "ts_near"


def test_ignores_otps_after_the_confirmation():
    conf = _conf("9005", 500.0, datetime(2026, 7, 20, 12, 0, 0))
    later = _otp("9005", 500.0, datetime(2026, 7, 20, 12, 1, 0), "ts_later")
    assert find_otp_reply_target(conf, [later]) is None


def test_respects_the_30_minute_window():
    conf = _conf("9005", 500.0, datetime(2026, 7, 20, 12, 0, 0))
    stale = _otp("9005", 500.0, datetime(2026, 7, 20, 11, 25, 0), "ts_stale")
    # 35 min before -> out of the 1800s window
    assert find_otp_reply_target(conf, [stale]) is None
    just_in = _otp("9005", 500.0, datetime(2026, 7, 20, 11, 31, 0), "ts_in")
    assert find_otp_reply_target(conf, [just_in]) == "ts_in"


def test_requires_same_card_and_amount_within_tolerance():
    conf = _conf("9005", 500.0, datetime(2026, 7, 20, 12, 0, 0))
    wrong_card = _otp("6547", 500.0, datetime(2026, 7, 20, 11, 59, 0), "c")
    wrong_amt = _otp("9005", 520.0, datetime(2026, 7, 20, 11, 59, 0), "a")
    assert find_otp_reply_target(conf, [wrong_card, wrong_amt]) is None
    ok_amt = _otp("9005", 500.5, datetime(2026, 7, 20, 11, 59, 0), "ok")
    assert find_otp_reply_target(conf, [ok_amt]) == "ok"


def test_skips_already_used_otps():
    conf = _conf("9005", 500.0, datetime(2026, 7, 20, 12, 0, 0))
    used = _otp("9005", 500.0, datetime(2026, 7, 20, 11, 58, 0), "used")
    free = _otp("9005", 500.0, datetime(2026, 7, 20, 11, 50, 0), "free")
    got = find_otp_reply_target(conf, [used, free], used_otp_ts={"used"})
    assert got == "free"


def test_no_candidate_returns_none_for_standalone_fallback():
    conf = _conf("9005", 500.0, datetime(2026, 7, 20, 12, 0, 0))
    assert find_otp_reply_target(conf, []) is None
