"""Bolt interaction handlers. Every handler ack()s within Slack's 3s deadline
BEFORE any Sheets/Slack work (CLAUDE.md), then delegates to service.py.

Three interactions:
  * household_select  -- static_select in the prompt: log (or exclude) at once.
  * open_remark       -- button: open the remark modal (must beat the 3s
                         trigger_id expiry, so households are served from cache).
  * remark_submit     -- modal submit: log (or exclude) with the typed remark.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import blocks  # noqa: E402
import service  # noqa: E402
from households import get_households  # noqa: E402

RESOLVED = ("logged", "excluded")


def _current_state(body):
    """Resolution state of the interacted message from its metadata, if Slack
    included it in the payload. Best-effort double-submit guard: two ops both
    seeing the still-pending prompt is still possible, but append is atomic so
    the worst case is a rare duplicate row, not a corrupted one."""
    md = (body.get("message") or {}).get("metadata") or {}
    return (md.get("event_payload") or {}).get("state", "")


def _apply(client, ref, prompt_channel, prompt_ts, choice, user_id, remark):
    """Shared tail for both the dropdown and the modal: load the txn and either
    log it to a household or record an exclusion."""
    otp = service.load_txn(client, ref["t"])
    if otp is None:
        client.chat_update(
            channel=prompt_channel, ts=prompt_ts,
            text="Could not load transaction",
            blocks=[{"type": "section", "text": {"type": "mrkdwn",
                     "text": "⚠️ Couldn't re-read this transaction to log it. "
                             "Please handle it manually."}}])
        return
    if choice == blocks.EXCLUDE_VALUE:
        service.exclude(client, otp, ref, prompt_channel, prompt_ts, user_id,
                        reason=remark)
    else:
        service.log_household(client, otp, ref, prompt_channel, prompt_ts,
                              choice, user_id, remark)


def register(app):
    @app.action(blocks.SELECT_ACTION_ID)
    def household_selected(ack, body, client, logger):
        ack()
        try:
            if _current_state(body) in RESOLVED:
                return  # someone already handled it
            action = body["actions"][0]
            ref = blocks.parse_ref(action["block_id"])
            choice = action["selected_option"]["value"]
            _apply(client, ref,
                   body["channel"]["id"], body["message"]["ts"],
                   choice, body["user"]["id"], remark="")
        except Exception:  # noqa: BLE001
            logger.exception("household_selected failed")

    @app.action(blocks.REMARK_ACTION_ID)
    def open_remark(ack, body, client, logger):
        ack()
        try:
            ref = blocks.parse_ref(body["actions"][0]["block_id"])
            view = blocks.remark_modal_view(
                ref["t"], ref["p"], body["channel"]["id"],
                body["message"]["ts"], get_households())
            client.views_open(trigger_id=body["trigger_id"], view=view)
        except Exception:  # noqa: BLE001
            logger.exception("open_remark failed")

    @app.view(blocks.REMARK_MODAL_CALLBACK)
    def remark_submitted(ack, body, view, client, logger):
        ack()
        try:
            ref = blocks.parse_ref(view["private_metadata"])
            values = view["state"]["values"]
            choice = (values[blocks.MODAL_SELECT_BLOCK][blocks.MODAL_SELECT_ACTION]
                      ["selected_option"]["value"])
            remark = (values[blocks.REMARK_INPUT_BLOCK][blocks.REMARK_INPUT_ACTION]
                      .get("value") or "")
            _apply(client, ref, ref["c"], ref["m"], choice,
                   body["user"]["id"], remark)
        except Exception:  # noqa: BLE001
            logger.exception("remark_submitted failed")
