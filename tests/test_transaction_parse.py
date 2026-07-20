import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date  # noqa: E402

from config import TEST_SENDER_ID, TRANSACTION_FLOOR_DATE  # noqa: E402
from parse import parse_transaction_message, transaction_sender_id  # noqa: E402

_FIX = os.path.join(os.path.dirname(__file__), "fixtures",
                    "transaction_messages.json")
with open(_FIX) as f:
    MESSAGES = {m["_case"]: m for m in json.load(f)}


def test_parse_upi_debit_from_raw_sms():
    o = parse_transaction_message(MESSAGES["upi_debit_valid"])
    assert o is not None
    assert o.amount == 82.0
    assert o.card_last4 == "0978"                 # a/c xx0978
    assert o.ts.date() == date(2026, 7, 18)
    assert (o.ts.hour, o.ts.minute, o.ts.second) == (17, 33, 41)
    assert o.merchant_raw == "SONU KUMAR PODDAR"  # UPI payee


def test_parse_icici_card_debit_time_from_footer():
    # ICICI raw SMS carries only a date (DD-Mon-YY); the time must come from the
    # footer :clock3: timestamp.
    o = parse_transaction_message(MESSAGES["icici_card_debit_valid"])
    assert o is not None
    assert o.amount == 540.0
    assert o.card_last4 == "9005"
    assert o.ts.date() == date(2026, 7, 19)       # 19-Jul-26 normalized to 2026
    assert (o.ts.hour, o.ts.minute) == (22, 43)   # from footer clock
    assert o.merchant_raw == "UrbanClap Techn"


def test_credit_is_not_parsed():
    assert parse_transaction_message(MESSAGES["credit_ignored"]) is None


def test_sender_id_extracted_from_footer():
    assert transaction_sender_id(MESSAGES["upi_debit_valid"]) == "VK-OBOPAY-S"
    assert transaction_sender_id(MESSAGES["test_sender_ignored"]) == TEST_SENDER_ID


def test_amount_not_confused_by_avl_bal_or_limit():
    # "Avl Bal 85653.99" / "Avl Limit: INR 4,76,432.47" must never be picked up.
    assert parse_transaction_message(MESSAGES["upi_debit_valid"]).amount == 82.0
    assert parse_transaction_message(
        MESSAGES["icici_card_debit_valid"]).amount == 540.0


def test_run_level_filters_keep_only_valid_debits():
    # Mirror run.run_transaction_source's intake filters over the whole fixture:
    # drop the emulator sender, non-debits, and anything before the floor date.
    kept = []
    for m in MESSAGES.values():
        if transaction_sender_id(m) == TEST_SENDER_ID:
            continue
        o = parse_transaction_message(m)
        if not o or o.ts.date() < TRANSACTION_FLOOR_DATE:
            continue
        kept.append(o.card_last4)
    assert sorted(kept) == ["0978", "9005"]        # upi + icici card only
