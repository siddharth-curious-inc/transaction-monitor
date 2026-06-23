"""Retry de-duplication and OTP <-> logged-row matching.

Match key (locked):  Date  +  Payment method  +  Amount (+/- tolerance).
Platform is a TIE-BREAKER only, never a hard requirement.
Rows are consumed greedily one-to-one so a single logged row can't satisfy
two OTPs and two OTPs can't both claim one row.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from config import (AMOUNT_TOLERANCE, CARD_TO_PAYMENT_METHOD,
                    DEDUP_WINDOW_SECONDS, MERCHANT_ALIAS)


@dataclass
class LoggedTxn:
    household: str
    date: date
    platform: str
    amount: float
    payment_method: str
    row: int
    consumed: bool = False


@dataclass
class MatchResult:
    otp: "object"
    platform: str          # aliased best-effort platform for display
    payment_method: str
    logged: LoggedTxn = None  # the row it matched, if added


def aliased_platform(otp) -> str:
    return MERCHANT_ALIAS.get(otp.merchant_raw, otp.merchant_raw)


def dedup_retries(otps, window_seconds=DEDUP_WINDOW_SECONDS):
    """Collapse OTPs with the same card+amount fired within `window_seconds`
    of each other into a single expected transaction (keeps the earliest)."""
    groups = defaultdict(list)
    for o in otps:
        groups[(o.card_last4, round(o.amount, 2))].append(o)

    kept = []
    for items in groups.values():
        items.sort(key=lambda x: x.ts)
        anchor = items[0]
        kept.append(anchor)
        for o in items[1:]:
            if (o.ts - anchor.ts).total_seconds() <= window_seconds:
                continue  # treated as a retry of `anchor`, dropped
            anchor = o
            kept.append(anchor)
    kept.sort(key=lambda x: x.ts)
    return kept


def match(otps, logged, tolerance=AMOUNT_TOLERANCE):
    """Return (added, pending) as two lists of MatchResult."""
    added, pending = [], []
    for o in otps:
        pm = CARD_TO_PAYMENT_METHOD.get(o.card_last4)
        plat = aliased_platform(o)
        candidates = [
            t for t in logged
            if not t.consumed
            and pm is not None
            and t.payment_method == pm
            and t.date == o.ts.date()
            and abs(t.amount - o.amount) <= tolerance
        ]
        if not candidates:
            pending.append(MatchResult(o, plat, pm))
            continue
        # tie-break: prefer a platform match, then the closest amount
        candidates.sort(key=lambda t: (t.platform != plat, abs(t.amount - o.amount)))
        chosen = candidates[0]
        chosen.consumed = True
        added.append(MatchResult(o, plat, pm, logged=chosen))
    return added, pending
