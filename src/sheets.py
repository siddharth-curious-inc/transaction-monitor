"""Read the Finances Tracker via the Sheets API (service account, read-only).

Household tabs are auto-detected by their header row, so newly cloned
households are picked up with no code change and junk tabs are skipped.
"""
import os
import re
from datetime import date, datetime

import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import (COL_AMOUNT, COL_DATE, COL_PAYMENT, COL_PLATFORM,
                    GOOGLE_SA_JSON_PATH, HOUSEHOLD_HEADER_MARKERS, SHEET_ID)
from match import LoggedTxn

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
_NUM_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?")


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


def read_logged_txns(only_date: date):
    """Return all LoggedTxn rows dated `only_date` across household tabs."""
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
            if d != only_date:
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
