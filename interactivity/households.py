"""Small TTL cache over sheets.list_household_tabs so a burst of prompts (or a
modal open, which must answer within the 3s trigger_id window) doesn't hit the
Sheets API every time, while new households still appear within the TTL."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sheets import list_household_tabs  # noqa: E402

_TTL_SECONDS = 120
_cache = {"at": 0.0, "tabs": []}


def get_households(force=False):
    now = time.monotonic()
    if force or not _cache["tabs"] or (now - _cache["at"]) > _TTL_SECONDS:
        _cache["tabs"] = list_household_tabs()
        _cache["at"] = now
    return _cache["tabs"]
