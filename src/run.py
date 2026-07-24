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
    ACCOUNT_TO_PAYMENT_METHOD, CUTOVER_DATE, EVENING_GROUP, IST, MORNING_GROUP,
    NEW_AMOUNT_TOLERANCE, PENDING_FLOOR_DATE, PENDING_SHEET_URL, SHIFT_CUTOFF,
    TEST_SENDER_ID, TRANSACTION_CHANNEL_ID, TRANSACTION_FLOOR_DATE)
from match import (as_results, dedup_retries, link_to_otps, match,
                   reconcile_pending)
from parse import parse_message, parse_transaction_message, transaction_sender_id
from sheets import (build_pending_sheet_rows, pending_row_from_result,
                    read_logged_txns, read_pending_sheet, render_pending_rows,
                    write_pending_sheet)
from slack_io import (fetch_bot_prompt_states, fetch_messages_since,
                      fetch_transaction_messages_since, post_summary,
                      team_base_url)


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
    cols = ["Time", "Amount", "Platform / Payee", "Payment method"]
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
        f"🗂 Total still pending (all time): *{total_pending}*\n"
        f"You can view all pending transactions here: "
        f"<{sheet_url}|Unrecorded transactions – Finance Tracker>")]

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


def apply_bot_exclusions(confirmations, bot_states):
    """Mark confirmations that ops voided via the interactivity bot's dropdown.

    `bot_states` maps a #transaction-bridge ts -> the bot prompt's recorded
    state (from fetch_bot_prompt_states). A state of "excluded" flags the
    confirmation just like an :x' on the linked OTP would. OR-only: we never
    unset an exclusion already inherited from an :x:'d OTP via link_to_otps."""
    for o in confirmations:
        st = bot_states.get(o.slack_ts)
        if st and st.get("state") == "excluded":
            o.excluded = True
            if not o.exclude_reason:
                o.exclude_reason = st.get("reason", "")


def run_otp_source(now, dry_run=False, sheet_only=False):
    """LEGACY pipeline: #otp-bridge credit-card OTPs as the source of truth.
    Kept intact (including retry dedup) for runs before CUTOVER_DATE."""
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


def run_transaction_source(now, dry_run=False, sheet_only=False):
    """NEW pipeline: #transaction-bridge bank debit confirmations (cards + UPI)
    as the source of truth. No retry dedup (a confirmation is one settled
    transaction), ±1 amount tolerance, and the pending sheet carries forward
    unresolved pre-cutover rows so nothing is lost across the switch."""
    today = now.date()
    yesterday = today - timedelta(days=1)
    txn_start = datetime.combine(TRANSACTION_FLOOR_DATE, time.min, tzinfo=IST)

    # 1) parse debit confirmations off #transaction-bridge, dropping the
    #    emulator test sender, non-debits, and anything before the floor date.
    raw = fetch_transaction_messages_since(txn_start)
    confirmations, skipped_sender = [], 0
    for msg in raw:
        if transaction_sender_id(msg) == TEST_SENDER_ID:
            skipped_sender += 1
            continue
        o = parse_transaction_message(msg)
        if not o or o.ts.date() < TRANSACTION_FLOOR_DATE:
            continue
        o.slack_ts = msg.get("ts", "")
        confirmations.append(o)

    # 2) ops still react/reply in #otp-bridge, so link each CARD confirmation
    #    to its OTP there and inherit that OTP's :x: exclusion + thread comments.
    otps = []
    for m in fetch_messages_since(txn_start):
        po = parse_message(m["text"])
        if not po:
            continue
        po.excluded = m["excluded"]
        po.exclude_reason = m["reason"]
        po.comments = m["comments"]
        po.slack_ts = m["ts"]
        otps.append(po)
    link_to_otps(confirmations, otps, tolerance=NEW_AMOUNT_TOLERANCE)

    # 2b) fold in exclusions ops made via the interactivity bot's dropdown. That
    #     bot records an exclusion as state=excluded in its own prompt's Slack
    #     metadata (keyed by the #transaction-bridge ts); this supersedes the
    #     :x: reaction for NEW transactions. We OR it on top of any :x:-inherited
    #     exclusion from link_to_otps -- never unset -- so a bot-voided txn drops
    #     from pending just like an :x:'d one. (The legacy :x: path above still
    #     runs for old #otp-bridge OTPs, per CLAUDE.md.) Best-effort: a failure
    #     reading bot metadata must never crash the roundup.
    try:
        bot_states = fetch_bot_prompt_states(txn_start)
    except Exception as e:  # noqa: BLE001
        bot_states = {}
        print(f"[bot] WARNING: could not read bot prompt states: {e}")
    apply_bot_exclusions(confirmations, bot_states)

    active = [o for o in confirmations if not o.excluded]
    excluded = [o for o in confirmations if o.excluded]

    # 3) match active confirmations against the tracker. Read logged rows from
    #    PENDING_FLOOR_DATE (not the txn floor) so carry-forward reconciliation
    #    can still resolve old pendings dated before 13 Jul.
    logged = read_logged_txns(PENDING_FLOOR_DATE, today)
    added, pending = match(active, logged, tolerance=NEW_AMOUNT_TOLERANCE,
                           payment_method_map=ACCOUNT_TO_PAYMENT_METHOD)

    # 4) carry forward unresolved pre-cutover rows; dedupe overlap with freshly
    #    derived rows (prefer the new row for its current link + linked comments).
    base_url = team_base_url()
    new_rows = [pending_row_from_result(m, base_url, TRANSACTION_CHANNEL_ID)
                for m in pending]
    try:
        carried = read_pending_sheet()
    except Exception as e:  # noqa: BLE001 - carry-forward is best-effort
        carried = []
        print(f"[sheet] WARNING: could not read pending sheet for "
              f"carry-forward: {e}")
    still_old = reconcile_pending(carried, logged, tolerance=NEW_AMOUNT_TOLERANCE)
    # Drop carried rows that the new source now covers: either re-derived as a
    # fresh pending, or voided by ops (excluded). Both cases would otherwise
    # linger as stale duplicates in the overlap window. (Now-logged carried rows
    # are already dropped by reconcile_pending against the household tabs.)
    def _key(dt, pm, amt):
        return (dt, pm, round(amt, 2))
    drop_keys = {_key(r.date, r.payment_method, r.amount) for r in new_rows}
    drop_keys |= {_key(o.ts.date(), ACCOUNT_TO_PAYMENT_METHOD.get(o.card_last4),
                       o.amount) for o in excluded}
    carried_kept = [r for r in still_old
                    if _key(r.date, r.payment_method, r.amount) not in drop_keys]
    merged = new_rows + carried_kept
    sheet_rows = render_pending_rows(merged)

    added_today = [m for m in added if m.otp.ts.date() == today]
    pending_today = [m for m in pending if m.otp.ts.date() == today]
    pending_yesterday = [m for m in pending if m.otp.ts.date() == yesterday]
    excluded_today = as_results(
        [o for o in excluded if o.ts.date() == today],
        payment_method_map=ACCOUNT_TO_PAYMENT_METHOD)
    detected_today = sum(1 for o in confirmations if o.ts.date() == today)

    if dry_run:
        print(f"[diag] transaction-bridge messages fetched since "
              f"{txn_start:%d-%b-%Y}: {len(raw)} "
              f"(test-sender skipped: {skipped_sender})")
        print(f"[diag] parsed as debit confirmations: {len(confirmations)} "
              f"(excluded via linked OTP: {len(excluded)})")
        print(f"[diag] logged rows {PENDING_FLOOR_DATE:%d-%b} to {today:%d-%b}: "
              f"{len(logged)}")
        print(f"[diag] new pending: {len(new_rows)}  carried-forward kept: "
              f"{len(carried_kept)}  total pending: {len(merged)}")
        print("----- DRY RUN: would overwrite the pending sheet with -----")
        for r in sheet_rows:
            print(" | ".join(r))
        print("-----------------------------------------------------------")
    else:
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
        excluded_today, len(merged), PENDING_SHEET_URL, now)
    post_summary(main_msg, reply, dry_run=dry_run)


def main(dry_run=False, sheet_only=False, source=None):
    """Dispatch to the active source of truth. `source` forces a pipeline
    ('otp' or 'transaction') for testing; by default it's decided from the IST
    date against CUTOVER_DATE, so the switch happens automatically on the day."""
    now = datetime.now(IST)
    if source is None:
        source = "transaction" if now.date() >= CUTOVER_DATE else "otp"
    if source == "transaction":
        run_transaction_source(now, dry_run=dry_run, sheet_only=sheet_only)
    else:
        run_otp_source(now, dry_run=dry_run, sheet_only=sheet_only)


if __name__ == "__main__":
    _dry = "--dry-run" in sys.argv
    # --dry-run wins if both are passed, so a dry run never has side effects.
    _sheet_only = "--sheet-only" in sys.argv and not _dry
    _source = next((a.split("=", 1)[1] for a in sys.argv[1:]
                    if a.startswith("--source=")), None)
    main(dry_run=_dry, sheet_only=_sheet_only, source=_source)
