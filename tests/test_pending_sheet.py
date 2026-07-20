import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date, datetime  # noqa: E402

import sheets  # noqa: E402
from match import MatchResult  # noqa: E402
from parse import OTP  # noqa: E402
from sheets import (PENDING_SHEET_HEADER, PendingRow, _serial_to_date,  # noqa: E402
                    pending_row_from_result, render_pending_rows)


def test_pending_row_from_result_links_to_given_channel():
    o = OTP(amount=82.0, merchant_raw="SONU KUMAR PODDAR", card_last4="0978",
            ts=datetime(2026, 7, 18, 17, 33), raw="")
    o.slack_ts = "1752839021.000100"
    o.comments = "Ishita note"
    m = MatchResult(o, "SONU KUMAR PODDAR", "Cashbook - Kabeer and Pallavi")
    row = pending_row_from_result(m, "https://curious.slack.com/", "C_TXN")
    assert row.date == date(2026, 7, 18)
    assert row.time == "17:33"
    assert row.amount == 82.0
    assert row.payment_method == "Cashbook - Kabeer and Pallavi"
    assert row.comments == "Ishita note"
    assert row.source_cell.startswith(
        '=HYPERLINK("https://curious.slack.com/archives/C_TXN/')
    assert row.source_cell.endswith('"Transaction msg")')


def test_render_pending_rows_header_and_oldest_first():
    late = PendingRow(date(2026, 7, 19), "10:00", 5.0, "P", "ICICI 9005", "", "s")
    early = PendingRow(date(2026, 7, 18), "09:00", 6.0, "P", "K&D 6547", "", "s")
    rows = render_pending_rows([late, early])
    assert rows[0] == PENDING_SHEET_HEADER
    assert rows[1][0] == "18-Jul-2026"
    assert rows[2][0] == "19-Jul-2026"
    assert rows[1][2] == "₹6.00"


def test_serial_to_date_handles_serial_and_string():
    serial = (date(2026, 7, 18) - date(1899, 12, 30)).days
    assert _serial_to_date(serial) == date(2026, 7, 18)
    assert _serial_to_date("18-Jul-2026") == date(2026, 7, 18)
    assert _serial_to_date("not a date") is None


def test_read_pending_sheet_preserves_link_and_parses_date(monkeypatch):
    serial = (date(2026, 7, 18) - date(1899, 12, 30)).days
    disp = [["18-Jul-2026", "17:33", "₹82.00", "SONU",
             "Cashbook - Kabeer and Pallavi", "note", "OTP message"]]
    form = [[serial, "17:33", "₹82.00", "SONU",
             "Cashbook - Kabeer and Pallavi", "note",
             '=HYPERLINK("https://x/archives/C/p1","OTP message")']]

    class FakeGet:
        def __init__(self, values):
            self._v = values

        def execute(self):
            return {"values": self._v}

    class FakeValues:
        def get(self, spreadsheetId, range, valueRenderOption):
            return FakeGet(form if valueRenderOption == "FORMULA" else disp)

    class FakeSpreadsheets:
        def values(self):
            return FakeValues()

    class FakeSvc:
        def spreadsheets(self):
            return FakeSpreadsheets()

    monkeypatch.setattr(sheets, "_service", lambda: FakeSvc())
    monkeypatch.setattr(sheets, "_pending_tab_title", lambda svc: "Pending")

    rows = sheets.read_pending_sheet()
    assert len(rows) == 1
    r = rows[0]
    assert r.date == date(2026, 7, 18)          # serial -> date
    assert r.amount == 82.0
    assert r.payment_method == "Cashbook - Kabeer and Pallavi"
    assert r.source_cell.startswith('=HYPERLINK(')   # formula preserved, not label
