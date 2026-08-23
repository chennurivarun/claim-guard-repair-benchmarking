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


def test_azure_v1_surface_never_gets_api_version():
    from app.llm.openai_compatible import _completion_url

    url = _completion_url(
        "https://ai-trans-aio-resource.services.ai.azure.com/openai/v1",
        "Llama-4-Maverick-17B-128E-Instruct-FP8",
        "2024-05-01-preview",
    )
    assert url == (
        "https://ai-trans-aio-resource.services.ai.azure.com/openai/v1/chat/completions"
    )
    assert "api-version" not in url


def test_classic_azure_deployment_path_keeps_api_version():
    from app.llm.openai_compatible import _completion_url

    url = _completion_url(
        "https://my-resource.openai.azure.com",
        "my-deployment",
        "2024-10-21",
    )
    assert "/openai/deployments/my-deployment/chat/completions" in url
    assert "api-version=2024-10-21" in url


def test_models_inference_path_keeps_api_version():
    from app.llm.openai_compatible import _completion_url

    url = _completion_url(
        "https://my-resource.services.ai.azure.com",
        "any-model",
        "2024-05-01-preview",
    )
    assert url.endswith("/models/chat/completions?api-version=2024-05-01-preview")
