"""Post sample #transaction-bridge messages (and a matching OTP) to the scratch
channel so you can exercise the interactivity bot end to end.

The real bridge messages are Block Kit (a "*Raw SMS:*" section + a :clock3:
footer), which can't be typed into Slack by hand -- so this posts them via the
API using the bot token. Reads SLACK_BOT_TOKEN + the channel ids from config
(which loads .env), so it targets whatever OTP_CHANNEL_ID / TRANSACTION_CHANNEL_ID
you've set for the scratch run.

    python tools/post_sample_txn.py verify   # parse locally, post nothing
    python tools/post_sample_txn.py upi       # a UPI debit -> standalone prompt
    python tools/post_sample_txn.py card      # an OTP + a card debit -> threaded prompt
    python tools/post_sample_txn.py all        # both (default)

Each debit uses a real rail last-4 from ACCOUNT_TO_PAYMENT_METHOD and a merchant
that's in the alias map, and a sender-id that is NOT the emulator, so the bot
picks them up.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from slack_sdk import WebClient  # noqa: E402
from slack_sdk.http_retry.builtin_handlers import (  # noqa: E402
    RateLimitErrorRetryHandler)

from config import (OTP_CHANNEL_ID, SLACK_BOT_TOKEN,  # noqa: E402
                    TRANSACTION_CHANNEL_ID)
from parse import parse_message, parse_transaction_message  # noqa: E402

# --- sample content ---------------------------------------------------------
# UPI (CashBook a/c xx0978 = "Cashbook - Kabeer and Pallavi"). Obopay SMS carries
# its own inline date-time, so no OTP and a standalone prompt is expected.
UPI_SMS = ("A/c xx0978 debited Rs. 413.00 on 21-07-2026 13:15:42 to "
           "UPI/618716845147/BLINKIT ECO. Avl Bal Rs. 5,000.00")
UPI_SENDER = "AD-CBOBPY-S"
UPI_CLOCK = "2026-07-21 13:15:42"

# Card (ICICI Credit Card XX9005 = "ICICI 9005"). ICICI SMS has only a date, so
# the time comes from the footer :clock3:. A matching OTP posted ~40s earlier
# should make the prompt a threaded reply under it.
CARD_SMS = ("INR 899.00 spent on ICICI Bank Card XX9005 on 21-Jul-26 on "
            "Amazon. Avl Limit: INR 50,000.00")
CARD_SENDER = "VM-ICICIB-S"
CARD_CLOCK = "2026-07-21 13:15:10"
CARD_OTP_TEXT = ("Time: 2026-07-21 13:14:30\n123456 is OTP for INR 899.00 "
                 "transaction towards Amazon using ICICI Bank Credit Card XX9005.")


def _txn_blocks(raw_sms, merchant, amount, sender_id, clock):
    """A #transaction-bridge-shaped Block Kit message: pretty fields, the
    authoritative Raw SMS section, and the footer context (sender-id + clock)."""
    return [
        {"type": "header",
         "text": {"type": "plain_text", "text": "💸 Debit alert", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Merchant:*\n{merchant}"},
            {"type": "mrkdwn", "text": f"*Amount:*\n₹{amount}"},
        ]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*Raw SMS:*\n```{raw_sms}```"}},
        {"type": "context", "elements": [
            {"type": "mrkdwn",
             "text": f":iphone: Pixel 7a   •   :email: {sender_id}   "
                     f"•   :clock3: {clock}"}],
         },
    ]


def _client():
    c = WebClient(token=SLACK_BOT_TOKEN)
    c.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    return c


def _verify(label, msg):
    otp = parse_transaction_message(msg)
    if otp is None:
        print(f"  [{label}] ✗ did NOT parse as a debit confirmation")
        return False
    print(f"  [{label}] ✓ amount={otp.amount} last4={otp.card_last4} "
          f"ts={otp.ts:%Y-%m-%d %H:%M:%S} merchant={otp.merchant_raw!r}")
    return True


def post_upi(client, verify_only):
    blocks = _txn_blocks(UPI_SMS, "Blinkit", "413.00", UPI_SENDER, UPI_CLOCK)
    msg = {"blocks": blocks}
    if not _verify("upi", msg) or verify_only:
        return
    client.chat_postMessage(channel=TRANSACTION_CHANNEL_ID, blocks=blocks,
                            text="Debit: ₹413.00 Blinkit")
    print("  [upi] posted to transaction channel")


def post_card(client, verify_only):
    blocks = _txn_blocks(CARD_SMS, "Amazon", "899.00", CARD_SENDER, CARD_CLOCK)
    msg = {"blocks": blocks}
    ok_txn = _verify("card", msg)
    otp = parse_message(CARD_OTP_TEXT)
    ok_otp = otp is not None
    print(f"  [otp ] {'✓' if ok_otp else '✗'} amount="
          f"{getattr(otp, 'amount', None)} last4={getattr(otp, 'card_last4', None)} "
          f"ts={getattr(otp, 'ts', None)}")
    if not (ok_txn and ok_otp) or verify_only:
        return
    # OTP first so it's an available reply target when the poller sees the debit.
    client.chat_postMessage(channel=OTP_CHANNEL_ID, text=CARD_OTP_TEXT)
    client.chat_postMessage(channel=TRANSACTION_CHANNEL_ID, blocks=blocks,
                            text="Debit: ₹899.00 Amazon")
    print("  [card] posted OTP + debit; expect a threaded prompt under the OTP")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    verify_only = what == "verify"
    if not SLACK_BOT_TOKEN and not verify_only:
        raise SystemExit("SLACK_BOT_TOKEN not set (fill .env).")
    client = None if verify_only else _client()
    print(f"channel (txn): {TRANSACTION_CHANNEL_ID}  (otp): {OTP_CHANNEL_ID}")
    if what in ("upi", "all", "verify"):
        post_upi(client, verify_only)
    if what in ("card", "all", "verify"):
        post_card(client, verify_only)


if __name__ == "__main__":
    main()
