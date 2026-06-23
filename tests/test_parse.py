import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from parse import parse_message  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "messages.txt")


def load():
    with open(FIX, encoding="utf-8") as f:
        return [b.strip() for b in f.read().split("===")]


def test_parses_all_three_cards():
    msgs = load()
    o1 = parse_message(msgs[0])
    assert o1.amount == 554.0
    assert o1.merchant_raw == "Swiggy"
    assert o1.card_last4 == "6547"
    assert o1.ts.hour == 17 and o1.ts.minute == 33

    o2 = parse_message(msgs[1])
    assert o2.amount == 581.0
    assert o2.merchant_raw == "INSTAMART"
    assert o2.card_last4 == "6570"

    o3 = parse_message(msgs[2])
    assert o3.amount == 155.0
    assert o3.merchant_raw == "BLINK COMME"
    assert o3.card_last4 == "9005"


def test_amount_with_thousands_separator():
    msg = "Time: 2026-06-23 12:00:00\n1234 is OTP for INR 1,299.00 transaction towards Amazon using ICICI Bank Credit Card XX9005."
    o = parse_message(msg)
    assert o.amount == 1299.0


def test_non_otp_returns_none():
    assert parse_message("hello team, standup at 10") is None
