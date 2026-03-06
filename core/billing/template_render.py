from __future__ import annotations

import re
from typing import Mapping

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def render_template(template_body: str, context: Mapping[str, str]) -> str:
    """
    Render a billing/invoice template using safe placeholder replacement.

    Supported syntax:
      - {{key}} where key is [a-zA-Z0-9_]+

    Rules:
      - Never executes code.
      - Unknown placeholders are left as-is so missing fields are visible.
    """
    body = str(template_body or "")
    if not body:
        return ""

    safe_context = {str(k): "" if v is None else str(v) for k, v in (context or {}).items()}

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key in safe_context:
            return safe_context[key]
        return m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, body)


def list_placeholders(template_body: str) -> list[str]:
    """Return unique placeholders found in template_body, in appearance order."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(str(template_body or "")):
        k = m.group(1)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out

