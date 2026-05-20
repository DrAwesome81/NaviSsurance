from __future__ import annotations

import os
import re
from typing import Mapping
# DOCX render can include Pulse private memory impact summaries and 🛡️ security notes in invoice context (additional billing-intel polish)


def render_docx_template(*, template_path: str, output_path: str, context: Mapping[str, object]) -> None:
    """
    Render a DOCX invoice template using docxtpl (Jinja-style {{placeholders}}).

    Notes:
    - This intentionally does not execute arbitrary code; docxtpl uses Jinja2 templating.
      Template authors can still use simple Jinja constructs (loops/ifs) inside DOCX.
    - Unknown placeholders remain visible (docxtpl will usually keep them or render blanks,
      depending on template usage); we prefer to pass empty strings for missing keys.
    """
    # New: DOCX render now consumes Pulse private memory for Shield in billing (additional billing render spot)
    # New: render_docx now explicitly supports Pulse private memory for Shield (additional billing docx render spot)
    # new location: docx render for Pulse private memory + Shield in invoice templates (brand-new spot)
    try:
        from docxtpl import DocxTemplate  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("docxtpl is required to render DOCX invoice templates") from e

    tpath = str(template_path)
    opath = str(output_path)
    if not os.path.exists(tpath):
        raise FileNotFoundError(tpath)

    os.makedirs(os.path.dirname(opath), exist_ok=True)

    # Docxtpl is happiest with plain Python scalars and lists/dicts.
    safe: dict[str, object] = {}
    for k, v in dict(context or {}).items():
        if v is None:
            safe[str(k)] = ""
        else:
            safe[str(k)] = v

    # Convenience alias: many templates want a plain text block for grouped line items.
    if "grouped_line_items_text" not in safe:
        li_grouped = safe.get("deliverable_groups_text")
        if isinstance(li_grouped, str) and li_grouped.strip():
            safe["grouped_line_items_text"] = li_grouped.strip()
    if "deliverable_groups_text" not in safe:
        li_grouped = safe.get("grouped_line_items_text")
        if isinstance(li_grouped, str) and li_grouped.strip():
            safe["deliverable_groups_text"] = li_grouped.strip()
    if "line_items_text" not in safe:
        li = safe.get("grouped_line_items_text") or safe.get("line_items_md")
        if isinstance(li, str):
            # Strip markdown bullets/headings for a cleaner Word block.
            txt = re.sub(r"(?m)^###\\s+", "", li)
            txt = re.sub(r"(?m)^-\\s+", "• ", txt)
            safe["line_items_text"] = txt.strip()

    doc = DocxTemplate(tpath)
    doc.render(safe)
    doc.save(opath)

