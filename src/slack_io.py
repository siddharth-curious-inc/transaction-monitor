"""Slack reads and writes via slack_sdk."""
import html

from slack_sdk import WebClient
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from config import (EXCLUDE_REACTION, OTP_CHANNEL_ID, SLACK_BOT_TOKEN,
                    SUMMARY_CHANNEL_ID)


def _client():
    # Reading the full backlog since the floor date makes a conversations.replies
    # call per threaded message, which on a large backlog trips Slack's Tier-3
    # rate limit (429 'ratelimited'). This handler waits out the server's
    # Retry-After and retries the call instead of crashing the whole run.
    client = WebClient(token=SLACK_BOT_TOKEN)
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    return client


def team_base_url():
    """Workspace base URL (e.g. 'https://curious.slack.com/'), fetched once per
    run via auth.test. Used to build OTP message permalinks locally so we don't
    make a chat.getPermalink call per pending row. Returns '' if unavailable."""
    try:
        url = _client().auth_test().get("url", "")
    except Exception:
        return ""
    return url if url.endswith("/") else url + "/"


def permalink(base_url, ts):
    """Deep link to an #otp-bridge message from its Slack `ts`. Slack archive
    links use the ts with the dot removed, prefixed with 'p'. Returns '' when
    the base URL or ts is missing."""
    if not base_url or not ts:
        return ""
    return f"{base_url}archives/{OTP_CHANNEL_ID}/p{ts.replace('.', '')}"


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


def _has_exclude_reaction(msg):
    """True if anyone reacted to the message with the :x: void emoji."""
    for r in msg.get("reactions", []) or []:
        if r.get("name") == EXCLUDE_REACTION:
            return True
    return False


def _reply_text(msg):
    """Thread reply body. Prefer the top-level ``text`` field so we don't
    repeat the same content when Slack also mirrors it in Block Kit blocks."""
    text = (msg.get("text") or "").strip()
    if not text:
        text = _full_text(msg).strip()
    return html.unescape(text)


def _thread_replies(client, ts):
    """All human reply texts in the thread, oldest first. Bot mirrors are
    skipped so only ops' own notes count."""
    resp = client.conversations_replies(channel=OTP_CHANNEL_ID, ts=ts, limit=20)
    # messages[0] is the OTP message itself; later entries are the replies.
    out = []
    for m in resp.get("messages", [])[1:]:
        if m.get("bot_id") or m.get("subtype") == "bot_message":
            continue  # only a human's note counts
        text = _reply_text(m)
        if text:
            out.append(text)
    return out


def fetch_messages_since(start):
    """Return the OTP messages posted at/after `start` as a list of dicts:
    ``{"text", "ts", "excluded", "reason", "comments"}``. ``excluded`` is True
    when ops reacted with :x:; ``reason`` is the first threaded reply, used as
    the void explanation (or "" when excluded without one); ``comments`` is
    every threaded reply joined together (ops' recon notes, e.g. which
    household a payment was for), or "" when the thread has none."""
    oldest = start.timestamp()

    client = _client()
    messages, cursor = [], None
    while True:
        resp = client.conversations_history(
            channel=OTP_CHANNEL_ID, oldest=str(oldest),
            limit=200, cursor=cursor)
        for m in resp.get("messages", []):
            excluded = _has_exclude_reaction(m)
            replies = []
            if (m.get("reply_count") or 0) > 0:
                replies = _thread_replies(client, m["ts"])
            messages.append({
                "text": _full_text(m),
                "ts": m.get("ts", ""),
                "excluded": excluded,
                "reason": replies[0] if excluded and replies else "",
                "comments": "; ".join(replies),
            })
        if resp.get("has_more"):
            cursor = resp["response_metadata"]["next_cursor"]
        else:
            break
    return messages


def _cell_text(cell):
    if not cell:
        return ""
    ct = cell.get("type")
    if ct == "raw_text":
        return cell.get("text", "")
    if ct == "raw_number":
        return str(cell.get("number", ""))
    if ct == "rich_text":
        return _text_from_blocks([cell])
    return ""


def _blocks_to_text(blocks):
    """Flatten Block Kit blocks into readable text for dry-run / logs."""
    out = []
    for b in blocks:
        t = b.get("type")
        if t == "divider":
            out.append("─" * 40)
        elif t in ("header", "section"):
            out.append(b["text"]["text"])
        elif t == "context":
            out.append(" ".join(e["text"] for e in b["elements"]))
        elif t == "table":
            for row in b.get("rows", []):
                out.append(" | ".join(_cell_text(c) for c in row))
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
