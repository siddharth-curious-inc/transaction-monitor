"""Central config. The only file you should normally need to edit."""
import os
from datetime import date, timezone, timedelta

# --- timezone ---------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))

# --- card last-4  ->  sheet "Payment method" dropdown value -----------------
CARD_TO_PAYMENT_METHOD = {
    "6547": "K&D 6547",
    "6570": "K&P 6570",
    "9005": "ICICI 9005",
}

# --- raw merchant string (exactly as it appears in the OTP) -> sheet Platform
# Seeded from the three samples. Extend this from your scraped distinct
# merchant strings. Keys MUST match the OTP text verbatim (incl. truncation).
MERCHANT_ALIAS = {
    "AKSHAYAKALP": "Online - other vendor",
    "AMAZON": "Amazon",
    "AMAZON PAY": "Amazon",
    "AXELIA SOLU": "Online - other vendor",
    "Avenue E-Co": "Online - other vendor",
    "BEEJAPURI D": "Online - other vendor",
    "BISTRO PG": "Online - other vendor",
    "BLINK COMME": "Blinkit",
    "BLINKIT": "Blinkit",
    "BLINKIT ECO": "Blinkit",
    "BLINKIT MON": "Blinkit",
    "BLINKIT RET": "Blinkit",
    "BUNDL TECHN": "Swiggy - Food",
    "Bonne Terre": "Online - other vendor",
    "Bundl Techn": "Swiggy - Food",
    "CHHAYAKART": "Online - other vendor",
    "CLEANOVO": "Online - other vendor",
    "COUNTRYDELI": "Online - other vendor",
    "CRAVE BY LE": "Online - other vendor",
    "DISTRICT MO": "Online - other vendor",
    "DOCUPRO SER": "Docupro",
    "Delightful": "Licious",
    "DriveU Mobi": "Online - other vendor",
    "FARMERR": "Online - other vendor",
    "FRESHTOHOME": "F2H",
    "FirstClub": "Firstclub",
    "Flipkart": "Flipkart",
    "Flipkart In": "Flipkart",
    "GOOGLESERVI": "Online - other vendor",
    "GROFERS COM": "Blinkit",
    "GROFERS IND": "Blinkit",
    "Gobbleright": "Online - other vendor",
    "H AND M HEN": "Online - other vendor",
    "HANDPICKD": "Handpickd",
    "HOMETRIANGL": "Online - other vendor",
    "HONESTLY IT": "Online - other vendor",
    "HYPPY": "Online - other vendor",
    "Hindustan P": "Online - other vendor",
    "INDIGO": "Online - other vendor",
    "INDIGO AIRL": "Online - other vendor",
    "INNOVATIVE": "BigBasket",
    "INSTAMART": "Instamart",
    "Ikea Ecom": "Online - other vendor",
    "Innovative": "BigBasket",
    "JIOIN APP D": "Online - other vendor",
    "Journal per": "Online - other vendor",
    "KALRASCAPE": "Online - other vendor",
    "Licious": "Licious",
    "Loafer and": "Online - other vendor",
    "MAESTROEDGE": "Online - other vendor",
    "MUNCHMART T": "Online - other vendor",
    "MYNTRA DESI": "Myntra",
    "Marcos Tomo": "Online - other vendor",
    "Muhavra Ent": "Online - other vendor",
    "Myntra": "Myntra",
    "NACIL AIR I": "Online - other vendor",
    "NEW AGE CON": "Online - other vendor",
    "NYKAA": "Online - other vendor",
    "Natures Bas": "Online - other vendor",
    "Nykaa E Ret": "Online - other vendor",
    "Nykaa Fashi": "Online - other vendor",
    "PCIPESTC": "Online - other vendor",
    "PORTER PG": "Porter",
    "PRODIGYPREN": "Online - other vendor",
    "PRONTO": "Pronto",
    "Porter": "Porter",
    "Potentifuel": "Online - other vendor",
    "Pronto": "Pronto",
    "RELIANCE RE": "Online - other vendor",
    "SIESTA O CL": "Online - other vendor",
    "SMARTSHIFT": "Porter",
    "SPIN CYCLES": "Spin cycle",
    "STICKITUP": "Online - other vendor",
    "SWACHH SAAT": "Online - other vendor",
    "SWIGGY": "Swiggy - Food",
    "SWIGGY IN": "Swiggy - Food",
    "SimpliNamdh": "Namdharis",
    "Swiggy": "Swiggy - Food",
    "Swiggy IN": "Swiggy - Food",
    "Swiggy Inst": "Instamart",
    "Swiggy Limi": "Swiggy - Food",
    "SwiggyCyber": "Swiggy - Food",
    "Swish": "Online - other vendor",
    "TECHMASH SO": "Online - other vendor",
    "TITAN": "Online - other vendor",
    "The Laundry": "Online - other vendor",
    "UBER INDIA": "Uber",
    "URBAN PLATT": "Online - other vendor",
    "UrbanClap T": "Urban Company",
    "VISAGE LINE": "Online - other vendor",
    "WWW NATURES": "Online - other vendor",
    "WWW SWIGGY": "Swiggy - Food",
    "ZENIN": "Online - other vendor",
    "ZEPTO MARKE": "Zepto",
    "ZEPTONOW": "Zepto",
    "ZOMATO LIMI": "Zomato",
    "ZOMATO LTD": "Zomato",
    "Zepto": "Zepto",
    "Zepto Marke": "Zepto",
    "Zeptonow": "Zepto",
    "bundl techn": "Swiggy - Food",
}

# --- matching knobs ---------------------------------------------------------
AMOUNT_TOLERANCE = 5.0        # +/- rupees on the amount match
DEDUP_WINDOW_SECONDS = 600    # collapse same card+amount OTPs within 10 min
PENDING_LOOKBACK_DAYS = 7     # how many prior days to also surface as pending
# Never look at dates before this, regardless of the lookback window. The
# tracker isn't reliable before this date, so older pendings are just noise.
PENDING_FLOOR_DATE = date(2026, 6, 23)

# A tab counts as a household sheet only if its header row contains ALL of
# these. Auto-skips Legend / To fix / Master Tracker / exports / etc., and
# auto-includes new households cloned from "Duplicate me".
HOUSEHOLD_HEADER_MARKERS = ["Amount paid (₹)", "Payment method"]

# Exact header names to locate columns within a household sheet.
COL_DATE = "Date (double click)"
COL_PLATFORM = "Platform"
COL_AMOUNT = "Amount paid (₹)"
COL_PAYMENT = "Payment method"

# --- secrets / ids (from environment) ---------------------------------------
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
OTP_CHANNEL_ID = os.environ.get("OTP_CHANNEL_ID", "")        # #otp-bridge
SUMMARY_CHANNEL_ID = os.environ.get("SUMMARY_CHANNEL_ID", "")  # roundup channel
SHEET_ID = os.environ.get("SHEET_ID", "")
GOOGLE_SA_JSON_PATH = os.environ.get("GOOGLE_SA_JSON_PATH", "")  # empty -> ADC/WIF
