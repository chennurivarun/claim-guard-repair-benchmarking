"""The compatible client must tolerate trailing chatter after the JSON object."""

import pytest

from app.llm.openai_compatible import _first_json_object


def test_plain_object_parses():
    assert _first_json_object('{"ok": "yes"}') == {"ok": "yes"}


def test_trailing_chatter_is_ignored():
    text = '{"ok": "yes", "n": 2}\nHope this helps! Let me know if you need more.'
    assert _first_json_object(text) == {"ok": "yes", "n": 2}


def test_leading_prose_before_object_is_skipped():
    text = 'Sure! Here is the JSON:\n{"ok": "yes"}'
    assert _first_json_object(text) == {"ok": "yes"}


def test_no_object_raises():
    with pytest.raises(ValueError):
        _first_json_object("no json here at all")
