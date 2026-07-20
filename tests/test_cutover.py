import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime  # noqa: E402

import run  # noqa: E402


def _stub_pipelines(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "run_otp_source",
                        lambda *a, **k: calls.append("otp"))
    monkeypatch.setattr(run, "run_transaction_source",
                        lambda *a, **k: calls.append("txn"))
    return calls


def test_source_override_forces_pipeline(monkeypatch):
    calls = _stub_pipelines(monkeypatch)
    run.main(source="otp")
    run.main(source="transaction")
    assert calls == ["otp", "txn"]


def test_date_gated_dispatch(monkeypatch):
    calls = _stub_pipelines(monkeypatch)

    class _Before:
        @staticmethod
        def now(tz):
            return datetime(2026, 7, 20, 12, 0, tzinfo=tz)   # day before cutover

    class _OnCutover:
        @staticmethod
        def now(tz):
            return datetime(2026, 7, 21, 9, 0, tzinfo=tz)    # cutover day

    monkeypatch.setattr(run, "datetime", _Before)
    run.main()
    assert calls[-1] == "otp"

    monkeypatch.setattr(run, "datetime", _OnCutover)
    run.main()
    assert calls[-1] == "txn"
