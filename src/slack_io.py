"""Slack reads and writes via slack_sdk."""
from slack_sdk import WebClient

from config import OTP_CHANNEL_ID, SLACK_BOT_TOKEN, SUMMARY_CHANNEL_ID


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


def fetch_messages_since(start):
    """Return raw OTP message strings posted at/after the `start` datetime."""
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


def _blocks_to_text(blocks):
    """Flatten Block Kit blocks into readable text for dry-run / logs."""
    out = []
    for b in blocks:
        t = b.get("type")
        if t == "divider":
            out.append("─" * 40)
        elif t == "header":
            out.append(b["text"]["text"])
        elif t == "section":
            out.append(b["text"]["text"])
        elif t == "context":
            out.append(" ".join(e["text"] for e in b["elements"]))
    return "\n".join(out)


def post_summary(main, reply=None, dry_run=False):
    """`main` and `reply` are (blocks, fallback_text) tuples; `reply` may be None."""
    main_blocks, main_text = main
    if dry_run:
        print("----- DRY RUN: would post to Slack -----")
        print(_blocks_to_text(main_blocks))
        if reply:
            print("----- DRY RUN: would post as a threaded reply -----")
            print(_blocks_to_text(reply[0]))
        print("----------------------------------------")
        return
    client = _client()
    resp = client.chat_postMessage(
        channel=SUMMARY_CHANNEL_ID, text=main_text, blocks=main_blocks,
        unfurl_links=False)
    if reply:
        reply_blocks, reply_text = reply
        client.chat_postMessage(
            channel=SUMMARY_CHANNEL_ID, text=reply_text, blocks=reply_blocks,
            thread_ts=resp["ts"], unfurl_links=False)
