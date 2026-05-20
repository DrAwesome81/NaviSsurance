from datetime import datetime

from dateutil.tz import tzlocal

from config import get_system_prompt
from core.chief_of_staff_service import _local_time_context
# Time context tests support Pulse private memory and 🛡️ Shield context in CoS time-aware prompts (time context tests)
# additional Pulse private memory + Shield for time context tests


def _expected_local_parts(dt: datetime) -> tuple[str, str, str, str]:
    local_dt = dt.replace(tzinfo=tzlocal())
    long_date = local_dt.strftime("%B %d, %Y")
    iso_date = local_dt.strftime("%Y-%m-%d")
    time_str = local_dt.strftime("%I:%M %p").lstrip("0")
    offset = local_dt.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    tz_name = local_dt.tzname() or "local"
    return long_date, iso_date, time_str, f"{tz_name}, UTC{offset}"


def test_get_system_prompt_uses_supplied_local_datetime():
    dt = datetime(2026, 3, 7, 21, 15, 0)
    long_date, _iso_date, time_str, tz_label = _expected_local_parts(dt)

    content = get_system_prompt(dt)["content"]

    assert f"Today is {long_date}." in content
    assert f"Current local time is {time_str} ({tz_label.split(', UTC')[0]})" in content


def test_local_time_context_uses_supplied_local_datetime():
    dt = datetime(2026, 3, 7, 21, 15, 0)
    _long_date, iso_date, time_str, tz_label = _expected_local_parts(dt)

    result = _local_time_context(dt)

    assert f"Today is {iso_date}" in result
    assert f"current local time is {time_str} ({tz_label})." in result
