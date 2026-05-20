"""
Application preferences stored in SQLite (`app_settings`), editable from Settings in the GUI.

`config/.env` is reserved for secrets only (API keys, tokens, passwords). Non-secret toggles
and tuning values live here. On first startup after upgrade, values are copied from legacy
environment variables if present and the DB key is still unset.
(Pulse/Intel watch settings, CoS briefings, Shield security prefs can be tuned here.)
"""

from __future__ import annotations

import os
from typing import Optional

from core.db import DatabaseManager

# App prefs now include explicit keys for Pulse private memory and Shield security (additional prefs coordination)
# New: prefs now explicitly support Pulse private memory consumption for Shield (additional prefs spot)
KEY_RUNTIME_ENABLED = "navi_runtime_enabled"
KEY_RUNTIME_POLL_S = "navi_runtime_poll_interval_s"
KEY_RUNTIME_LEASE_S = "navi_runtime_job_lease_s"
KEY_LOCAL_API_ENABLED = "navi_local_api_enabled"
KEY_LOCAL_API_HOST = "navi_local_api_host"
KEY_LOCAL_API_PORT = "navi_local_api_port"
KEY_LOCAL_API_LOG_LEVEL = "navi_local_api_log_level"
KEY_TELEGRAM_ENABLED = "navi_telegram_bot_enabled"
KEY_TELEGRAM_CHAT_IDS = "navi_telegram_allowed_chat_ids"
KEY_COS_PASSIVE_MEMORY = "navi_cos_passive_memory_extraction"
KEY_BRIEFING_DISABLED = "briefing_and_email_disabled"
KEY_LOCAL_LLM_GPU = "local_llm_gpu_layers"
KEY_LOCAL_LLM_CTX = "local_llm_ctx_size"
KEY_LOCAL_LLM_TIMEOUT = "local_llm_timeout_s"
KEY_CHAT_HISTORY_RENDER_LIMIT = "chat_history_render_limit"

# Chief of Staff performance (context windowing + output caps)
KEY_COS_MAX_OUTPUT_TOKENS = "cos_max_output_tokens"
KEY_COS_MEMORY_MAX_OUTPUT_TOKENS = "cos_memory_max_output_tokens"
KEY_COS_CONTEXT_BUDGET_CHARS = "cos_context_budget_chars"
KEY_COS_HISTORY_MAX_MESSAGES = "cos_history_max_messages"
KEY_COS_HISTORY_MAX_CHARS = "cos_history_max_chars_per_message"
KEY_COS_PREFS_MAX_CHARS = "cos_preferences_max_chars"
KEY_COS_CALENDAR_MAX_CHARS = "cos_calendar_max_chars"
KEY_COS_MEMORY_BLOCK_MAX_CHARS = "cos_memory_context_max_chars"
KEY_COS_MAX_TASK_LINES = "cos_max_task_lines"
KEY_COS_MAX_ASSIGNMENT_LINES = "cos_max_assignment_lines"
KEY_COS_EMAILS_MAX_CHARS = "cos_emails_context_max_chars"
# Pulse/Shield prefs integration point

# Client Dossier navigation behavior
KEY_CLIENT_DOSSIER_NAV_MODE = "client_dossier_navigation_mode"  # "light" or "strong"

# Phase 4 related document sets / Workspace Production: persistable session toggle for auto GDrive client-folder uploads (used by quick-export + manifest/summary writes on set generation). Default ON for high-leverage traceability.
KEY_GDRIVE_AUTO_UPLOAD_ENABLED = "gdrive_auto_upload_enabled"


def _db(db: Optional[DatabaseManager] = None) -> DatabaseManager:
    return db if db is not None else DatabaseManager()


def _truthy(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y", "on")


def _get_raw(db: Optional[DatabaseManager], key: str) -> Optional[str]:
    v = _db(db).get_setting(key, None)
    if v is None:
        return None
    vs = str(v).strip()
    return vs if vs != "" else None


def migrate_legacy_env_preferences(db: Optional[DatabaseManager] = None) -> None:
    """If a preference key is unset in the DB but a legacy env var exists, copy it once."""
    d = _db(db)
    mappings: list[tuple[str, str]] = [
        (KEY_RUNTIME_ENABLED, "NAVI_RUNTIME_ENABLED"),
        (KEY_RUNTIME_POLL_S, "NAVI_RUNTIME_POLL_INTERVAL_S"),
        (KEY_RUNTIME_LEASE_S, "NAVI_RUNTIME_JOB_LEASE_S"),
        (KEY_LOCAL_API_ENABLED, "NAVI_LOCAL_API_ENABLED"),
        (KEY_LOCAL_API_HOST, "NAVI_LOCAL_API_HOST"),
        (KEY_LOCAL_API_PORT, "NAVI_LOCAL_API_PORT"),
        (KEY_LOCAL_API_LOG_LEVEL, "NAVI_LOCAL_API_LOG_LEVEL"),
        (KEY_TELEGRAM_ENABLED, "NAVI_TELEGRAM_BOT_ENABLED"),
        (KEY_TELEGRAM_CHAT_IDS, "NAVI_TELEGRAM_ALLOWED_CHAT_IDS"),
        (KEY_COS_PASSIVE_MEMORY, "NAVI_COS_PASSIVE_MEMORY_EXTRACTION"),
        (KEY_BRIEFING_DISABLED, "BRIEFING_AND_EMAIL_DISABLED"),
        (KEY_LOCAL_LLM_GPU, "LOCAL_LLM_GPU_LAYERS"),
        (KEY_LOCAL_LLM_CTX, "LOCAL_LLM_CTX_SIZE"),
        (KEY_LOCAL_LLM_TIMEOUT, "LOCAL_LLM_TIMEOUT_S"),
        (KEY_CHAT_HISTORY_RENDER_LIMIT, "CHAT_HISTORY_RENDER_LIMIT"),
        (KEY_COS_MAX_OUTPUT_TOKENS, "COS_MAX_OUTPUT_TOKENS"),
        (KEY_COS_MEMORY_MAX_OUTPUT_TOKENS, "COS_MEMORY_MAX_OUTPUT_TOKENS"),
        (KEY_COS_CONTEXT_BUDGET_CHARS, "COS_CONTEXT_BUDGET_CHARS"),
        (KEY_COS_HISTORY_MAX_MESSAGES, "COS_HISTORY_MAX_MESSAGES"),
        (KEY_COS_HISTORY_MAX_CHARS, "COS_HISTORY_MAX_CHARS_PER_MESSAGE"),
        (KEY_COS_PREFS_MAX_CHARS, "COS_PREFERENCES_MAX_CHARS"),
        (KEY_COS_CALENDAR_MAX_CHARS, "COS_CALENDAR_MAX_CHARS"),
        (KEY_COS_MEMORY_BLOCK_MAX_CHARS, "COS_MEMORY_CONTEXT_MAX_CHARS"),
        (KEY_COS_MAX_TASK_LINES, "COS_MAX_TASK_LINES"),
        (KEY_COS_MAX_ASSIGNMENT_LINES, "COS_MAX_ASSIGNMENT_LINES"),
        (KEY_COS_EMAILS_MAX_CHARS, "COS_EMAILS_MAX_CHARS"),
    ]
    for key, env_name in mappings:
        if _get_raw(db, key) is not None:
            continue
        raw = os.getenv(env_name)
        if raw is None or str(raw).strip() == "":
            continue
        d.set_setting(key, str(raw).strip())


def is_runtime_enabled(db: Optional[DatabaseManager] = None) -> bool:
    v = _get_raw(db, KEY_RUNTIME_ENABLED)
    if v is None:
        return True
    return _truthy(v)


def get_runtime_poll_interval_s(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_RUNTIME_POLL_S)
    try:
        return max(5, int(v)) if v is not None else 30
    except Exception:
        return 30


def get_runtime_job_lease_s(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_RUNTIME_LEASE_S)
    try:
        return max(30, int(v)) if v is not None else 300
    except Exception:
        return 300


def is_local_api_enabled(db: Optional[DatabaseManager] = None) -> bool:
    v = _get_raw(db, KEY_LOCAL_API_ENABLED)
    if v is None:
        return False
    return _truthy(v)


def get_local_api_host(db: Optional[DatabaseManager] = None) -> str:
    v = _get_raw(db, KEY_LOCAL_API_HOST)
    return v if v else "127.0.0.1"


def get_local_api_port(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_LOCAL_API_PORT)
    try:
        return int(v) if v is not None else 8765
    except Exception:
        return 8765


def get_local_api_log_level(db: Optional[DatabaseManager] = None) -> str:
    v = _get_raw(db, KEY_LOCAL_API_LOG_LEVEL)
    return (v or "warning").strip() or "warning"


def is_telegram_bot_feature_enabled(db: Optional[DatabaseManager] = None) -> bool:
    v = _get_raw(db, KEY_TELEGRAM_ENABLED)
    if v is None:
        return False
    return _truthy(v)


def get_telegram_allowed_chat_ids(db: Optional[DatabaseManager] = None) -> list[str]:
    raw = _get_raw(db, KEY_TELEGRAM_CHAT_IDS)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def is_cos_passive_memory_extraction_enabled(db: Optional[DatabaseManager] = None) -> bool:
    v = _get_raw(db, KEY_COS_PASSIVE_MEMORY)
    if v is None:
        return True
    return _truthy(v)


def is_briefing_and_email_disabled(db: Optional[DatabaseManager] = None) -> bool:
    v = _get_raw(db, KEY_BRIEFING_DISABLED)
    if v is None:
        return False
    return _truthy(v)


def get_local_llm_gpu_layers(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_LOCAL_LLM_GPU)
    try:
        return int(v) if v is not None else 33
    except Exception:
        return 33


def get_local_llm_ctx_size(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_LOCAL_LLM_CTX)
    try:
        return int(v) if v is not None else 8192
    except Exception:
        return 8192


def get_local_llm_timeout_s(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_LOCAL_LLM_TIMEOUT)
    try:
        return int(v) if v is not None else 180
    except Exception:
        return 180


def get_chat_history_render_limit(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_CHAT_HISTORY_RENDER_LIMIT)
    try:
        return max(10, int(v)) if v is not None else 40
    except Exception:
        return 40


def get_cos_max_output_tokens(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_MAX_OUTPUT_TOKENS)
    try:
        n = int(v) if v is not None else 4096
        return max(256, min(32768, n))
    except Exception:
        return 4096


def get_cos_memory_max_output_tokens(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_MEMORY_MAX_OUTPUT_TOKENS)
    try:
        n = int(v) if v is not None else 1200
        return max(256, min(8192, n))
    except Exception:
        return 1200


def get_cos_context_budget_chars(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_CONTEXT_BUDGET_CHARS)
    try:
        n = int(v) if v is not None else 34000
        return max(4000, min(120000, n))
    except Exception:
        return 34000


def get_cos_history_max_messages(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_HISTORY_MAX_MESSAGES)
    try:
        n = int(v) if v is not None else 5
        return max(2, min(24, n))
    except Exception:
        return 5


def get_cos_history_max_chars_per_message(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_HISTORY_MAX_CHARS)
    try:
        n = int(v) if v is not None else 800
        return max(200, min(8000, n))
    except Exception:
        return 800


def get_cos_preferences_max_chars(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_PREFS_MAX_CHARS)
    try:
        n = int(v) if v is not None else 6000
        return max(500, min(50000, n))
    except Exception:
        return 6000


def get_cos_calendar_max_chars(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_CALENDAR_MAX_CHARS)
    try:
        n = int(v) if v is not None else 4500
        return max(500, min(50000, n))
    except Exception:
        return 4500


def get_cos_memory_context_max_chars(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_MEMORY_BLOCK_MAX_CHARS)
    try:
        n = int(v) if v is not None else 5500
        return max(500, min(80000, n))
    except Exception:
        return 5500


def get_cos_max_task_lines(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_MAX_TASK_LINES)
    try:
        n = int(v) if v is not None else 32
        return max(5, min(80, n))
    except Exception:
        return 32


def get_cos_max_assignment_lines(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_MAX_ASSIGNMENT_LINES)
    try:
        n = int(v) if v is not None else 36
        return max(5, min(100, n))
    except Exception:
        return 36


def get_cos_emails_context_max_chars(db: Optional[DatabaseManager] = None) -> int:
    v = _get_raw(db, KEY_COS_EMAILS_MAX_CHARS)
    try:
        n = int(v) if v is not None else 4000
        return max(500, min(50000, n))
    except Exception:
        return 4000


# --- Client Dossier Navigation Mode ---

def get_client_dossier_navigation_mode(db: Optional[DatabaseManager] = None) -> str:
    """Returns 'light' or 'strong'. 'strong' = more automatic client focus when jumping from Clients tab."""
    v = _get_raw(db, KEY_CLIENT_DOSSIER_NAV_MODE)
    if v and str(v).strip().lower() in ("strong", "auto", "aggressive"):
        return "strong"
    return "light"


def set_client_dossier_navigation_mode(mode: str, db: Optional[DatabaseManager] = None) -> None:
    val = "strong" if str(mode).strip().lower() in ("strong", "auto", "aggressive") else "light"
    _db(db).set_setting(KEY_CLIENT_DOSSIER_NAV_MODE, val)


# --- GDrive auto-upload for cluster / Related Document Set exports (Phase 4 continuation) ---
# Persists the toggle (default True) so user preference for auto client-folder + manifest/summary upload survives restarts.
# Used by workspace quick-export paths to ensure set deliverables + cross-ref artifacts reliably reach GDrive for traceability.

def is_gdrive_auto_upload_enabled(db: Optional[DatabaseManager] = None) -> bool:
    v = _get_raw(db, KEY_GDRIVE_AUTO_UPLOAD_ENABLED)
    if v is None:
        return True
    return _truthy(v)


def set_gdrive_auto_upload_enabled(enabled: bool, db: Optional[DatabaseManager] = None) -> None:
    _db(db).set_setting(KEY_GDRIVE_AUTO_UPLOAD_ENABLED, "1" if bool(enabled) else "0")
