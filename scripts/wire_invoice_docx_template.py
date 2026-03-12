from __future__ import annotations

import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile


def _iter_all_paragraphs(doc):
    # Document-level paragraphs
    for p in doc.paragraphs:
        yield p
    # Tables
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p


def _iter_cell_paragraphs(cell):
    for p in cell.paragraphs:
        yield p


def _replace_text_in_paragraph(p, *, literal_map: dict[str, str], regex_map: list[tuple[re.Pattern, str]]) -> bool:
    """
    Best-effort replacement while preserving formatting when possible.
    Falls back to whole-paragraph replacement if needed.
    """
    changed = False

    # First, try run-local replacements (preserves formatting).
    for r in p.runs:
        txt = r.text
        if not txt:
            continue
        new_txt = txt
        for k, v in literal_map.items():
            if k and k in new_txt:
                new_txt = new_txt.replace(k, v)
        for rx, repl in regex_map:
            if rx.search(new_txt):
                new_txt = rx.sub(repl, new_txt)
        if new_txt != txt:
            r.text = new_txt
            changed = True

    # If regex spans across runs, try paragraph-level replacement.
    full = "".join(r.text for r in p.runs)
    if not full:
        return changed

    new_full = full
    for k, v in literal_map.items():
        if k and k in new_full:
            new_full = new_full.replace(k, v)
    for rx, repl in regex_map:
        if rx.search(new_full):
            new_full = rx.sub(repl, new_full)

    if new_full != full:
        # This will collapse runs (formatting) for this paragraph, but only when required.
        p.text = new_full
        return True

    return changed


def _cell_contains(cell, needle_upper: str) -> bool:
    try:
        return needle_upper in (cell.text or "").upper()
    except Exception:
        return False


def _replace_in_cell(cell, *, literal_map: dict[str, str], regex_map: list[tuple[re.Pattern, str]]) -> bool:
    changed = False
    for p in _iter_cell_paragraphs(cell):
        if _replace_text_in_paragraph(p, literal_map=literal_map, regex_map=regex_map):
            changed = True
    return changed


def _set_cell_text_preserve_first_run(cell, text: str, *, paragraph_index: int = 0, clear_other_paragraphs: bool = True) -> None:
    """
    Replace the visible text in a cell while preserving the first run's formatting
    as much as python-docx allows.
    """
    if not cell.paragraphs:
        cell.text = text
        return
    pidx = max(0, min(int(paragraph_index), len(cell.paragraphs) - 1))
    p0 = cell.paragraphs[pidx]
    if p0.runs:
        p0.runs[0].text = text
        for r in p0.runs[1:]:
            r.text = ""
    else:
        p0.add_run(text)
    if clear_other_paragraphs:
        for i, p in enumerate(cell.paragraphs):
            if i == pidx:
                continue
            p.text = ""


def _insert_tag_paragraph_before(cell, tag_text: str) -> None:
    if not cell.paragraphs:
        cell.text = tag_text
        return
    # Ensure the tag is in a single run (docxtpl/Jinja is sensitive to split runs)
    p = cell.paragraphs[0].insert_paragraph_before(tag_text)
    if p.runs:
        # Make sure entire tag stays in one run
        for r in p.runs[1:]:
            r.text = ""


def _remove_row(table, row_idx: int) -> None:
    # python-docx doesn't expose row deletion; remove underlying XML element.
    row = table.rows[row_idx]
    table._tbl.remove(row._tr)  # type: ignore[attr-defined]


def _docx_xml_replace_inplace(docx_path: Path, *, replacements: dict[str, str]) -> None:
    """
    Replace literal strings inside word/document.xml (useful for hyperlink text that
    python-docx doesn't expose as runs).
    """
    if not replacements:
        return
    with TemporaryDirectory() as td:
        td_p = Path(td)
        with zipfile.ZipFile(str(docx_path), "r") as z:
            z.extractall(td_p)
        doc_xml = td_p / "word" / "document.xml"
        if doc_xml.exists():
            s = doc_xml.read_text(encoding="utf-8", errors="ignore")
            for k, v in replacements.items():
                if k:
                    s = s.replace(k, v)
            doc_xml.write_text(s, encoding="utf-8")
        # Repack
        tmp_out = td_p / "_out.docx"
        with zipfile.ZipFile(str(tmp_out), "w", compression=zipfile.ZIP_DEFLATED) as z2:
            for fp in td_p.rglob("*"):
                if fp.is_dir():
                    continue
                if fp.name == "_out.docx":
                    continue
                z2.write(str(fp), str(fp.relative_to(td_p)).replace("\\", "/"))
        docx_path.write_bytes(tmp_out.read_bytes())


def wire_invoice_docx(*, in_path: Path, out_path: Path) -> None:
    try:
        from docx import Document  # python-docx
    except Exception as e:  # pragma: no cover
        raise RuntimeError("python-docx is required to wire DOCX templates") from e

    doc = Document(str(in_path))

    # -----------------------
    # Table-aware wiring
    # -----------------------
    # This preserves the existing fonts/spacing by only replacing literal text
    # within existing cells/runs (instead of overwriting cell.text wholesale).

    # Common regex (invoice meta)
    rx_invoice_no = re.compile(r"\bPM\d{3,8}\b")
    rx_range = re.compile(r"\b\d{2}/\d{2}/\d{2,4}\s*-\s*\d{2}/\d{2}/\d{2,4}\b")
    rx_due = re.compile(r"\bDue upon receipt\b", flags=re.IGNORECASE)

    # Table 0: BILL TO + invoice meta
    if doc.tables:
        t0 = doc.tables[0]
        for row in t0.rows:
            for cell in row.cells:
                cell_upper = (cell.text or "").upper()
                if "BILL TO" in cell_upper:
                    _replace_in_cell(
                        cell,
                        literal_map={
                            "Dova Health": "{{client_name}}",
                            "Solveig Johannessen": "{{billing_contact_name}}",
                        },
                        regex_map=[
                            (
                                re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
                                "{{billing_email}}",
                            )
                        ],
                    )
                if "INVOICE" in cell_upper and "DATES INCLUDED" in cell_upper:
                    _replace_in_cell(
                        cell,
                        literal_map={},
                        regex_map=[
                            (rx_invoice_no, "{{invoice_number}}"),
                            (rx_range, "{{period_range}}"),
                            (rx_due, "{{due_date}}"),
                        ],
                    )

    # Table 1: line items + payment + totals
    if len(doc.tables) >= 2:
        t1 = doc.tables[1]

        # Locate header row and key columns by header text (fallback to known layout).
        header_row_idx = 0
        header_texts = [(c_i, (cell.text or "").upper()) for c_i, cell in enumerate(t1.rows[0].cells)]

        def _col_for(substr: str, fallback: int) -> int:
            for c_i, txt in header_texts:
                if substr in txt:
                    return c_i
            return fallback

        col_work = _col_for("WORK PERFORMED", 1)
        col_item = _col_for("ITEMIZED DESCRIPTION", 2)
        col_hours = _col_for("HOURS", 3)
        col_rate = _col_for("RATE", 4)
        col_amount = _col_for("AMOUNT", 5)

        # Find payment instructions row index (where the line items stop).
        payment_row_idx = None
        for r_i, row in enumerate(t1.rows):
            if any(_cell_contains(c, "PAYMENT INSTRUCTIONS") for c in row.cells):
                payment_row_idx = r_i
                break

        # Use first data row under header as the template row for docxtpl looping.
        template_row_idx = header_row_idx + 1
        if template_row_idx < len(t1.rows):
            r = t1.rows[template_row_idx]

            # Add loop start tag to the first populated cell (work performed).
            _insert_tag_paragraph_before(r.cells[col_work], "{% for li in line_items %}")
            # Keep both paragraphs: the tag paragraph (0) and the placeholder paragraph (1).
            _set_cell_text_preserve_first_run(
                r.cells[col_work], "{{li.work_performed}}", paragraph_index=1, clear_other_paragraphs=False
            )
            _set_cell_text_preserve_first_run(r.cells[col_item], "{{li.itemized_description}}")
            _set_cell_text_preserve_first_run(r.cells[col_hours], "{{li.hours_percentage}}")
            _set_cell_text_preserve_first_run(r.cells[col_rate], "{{li.rate_per_hour}}")
            _set_cell_text_preserve_first_run(r.cells[col_amount], "{{li.amount}}{% endfor %}")

        # Remove remaining sample line-item rows between the template row and payment instructions.
        stop = payment_row_idx if payment_row_idx is not None else len(t1.rows)
        # Delete from bottom to top to keep indices valid.
        for r_i in range(stop - 1, template_row_idx + 1, -1):
            _remove_row(t1, r_i)

        # Totals row: the row after the PAYMENT INSTRUCTIONS header row contains the amount(s) in this template.
        if payment_row_idx is not None:
            # payment_row_idx may have shifted after deletions; re-find it
            payment_row_idx2 = None
            for r_i, row in enumerate(t1.rows):
                if any(_cell_contains(c, "PAYMENT INSTRUCTIONS") for c in row.cells):
                    payment_row_idx2 = r_i
                    break
            if payment_row_idx2 is not None and payment_row_idx2 + 1 < len(t1.rows):
                amt_row = t1.rows[payment_row_idx2 + 1]
                for cell in amt_row.cells:
                    txt = (cell.text or "").strip()
                    if not txt:
                        continue
                    if "$" in txt or txt.replace(",", "").replace(".", "").isdigit():
                        _set_cell_text_preserve_first_run(cell, "{{total_amount_display}}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))

    # Replace hyperlink-only email text (python-docx doesn't expose it as runs).
    _docx_xml_replace_inplace(
        out_path,
        replacements={
            "solveig.johannessen@dovahealth.ca": "{{billing_email}}",
        },
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python scripts/wire_invoice_docx_template.py <input.docx> [output.docx]")
        return 2

    in_path = Path(argv[1]).resolve()
    if not in_path.exists():
        raise FileNotFoundError(str(in_path))

    if len(argv) >= 3:
        out_path = Path(argv[2]).resolve()
    else:
        out_path = in_path.with_name(in_path.stem + "_TEMPLATE.docx")

    wire_invoice_docx(in_path=in_path, out_path=out_path)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

