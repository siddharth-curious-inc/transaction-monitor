"""Parse ICICI OTP messages. All three cards share one template; only
'INR Prepaid Card' vs 'Credit Card' differs, and we key on the last-4."""
import re
from dataclasses import dataclass
from datetime import datetime

AMOUNT_RE = re.compile(r"INR\s+([\d,]+\.\d{2})\s+transaction")
MERCHANT_RE = re.compile(r"towards\s+(.+?)\s+using\s+ICICI")
CARD_RE = re.compile(r"Card\s+XX(\d{4})")
TIME_RE = re.compile(r"Time:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


@dataclass
class OTP:
    amount: float          # normalized rupees, e.g. 413.0
    merchant_raw: str      # verbatim from message, e.g. "BLINK COMME"
    card_last4: str        # "6547"
    ts: datetime           # naive datetime, IST wall-clock from the body
    raw: str               # original full text
    excluded: bool = False    # ops reacted with :x: to void this transaction
    exclude_reason: str = ""  # first human thread reply explaining the void


def parse_message(text: str):
    """Return an OTP, or None if the text isn't a parseable OTP message."""
    a = AMOUNT_RE.search(text)
    c = CARD_RE.search(text)
    t = TIME_RE.search(text)
    if not (a and c and t):
        return None
    m = MERCHANT_RE.search(text)
    return OTP(
        amount=float(a.group(1).replace(",", "")),
        merchant_raw=m.group(1).strip() if m else "",
        card_last4=c.group(1),
        ts=datetime.strptime(t.group(1), "%Y-%m-%d %H:%M:%S"),
        raw=text,
    )
