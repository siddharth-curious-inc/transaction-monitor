"""Detect new #transaction-bridge confirmations and post an interactive prompt
for each. Runs as a background thread inside the always-on bot.

We poll (not the Events API) so a missed cycle self-heals: the lookback window
is wider than the interval, and a transaction that already has a prompt is never
prompted again. "Already prompted" is reconstructed from the bot's own prompts
in #otp-bridge (their metadata carries the originating txn_ts), so the state
survives a restart with no external store; an in-memory set covers the brief
window before a just-posted prompt is visible to the next history read.
"""
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import blocks  # noqa: E402
from config import (BOT_START_LOOKBACK_SECONDS, IST, OTP_CHANNEL_ID,  # noqa: E402
                    POLL_INTERVAL_SECONDS, POLL_LOOKBACK_SECONDS, TEST_SENDER_ID)
from households import get_households  # noqa: E402
from otp_match import find_otp_reply_target  # noqa: E402
from parse import (parse_message, parse_transaction_message,  # noqa: E402
                   transaction_sender_id)
from service import derive_fields  # noqa: E402
from slack_io import (fetch_bot_prompt_states, fetch_messages_since,  # noqa: E402
                      fetch_transaction_messages_since)


def _confirmations_since(start):
    """Parsed debit confirmations in the window, newest-relevant first is not
    required; test-sender and non-debits are dropped (same rules as the
    pipeline)."""
    out = []
    for msg in fetch_transaction_messages_since(start):
        if transaction_sender_id(msg) == TEST_SENDER_ID:
            continue
        otp = parse_transaction_message(msg)
        if otp is None:
            continue
        otp.slack_ts = msg.get("ts", "")
        if otp.slack_ts:
            out.append(otp)
    return out


def _otp_candidates_since(start):
    out = []
    for m in fetch_messages_since(start):
        o = parse_message(m["text"])
        if o is None:
            continue
        o.slack_ts = m["ts"]
        out.append(o)
    return out


def poll_once(client, seen, lookback_seconds=POLL_LOOKBACK_SECONDS):
    """One poll cycle. `seen` is an in-memory set of already-prompted txn_ts,
    mutated in place. Returns the number of prompts posted this cycle."""
    start = datetime.now(IST) - timedelta(seconds=lookback_seconds)

    prompt_states = fetch_bot_prompt_states(start)
    prompted = set(prompt_states) | seen
    used_otp_ts = {s["otp_parent_ts"] for s in prompt_states.values()
                   if s.get("otp_parent_ts")}

    confirmations = _confirmations_since(start)
    to_post = [c for c in confirmations if c.slack_ts not in prompted]
    if not to_post:
        return 0

    otp_candidates = _otp_candidates_since(start)
    households = get_households()
    posted = 0
    for otp in to_post:
        rail_kind, payment_method, platform = derive_fields(otp)
        parent = None
        if rail_kind == "cc":
            parent = find_otp_reply_target(otp, otp_candidates, used_otp_ts)
        bk = blocks.prompt_blocks(
            otp.amount, payment_method, platform, otp.ts, rail_kind,
            households, otp.slack_ts, parent or "")
        text = f"New transaction to categorise: ₹{otp.amount:,.2f} {platform}"
        kwargs = dict(channel=OTP_CHANNEL_ID, text=text, blocks=bk,
                      metadata=blocks.prompt_metadata(
                          otp.slack_ts, "pending", otp_parent_ts=parent or ""))
        if parent:
            kwargs["thread_ts"] = parent
        client.chat_postMessage(**kwargs)
        seen.add(otp.slack_ts)
        if parent:
            used_otp_ts.add(parent)  # one prompt per OTP within the cycle
        posted += 1
    return posted


def run_poll_loop(client):
    seen = set()
    first = True
    while True:
        try:
            # A wider look-back on the first cycle after (re)start backfills any
            # confirmations missed while down; steady state uses the small
            # self-healing window.
            lookback = (BOT_START_LOOKBACK_SECONDS if first
                        else POLL_LOOKBACK_SECONDS)
            n = poll_once(client, seen, lookback)
            first = False
            if n:
                print(f"[poll] posted {n} prompt(s)")
        except Exception as e:  # noqa: BLE001 - a bad cycle must not kill the loop
            print(f"[poll] WARNING: cycle failed: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)
