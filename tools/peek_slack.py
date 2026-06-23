"""Inspect what #otp-bridge actually returns. Slack-only — needs no GCP,
so it works even while service-account impersonation is unresolved.

Set SLACK_BOT_TOKEN and OTP_CHANNEL_ID in your environment, then:
    python tools/peek_slack.py

Prints how many messages came back since midnight IST, where each one's text
lives (text / attachments / blocks), and what the extractor pulls out.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from datetime import datetime

from slack_sdk import WebClient

from config import IST  # noqa: E402
from slack_io import _full_text  # noqa: E402


def main():
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    channel = os.environ.get("OTP_CHANNEL_ID", "")
    if not token or not channel:
        print("Set SLACK_BOT_TOKEN and OTP_CHANNEL_ID first.")
        return

    now = datetime.now(IST)
    oldest = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    resp = WebClient(token=token).conversations_history(
        channel=channel, oldest=str(oldest), limit=50)
    msgs = resp.get("messages", [])
    print(f"Fetched {len(msgs)} message(s) since 00:00 IST today.\n")

    for i, m in enumerate(msgs[:3]):
        print(f"--- message {i} ---")
        print(f"  has text field:        {bool(m.get('text'))}")
        print(f"  has attachments:       {bool(m.get('attachments'))}")
        print(f"  has blocks:            {bool(m.get('blocks'))}")
        print(f"  subtype / bot_id:      {m.get('subtype')} / {m.get('bot_id')}")
        extracted = _full_text(m)
        print(f"  extractor output:\n{extracted[:400] or '    <empty>'}\n")


if __name__ == "__main__":
    main()
