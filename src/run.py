"""Entry point.

Run modes:
  python src/run.py                # live: overwrite pending sheet + post to Slack
  python src/run.py --dry-run      # no side effects: print the Slack message and
                                   #   the pending-sheet rows that would be written
  python src/run.py --sheet-only   # overwrite pending sheet only; do NOT post to Slack
"""
import sys
from datetime import datetime, time, timedelta

from config import (
    EVENING_GROUP, IST, MORNING_GROUP, PENDING_FLOOR_DATE,
    PENDING_SHEET_URL, SHIFT_CUTOFF)
from match import as_results, dedup_retries, match
from parse import parse_message
from sheets import (build_pending_sheet_rows, read_logged_txns,
                    write_pending_sheet)
from slack_io import fetch_messages_since, post_summary, team_base_url


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


def _txn_table(results, with_household=False, with_reason=False, with_comments=False):
    """A Block Kit table block. Columns: Time | Amount | Platform | Card used,
    plus a 'Logged for' household column for the logged list, a 'Reason'
    column (the ops void note) for the excluded list, or a 'Comments' column
    (every threaded reply, e.g. ops' household note) for the pending lists."""
    cols = ["Time", "Amount", "Platform", "Card used"]
    if with_household:
        cols.append("Logged for")
    if with_reason:
        cols.append("Reason")
    if with_comments:
        cols.append("Comments")
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
        if with_comments:
            row.append(_cell(o.comments or "--"))
        rows.append(row)
    # right-align the Amount column (index 1); leave the rest default-left.
    # Slack requires every column_settings entry to be an object, so the
    # default-styled columns use an empty object ({}) rather than null.
    settings = [{}, {"align": "right"}] + [{} for _ in cols[2:]]
    return {"type": "table", "rows": rows, "column_settings": settings}


def _on_shift_group(when):
    """Slack user-group mention for whoever's on shift at `when` (IST).
    Runs before the cutoff ping the morning group; everything later in the day
    pings the evening group. Decided from the clock so it stays correct even if
    a scheduled run fires off-time."""
    group_id, handle = MORNING_GROUP if when.time() < SHIFT_CUTOFF else EVENING_GROUP
    return f"<!subteam^{group_id}|{handle}>"


def compose(detected, added, pending_today, pending_yesterday, excluded,
            total_pending, sheet_url, when):
    """Build the Block Kit payloads. Returns (main, reply) where each is a
    (blocks, fallback_text) tuple; `reply` is None when there's nothing logged
    or excluded to detail. The logged/excluded lists are posted as a thread
    reply to keep channel-level focus on what is still pending.

    The main message shows only Today + Yesterday pending; the full backlog
    (`total_pending` rows) lives on the pending sheet, linked via `sheet_url`."""
    on_shift = _on_shift_group(when)
    blocks = [
        _header("📊 Credit Card (OTP) → Tracker Roundup"),
        # %-I (no-leading-zero hour) isn't portable to Windows, so build the
        # 12-hour clock by hand to keep dry-runs working everywhere.
        _context(f"{when:%d %b %Y}, {when.hour % 12 or 12}:{when:%M %p}"),
        _section(
            f"Transactions detected since 00:00 today: *{detected}* (retries deduplicated)\n"
            f"✅ Logged in Finances Tracker: *{len(added)}*\n"
            f"⚠️ Pending today (not yet logged): *{len(pending_today)}*\n"
            f"🗂 Total still pending (all dates): *{total_pending}*\n"
            f"🚫 Excluded by ops: *{len(excluded)}*\n"
            f"On shift: {on_shift}"),
        _DIVIDER,
        _section("*⚠️ Pending - Today*"),
    ]
    if pending_today:
        blocks.append(_txn_table(pending_today, with_comments=True))
    else:
        blocks.append(_context("_Nothing pending - everything today is logged._"))

    blocks += [_DIVIDER, _section("*🚨 Pending - Yesterday*")]
    if pending_yesterday:
        items = sorted(pending_yesterday, key=lambda m: m.otp.ts)
        blocks.append(_txn_table(items, with_comments=True))
    else:
        blocks.append(_context("_Nothing pending from yesterday._"))

    blocks += [_DIVIDER, _section(
        f"🗂 To view *all* pending transactions, <{sheet_url}|click here> "
        f"(the pending tab on the Finances Tracker, refreshed every run).")]

    main_text = (f"OTP → Tracker Roundup: {len(pending_today)} pending today, "
                 f"{len(pending_yesterday)} pending yesterday, "
                 f"{total_pending} total pending — {on_shift}")
    main = (blocks, main_text)

    reply_blocks = []
    if added:
        reply_blocks += [_section(f"*✅ Logged today ({when:%d %b %Y})*"),
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


def main(dry_run=False, sheet_only=False):
    now = datetime.now(IST)
    today = now.date()
    yesterday = today - timedelta(days=1)
    # Read the full backlog since the floor date: the pending sheet holds
    # everything, and Slack shows only today + yesterday out of it.
    start = datetime.combine(PENDING_FLOOR_DATE, time.min, tzinfo=IST)

    raw = fetch_messages_since(start)
    parsed = []
    for msg in raw:
        o = parse_message(msg["text"])
        if not o:
            continue
        o.excluded = msg["excluded"]
        o.exclude_reason = msg["reason"]
        o.comments = msg["comments"]
        o.slack_ts = msg["ts"]
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
    pending_yesterday = [m for m in pending if m.otp.ts.date() == yesterday]
    excluded_today = as_results([o for o in excluded if o.ts.date() == today])
    detected_today = sum(1 for o in otps if o.ts.date() == today)

    # Full pending backlog -> the pending sheet (with source-message links).
    base_url = team_base_url()
    sheet_rows = build_pending_sheet_rows(pending, base_url)

    if dry_run:
        print(f"[diag] slack messages fetched since {start:%d-%b-%Y}: {len(raw)}")
        print(f"[diag] parsed as OTPs: {len(parsed)}  "
              f"(after retry-dedup: {len(otps)}, excluded by ops: {len(excluded)})")
        print(f"[diag] logged rows {start:%d-%b} to {today:%d-%b} across "
              f"household tabs: {len(logged)}")
        print(f"[diag] total pending (all dates): {len(pending)}")
        print("----- DRY RUN: would overwrite the pending sheet with -----")
        for r in sheet_rows:
            print(" | ".join(r))
        print("-----------------------------------------------------------")
    else:
        # live and sheet-only both overwrite the sheet; a Sheets failure is
        # logged but never blocks the Slack post (the link is static anyway).
        try:
            write_pending_sheet(sheet_rows)
            print(f"[sheet] overwrote pending tab with {len(sheet_rows) - 1} row(s)")
        except Exception as e:  # noqa: BLE001 - surface, don't crash the run
            print(f"[sheet] WARNING: pending-sheet write failed: {e}")

    if sheet_only:
        print("[mode] sheet-only: not posting to Slack")
        return

    main_msg, reply = compose(
        detected_today, added_today, pending_today, pending_yesterday,
        excluded_today, len(pending), PENDING_SHEET_URL, now)
    post_summary(main_msg, reply, dry_run=dry_run)


if __name__ == "__main__":
    _dry = "--dry-run" in sys.argv
    # --dry-run wins if both are passed, so a dry run never has side effects.
    _sheet_only = "--sheet-only" in sys.argv and not _dry
    main(dry_run=_dry, sheet_only=_sheet_only)
