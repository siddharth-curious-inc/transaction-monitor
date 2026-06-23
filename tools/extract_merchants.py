"""Extract distinct merchant strings from a scraped #otp-bridge dump, so you
can build the MERCHANT_ALIAS map in src/config.py.

Usage:
    python tools/extract_merchants.py path/to/your_scraped_dump.txt

Works regardless of how the dump is laid out (one message per line, JSON, one
big blob) — it just scans for the "towards X using ICICI" pattern everywhere.
Prints each distinct merchant with a frequency count and flags which are not
yet in your alias map, then emits a paste-ready block for the unmapped ones.
"""
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from config import MERCHANT_ALIAS  # noqa: E402

MERCHANT_RE = re.compile(r"towards\s+(.+?)\s+using\s+ICICI")


def main(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    merchants = Counter(m.strip() for m in MERCHANT_RE.findall(text))
    if not merchants:
        print("No merchant strings found. Is this the right dump / format?")
        return

    print(f"{len(merchants)} distinct merchant strings (by frequency):\n")
    for name, n in merchants.most_common():
        status = "mapped" if name in MERCHANT_ALIAS else "UNMAPPED"
        print(f"  {n:5d}  {name!r:32}  [{status}]")

    unmapped = sorted(m for m in merchants if m not in MERCHANT_ALIAS)
    if unmapped:
        print("\n# Paste into MERCHANT_ALIAS in src/config.py, fill each value")
        print("# with one of your 26 dropdown Platform names:")
        for m in unmapped:
            print(f'    "{m}": "",  # TODO')
    else:
        print("\nAll merchant strings are already mapped. 🎉")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python tools/extract_merchants.py <dump.txt>")
    else:
        main(sys.argv[1])
