from types import SimpleNamespace

from config import LOCAL_LLM_TIMEOUT_S
from core import local_llm


def test_main_local_fast_profile_uses_tighter_budget():
    profile = local_llm.session_profile("main_local_fast")
    assert profile["class"] == "local_fast"
    assert int(profile["max_tokens"]) == 220
    assert int(profile["timeout_s"]) < LOCAL_LLM_TIMEOUT_S


def test_run_local_completion_uses_profile_timeout(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(
            returncode=0,
            stdout="<<ASSISTANT_RESPONSE>>\nOK\n[ Prompt: 1.0 t/s | Generation: 1.0 t/s ]\nExiting...",
            stderr="",
        )

    monkeypatch.setattr(local_llm, "verify_local_runtime", lambda: None)
    monkeypatch.setattr(local_llm.subprocess, "run", fake_run)

    out = local_llm.run_local_completion(
        [{"role": "user", "content": "Respond with exactly OK"}],
        "main_local_fast",
    )

    assert out == "OK"
    assert captured["timeout"] == 14


def test_run_local_completion_defaults_to_global_timeout(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return SimpleNamespace(
            returncode=0,
            stdout="<<ASSISTANT_RESPONSE>>\nOK\n[ Prompt: 1.0 t/s | Generation: 1.0 t/s ]\nExiting...",
            stderr="",
        )

    monkeypatch.setattr(local_llm, "verify_local_runtime", lambda: None)
    monkeypatch.setattr(local_llm.subprocess, "run", fake_run)

    out = local_llm.run_local_completion(
        [{"role": "user", "content": "Respond with exactly OK"}],
        "unconfigured_session",
    )

    assert out == "OK"
    assert captured["timeout"] == LOCAL_LLM_TIMEOUT_S
