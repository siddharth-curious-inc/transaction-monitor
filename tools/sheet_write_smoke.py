"""Live Sheets-write smoke test for the interactivity bot's write path, meant to
run in GitHub Actions under WIF (local ADC is blocked by org policy). It touches
ONLY the tab named in TEST_HOUSEHOLD_TAB, so point that at a scratch tab.

  SHEET_ID=<workbook>  TEST_HOUSEHOLD_TAB="test - Sid"  python tools/sheet_write_smoke.py

Steps: list the dropdown households, append one obvious test row to the scratch
tab exactly as a dropdown selection would, and read the tab back to confirm the
row landed in a matcher-parseable shape (the "stays pending forever" guard)."""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import IST, SHEET_ID  # noqa: E402
from sheets import (_parse_amount, _parse_date, _service,  # noqa: E402
                    append_household_row, list_household_tabs)

TAB = os.environ.get("TEST_HOUSEHOLD_TAB", "")
if not TAB:
    raise SystemExit("Set TEST_HOUSEHOLD_TAB to a SCRATCH tab (never a real one).")

print(f"workbook: {SHEET_ID}")
print(f"target tab: {TAB!r}\n")

tabs = list_household_tabs()
print(f"household tabs offered in dropdown ({len(tabs)}):")
for t in tabs:
    print("   -", t)
if TAB not in tabs:
    print(f"\nWARNING: {TAB!r} is not in the household dropdown "
          "(missing header markers or in EXCLUDED_HOUSEHOLD_TABS).")

when = datetime.now(IST).date()
print(f"\nappending a test row to {TAB!r} ...")
resp = append_household_row(TAB, when, "CI Test Platform", 1.0, "K&P 6570",
                            remark="automated sheet-write test")
updated = resp.get("updates", {}).get("updatedRange", "?")
print(f"  appended at {updated}")

# Read the tab back and confirm the row we just wrote parses like the matcher does.
svc = _service().spreadsheets()
rows = svc.values().get(spreadsheetId=SHEET_ID,
                        range=f"'{TAB}'!A1:Z").execute().get("values", [])
header = rows[0] if rows else []
di = header.index("Date (double click)") if "Date (double click)" in header else None
ai = header.index("Amount paid (₹)") if "Amount paid (₹)" in header else None
last = rows[-1] if len(rows) > 1 else []
print("\nlast row (as read back):", last)
if di is not None and ai is not None and last:
    d = _parse_date(last[di]) if di < len(last) else None
    amt = _parse_amount(last[ai]) if ai < len(last) else None
    print(f"  parsed Date -> {d}  Amount -> {amt}")
    ok = d == when and amt == 1.0
    print("RESULT:", "OK — row is matcher-parseable" if ok
          else "MISMATCH — check the write format")
    sys.exit(0 if ok else 1)
print("RESULT: appended, but could not locate Date/Amount columns to verify")
