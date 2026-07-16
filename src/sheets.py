"""Read the Finances Tracker and write the pending-backlog tab via the Sheets
API (service account).

Household tabs are auto-detected by their header row, so newly cloned
households are picked up with no code change and junk tabs are skipped. The
pending tab (PENDING_SHEET_GID) is overwritten on every run.
"""
import os
import re
from datetime import date, datetime

import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import (COL_AMOUNT, COL_DATE, COL_PAYMENT, COL_PLATFORM,
                    GOOGLE_SA_JSON_PATH, HOUSEHOLD_HEADER_MARKERS,
                    PENDING_SHEET_GID, SHEET_ID)
from match import LoggedTxn
from slack_io import permalink

# Read + write. The service account is shared on the workbook as Editor; reads
# (household tabs) and the pending-tab overwrite both use this single scope.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PENDING_SHEET_HEADER = [
    "Date", "Time", "Amount", "Platform", "Card used", "Comments",
    "Transaction source"]
_NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")


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
