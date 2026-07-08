import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from slack_io import _reply_text  # noqa: E402


def test_reply_text_does_not_duplicate_text_and_blocks():
    msg = {
        "text": "Disha Anirudh",
        "blocks": [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [{"type": "text", "text": "Disha Anirudh"}],
                    }
                ],
            }
        ],
    }
    assert _reply_text(msg) == "Disha Anirudh"


def test_reply_text_falls_back_to_blocks_when_text_empty():
    msg = {
        "text": "",
        "blocks": [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [{"type": "text", "text": "refund issued"}],
                    }
                ],
            }
        ],
    }
    assert _reply_text(msg) == "refund issued"
