"""Read the Finances Tracker and write the pending-backlog tab via the Sheets
API (service account).

Household tabs are auto-detected by their header row, so newly cloned
households are picked up with no code change and junk tabs are skipped. The
pending tab (PENDING_SHEET_GID) is overwritten on every run.
"""
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import (COL_AMOUNT, COL_DATE, COL_PAYMENT, COL_PLATFORM, COL_REMARK,
                    EXCLUDED_HOUSEHOLD_TABS, GOOGLE_SA_JSON_PATH,
                    HOUSEHOLD_HEADER_MARKERS, PENDING_SHEET_GID, SHEET_ID)
from match import LoggedTxn
from slack_io import permalink

# Google Sheets serial-date epoch (1899-12-30). Date cells read back with the
# FORMULA/UNFORMATTED render option come through as serial day counts.
_SHEETS_EPOCH = date(1899, 12, 30)

# Read + write. The service account is shared on the workbook as Editor; reads
# (household tabs) and the pending-tab overwrite both use this single scope.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PENDING_SHEET_HEADER = [
    "Date", "Time", "Amount", "Platform / Payee", "Payment method", "Comments",
    "Transaction source"]
_NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")


@dataclass
class PendingRow:
    """One pending-tab row in structured form: either freshly derived from a
    MatchResult (pending_row_from_result) or read back off the sheet for
    carry-forward (read_pending_sheet). `source_cell` is the ready-to-write
    "Transaction source" cell -- a HYPERLINK formula or a plain label -- kept
    verbatim so a carried row preserves its original message link."""
    date: date
    time: str            # "HH:MM" for display
    amount: float
    platform: str
    payment_method: str
    comments: str
    source_cell: str


def _credentials():
    # If a SA key file is present (legacy/local), use it. Otherwise fall back
    # to Application Default Credentials: Workload Identity Federation in CI,
    # or `gcloud auth application-default login` locally. Keyless by default.
    if GOOGLE_SA_JSON_PATH and os.path.exists(GOOGLE_SA_JSON_PATH):
        return service_account.Credentials.from_service_account_file(
            GOOGLE_SA_JSON_PATH, scopes=SCOPES)
    creds, _ = google.auth.default(scopes=SCOPES)
    return creds


def _service():
    return build("sheets", "v4", credentials=_credentials(),
                 cache_discovery=False)


def _parse_amount(s):
    if s is None:
        return None
    m = _NUM_RE.search(str(s).replace(" ", ""))
    return float(m.group(0).replace(",", "")) if m else None


def _parse_date(s):
    """Parse the sheet's '23-Jun-2026' format. Returns None on anything else
    (ops formatting mistakes are intentionally not rescued)."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _col_index(header, name):
    for i, h in enumerate(header):
        if h.strip() == name:
            return i
    return None


def _is_household(header):
    present = {h.strip() for h in header}
    return all(marker in present for marker in HOUSEHOLD_HEADER_MARKERS)


def read_logged_txns(start_date: date, end_date: date = None):
    """Return all LoggedTxn rows dated within [start_date, end_date] (inclusive)
    across household tabs. `end_date` defaults to `start_date` (single day)."""
    if end_date is None:
        end_date = start_date
    svc = _service().spreadsheets()
    meta = svc.get(spreadsheetId=SHEET_ID).execute()
    titles = [s["properties"]["title"] for s in meta["sheets"]]

    # batch read every tab's used range as displayed strings
    ranges = [f"'{t}'!A1:Z" for t in titles]
    resp = svc.values().batchGet(
        spreadsheetId=SHEET_ID, ranges=ranges,
        valueRenderOption="FORMATTED_VALUE").execute()

    out = []
    for title, vr in zip(titles, resp.get("valueRanges", [])):
        rows = vr.get("values", [])
        if not rows:
            continue
        header = rows[0]
        if not _is_household(header):
            continue
        di = _col_index(header, COL_DATE)
        pi = _col_index(header, COL_PLATFORM)
        ai = _col_index(header, COL_AMOUNT)
        mi = _col_index(header, COL_PAYMENT)
        if None in (di, ai, mi):
            continue
        for r_idx, row in enumerate(rows[1:], start=2):  # 1-based, skip header
            def cell(i):
                return row[i] if i is not None and i < len(row) else None
            d = _parse_date(cell(di))
            if d is None or not (start_date <= d <= end_date):
                continue
            amt = _parse_amount(cell(ai))
            pm = (cell(mi) or "").strip()
            if amt is None or not pm:
                continue
            out.append(LoggedTxn(
                household=title,
                date=d,
                platform=(cell(pi) or "").strip(),
                amount=amt,
                payment_method=pm,
                row=r_idx,
            ))
    return out


def _filter_household_tabs(items):
    """Pure core of list_household_tabs. `items` is an iterable of
    (title, header_row); returns qualifying titles sorted alphabetically."""
    out = [t for t, h in items
           if h and _is_household(h) and t not in EXCLUDED_HOUSEHOLD_TABS]
    return sorted(out, key=str.casefold)


def list_household_tabs():
    """Return household tab titles for the interactivity bot's dropdown, sorted
    alphabetically. A tab qualifies if its header row carries the household
    markers (same auto-detection as read_logged_txns) AND its title is not in
    EXCLUDED_HOUSEHOLD_TABS -- the latter drops the "Duplicate me" template and
    the frozen export tab, which do carry the markers but aren't destinations."""
    svc = _service().spreadsheets()
    meta = svc.get(spreadsheetId=SHEET_ID).execute()
    titles = [s["properties"]["title"] for s in meta["sheets"]]
    ranges = [f"'{t}'!A1:Z1" for t in titles]
    resp = svc.values().batchGet(
        spreadsheetId=SHEET_ID, ranges=ranges,
        valueRenderOption="FORMATTED_VALUE").execute()
    items = [(title, (vr.get("values") or [[]])[0])
             for title, vr in zip(titles, resp.get("valueRanges", []))]
    return _filter_household_tabs(items)


def _household_row_values(header, txn_date, platform, amount, payment_method,
                          remark=""):
    """Pure core of append_household_row: given the tab's `header` row, return
    the cell row to append, aligned so values.append maps it left-to-right from
    column A. Date is `DD-Mon-YYYY` to match the matcher's `_parse_date`; a
    mismatch would leave the item pending forever. Amount stays numeric. Columns
    other than Date/Platform/Amount/Payment method/Remark are left blank for ops.
    Raises RuntimeError if a matcher-critical column is absent."""
    idx = {
        COL_DATE: _col_index(header, COL_DATE),
        COL_PLATFORM: _col_index(header, COL_PLATFORM),
        COL_AMOUNT: _col_index(header, COL_AMOUNT),
        COL_PAYMENT: _col_index(header, COL_PAYMENT),
        COL_REMARK: _col_index(header, COL_REMARK),
    }
    # Date + Amount + Payment method are load-bearing for the matcher; a tab
    # missing any of them isn't a place we can safely log to.
    missing = [c for c in (COL_DATE, COL_AMOUNT, COL_PAYMENT) if idx[c] is None]
    if missing:
        raise RuntimeError(f"household tab missing column(s) {missing}")

    values = {
        idx[COL_DATE]: f"{txn_date:%d-%b-%Y}",
        idx[COL_PLATFORM]: platform or "",
        idx[COL_AMOUNT]: amount,
        idx[COL_PAYMENT]: payment_method or "",
    }
    if idx[COL_REMARK] is not None and remark:
        values[idx[COL_REMARK]] = remark
    width = max(values) + 1
    return [values.get(i, "") for i in range(width)]


def append_household_row(title, txn_date, platform, amount, payment_method,
                         remark=""):
    """Append one transaction row to household tab `title` via values.append
    with INSERT_ROWS -- atomic server-side, so two concurrent ops submissions
    can't collide on the same target row (no scan-for-empty-row).

    Returns the API response. Raises on any Sheets error (caller surfaces it)."""
    svc = _service().spreadsheets()
    header = svc.values().get(
        spreadsheetId=SHEET_ID, range=f"'{title}'!1:1",
        valueRenderOption="FORMATTED_VALUE").execute().get("values", [[]])
    header = header[0] if header else []
    try:
        row = _household_row_values(header, txn_date, platform, amount,
                                    payment_method, remark)
    except RuntimeError as e:
        raise RuntimeError(f"{e} on tab {title!r}")
    return svc.values().append(
        spreadsheetId=SHEET_ID, range=f"'{title}'!A:Z",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]}).execute()


def _hyperlink(url, label):
    """A Sheets HYPERLINK formula (USER_ENTERED). Doubles any quotes in the URL
    so a stray quote can't break out of the formula. Falls back to a plain
    label when there's no URL."""
    if not url:
        return label
    return f'=HYPERLINK("{url.replace(chr(34), chr(34) * 2)}", "{label}")'


def build_pending_sheet_rows(pending_results, base_url):
    """Header + one row per pending transaction for the pending tab, sorted
    oldest-first (an aging worklist: the most overdue pending is at the top).

    Columns: Date | Time | Amount | Platform | Card used | Comments |
    Transaction source (a hyperlink to the originating #otp-bridge message)."""
    rows = [list(PENDING_SHEET_HEADER)]
    for m in sorted(pending_results, key=lambda r: r.otp.ts):
        o = m.otp
        rows.append([
            f"{o.ts:%d-%b-%Y}",
            f"{o.ts:%H:%M}",
            f"₹{o.amount:,.2f}",
            m.platform or "",
            m.payment_method or "",
            o.comments or "",
            _hyperlink(permalink(base_url, o.slack_ts), "OTP message"),
        ])
    return rows


def pending_row_from_result(m, base_url, channel_id):
    """Turn a freshly-matched pending MatchResult into a PendingRow, linking its
    "Transaction source" cell to the message in `channel_id`."""
    o = m.otp
    return PendingRow(
        date=o.ts.date(),
        time=f"{o.ts:%H:%M}",
        amount=o.amount,
        platform=m.platform or "",
        payment_method=m.payment_method or "",
        comments=o.comments or "",
        source_cell=_hyperlink(
            permalink(base_url, o.slack_ts, channel_id), "Transaction msg"),
    )


def render_pending_rows(pending_rows):
    """Header + one cell-row per PendingRow, sorted oldest-first (aging
    worklist: most overdue at the top)."""
    rows = [list(PENDING_SHEET_HEADER)]
    for r in sorted(pending_rows, key=lambda r: (r.date, r.time)):
        rows.append([
            f"{r.date:%d-%b-%Y}",
            r.time,
            f"₹{r.amount:,.2f}",
            r.platform or "",
            r.payment_method or "",
            r.comments or "",
            r.source_cell or "",
        ])
    return rows


def _cell(row, i):
    return row[i] if i < len(row) else None


def _serial_to_date(v):
    """Coerce a pending-sheet Date cell to a date: a serial number (how Sheets
    stores a parsed date) or a displayed/text date string. None if neither."""
    if isinstance(v, (int, float)):
        return _SHEETS_EPOCH + timedelta(days=int(v))
    return _parse_date(v)


def read_pending_sheet():
    """Read the current pending tab back into PendingRows for carry-forward.

    Two passes over the same range: FORMATTED_VALUE for the human display cells
    (Time/Amount/Platform/Card/Comments) and FORMULA for the Date (as a serial,
    robust to whatever display format the tab uses) and the Transaction-source
    cell (to preserve its =HYPERLINK formula, which FORMATTED_VALUE would
    collapse to just the label). Unparseable rows are skipped."""
    svc = _service().spreadsheets()
    title = _pending_tab_title(svc)
    rng = f"'{title}'!A2:G"
    disp = svc.values().get(
        spreadsheetId=SHEET_ID, range=rng,
        valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
    form = svc.values().get(
        spreadsheetId=SHEET_ID, range=rng,
        valueRenderOption="FORMULA").execute().get("values", [])

    out = []
    for i, drow in enumerate(disp):
        frow = form[i] if i < len(form) else []
        d = _serial_to_date(_cell(frow, 0)) or _parse_date(_cell(drow, 0))
        amt = _parse_amount(_cell(drow, 2))
        pm = (_cell(drow, 4) or "").strip()
        if d is None or amt is None or not pm:
            continue  # header leftovers / ops-mangled rows aren't carried
        source = _cell(frow, 6) or _cell(drow, 6) or ""
        out.append(PendingRow(
            date=d,
            time=(_cell(drow, 1) or "").strip(),
            amount=amt,
            platform=(_cell(drow, 3) or "").strip(),
            payment_method=pm,
            comments=(_cell(drow, 5) or "").strip(),
            source_cell=source,
        ))
    return out


def _pending_tab_title(svc):
    """Resolve PENDING_SHEET_GID to its current tab title so a rename of the
    tab doesn't break the write. Raises if the gid isn't in the workbook."""
    meta = svc.get(spreadsheetId=SHEET_ID).execute()
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == PENDING_SHEET_GID:
            return s["properties"]["title"]
    raise RuntimeError(
        f"pending sheet gid {PENDING_SHEET_GID} not found in workbook {SHEET_ID}")


def write_pending_sheet(rows):
    """Overwrite the pending tab with `rows` (header + data). Clears the whole
    A:G range first so rows that got logged since the last run drop off."""
    svc = _service().spreadsheets()
    title = _pending_tab_title(svc)
    svc.values().clear(spreadsheetId=SHEET_ID, range=f"'{title}'!A:G").execute()
    svc.values().update(
        spreadsheetId=SHEET_ID, range=f"'{title}'!A1",
        valueInputOption="USER_ENTERED", body={"values": rows}).execute()
