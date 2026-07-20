"""Parse ICICI OTP messages (legacy #otp-bridge source) and bank debit
confirmations (new #transaction-bridge source).

Legacy: all three cards share one OTP template; only 'INR Prepaid Card' vs
'Credit Card' differs, and we key on the last-4.

New source: messages are Slack Block Kit. The raw forwarded SMS lives verbatim
in a section block ("*Raw SMS:*\\n```...```") and is the authoritative parse
source -- NOT the pretty header fields. Two SMS dialects are handled (CashBook/
Obopay UPI and ICICI cards); see parse_transaction_message."""
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
    comments: str = ""        # all human thread replies (e.g. household notes)
    slack_ts: str = ""        # Slack message ts (for the source-message permalink)


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


# --- #transaction-bridge (bank debit confirmations) -------------------------
# The transaction amount is anchored to the debit verb so we never pick up
# "Avl Bal" / "Avl Limit" figures that follow it in the same SMS.
TXN_AMOUNT_OBOPAY_RE = re.compile(r"debited\s+Rs\.?\s*([\d,]+\.\d{2})", re.I)
TXN_AMOUNT_ICICI_RE = re.compile(r"INR\s*([\d,]+\.\d{2})\s+spent", re.I)
TXN_LAST4_OBOPAY_RE = re.compile(r"a/c\s+xx(\d{4})", re.I)
TXN_LAST4_ICICI_RE = re.compile(r"Card\s+XX(\d{4})", re.I)
# Obopay: "on 06-07-2026 16:45:44" (DD-MM-YYYY HH:MM:SS)
TXN_DT_OBOPAY_RE = re.compile(r"on\s+(\d{2}-\d{2}-\d{4})\s+(\d{2}:\d{2}:\d{2})")
# ICICI: "on 19-Jul-26" (DD-Mon-YY, no time in the SMS body)
TXN_DATE_ICICI_RE = re.compile(r"on\s+(\d{2}-[A-Za-z]{3}-\d{2})\b")
# UPI payee is the segment after the numeric ref: "UPI/618716845147/HENNES N MAURITZ."
TXN_MERCHANT_UPI_RE = re.compile(r"UPI/[^/]*/([^.]+)")
# ICICI card merchant sits after the SECOND "on", before ". Avl":
# "...on 19-Jul-26 on UrbanClap Techn. Avl Limit: ..."
TXN_MERCHANT_ICICI_RE = re.compile(
    r"on\s+\d{2}-[A-Za-z]{3}-\d{2}\s+on\s+(.+?)\.\s", re.I)
# Footer context segments render the emoji names literally, e.g.
# ":iphone: Pixel 7a   •   :email: AD-CBOBPY-S   •   :clock3: 2026-07-06 16:45:44"
FOOTER_CLOCK_RE = re.compile(r":clock3:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


def _blocks(msg):
    """Blocks off a Slack message dict; also unwraps attachment-hosted blocks."""
    out = list(msg.get("blocks") or [])
    for att in msg.get("attachments") or []:
        out.extend(att.get("blocks") or [])
    return out


def _raw_sms(msg):
    """The verbatim SMS from the '*Raw SMS:*' section block, code-fence and
    label stripped. Returns '' if no such block is present."""
    for b in _blocks(msg):
        if b.get("type") != "section":
            continue
        txt = (b.get("text") or {}).get("text", "")
        if "Raw SMS" in txt:
            body = txt.split("Raw SMS:", 1)[-1]
            return body.replace("*", "").replace("`", "").strip()
    return ""


def _footer_text(msg):
    """Concatenated text of the message's context block(s) -- the footer that
    carries the sender-id and the :clock3: wall-clock timestamp."""
    parts = []
    for b in _blocks(msg):
        if b.get("type") != "context":
            continue
        for el in b.get("elements") or []:
            t = el.get("text")
            if t:
                parts.append(t)
    return "  ".join(parts)


def transaction_sender_id(msg):
    """The SMS sender-id from the footer (the segment after the :email: icon,
    e.g. 'AD-CBOBPY-S', or '9876543210' for the emulator). '' if absent."""
    for seg in _footer_text(msg).split("•"):
        seg = seg.strip()
        if ":email:" in seg:
            return seg.split(":email:", 1)[-1].strip()
    return ""


def _field_value(msg, label):
    """Value of a '*Label:*\\nvalue' entry in the fields section block."""
    for b in _blocks(msg):
        if b.get("type") != "section":
            continue
        for f in b.get("fields") or []:
            txt = f.get("text", "")
            if txt.startswith(f"*{label}:*"):
                return txt.split("\n", 1)[-1].strip() if "\n" in txt else ""
    return ""


def _txn_merchant(sms, msg):
    """Best-effort merchant/payee: parsed from the raw SMS (authoritative),
    falling back to the pretty *Merchant:* field."""
    m = TXN_MERCHANT_UPI_RE.search(sms) or TXN_MERCHANT_ICICI_RE.search(sms)
    if m:
        return m.group(1).strip()
    return _field_value(msg, "Merchant")


def parse_transaction_message(msg):
    """Parse a #transaction-bridge Block Kit message into an OTP-shaped record,
    or None if it isn't a parseable *debit* confirmation.

    `msg` is a Slack message dict. Only debits count (a debit confirmation is a
    settled transaction); credits/other are ignored. All money/account/date
    fields come from the raw SMS; the footer :clock3: supplies the time when the
    SMS itself carries only a date (ICICI cards)."""
    sms = _raw_sms(msg)
    if not sms:
        return None
    # debit-only: Obopay says "debited", ICICI says "spent using". Anything
    # else (e.g. a "credited" refund) is not a spend and is skipped.
    if not re.search(r"\bdebited\b|\bspent\b", sms, re.I):
        return None

    a = TXN_AMOUNT_OBOPAY_RE.search(sms) or TXN_AMOUNT_ICICI_RE.search(sms)
    c = TXN_LAST4_OBOPAY_RE.search(sms) or TXN_LAST4_ICICI_RE.search(sms)
    if not (a and c):
        return None

    dt_o = TXN_DT_OBOPAY_RE.search(sms)
    if dt_o:
        ts = datetime.strptime(f"{dt_o.group(1)} {dt_o.group(2)}",
                               "%d-%m-%Y %H:%M:%S")
    else:
        d_i = TXN_DATE_ICICI_RE.search(sms)
        if not d_i:
            return None
        day = datetime.strptime(d_i.group(1), "%d-%b-%y").date()
        # SMS has no time; take it from the footer clock, else midnight.
        clk = FOOTER_CLOCK_RE.search(_footer_text(msg))
        if clk:
            ts = datetime.strptime(clk.group(1), "%Y-%m-%d %H:%M:%S")
            ts = ts.replace(year=day.year, month=day.month, day=day.day)
        else:
            ts = datetime.combine(day, datetime.min.time())

    return OTP(
        amount=float(a.group(1).replace(",", "")),
        merchant_raw=_txn_merchant(sms, msg),
        card_last4=c.group(1),
        ts=ts,
        raw=sms,
    )
