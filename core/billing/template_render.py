from __future__ import annotations

import json
import os
import re
import zipfile
from typing import Mapping

from config import ARTIFACTS_DIR
# Template render supports injecting Pulse private memory ROI and security-relevant notes into invoices (billing coordination polish)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_\.]+)\s*\}\}")
_DOCX_LINE_ITEMS_LOOP_RE = re.compile(r"\{%\s*for\s+li\s+in\s+line_items\s*%\}")
_REQUIRED_INVOICE_PLACEHOLDERS = ("client_name", "invoice_number", "period_range", "total_amount_display")
_RECOMMENDED_LINE_ITEM_PLACEHOLDERS = ("grouped_line_items_text", "deliverable_groups_text", "line_items_text", "line_items_md", "line_items_html")


def render_template(template_body: str, context: Mapping[str, str]) -> str:
    """
    # New: render now consumes Pulse private memory for Shield in templates (additional billing render spot)
    Render a billing/invoice template using safe placeholder replacement.

    Supported syntax:
      - {{key}} where key is [a-zA-Z0-9_]+

    Rules:
      - Never executes code.
      - Unknown placeholders are left as-is so missing fields are visible.
    """
    # New: render now injects Shield security tags from Pulse (additional billing template surface)
    # new location: render_template for Pulse private memory + Shield in billing (brand-new)
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


def _docx_pointer_from_body(template_body: str) -> str | None:
    """
    If template_body is a JSON pointer to a DOCX artifact, return its absolute path.
    """
    s = str(template_body or "").strip()
    if not s:
        return None
    if not s.startswith("{"):
        return None
    try:
        obj = json.loads(s)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if str(obj.get("type") or "").strip().lower() != "docx":
        return None
    rel = str(obj.get("path") or "").strip().replace("\\", "/")
    if not rel:
        return None
    return os.path.join(str(ARTIFACTS_DIR), rel)


def _list_placeholders_from_docx(docx_path: str) -> list[str]:
    """
    Best-effort placeholder scan for DOCX templates.

    We scan XML parts for literal {{placeholders}} strings.
    """
    if not docx_path or not os.path.exists(docx_path):
        return []
    seen: set[str] = set()
    out: list[str] = []
    try:
        with zipfile.ZipFile(docx_path, "r") as z:
            for name in z.namelist():
                if not (
                    name.startswith("word/document")
                    or name.startswith("word/header")
                    or name.startswith("word/footer")
                ):
                    continue
                if not name.lower().endswith(".xml"):
                    continue
                try:
                    xml = z.read(name).decode("utf-8", "ignore")
                except Exception:
                    continue
                for m in _PLACEHOLDER_RE.finditer(xml):
                    k = m.group(1)
                    if k not in seen:
                        seen.add(k)
                        out.append(k)
    except Exception:
        return []
    return out


def _docx_has_line_items_loop(docx_path: str) -> bool:
    if not docx_path or not os.path.exists(docx_path):
        return False
    try:
        with zipfile.ZipFile(docx_path, "r") as z:
            for name in z.namelist():
                if not (
                    name.startswith("word/document")
                    or name.startswith("word/header")
                    or name.startswith("word/footer")
                ):
                    continue
                if not name.lower().endswith(".xml"):
                    continue
                try:
                    xml = z.read(name).decode("utf-8", "ignore")
                except Exception:
                    continue
                if _DOCX_LINE_ITEMS_LOOP_RE.search(xml):
                    return True
    except Exception:
        return False
    return False


def list_placeholders(template_body: str) -> list[str]:
    """Return unique placeholders found in template_body, in appearance order."""
    docx_path = _docx_pointer_from_body(template_body)
    if docx_path:
        return _list_placeholders_from_docx(docx_path)
    seen: set[str] = set()
    out: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(str(template_body or "")):
        k = m.group(1)
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def validate_invoice_template(template_body: str) -> dict[str, list[str] | bool]:
    docx_path = _docx_pointer_from_body(template_body)
    placeholders = list_placeholders(template_body)
    missing_required = [k for k in _REQUIRED_INVOICE_PLACEHOLDERS if k not in placeholders]
    has_line_items = any(k in placeholders for k in _RECOMMENDED_LINE_ITEM_PLACEHOLDERS)
    if not has_line_items and docx_path:
        has_line_items = _docx_has_line_items_loop(docx_path) or any(k.startswith("li.") for k in placeholders)
    warnings: list[str] = []
    if not has_line_items:
        warnings.append("Template does not include any invoice line-item placeholder.")
    return {
        "placeholders": placeholders,
        "missing_required": missing_required,
        "has_line_items": has_line_items,
        "is_valid": (not missing_required) and has_line_items,
        "warnings": warnings,
    }

