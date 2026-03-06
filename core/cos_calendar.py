from __future__ import annotations

import os
import pickle
from datetime import datetime, timedelta, timezone
from typing import Any


def _config_paths() -> tuple[str, str]:
    from config import CONFIG_DIR

    token_path = os.path.join(CONFIG_DIR, "navi_token.pkl")
    client_secret_path = os.path.join(CONFIG_DIR, "client_secret.json")
    return token_path, client_secret_path


def calendar_available() -> tuple[bool, str]:
    """
    Read-only calendar availability check.
    Return (ok, message). This is intentionally conservative to avoid triggering OAuth flows.
    """
    try:
        import google  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
        from google.auth.transport.requests import Request  # noqa: F401
    except Exception:
        return False, "Google Calendar dependencies not installed."

    token_path, _ = _config_paths()
    if not os.path.exists(token_path):
        return False, "Google token file not found (config/navi_token.pkl)."
    return True, ""


def _load_creds(token_path: str):
    from google.auth.transport.requests import Request

    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
        creds.refresh(Request())
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
    return creds


_WRITE_SCOPES: set[str] = {
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.events.owned",
}


def calendar_write_available() -> tuple[bool, str]:
    """
    Write-capability check for creating events.
    Returns (ok, message). Never triggers interactive OAuth.
    """
    ok, msg = calendar_available()
    if not ok:
        return False, msg
    token_path, _ = _config_paths()
    try:
        creds = _load_creds(token_path)
    except Exception as e:
        return False, f"Could not load Google token file: {e}"

    scopes = set(getattr(creds, "scopes", None) or [])
    # Some credential objects may not expose scopes; in that case we can't preflight.
    if not scopes:
        return True, ""
    if scopes.intersection(_WRITE_SCOPES):
        return True, ""
    return (
        False,
        "Google token is missing Calendar write scope. Re-authorize with "
        "'https://www.googleapis.com/auth/calendar' (delete config/navi_token.pkl and re-auth).",
    )


def get_calendar_events(
    *,
    time_min: str,
    time_max: str,
    max_calendars: int = 50,
) -> list[dict[str, Any]]:
    """
    Read-only calendar event fetcher.
    Returns events across selected, non-hidden calendars.
    """
    ok, msg = calendar_available()
    if not ok:
        return []

    from googleapiclient.discovery import build

    token_path, _ = _config_paths()
    creds = _load_creds(token_path)
    service = build("calendar", "v3", credentials=creds)

    all_events: list[dict[str, Any]] = []
    cal_list = service.calendarList().list().execute().get("items", [])[:max_calendars]
    for cal in cal_list:
        try:
            if not cal.get("selected", False) or cal.get("hidden", False):
                continue
            events = (
                service.events()
                .list(
                    calendarId=cal["id"],
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
                .get("items", [])
            )
            for event in events:
                if event.get("transparency") == "transparent":
                    continue
                event["calendarName"] = cal.get("summary", "Unknown Calendar")
                all_events.append(event)
        except Exception:
            continue

    def _sort_key(e):
        start = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date") or ""
        return start

    all_events.sort(key=_sort_key)
    return all_events


def create_calendar_event(
    *,
    summary: str,
    start_dt: datetime,
    end_dt: datetime,
    calendar_id: str = "primary",
    description: str = "",
) -> tuple[bool, str, dict[str, Any] | None]:
    """
    Create a Google Calendar event.
    Returns (ok, message, created_event_dict_or_none).
    """
    ok, msg = calendar_write_available()
    if not ok:
        return False, msg, None

    title = (summary or "").strip()
    if not title:
        return False, "Event title is required.", None
    if end_dt <= start_dt:
        return False, "Event end time must be after start time.", None

    # If caller passes naive datetimes, assume local timezone.
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=local_tz)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=local_tz)

    try:
        from googleapiclient.discovery import build

        token_path, _ = _config_paths()
        creds = _load_creds(token_path)
        service = build("calendar", "v3", credentials=creds)

        event_body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start_dt.isoformat()},
            "end": {"dateTime": end_dt.isoformat()},
        }
        if description:
            event_body["description"] = str(description).strip()

        created = (
            service.events()
            .insert(calendarId=(calendar_id or "primary").strip(), body=event_body)
            .execute()
        )
        return True, "", created
    except Exception as e:
        return False, f"Failed to create calendar event: {e}", None


def format_events_brief(events: list[dict[str, Any]], tz=timezone.utc) -> str:
    """
    Convert Google Calendar API events into compact bullet list.
    """
    if not events:
        return "No meetings scheduled."
    lines = []
    for e in events[:20]:
        start = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date")
        summary = e.get("summary") or "Untitled Event"
        cal = e.get("calendarName") or "Calendar"
        time_str = ""
        try:
            if start and "T" in start:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                time_str = dt.astimezone(tz).strftime("%I:%M %p").lstrip("0")
            else:
                time_str = "All day"
        except Exception:
            time_str = str(start or "")
        lines.append(f"- {time_str}: {summary} ({cal})")
    return "\n".join(lines)

