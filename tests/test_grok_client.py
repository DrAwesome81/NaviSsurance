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
