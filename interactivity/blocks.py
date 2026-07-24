"""Block Kit payloads for the interactivity bot: the interactive prompt, the
resolved / excluded / error variants it updates to, the remark modal, and the
Slack message-metadata stamped on every prompt.

Kept free of Slack/Sheets I/O so the shapes are unit-testable. The transaction
identity travels in the actions block's `block_id` (a tiny JSON of txn_ts +
otp_parent_ts); the handler re-fetches and re-parses the #transaction-bridge
message from txn_ts to recover the money/date fields, so the sheet write always
matches what the parser produced (no drift between prompt and write)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import PROMPT_EVENT_TYPE  # noqa: E402

SELECT_ACTION_ID = "household_select"
REMARK_ACTION_ID = "open_remark"
REMARK_MODAL_CALLBACK = "remark_submit"
REMARK_INPUT_BLOCK = "remark_block"
REMARK_INPUT_ACTION = "remark_text"
MODAL_SELECT_BLOCK = "household_block"
MODAL_SELECT_ACTION = "household_choice"
EXCLUDE_VALUE = "__exclude__"
EXCLUDE_LABEL = "🚫 Exclude — not a household transaction"


def block_ref(txn_ts, otp_parent_ts="", channel="", msg_ts=""):
    """Compact JSON stashed in the actions block_id / modal private_metadata.
    Small on purpose (block_id caps at 255, private_metadata at 3000).

    `channel`/`msg_ts` are only needed for the modal: a view_submission carries
    no reference to the message that opened it, so the prompt's own coords ride
    along to let the submit handler update it. In-message actions omit them --
    the action body already carries the container message + channel."""
    d = {"t": txn_ts, "p": otp_parent_ts or ""}
    if channel:
        d["c"] = channel
    if msg_ts:
        d["m"] = msg_ts
    return json.dumps(d, separators=(",", ":"))


def parse_ref(raw):
    """Inverse of block_ref. Returns a dict with keys t, p, c, m (missing -> '')."""
    d = json.loads(raw)
    return {"t": d.get("t", ""), "p": d.get("p", ""),
            "c": d.get("c", ""), "m": d.get("m", "")}


def prompt_metadata(txn_ts, state, household="", reason="", otp_parent_ts=""):
    """Slack message metadata for a prompt. event_payload is flat (Slack
    forbids nested objects). Re-sent verbatim on every chat.update, since
    chat.update drops metadata that isn't included."""
    return {
        "event_type": PROMPT_EVENT_TYPE,
        "event_payload": {
            "txn_ts": txn_ts,
            "state": state,
            "household": household or "",
            "reason": reason or "",
            "otp_parent_ts": otp_parent_ts or "",
        },
    }


def _emoji(rail_kind):
    return "💳" if rail_kind == "cc" else "🏦"


def _condensed(amount, payment_method, platform, ts, rail_kind):
    return (f"{_emoji(rail_kind)} *₹{amount:,.2f}* · {payment_method or '—'} · "
            f"{platform or '—'}\n{ts:%d %b %Y}, "
            f"{ts.hour % 12 or 12}:{ts:%M %p}")


def _household_options(households):
    opts = [{"text": {"type": "plain_text", "text": h[:75], "emoji": True},
             "value": h[:75]} for h in households]
    opts.append({"text": {"type": "plain_text", "text": EXCLUDE_LABEL,
                          "emoji": True}, "value": EXCLUDE_VALUE})
    return opts


def prompt_blocks(amount, payment_method, platform, ts, rail_kind, households,
                  txn_ts, otp_parent_ts=""):
    """The interactive prompt: condensed txn line + a household dropdown (with
    the Exclude option) and a Remark button, all sharing one actions block whose
    block_id carries the transaction ref."""
    return [
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": _condensed(amount, payment_method, platform, ts,
                                     rail_kind)}},
        {"type": "actions",
         "block_id": block_ref(txn_ts, otp_parent_ts),
         "elements": [
             {"type": "static_select",
              "action_id": SELECT_ACTION_ID,
              "placeholder": {"type": "plain_text",
                              "text": "Select household", "emoji": True},
              "options": _household_options(households)},
             {"type": "button",
              "action_id": REMARK_ACTION_ID,
              "text": {"type": "plain_text", "text": "Remark", "emoji": True},
              "value": "remark"},
         ]},
    ]


def resolved_blocks(amount, payment_method, platform, ts, rail_kind, household,
                    user_id, remark=""):
    """What a prompt becomes after a household is chosen: a ✅ line naming the
    household and the selecting user; interactive controls removed."""
    line = (f"{_condensed(amount, payment_method, platform, ts, rail_kind)}\n"
            f"✅ Logged to *{household}* by <@{user_id}>")
    if remark:
        line += f"\n📝 {remark}"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": line}}]


def excluded_blocks(amount, payment_method, platform, ts, rail_kind, user_id,
                    reason=""):
    """What a prompt becomes after Exclude: a 🚫 line; controls removed."""
    line = (f"{_condensed(amount, payment_method, platform, ts, rail_kind)}\n"
            f"🚫 Excluded by <@{user_id}>")
    if reason:
        line += f" — {reason}"
    return [{"type": "section", "text": {"type": "mrkdwn", "text": line}}]


def error_blocks(amount, payment_method, platform, ts, rail_kind, message):
    """A prompt updated to show a write failure, keeping the controls so ops can
    retry. Never fail silently."""
    line = (f"{_condensed(amount, payment_method, platform, ts, rail_kind)}\n"
            f"⚠️ {message}")
    return [{"type": "section", "text": {"type": "mrkdwn", "text": line}}]


def remark_modal_view(txn_ts, otp_parent_ts, channel, msg_ts, households):
    """Modal opened by the Remark button: household dropdown + an optional
    free-text remark (input blocks are modal-only). private_metadata carries the
    transaction ref AND the prompt message's coords through to the
    view_submission handler (which otherwise couldn't find the message)."""
    return {
        "type": "modal",
        "callback_id": REMARK_MODAL_CALLBACK,
        "private_metadata": block_ref(txn_ts, otp_parent_ts, channel, msg_ts),
        "title": {"type": "plain_text", "text": "Log transaction"},
        "submit": {"type": "plain_text", "text": "Log"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "input",
             "block_id": MODAL_SELECT_BLOCK,
             "label": {"type": "plain_text", "text": "Household"},
             "element": {
                 "type": "static_select",
                 "action_id": MODAL_SELECT_ACTION,
                 "placeholder": {"type": "plain_text",
                                 "text": "Select household", "emoji": True},
                 "options": _household_options(households)}},
            {"type": "input",
             "block_id": REMARK_INPUT_BLOCK,
             "optional": True,
             "label": {"type": "plain_text", "text": "Remark (optional)"},
             "element": {"type": "plain_text_input",
                         "action_id": REMARK_INPUT_ACTION,
                         "multiline": False}},
        ],
    }
