from __future__ import annotations

import base64
import html
import io
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportedTemplate:
    engine: str
    body: str


def wire_invoice_placeholders_html(template_body: str) -> str:
    """
    Best-effort helper to replace obvious literal invoice fields in a PDF-imported HTML
    template with placeholders.

    This is intentionally heuristic and only triggers when common anchors are found.
    """
    body = str(template_body or "")
    if not body:
        return body

    # The imported template includes a "Tip" HTML comment containing placeholders.
    # Ignore comments when deciding whether the template is already wired.
    body_no_comments = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    if "{{line_items_html}}" in body_no_comments and (
        "{{client_name}}" in body_no_comments or "{{invoice_number}}" in body_no_comments
    ):
        return body

    def _replace_next_span_text(body_s: str, *, anchor_re: str, replacement: str) -> tuple[str, bool]:
        m = re.search(anchor_re, body_s, flags=re.IGNORECASE)
        if not m:
            return body_s, False
        nxt = body_s.find("<span", m.end())
        if nxt < 0:
            return body_s, False
        gt = body_s.find(">", nxt)
        if gt < 0:
            return body_s, False
        end = body_s.find("</span>", gt)
        if end < 0:
            return body_s, False
        return body_s[: gt + 1] + replacement + body_s[end:], True

    def _replace_largest_font_span_after(
        body_s: str, *, anchor_re: str, replacement: str, window_chars: int = 2500, min_font_px: float = 18.0
    ) -> tuple[str, bool]:
        m = re.search(anchor_re, body_s, flags=re.IGNORECASE)
        if not m:
            return body_s, False
        start = m.end()
        window = body_s[start : start + max(200, int(window_chars))]
        spans: list[tuple[float, int, int]] = []
        for sm in re.finditer(r"<span\s+style=\"[^\"]*font-size:(?P<fs>[\d.]+)px;[^\"]*\">", window):
            try:
                fs = float(sm.group("fs"))
            except Exception:
                continue
            if fs < float(min_font_px):
                continue
            span_abs_start = start + sm.start()
            gt = body_s.find(">", span_abs_start)
            if gt < 0:
                continue
            end = body_s.find("</span>", gt)
            if end < 0:
                continue
            spans.append((fs, gt + 1, end))
        if not spans:
            return body_s, False
        spans.sort(key=lambda t: t[0], reverse=True)
        _fs, txt_start, txt_end = spans[0]
        return body_s[:txt_start] + replacement + body_s[txt_end:], True

    changed = False

    # BILL TO: → next span is usually the client name.
    body, ok = _replace_next_span_text(body, anchor_re=r">\s*BILL TO:\s*</span>", replacement="{{client_name}}")
    changed = changed or ok

    # Within a small window after BILL TO, replace the first email-like span with {{billing_email}}.
    m_bill = re.search(r">\s*BILL TO:\s*</span>", body, flags=re.IGNORECASE)
    if m_bill:
        window = body[m_bill.end() : m_bill.end() + 2000]
        m_email = re.search(r"(<span[^>]*>)([^<]*@[^<]*)(</span>)", window)
        if m_email:
            email_full = m_email.group(0)
            email_repl = m_email.group(1) + "{{billing_email}}" + m_email.group(3)
            body = body.replace(email_full, email_repl, 1)
            changed = True

    # INVOICE # → next span is usually the invoice number.
    body, ok = _replace_next_span_text(body, anchor_re=r">\s*INVOICE\s*#\s*</span>", replacement="{{invoice_number}}")
    changed = changed or ok

    # DATES INCLUDED → next span is usually the date range.
    body, ok = _replace_next_span_text(body, anchor_re=r">\s*DATES INCLUDED\s*</span>", replacement="{{period_range}}")
    changed = changed or ok

    # INVOICE DUE DATE → next span is due date text.
    body, ok = _replace_next_span_text(body, anchor_re=r">\s*INVOICE DUE DATE\s*</span>", replacement="{{due_date}}")
    changed = changed or ok

    # TOTAL → replace the largest-font span after the label (the amount).
    body, ok = _replace_largest_font_span_after(
        body, anchor_re=r">\s*TOTAL\s*</span>", replacement="{{total_amount_display}}", window_chars=4000, min_font_px=18.0
    )
    changed = changed or ok

    # Add a positioned {{line_items_html}} container near "ITEMIZED DESCRIPTION" if present.
    if "{{line_items_html}}" not in body_no_comments:
        m_desc = re.search(
            r'(<span style="[^"]*left:(?P<left>[\d.]+)px;\s*top:(?P<top>[\d.]+)px;[^"]*">)\s*ITEMIZED DESCRIPTION\s*</span>',
            body,
            flags=re.IGNORECASE,
        )
        if m_desc:
            left = float(m_desc.group("left"))
            top = float(m_desc.group("top"))
            insert_at = body.find("</span>", m_desc.end())
            if insert_at != -1:
                insert_at += len("</span>")
                block = (
                    "\n"
                    f'    <div style="position:absolute; left:{left:.2f}px; top:{(top + 45.0):.2f}px; '
                    "width:520px; max-height:360px; overflow:hidden; "
                    "font-size:11.5px; color:#111; line-height:1.2; "
                    "white-space:normal; word-break:break-word;\">"
                    "{{line_items_html}}</div>\n"
                )
                body = body[:insert_at] + block + body[insert_at:]
                changed = True

    # Remove a handful of common hardcoded row spans (keeps headers + lets {{line_items_html}} drive content).
    row_keywords = [
        "Fractional Leadership",
        "Vice",
        "Regulatory Affairs",
        "Quality Assurance",
        "DovaVision",
        "General/Both",
        "Planning and strategy",
        "SOP and policy",
        "audit prep",
        "n/a",
        "workday",
        "(50% time)",
        "35%",
        "65%",
        "$200",
        "$6066.67",
        "$11,266.66",
        "$17,333.33",
    ]
    for kw in row_keywords:
        pat = re.compile(rf"<span[^>]*>[^<]*{re.escape(kw)}[^<]*</span>", flags=re.IGNORECASE)
        new_body, n = pat.subn("", body)
        if n:
            body = new_body
            changed = True

    return body if changed else str(template_body or "")


def import_invoice_template_from_pdf(pdf_path: str) -> ImportedTemplate:
    """
    Convert a PDF invoice into an HTML template usable in the Billing tab.

    Strategy:
    - Render each page to a JPEG (embedded as base64) at ~1.5x scale.
    - Overlay extracted text spans as absolutely-positioned <span> elements so the
      user can replace specific text with {{placeholders}} in the template editor.

    Notes:
    - This is not a perfect semantic conversion (tables remain visual), but it
      preserves layout including shapes/images.
    - The background page image is shown at low opacity to avoid double-text
      artifacts while keeping shapes/lines visible.
    """
    try:
        # PyMuPDF import (preferred modern name).
        import pymupdf as fitz  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required to import PDF templates (import pymupdf failed)") from e

    try:
        from PIL import Image  # pillow
    except Exception as e:  # pragma: no cover
        raise RuntimeError("pillow is required to import PDF templates") from e

    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(str(p))

    doc = fitz.open(str(p))
    scale = 1.5
    mtx = fitz.Matrix(scale, scale)

    page_divs: list[str] = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        pix = page.get_pixmap(matrix=mtx, alpha=False)
        # Convert to JPEG to keep template size manageable in SQLite.
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75, optimize=True)
        jpg_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        w_px = int(pix.width)
        h_px = int(pix.height)

        # Extract text spans with bounding boxes.
        # Coordinates from PyMuPDF are in points; scale them to match pixmap.
        spans: list[str] = []
        text = page.get_text("dict")
        for block in text.get("blocks", []) or []:
            for line in block.get("lines", []) or []:
                for span in line.get("spans", []) or []:
                    s = str(span.get("text") or "")
                    if not s.strip():
                        continue
                    bbox = span.get("bbox") or None
                    if not bbox or len(bbox) != 4:
                        continue
                    x0, y0, x1, y1 = bbox
                    left = float(x0) * scale
                    top = float(y0) * scale
                    font_size = max(6.0, float(span.get("size") or 10.0) * scale)
                    # Keep it simple: color/weight are best-effort.
                    # Using page image opacity helps hide minor mismatches.
                    spans.append(
                        "<span style=\""
                        f"position:absolute; left:{left:.2f}px; top:{top:.2f}px; "
                        f"font-size:{font_size:.2f}px; color:#111; white-space:pre;\""
                        f">{html.escape(s)}</span>"
                    )

        page_divs.append(
            "\n".join(
                [
                    f"<div class=\"page\" style=\"position:relative; width:{w_px}px; height:{h_px}px; margin:18px auto; background:#fff; box-shadow:0 2px 10px rgba(0,0,0,.25);\">",
                    f"  <img alt=\"page\" src=\"data:image/jpeg;base64,{jpg_b64}\" style=\"position:absolute; left:0; top:0; width:{w_px}px; height:{h_px}px; opacity:0.22;\" />",
                    "  <div class=\"overlay\" style=\"position:absolute; left:0; top:0; right:0; bottom:0;\">",
                    *[f"    {sp}" for sp in spans],
                    "  </div>",
                    "</div>",
                ]
            )
        )

    doc.close()

    body = "\n".join(
        [
            "<!-- engine: placeholder_v1_html -->",
            "<!-- Tip: Replace literals with placeholders like {{client_name}}, {{period_start}}, {{period_end}}, {{total_amount}}, {{line_items_html}} -->",
            "<!doctype html>",
            "<html>",
            "<head>",
            "  <meta charset=\"utf-8\" />",
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />",
            "  <title>Invoice</title>",
            "  <style>",
            "    body { background:#1c1e24; margin:0; padding:18px; }",
            "    .page { border-radius: 6px; overflow:hidden; }",
            "  </style>",
            "</head>",
            "<body>",
            *page_divs,
            "</body>",
            "</html>",
        ]
    )
    body = wire_invoice_placeholders_html(body)
    return ImportedTemplate(engine="placeholder_v1_html", body=body)

