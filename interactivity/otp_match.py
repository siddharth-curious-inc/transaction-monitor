"""Find the #otp-bridge OTP a credit-card confirmation should be posted under.

There is no shared id between a #transaction-bridge confirmation and its OTP, so
we match on card last-4 + amount + time proximity, with the strict rules from
CLAUDE.md (tighter than match.link_to_otps, which the scheduled pipeline uses
for a different purpose):

  * only OTPs that fired STRICTLY BEFORE the confirmation count;
  * only within a bounded window (OTP_MATCH_WINDOW_SECONDS, ~30 min);
  * pick the closest one before the confirmation;
  * never reuse an OTP the bot has already replied to (`used_otp_ts`);
  * no candidate -> return None, and the caller posts a standalone prompt.

This is a pure function (no Slack/Sheets I/O) so it's directly unit-testable.
Timestamps are naive IST wall-clock, exactly as parse.py produces them for both
channels, so they're directly comparable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import NEW_AMOUNT_TOLERANCE, OTP_MATCH_WINDOW_SECONDS  # noqa: E402


def find_otp_reply_target(confirmation, otp_candidates, used_otp_ts=frozenset(),
                          window_seconds=OTP_MATCH_WINDOW_SECONDS,
                          tolerance=NEW_AMOUNT_TOLERANCE):
    """Return the Slack ts of the OTP message to reply under, or None.

    `confirmation` and each `otp_candidates` entry are OTP-shaped records
    (card_last4, amount, ts, slack_ts). `used_otp_ts` is the set of OTP ts the
    bot has already replied to (reconstructed from existing prompts)."""
    best, best_gap = None, None
    for o in otp_candidates:
        if not o.slack_ts or o.slack_ts in used_otp_ts:
            continue
        if o.card_last4 != confirmation.card_last4:
            continue
        if abs(o.amount - confirmation.amount) > tolerance:
            continue
        gap = (confirmation.ts - o.ts).total_seconds()
        if gap <= 0 or gap > window_seconds:  # must be strictly before, in-window
            continue
        if best is None or gap < best_gap:    # closest before wins
            best, best_gap = o, gap
    return best.slack_ts if best is not None else None
