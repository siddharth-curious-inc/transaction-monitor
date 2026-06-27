"""Retry de-duplication and OTP <-> logged-row matching.

Match key (locked):  Date  +  Payment method  +  Amount (+/- tolerance).
Platform is a soft signal, not a hard requirement: a same-platform near-exact
match is preferred, but cross-platform matches are still allowed when nothing
better competes for the row.
Rows are consumed one-to-one so a single logged row can't satisfy two OTPs and
two OTPs can't both claim one row. Assignment is done globally best-first (by
platform agreement then amount closeness) rather than in OTP time order, so a
row is awarded to its best claimant instead of whichever OTP happens to be
processed first.
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
    results = {
        id(o): MatchResult(o, aliased_platform(o),
                           CARD_TO_PAYMENT_METHOD.get(o.card_last4))
        for o in otps
    }

    # Every feasible (otp, row) pairing, ranked so the best pairing wins the row:
    # same platform first, then the smallest amount difference. Assigning these
    # globally (rather than per-OTP in time order) stops a worse, earlier OTP
    # from consuming a row that is a near-exact same-platform match for another.
    pairs = []
    for o in otps:
        pm = CARD_TO_PAYMENT_METHOD.get(o.card_last4)
        if pm is None:
            continue
        plat = aliased_platform(o)
        for t in logged:
            if (t.payment_method == pm
                    and t.date == o.ts.date()
                    and abs(t.amount - o.amount) <= tolerance):
                pairs.append((t.platform != plat, abs(t.amount - o.amount), o, t))
    pairs.sort(key=lambda p: (p[0], p[1]))

    for _, _, o, t in pairs:
        if t.consumed or results[id(o)].logged is not None:
            continue
        t.consumed = True
        results[id(o)].logged = t

    added, pending = [], []
    for o in otps:
        res = results[id(o)]
        (added if res.logged is not None else pending).append(res)
    return added, pending
