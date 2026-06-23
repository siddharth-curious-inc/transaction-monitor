"""Slack reads and writes via slack_sdk."""
from datetime import datetime

from slack_sdk import WebClient

from config import IST, OTP_CHANNEL_ID, SLACK_BOT_TOKEN, SUMMARY_CHANNEL_ID


def _client():
    return WebClient(token=SLACK_BOT_TOKEN)


def _text_from_blocks(blocks):
    """Pull text out of Block Kit blocks (section / rich_text / context)."""
    out = []
    for b in blocks or []:
        t = b.get("type")
        if t == "section":
            txt = b.get("text")
            if isinstance(txt, dict):
                out.append(txt.get("text", ""))
            for f in b.get("fields", []) or []:
                if isinstance(f, dict):
                    out.append(f.get("text", ""))
        elif t == "rich_text":
            for el in b.get("elements", []) or []:
                for sub in el.get("elements", []) or []:
                    if sub.get("type") == "text":
                        out.append(sub.get("text", ""))
                    elif sub.get("type") == "link":
                        out.append(sub.get("text") or sub.get("url", ""))
        elif t == "context":
            for el in b.get("elements", []) or []:
                if isinstance(el, dict):
                    out.append(el.get("text", ""))
    return "\n".join(p for p in out if p)


def _full_text(msg):
    """OTP body can live in text, attachments, and/or Block Kit blocks."""
    parts = [msg.get("text", "")]
    for att in msg.get("attachments", []) or []:
        parts.append(att.get("text", "") or att.get("fallback", ""))
        parts.append(_text_from_blocks(att.get("blocks")))
    parts.append(_text_from_blocks(msg.get("blocks")))
    return "\n".join(p for p in parts if p)


def fetch_messages_since_midnight():
    """Return raw OTP message strings posted since 00:00 IST today."""
    now = datetime.now(IST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    oldest = start.timestamp()

    client = _client()
    texts, cursor = [], None
    while True:
        resp = client.conversations_history(
            channel=OTP_CHANNEL_ID, oldest=str(oldest),
            limit=200, cursor=cursor)
        for m in resp.get("messages", []):
            texts.append(_full_text(m))
        if resp.get("has_more"):
            cursor = resp["response_metadata"]["next_cursor"]
        else:
            break
    return texts


def post_summary(text, dry_run=False):
    if dry_run:
        print("----- DRY RUN: would post to Slack -----")
        print(text)
        print("----------------------------------------")
        return
    _client().chat_postMessage(
        channel=SUMMARY_CHANNEL_ID, text=text, unfurl_links=False)
