from __future__ import annotations

import sys
import types

from core import grok_client


def test_get_api_key_prefers_xai_over_grok(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "grok-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-key")
    assert grok_client._get_api_key() == "xai-key"


def test_grok_available_false_when_key_missing_with_sdk_present(monkeypatch):
    fake_xai = types.SimpleNamespace(Client=object)
    monkeypatch.setitem(sys.modules, "xai_sdk", fake_xai)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)

    ok, msg = grok_client.grok_available()
    assert ok is False
    assert "not set" in msg.lower()


def test_grok_available_true_with_sdk_and_key(monkeypatch):
    fake_xai = types.SimpleNamespace(Client=object)
    monkeypatch.setitem(sys.modules, "xai_sdk", fake_xai)
    monkeypatch.setenv("GROK_API_KEY", "abc")

    ok, msg = grok_client.grok_available()
    assert ok is True
    assert msg == ""


def test_grok_completion_messages_maps_roles_and_returns_content(monkeypatch):
    class _Resp:
        content = "assistant output"

    class _ChatSession:
        def __init__(self):
            self.appended = []

        def append(self, item):
            self.appended.append(item)

        def sample(self):
            return _Resp()

    class _Client:
        last_chat = None

        def __init__(self, api_key=None, timeout=0):
            self.chat = self

        def create(self, model=None, store_messages=False):
            _Client.last_chat = _ChatSession()
            return _Client.last_chat

    fake_chat_mod = types.SimpleNamespace(
        system=lambda text: ("system", text),
        user=lambda text: ("user", text),
        assistant=lambda text: ("assistant", text),
    )
    fake_xai_mod = types.SimpleNamespace(Client=_Client)
    monkeypatch.setitem(sys.modules, "xai_sdk", fake_xai_mod)
    monkeypatch.setitem(sys.modules, "xai_sdk.chat", fake_chat_mod)
    monkeypatch.setenv("GROK_API_KEY", "abc")

    out = grok_client.grok_completion_messages(
        [
            {"role": "system", "content": "s1"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "   "},  # ignored empty
        ],
        model="fake-model",
    )

    assert out == "assistant output"
    assert _Client.last_chat is not None
    assert _Client.last_chat.appended == [("system", "s1"), ("user", "u1"), ("assistant", "a1")]


def test_format_grok_user_facing_error_transient_service():
    err = RuntimeError('status = StatusCode.INTERNAL details = "Service temporarily unavailable."')
    msg = grok_client.format_grok_user_facing_error(err)
    assert "temporarily unavailable" in msg.lower()
    assert "1–2 minutes" in msg or "1-2 minutes" in msg


def test_format_grok_user_facing_error_other_truncates():
    err = RuntimeError("x" * 300)
    msg = grok_client.format_grok_user_facing_error(err)
    assert msg.startswith("Grok error:")
    assert len(msg) < 200


def test_is_transient_grok_error_detects_internal_service_message():
    err = RuntimeError('status = StatusCode.INTERNAL details = "Service temporarily unavailable."')
    assert grok_client.is_transient_grok_error(err) is True


def test_is_user_facing_llm_failure_message_detects_formatted_grok_errors():
    assert grok_client.is_user_facing_llm_failure_message(
        "Could not complete the request right now — xAI/Grok is temporarily unavailable "
        "or the network had a hiccup. Please try again in 1–2 minutes."
    )
    assert grok_client.is_user_facing_llm_failure_message(
        "xAI/Grok service is temporarily unavailable. Please wait 1–2 minutes and try again."
    )
    assert grok_client.is_user_facing_llm_failure_message("Request timed out. Try again.")
    assert grok_client.is_user_facing_llm_failure_message(
        "Rate limit or quota reached. Check your xAI credits."
    )
    assert grok_client.is_user_facing_llm_failure_message("Grok error: boom")
    assert grok_client.is_user_facing_llm_failure_message("Failed to process request: boom")
    assert grok_client.is_user_facing_llm_failure_message("Error: something went wrong")
    assert grok_client.is_user_facing_llm_failure_message("❌ Failed to process request: x")
    assert not grok_client.is_user_facing_llm_failure_message("Here is your plan for today.")
    assert not grok_client.is_user_facing_llm_failure_message("")


def test_grok_completion_retries_on_transient_error(monkeypatch):
    class _Resp:
        content = "ok"

    calls = {"n": 0}

    class _Chat:
        def sample(self):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError(
                    'status = StatusCode.INTERNAL details = "Service temporarily unavailable."'
                )
            return _Resp()

    class _Client:
        def __init__(self, api_key=None, timeout=0):
            pass

        @property
        def chat(self):
            return self

        def create(self, **kwargs):
            return _Chat()

    fake_chat_mod = types.SimpleNamespace(
        system=lambda text: ("system", text),
        user=lambda text: ("user", text),
    )
    fake_xai_mod = types.SimpleNamespace(Client=_Client)
    monkeypatch.setitem(sys.modules, "xai_sdk", fake_xai_mod)
    monkeypatch.setitem(sys.modules, "xai_sdk.chat", fake_chat_mod)
    monkeypatch.setenv("GROK_API_KEY", "abc")
    monkeypatch.setattr(grok_client, "_grok_completion_max_attempts", lambda: 3)
    monkeypatch.setattr(grok_client.time, "sleep", lambda _s: None)

    out = grok_client.grok_completion("sys", "user")
    assert out == "ok"
    assert calls["n"] == 3
