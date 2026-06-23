"""Entry point. Run:  python src/run.py [--dry-run]"""
import sys
from datetime import datetime

from config import IST
from match import dedup_retries, match
from parse import parse_message
from sheets import read_logged_txns
from slack_io import fetch_messages_since_midnight, post_summary


def _fmt(mr, with_household=False):
    o = mr.otp
    base = f"₹{o.amount:,.2f} · {mr.platform} · {mr.payment_method} · {o.ts:%H:%M}"
    if with_household and mr.logged is not None:
        base += f" → {mr.logged.household}"
    return base


def compose(detected, added, pending, when):
    lines = [
        f"*📊 OTP → Tracker Roundup* · {when:%d %b %Y, %-I:%M %p} IST",
        "",
        f"Transactions detected since 00:00 today: *{detected}* (retries collapsed)",
        f"✅ Logged in Finances Tracker: *{len(added)}*",
        f"⚠️ Pending (not yet logged): *{len(pending)}*",
    ]
    if pending:
        lines += ["", "*Pending:*"] + [f"• {_fmt(m)}" for m in pending]
    if added:
        lines += ["", "*Logged:*"] + [f"• {_fmt(m, with_household=True)}" for m in added]
    return "\n".join(lines)


def main(dry_run=False):
    now = datetime.now(IST)

    raw = fetch_messages_since_midnight()
    parsed = [o for o in (parse_message(t) for t in raw) if o]
    otps = dedup_retries(parsed)

    logged = read_logged_txns(only_date=now.date())
    added, pending = match(otps, logged)

    if dry_run:
        print(f"[diag] slack messages fetched since 00:00: {len(raw)}")
        print(f"[diag] parsed as OTPs: {len(parsed)}  "
              f"(after retry-dedup: {len(otps)})")
        print(f"[diag] logged rows on {now:%d-%b-%Y} across household tabs: "
              f"{len(logged)}")

    msg = compose(len(otps), added, pending, now)
    post_summary(msg, dry_run=dry_run)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
