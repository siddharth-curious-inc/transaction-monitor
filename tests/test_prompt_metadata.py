import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "interactivity"))

import blocks  # noqa: E402
from config import PROMPT_EVENT_TYPE  # noqa: E402
from slack_io import _prompt_state_from_msg  # noqa: E402


def test_block_ref_round_trips_all_fields():
    raw = blocks.block_ref("111.2", "999.8", channel="C1", msg_ts="333.4")
    got = blocks.parse_ref(raw)
    assert got == {"t": "111.2", "p": "999.8", "c": "C1", "m": "333.4"}


def test_block_ref_omits_empty_coords_for_in_message_use():
    got = blocks.parse_ref(blocks.block_ref("111.2"))
    assert got["t"] == "111.2" and got["p"] == ""
    assert got["c"] == "" and got["m"] == ""


def test_metadata_payload_is_flat():
    # Slack forbids nested objects / arrays-of-objects in event_payload.
    md = blocks.prompt_metadata("111.2", "logged", household="H", reason="r",
                                otp_parent_ts="999.8")
    assert md["event_type"] == PROMPT_EVENT_TYPE
    for v in md["event_payload"].values():
        assert isinstance(v, (str, int, float, bool))


def test_prompt_state_extracted_from_bot_message():
    msg = {"metadata": blocks.prompt_metadata(
        "111.2", "excluded", reason="refund", otp_parent_ts="999.8")}
    txn_ts, state = _prompt_state_from_msg(msg)
    assert txn_ts == "111.2"
    assert state["state"] == "excluded"
    assert state["reason"] == "refund"
    assert state["otp_parent_ts"] == "999.8"


def test_non_prompt_messages_are_ignored():
    assert _prompt_state_from_msg({}) == (None, None)
    assert _prompt_state_from_msg(
        {"metadata": {"event_type": "something_else",
                      "event_payload": {"txn_ts": "1"}}}) == (None, None)
    # our event_type but no txn_ts -> not usable
    assert _prompt_state_from_msg(
        {"metadata": {"event_type": PROMPT_EVENT_TYPE,
                      "event_payload": {}}}) == (None, None)
