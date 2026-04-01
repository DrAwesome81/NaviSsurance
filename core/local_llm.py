import logging
import os
import re
import subprocess
from typing import Iterable

from config import (
    LOCAL_LLM_CHAT_TEMPLATE,
    LOCAL_LLM_CLI_PATH,
    LOCAL_LLM_CTX_SIZE,
    LOCAL_LLM_GPU_LAYERS,
    LOCAL_LLM_MODEL_PATH,
    LOCAL_LLM_TIMEOUT_S,
)

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_HISTORY_LIMIT = 10
_ASSISTANT_MARKER = "<<ASSISTANT_RESPONSE>>"

_SESSION_PROFILES: dict[str, dict[str, int | str]] = {
    "main_local_fast": {"class": "local_fast", "max_tokens": 220, "timeout_s": 14},
    "notes_session": {"class": "local_background", "max_tokens": 900},
    "briefing_session": {"class": "local_fast", "max_tokens": 260},
    "task_detection": {"class": "local_fast", "max_tokens": 8},
    "task_query": {"class": "local_fast", "max_tokens": 220},
    "user_memory_extract": {"class": "local_fast", "max_tokens": 180, "timeout_s": 12},
    "conversation_chunk_summarize": {"class": "local_fast", "max_tokens": 260, "timeout_s": 16},
    "memory_reflection": {"class": "local_fast", "max_tokens": 260, "timeout_s": 16},
    "doc_gen": {"class": "local_background", "max_tokens": 900},
}


def _extract_assistant_text(raw_output: str) -> str:
    text = (raw_output or "").strip()
    if not text:
        return ""
    prompt_idx = text.find("\n> ")
    if prompt_idx >= 0:
        prompt_body = text[prompt_idx + 3:]
        prompt_end = prompt_body.find("\n\n")
        if prompt_end >= 0:
            text = prompt_body[prompt_end + 2:].strip()
    marker = _ASSISTANT_MARKER
    idx = text.rfind(marker)
    if idx >= 0:
        text = text[idx + len(marker):].strip()
    if text.startswith("Conversation transcript:"):
        trunc_idx = text.rfind("... (truncated)")
        if trunc_idx >= 0:
            trimmed = text[trunc_idx + len("... (truncated)"):].strip()
            if trimmed:
                text = trimmed
    perf_marker = "[ Prompt:"
    perf_idx = text.rfind(perf_marker)
    if perf_idx >= 0:
        text = text[:perf_idx].strip()
    exit_idx = text.rfind("Exiting...")
    if exit_idx >= 0:
        text = text[:exit_idx].strip()
    text = re.sub(r"\[Start thinking\].*?\[End thinking\]\s*", "", text, flags=re.DOTALL).strip()
    if text.endswith(">"):
        text = text[:-1].rstrip()
    return text.strip()


def session_profile(session_id: str | None) -> dict[str, int | str]:
    sid = str(session_id or "").strip()
    if sid.startswith("notes_"):
        return dict(_SESSION_PROFILES["notes_session"])
    profile = _SESSION_PROFILES.get(sid)
    if profile:
        return dict(profile)
    return {"class": "local_fast", "max_tokens": 500, "timeout_s": LOCAL_LLM_TIMEOUT_S}


def verify_local_runtime() -> None:
    missing: list[str] = []
    if not os.path.exists(LOCAL_LLM_CLI_PATH):
        missing.append(f"llama-cli.exe not found at {LOCAL_LLM_CLI_PATH}")
    if not os.path.exists(LOCAL_LLM_MODEL_PATH):
        missing.append(f"Qwen model not found at {LOCAL_LLM_MODEL_PATH}")
    if missing:
        raise FileNotFoundError("; ".join(missing))


def _coerce_messages(messages: Iterable[dict] | None) -> list[dict]:
    out: list[dict] = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role in {"system", "user", "assistant"} and content:
            out.append({"role": role, "content": content})
    return out


def _trim_messages(messages: list[dict]) -> list[dict]:
    system_messages = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    if len(non_system) <= _HISTORY_LIMIT:
        return system_messages + non_system
    return system_messages + non_system[-_HISTORY_LIMIT:]


def build_local_prompt(messages: Iterable[dict] | None, session_id: str | None) -> str:
    trimmed = _trim_messages(_coerce_messages(messages))
    lines = [
        "/no_think",
        "You are writing the next assistant reply for NaviSsurance.",
        f"Session id: {str(session_id or '').strip() or 'default'}",
        "Follow system instructions exactly.",
        "If the latest instruction asks for JSON only, command lines only, or another strict format, return only that format.",
        "Do not explain your formatting choices.",
        "",
        "Conversation transcript:",
        "",
    ]
    for item in trimmed:
        lines.append(f"[{item['role'].upper()}]")
        lines.append(item["content"])
        lines.append("")
    lines.append("Write only the assistant reply after this marker.")
    lines.append(_ASSISTANT_MARKER)
    return "\n".join(lines).strip()


def run_local_completion(messages: Iterable[dict] | None, session_id: str | None) -> str:
    verify_local_runtime()
    profile = session_profile(session_id)
    timeout_s = int(profile.get("timeout_s", LOCAL_LLM_TIMEOUT_S))
    prompt = build_local_prompt(messages, session_id)
    command = [
        LOCAL_LLM_CLI_PATH,
        "--model",
        LOCAL_LLM_MODEL_PATH,
        "--log-disable",
        "--no-display-prompt",
        "--color",
        "off",
        "--device",
        "CUDA0",
        "--gpu-layers",
        str(LOCAL_LLM_GPU_LAYERS),
        "--ctx-size",
        str(LOCAL_LLM_CTX_SIZE),
        "--simple-io",
        "--single-turn",
        "--reasoning-budget",
        "0",
        "--temp",
        "0.2",
        "--top-p",
        "0.7",
        "--n-predict",
        str(int(profile.get("max_tokens", 500))),
        "--prompt",
        prompt,
        "--conversation",
        "--chat-template",
        LOCAL_LLM_CHAT_TEMPLATE,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout_s,
        creationflags=CREATE_NO_WINDOW,
    )
    stdout = _extract_assistant_text(completed.stdout or "")
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        detail = stderr or stdout or f"llama-cli exited with code {completed.returncode}"
        raise RuntimeError(detail)
    if not stdout:
        raise RuntimeError(stderr or "Local runtime returned empty output.")
    if stderr:
        logger.debug("local llama-cli stderr: %s", stderr[:400])
    return stdout
