"""Shared logic between the poller and the interaction handlers: derive the
display/write fields for a transaction, re-load a #transaction-bridge message
from its ts, and perform the two terminal actions (log a household row / record
an exclusion) including the Slack message update and the top-level reaction.

Kept separate from handlers.py so the ack()-then-work handlers stay thin, and so
the write path is exercised the same way whether the household came from the
in-message dropdown or the remark modal.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import blocks  # noqa: E402
from config import (ACCOUNT_TO_PAYMENT_METHOD, DRY_RUN, OTP_LINKED_CARDS,  # noqa: E402
                    PROMPT_REACTION, TRANSACTION_CHANNEL_ID)
from match import aliased_platform  # noqa: E402
from parse import parse_transaction_message  # noqa: E402
from sheets import append_household_row  # noqa: E402


def derive_fields(otp):
    """(rail_kind, payment_method, platform) for a parsed confirmation.
    rail_kind is 'cc' for OTP-linked cards, else 'upi'."""
    payment_method = ACCOUNT_TO_PAYMENT_METHOD.get(otp.card_last4, "")
    platform = aliased_platform(otp)
    rail_kind = "cc" if otp.card_last4 in OTP_LINKED_CARDS else "upi"
    return rail_kind, payment_method, platform


def load_txn(client, txn_ts):
    """Re-fetch the #transaction-bridge message by ts and re-parse it, so the
    sheet write is driven by the same parser that produced the prompt (no drift).
    Returns the OTP (with slack_ts set) or None if it can't be found/parsed."""
    resp = client.conversations_history(
        channel=TRANSACTION_CHANNEL_ID, latest=txn_ts, oldest=txn_ts,
        inclusive=True, limit=1)
    msgs = resp.get("messages", [])
    if not msgs:
        return None
    otp = parse_transaction_message(msgs[0])
    if otp is None:
        return None
    otp.slack_ts = txn_ts
    return otp


def _react_top_level(client, channel, otp_parent_ts, prompt_ts):
    """Add the ✅ reaction to the TOP-LEVEL message so ops see resolution at a
    glance: the OTP parent for a threaded CC prompt, else the prompt itself."""
    from slack_io import add_reaction
    add_reaction(channel, otp_parent_ts or prompt_ts, PROMPT_REACTION)


def log_household(client, otp, ref, prompt_channel, prompt_ts, household,
                  user_id, remark=""):
    """Append the household row, then update the prompt to ✅ and react on the
    top-level message. On write failure, update the prompt to a visible error
    and re-raise so it's logged. `ref` is the parsed block ref (txn/otp coords)."""
    rail_kind, payment_method, platform = derive_fields(otp)

    if DRY_RUN:
        print(f"[dry-run] would append to {household!r}: "
              f"{otp.ts:%d-%b-%Y} | {platform} | {otp.amount} | "
              f"{payment_method} | remark={remark!r}")
    else:
        try:
            append_household_row(household, otp.ts.date(), platform, otp.amount,
                                 payment_method, remark)
        except Exception as e:  # noqa: BLE001 - surface to ops, never silent
            client.chat_update(
                channel=prompt_channel, ts=prompt_ts,
                text="Logging failed",
                blocks=blocks.error_blocks(
                    otp.amount, payment_method, platform, otp.ts, rail_kind,
                    f"Couldn't log to {household}: {e}. Try again."),
                metadata=blocks.prompt_metadata(
                    ref["t"], "pending", otp_parent_ts=ref["p"]))
            raise

    client.chat_update(
        channel=prompt_channel, ts=prompt_ts,
        text=f"Logged to {household}",
        blocks=blocks.resolved_blocks(
            otp.amount, payment_method, platform, otp.ts, rail_kind,
            household, user_id, remark),
        metadata=blocks.prompt_metadata(
            ref["t"], "logged", household=household, otp_parent_ts=ref["p"]))
    _react_top_level(client, prompt_channel, ref["p"], prompt_ts)


def exclude(client, otp, ref, prompt_channel, prompt_ts, user_id, reason=""):
    """Record an exclusion: update the prompt to 🚫 with state=excluded in the
    metadata (the record the scheduled pipeline reads to drop it from pending)."""
    rail_kind, payment_method, platform = derive_fields(otp)
    if DRY_RUN:
        print(f"[dry-run] would exclude txn {ref['t']} ({payment_method} "
              f"₹{otp.amount})")
    client.chat_update(
        channel=prompt_channel, ts=prompt_ts,
        text="Excluded",
        blocks=blocks.excluded_blocks(
            otp.amount, payment_method, platform, otp.ts, rail_kind, user_id,
            reason),
        metadata=blocks.prompt_metadata(
            ref["t"], "excluded", reason=reason, otp_parent_ts=ref["p"]))
