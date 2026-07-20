"""Inspect what a bridge channel actually returns. Slack-only — needs no GCP,
so it works even while service-account impersonation is unresolved.

Set SLACK_BOT_TOKEN, then point it at a channel:
    python tools/peek_slack.py              # #otp-bridge (OTP_CHANNEL_ID)
    python tools/peek_slack.py transaction  # #transaction-bridge + SMS/sender parse

Prints how many messages came back since midnight IST, where each one's text
lives (text / attachments / blocks), and what the extractor pulls out. For the
transaction channel it also shows the parsed raw-SMS, footer sender-id, and the
parsed debit confirmation, so you can confirm the Block Kit parser before a run.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from datetime import datetime

from slack_sdk import WebClient

from config import IST  # noqa: E402
from parse import (_raw_sms, parse_transaction_message,  # noqa: E402
                   transaction_sender_id)
from slack_io import _full_text  # noqa: E402


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "otp"
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    env = "TRANSACTION_CHANNEL_ID" if which == "transaction" else "OTP_CHANNEL_ID"
    channel = os.environ.get(env, "")
    if not token or not channel:
        print(f"Set SLACK_BOT_TOKEN and {env} first.")
        return

    now = datetime.now(IST)
    oldest = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    resp = WebClient(token=token).conversations_history(
        channel=channel, oldest=str(oldest), limit=50)
    msgs = resp.get("messages", [])
    print(f"Fetched {len(msgs)} message(s) from {env} since 00:00 IST today.\n")

    for i, m in enumerate(msgs[:3]):
        print(f"--- message {i} ---")
        print(f"  has text field:        {bool(m.get('text'))}")
        print(f"  has attachments:       {bool(m.get('attachments'))}")
        print(f"  has blocks:            {bool(m.get('blocks'))}")
        print(f"  subtype / bot_id:      {m.get('subtype')} / {m.get('bot_id')}")
        if which == "transaction":
            print(f"  raw SMS:               {_raw_sms(m) or '<none>'}")
            print(f"  footer sender-id:      {transaction_sender_id(m) or '<none>'}")
            print(f"  parsed confirmation:   {parse_transaction_message(m)}")
        else:
            extracted = _full_text(m)
            print(f"  extractor output:\n{extracted[:400] or '    <empty>'}")
        print()


if __name__ == "__main__":
    main()
