"""Entry point. Run:  python src/run.py [--dry-run]"""
import sys
from datetime import datetime, time, timedelta
from itertools import groupby

from config import (
    EVENING_GROUP, IST, MORNING_GROUP, PENDING_FLOOR_DATE,
    PENDING_LOOKBACK_DAYS, SHIFT_CUTOFF)
from match import as_results, dedup_retries, match
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


def _cell(text):
    # Slack rejects empty table cells ("must be more than 0 characters"), so a
    # blank (an :x: with no reason, or an unmapped card/platform) renders as an
    # em dash instead of crashing the whole chat.postMessage with invalid_blocks.
    return {"type": "raw_text", "text": text if text else "—"}


def _txn_table(results, with_household=False, with_reason=False):
    """A Block Kit table block. Columns: Time | Amount | Platform | Card used,
    plus a 'Logged for' household column for the logged list, or a 'Reason'
    column (the ops void note) for the excluded list."""
    cols = ["Time", "Amount", "Platform", "Card used"]
    if with_household:
        cols.append("Logged for")
    if with_reason:
        cols.append("Reason")
    rows = [[_cell(c) for c in cols]]
    for m in results:
        o = m.otp
        row = [
            _cell(f"{o.ts:%H:%M}"),
            _cell(f"₹{o.amount:,.2f}"),
            _cell(m.platform),
            _cell(m.payment_method),
        ]
        if with_household:
            row.append(_cell(m.logged.household if m.logged is not None else "—"))
        if with_reason:
            # left blank when ops X'd without bothering to explain
            row.append(_cell(o.exclude_reason))
        rows.append(row)
    # right-align the Amount column (index 1); leave the rest default-left.
    # Slack requires every column_settings entry to be an object, so the
    # default-styled columns use an empty object ({}) rather than null.
    settings = [{}, {"align": "right"}] + [{} for _ in cols[2:]]
    return {"type": "table", "rows": rows, "column_settings": settings}


def _ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _date_heading(d):
    return f"{_ordinal(d.day)} {d:%B}"


def _on_shift_group(when):
    """Slack user-group mention for whoever's on shift at `when` (IST).
    Runs before the cutoff ping the morning group; everything later in the day
    pings the evening group. Decided from the clock so it stays correct even if
    a scheduled run fires off-time."""
    group_id, handle = MORNING_GROUP if when.time() < SHIFT_CUTOFF else EVENING_GROUP
    return f"<!subteam^{group_id}|{handle}>"


def compose(detected, added, pending_today, pending_prev, excluded, when):
    """Build the Block Kit payloads. Returns (main, reply) where each is a
    (blocks, fallback_text) tuple; `reply` is None when there's nothing logged
    or excluded to detail. The logged/excluded lists are posted as a thread
    reply to keep channel-level focus on what is still pending."""
    on_shift = _on_shift_group(when)
    blocks = [
        _header("📊 Credit Card (OTP) → Tracker Roundup"),
        # %-I (no-leading-zero hour) isn't portable to Windows, so build the
        # 12-hour clock by hand to keep dry-runs working everywhere.
        _context(f"{when:%d %b %Y}, {when.hour % 12 or 12}:{when:%M %p}"),
        _section(
            f"Transactions detected since 00:00 today: *{detected}* (retries deduplicated)\n"
            f"✅ Logged in Finances Tracker: *{len(added)}*\n"
            f"⚠️ Pending (not yet logged): *{len(pending_today)}*\n"
            f"🚫 Excluded by ops: *{len(excluded)}*\n"
            f"On shift: {on_shift}"),
        _DIVIDER,
        _section("*⚠️ Pending - Today*"),
    ]
    if pending_today:
        blocks.append(_txn_table(pending_today))
    else:
        blocks.append(_context("_Nothing pending - everything today is logged._"))

    if pending_prev:
        blocks += [_DIVIDER, _section("*🚨 Pending - Previous Dates*")]
        # newest date first; within a date keep chronological order
        by_day = sorted(pending_prev, key=lambda m: m.otp.ts, reverse=True)
        for day, group in groupby(by_day, key=lambda m: m.otp.ts.date()):
            items = sorted(group, key=lambda m: m.otp.ts)
            blocks.append(_context(f"*{_date_heading(day)}*"))
            blocks.append(_txn_table(items))

    main_text = (f"OTP → Tracker Roundup: {len(pending_today)} pending today, "
                 f"{len(pending_prev)} pending from previous dates — {on_shift}")
    main = (blocks, main_text)

    reply_blocks = []
    if added:
        reply_blocks += [_section("*✅ Logged*"),
                         _txn_table(added, with_household=True)]
    if excluded:
        if reply_blocks:
            reply_blocks.append(_DIVIDER)
        reply_blocks += [_section("*🚫 Excluded by ops*"),
                         _txn_table(excluded, with_reason=True)]

    reply = None
    if reply_blocks:
        reply_text = (f"Logged {len(added)} transaction(s) in the tracker; "
                      f"{len(excluded)} excluded by ops")
        reply = (reply_blocks, reply_text)
    return main, reply


def main(dry_run=False):
    now = datetime.now(IST)
    today = now.date()
    # rolling lookback, but never earlier than the configured floor date
    start_date = max(today - timedelta(days=PENDING_LOOKBACK_DAYS), PENDING_FLOOR_DATE)
    start = datetime.combine(start_date, time.min, tzinfo=IST)

    raw = fetch_messages_since(start)
    parsed = []
    for msg in raw:
        o = parse_message(msg["text"])
        if not o:
            continue
        o.excluded = msg["excluded"]
        o.exclude_reason = msg["reason"]
        parsed.append(o)
    otps = dedup_retries(parsed)

    # OTPs ops voided with :x: are reported separately and never matched, so
    # they can't surface as pending (today or on previous dates).
    active = [o for o in otps if not o.excluded]
    excluded = [o for o in otps if o.excluded]

    logged = read_logged_txns(start.date(), today)
    added, pending = match(active, logged)

    added_today = [m for m in added if m.otp.ts.date() == today]
    pending_today = [m for m in pending if m.otp.ts.date() == today]
    pending_prev = [m for m in pending if m.otp.ts.date() < today]
    excluded_today = as_results([o for o in excluded if o.ts.date() == today])
    detected_today = sum(1 for o in otps if o.ts.date() == today)

    if dry_run:
        print(f"[diag] slack messages fetched since {start:%d-%b-%Y}: {len(raw)}")
        print(f"[diag] parsed as OTPs: {len(parsed)}  "
              f"(after retry-dedup: {len(otps)}, excluded by ops: {len(excluded)})")
        print(f"[diag] logged rows {start:%d-%b} to {today:%d-%b} across "
              f"household tabs: {len(logged)}")

    main_msg, reply = compose(
        detected_today, added_today, pending_today, pending_prev,
        excluded_today, now)
    post_summary(main_msg, reply, dry_run=dry_run)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
