"""Central config. The only file you should normally need to edit."""
import os
from datetime import date, time, timezone, timedelta

# Load a local .env (repo root) if python-dotenv is available, so local runs of
# the bot / pipeline can source SLACK_*/SHEET_ID/scratch channel ids from a file
# instead of exporting them by hand. A no-op in CI (no .env, and real env vars
# already win -- load_dotenv never overrides an already-set variable).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), os.pardir, ".env"))
except ImportError:
    pass

# --- timezone ---------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))

# --- card last-4  ->  sheet "Payment method" dropdown value -----------------
# LEGACY (OTP source of truth). Only the three credit/prepaid cards fire OTPs.
CARD_TO_PAYMENT_METHOD = {
    "6547": "K&D 6547",
    "6570": "K&P 6570",
    "9005": "ICICI 9005",
}

# --- account/card last-4 in the SMS body  ->  "Payment method" dropdown ------
# NEW source of truth (#transaction-bridge debit confirmations). The rail is
# identified from the last-4 in the SMS body (never from the forwarding phone),
# and the last-4 is unique per rail, so a single flat map covers UPI (CashBook/
# Obopay) and the ICICI cards. Superset of CARD_TO_PAYMENT_METHOD.
ACCOUNT_TO_PAYMENT_METHOD = {
    "6679": "Cashbook - Ishita and Harsh",     # CashBook a/c xx6679 (UPI)
    "0978": "Cashbook - Kabeer and Pallavi",   # CashBook a/c xx0978 (UPI)
    "6547": "K&D 6547",                          # ICICI INR Prepaid Card XX6547
    "6570": "K&P 6570",                          # ICICI INR Prepaid Card XX6570
    "9005": "ICICI 9005",                        # ICICI Credit Card XX9005
}

# Rails that carry a linkable #otp-bridge OTP (the credit/prepaid cards). UPI
# rails never fire an OTP, so they get no exclusion/comment linking.
OTP_LINKED_CARDS = frozenset(CARD_TO_PAYMENT_METHOD)

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

# --- on-shift Slack user groups to ping in the roundup ----------------------
# Runs before SHIFT_CUTOFF ping the morning group; runs at/after it (through
# the day) ping the evening group. The script doesn't know which scheduled run
# triggered it, so it decides purely from the current IST time -- more resilient
# than hard-coding the Cloud Scheduler timings.
SHIFT_CUTOFF = time(14, 0)                       # 2:00 PM IST
MORNING_GROUP = ("S0AR579HUCD", "5-am-club")     # (user group id, handle)
EVENING_GROUP = ("S0AR28NAZNX", "2-se-11")

# --- ops controls -----------------------------------------------------------
# Ops react to an #otp-bridge message with this emoji to void the transaction
# (refund, failed attempt, etc.). It's then counted as "excluded" rather than
# pending, and never needs logging on the tracker.
#
# This is the LEGACY exclusion channel: it still governs old #otp-bridge OTPs so
# ones ops already X'd don't resurface as pending. For NEW #transaction-bridge
# confirmations it's superseded by the interactivity bot's dropdown "Exclude"
# option, which records the exclusion in the bot message's Slack metadata (read
# back by the scheduled pipeline via fetch_bot_prompt_states).
EXCLUDE_REACTION = "x"        # the :x: red cross

# --- matching knobs ---------------------------------------------------------
AMOUNT_TOLERANCE = 5.0        # (legacy/OTP) +/- rupees; wobble for pre-auth OTPs
NEW_AMOUNT_TOLERANCE = 1.0    # (new source) confirmations are exact settled
                              # amounts, so only a +/-1 rupee rounding cushion.
DEDUP_WINDOW_SECONDS = 600    # (legacy/OTP) collapse same card+amount within 10 min.
                              # NOT used for the new source: a debit confirmation
                              # is one settled transaction, so no retry dedup.
PENDING_LOOKBACK_DAYS = 7     # (legacy) prior-days window; superseded by the
                              # floor date below now that the full backlog lives
                              # on the pending sheet rather than in the Slack message.
# Never look at dates before this. The tracker isn't reliable before this date,
# so older pendings are just noise. This is also the start of the full pending
# backlog written to the pending sheet each run.
PENDING_FLOOR_DATE = date(2026, 6, 23)

# --- source-of-truth cutover ------------------------------------------------
# Until this date the source of truth is #otp-bridge (credit-card OTPs). From
# this date onward it is #transaction-bridge (bank debit confirmations, cards +
# UPI). The switch is decided from the current IST date, so the changeover is
# automatic and needs no code change on the day.
CUTOVER_DATE = date(2026, 7, 21)

# Ignore #transaction-bridge messages before this date -- they're pre-rollout
# test transactions. Also the start of the freshly-derived new-source backlog;
# pre-cutover pendings survive via carry-forward on the pending sheet.
TRANSACTION_FLOOR_DATE = date(2026, 7, 13)

# The emulator test sender. Any #transaction-bridge message whose footer
# sender-id equals this is skipped at any date.
TEST_SENDER_ID = "9876543210"

# --- pending backlog sheet --------------------------------------------------
# A dedicated, ops-facing tab on the SAME Finances Tracker workbook (SHEET_ID)
# that the bot overwrites every run with the full set of still-pending
# transactions since PENDING_FLOOR_DATE. The Slack roundup only shows Today +
# Yesterday and links here for the rest. gid identifies the tab; the tab title
# is resolved from the gid at write time so a rename doesn't break anything.
# The URL itself is built below from SHEET_ID (not hardcoded here) so there's
# one source of truth for the workbook ID.
PENDING_SHEET_GID = 2073293626

# A tab counts as a household sheet only if its header row contains ALL of
# these. Auto-skips Legend / To fix / Master Tracker / exports / etc., and
# auto-includes new households cloned from "Duplicate me".
HOUSEHOLD_HEADER_MARKERS = ["Amount paid (₹)", "Payment method"]

# Tabs to hide from the interactivity bot's household dropdown even though some
# of them DO carry the household header markers (the "Duplicate me" template and
# the frozen export tab in particular). Header-marker detection alone already
# skips Legend / To fix / Master Tracker; this set removes the rest so ops never
# see a non-household destination. Compared case-sensitively against tab titles.
EXCLUDED_HOUSEHOLD_TABS = frozenset({
    "To fix",
    "Legend",
    "Unrecorded transactions",
    "Duplicate me",
    "Wallet updates",
    "Master Tracker",
    "transactions-2026-06-01-to-2026-06-09",
})

# Exact header names to locate columns within a household sheet.
COL_DATE = "Date (double click)"
COL_PLATFORM = "Platform"
COL_AMOUNT = "Amount paid (₹)"
COL_PAYMENT = "Payment method"
COL_REMARK = "Remark"

# --- secrets / ids (from environment) ---------------------------------------
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
# App-level token (xapp-, scope connections:write) for Socket Mode. Only the
# interactivity bot needs it; the scheduled pipeline leaves it unset.
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")
# Channel IDs are NOT secrets (they appear in every message permalink), so they
# live here as defaults rather than as GitHub secrets -- keeping them out of the
# secrets set means their values aren't masked as *** in Actions logs, so the
# permalinks the bot builds are readable and verifiable. An env var still
# overrides if you ever need to point at a different channel.
OTP_CHANNEL_ID = os.environ.get("OTP_CHANNEL_ID", "C0ALWS4J0HZ")          # #otp-bridge
TRANSACTION_CHANNEL_ID = os.environ.get("TRANSACTION_CHANNEL_ID", "C0BGPNTRJLV")  # #transaction-bridge
SUMMARY_CHANNEL_ID = os.environ.get("SUMMARY_CHANNEL_ID", "")  # roundup channel
SHEET_ID = os.environ.get("SHEET_ID", "")
PENDING_SHEET_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
    f"?gid={PENDING_SHEET_GID}#gid={PENDING_SHEET_GID}") if SHEET_ID else ""
GOOGLE_SA_JSON_PATH = os.environ.get("GOOGLE_SA_JSON_PATH", "")  # empty -> ADC/WIF


# --- interactivity bot (Socket Mode) ----------------------------------------
# The always-on bot in interactivity/ that posts an interactive prompt for each
# #transaction-bridge confirmation and writes the chosen household's row on
# selection. Runs separately from the scheduled pipeline (see CLAUDE.md).

# Slack message-metadata event_type stamped on every prompt the bot posts. It
# ties a prompt back to its #transaction-bridge message (txn_ts) and carries the
# resolution state ("pending" | "logged" | "excluded"); both the bot (prompt
# de-duplication, used-OTP tracking) and the scheduled pipeline (reading bot
# exclusions) key off it.
PROMPT_EVENT_TYPE = "txn_prompt"

# Emoji the bot adds as a reaction on the TOP-LEVEL channel message once a
# household is chosen (the OTP parent for a credit-card reply, or the prompt
# itself for a standalone UPI prompt), so ops see "resolved & logged" at a
# glance without opening the thread. Name only, no colons (reactions.add).
PROMPT_REACTION = "white_check_mark"

# Poll cadence over #transaction-bridge. The lookback is wider than the interval
# so a skipped cycle self-heals on the next one (posted-prompt tracking stops a
# transaction ever getting two prompts). On a fresh start the bot only looks
# back BOT_START_LOOKBACK so a first deploy doesn't prompt weeks of backlog.
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "75"))
POLL_LOOKBACK_SECONDS = int(os.environ.get("POLL_LOOKBACK_SECONDS", "300"))
BOT_START_LOOKBACK_SECONDS = int(
    os.environ.get("BOT_START_LOOKBACK_SECONDS", "3600"))

# Only consider an #otp-bridge OTP the reply target for a card confirmation if
# it fired within this window BEFORE the confirmation (see otp_match).
OTP_MATCH_WINDOW_SECONDS = int(os.environ.get("OTP_MATCH_WINDOW_SECONDS", "1800"))

# Cloud Run requires the container to listen on $PORT even though the bot serves
# no real HTTP; a trivial health endpoint binds here.
HEALTH_PORT = int(os.environ.get("PORT", "8080"))

# Bot dry-run: prompts are posted and their messages still update so you can
# watch the full click flow, but the household-row Sheets write is printed
# instead of performed. Handy for a first smoke test against a scratch channel.
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
