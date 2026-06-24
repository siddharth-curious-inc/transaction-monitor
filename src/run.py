"""Entry point. Run:  python src/run.py [--dry-run]"""
import sys
from datetime import datetime, timedelta
from itertools import groupby

from config import IST, PENDING_LOOKBACK_DAYS
from match import dedup_retries, match
from parse import parse_message
from sheets import read_logged_txns
from slack_io import fetch_messages_since, post_summary


def _header(text):
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


_DIVIDER = {"type": "divider"}


def _bullets(results, with_household=False):
    return _section("\n".join(f"• {_fmt(m, with_household)}" for m in results))


def _fmt(mr, with_household=False):
    o = mr.otp
    base = f"₹{o.amount:,.2f} · {mr.platform} · {mr.payment_method} · {o.ts:%H:%M}"
    if with_household and mr.logged is not None:
        base += f" → {mr.logged.household}"
    return base


def _ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _date_heading(d):
    return f"{_ordinal(d.day)} {d:%B}"


def compose(detected, added, pending_today, pending_prev, when):
    """Build the Block Kit payloads. Returns (main, reply) where each is a
    (blocks, fallback_text) tuple; `reply` is None when nothing was logged.
    The logged list is posted as a thread reply to keep channel-level focus
    on what is still pending."""
    blocks = [
        _header("📊 Credit Card (OTP) → Tracker Roundup"),
        _context(f"{when:%d %b %Y, %-I:%M %p}"),
        _section(
            f"Transactions detected since 00:00 today: *{detected}* (retries deduplicated)\n"
            f"✅ Logged in Finances Tracker: *{len(added)}*\n"
            f"⚠️ Pending (not yet logged): *{len(pending_today)}*"),
        _DIVIDER,
        _section("*⚠️ Pending - Today*"),
    ]
    if pending_today:
        blocks.append(_bullets(pending_today))
    else:
        blocks.append(_context("_Nothing pending - everything today is logged._"))

    if pending_prev:
        blocks += [_DIVIDER, _section("*🚨 Pending - Previous Dates*")]
        # newest date first; within a date keep chronological order
        by_day = sorted(pending_prev, key=lambda m: m.otp.ts, reverse=True)
        for day, group in groupby(by_day, key=lambda m: m.otp.ts.date()):
            items = sorted(group, key=lambda m: m.otp.ts)
            blocks.append(_context(f"*{_date_heading(day)}*"))
            blocks.append(_bullets(items))

    main_text = (f"OTP → Tracker Roundup: {len(pending_today)} pending today, "
                 f"{len(pending_prev)} pending from previous dates")
    main = (blocks, main_text)

    reply = None
    if added:
        reply_blocks = [_section("*✅ Logged*"), _bullets(added, with_household=True)]
        reply = (reply_blocks, f"Logged {len(added)} transaction(s) in the tracker")
    return main, reply


def main(dry_run=False):
    now = datetime.now(IST)
    today = now.date()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=PENDING_LOOKBACK_DAYS)

    raw = fetch_messages_since(start)
    parsed = [o for o in (parse_message(t) for t in raw) if o]
    otps = dedup_retries(parsed)

    logged = read_logged_txns(start.date(), today)
    added, pending = match(otps, logged)

    added_today = [m for m in added if m.otp.ts.date() == today]
    pending_today = [m for m in pending if m.otp.ts.date() == today]
    pending_prev = [m for m in pending if m.otp.ts.date() < today]
    detected_today = sum(1 for o in otps if o.ts.date() == today)

    if dry_run:
        print(f"[diag] slack messages fetched since {start:%d-%b-%Y}: {len(raw)}")
        print(f"[diag] parsed as OTPs: {len(parsed)}  "
              f"(after retry-dedup: {len(otps)})")
        print(f"[diag] logged rows {start:%d-%b} to {today:%d-%b} across "
              f"household tabs: {len(logged)}")

    main_msg, reply = compose(
        detected_today, added_today, pending_today, pending_prev, now)
    post_summary(main_msg, reply, dry_run=dry_run)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
