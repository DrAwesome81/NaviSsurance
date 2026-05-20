from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import defaultdict
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.file_handler import extract_text_from_file
from core.workspace_orchestrator import WorkspaceFile, WorkspaceTaskSpec, build_reference_pack
# Eval script validates workspace reference packs with Pulse private memory regulatory themes and 🛡️ Shield docs (workspace eval coordination)
# additional Pulse private memory + Shield for workspace eval script
# Pulse private memory + Shield (eval workspace reference pack surface)

def _ints_from_csv(v: str) -> list[int]:
    return [int(x.strip()) for x in (v or "").split(",") if x.strip()]


def _extract_with_fallback(path: str) -> str:
    content = extract_text_from_file(path) or ""
    if content.strip():
        return content
    ext = Path(path).suffix.lower()
    if ext in {".txt", ".md", ".markdown", ".py", ".json", ".csv", ".xml", ".html", ".css", ".js"}:
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    return ""


def _load_cases(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:
                raise ValueError(f"Invalid JSONL at line {i}: {e}") from e
    return rows


def _resolve_case_files(case: dict) -> tuple[list[WorkspaceFile], dict[str, str]]:
    files = case.get("files") or []
    workspace_files: list[WorkspaceFile] = []
    file_contents: dict[str, str] = {}
    for f in files:
        if isinstance(f, str):
            path = str(Path(f).resolve())
            display_name = Path(path).name
            file_type = "unknown"
            content = _extract_with_fallback(path)
        else:
            path = str(Path(str(f.get("path") or "")).resolve())
            display_name = str(f.get("display_name") or Path(path).name)
            file_type = str(f.get("file_type") or "unknown")
            if "content" in f:
                content = str(f.get("content") or "")
            else:
                content = _extract_with_fallback(path)
        workspace_files.append(
            WorkspaceFile(path=path, display_name=display_name, file_type=file_type)
        )
        file_contents[path] = content
    return workspace_files, file_contents


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Workspace reference-pack coverage across cap settings."
    )
    parser.add_argument(
        "--cases",
        required=True,
        help="Path to JSONL cases. Each row: {id?, goal, context?, feedback?, previous_markdown?, files:[...]}",
    )
    parser.add_argument(
        "--output",
        default="workspace_ref_eval.csv",
        help="Output CSV path for detailed per-case results.",
    )
    parser.add_argument(
        "--max-total-chars",
        default="30000,45000,60000",
        help="Comma-separated max_total_chars values.",
    )
    parser.add_argument(
        "--chunks-per-file",
        default="3,5,6",
        help="Comma-separated max_chunks_per_file values.",
    )
    parser.add_argument(
        "--small-file-max-chars",
        default="6000,8000,12000",
        help="Comma-separated small_file_max_chars values.",
    )
    args = parser.parse_args()

    cases = _load_cases(Path(args.cases))
    if not cases:
        raise ValueError("No cases found in JSONL.")

    grid_total = _ints_from_csv(args.max_total_chars)
    grid_chunks = _ints_from_csv(args.chunks_per_file)
    grid_small = _ints_from_csv(args.small_file_max_chars)
    if not (grid_total and grid_chunks and grid_small):
        raise ValueError("All tuning grids must contain at least one value.")

    rows: list[dict] = []
    for case_idx, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or f"case_{case_idx}")
        goal = str(case.get("goal") or "").strip()
        context = str(case.get("context") or "")
        feedback = str(case.get("feedback") or "")
        previous_markdown = str(case.get("previous_markdown") or "")
        workspace_files, file_contents = _resolve_case_files(case)
        task = WorkspaceTaskSpec(goal=goal, context=context, files=workspace_files, max_rounds=1)

        for max_total, chunks_per_file, small_max in itertools.product(
            grid_total, grid_chunks, grid_small
        ):
            pack, stats = build_reference_pack(
                task_spec=task,
                file_contents=file_contents,
                goal=goal,
                feedback=feedback,
                previous_markdown=previous_markdown,
                max_total_chars=max_total,
                max_chunks_per_file=chunks_per_file,
                include_small_files_full=True,
                small_file_max_chars=small_max,
                return_stats=True,
            )
            rows.append(
                {
                    "case_id": case_id,
                    "goal_chars": len(goal),
                    "max_total_chars": max_total,
                    "max_chunks_per_file": chunks_per_file,
                    "small_file_max_chars": small_max,
                    "pack_chars": stats.get("pack_chars", len(pack)),
                    "selected_files_count": stats.get("selected_files_count", 0),
                    "files_with_content": stats.get("files_with_content", 0),
                    "files_fully_included": stats.get("files_fully_included", 0),
                    "files_partially_included": stats.get("files_partially_included", 0),
                    "files_omitted": stats.get("files_omitted", 0),
                    "excerpt_count": stats.get("excerpt_count", 0),
                    "used_chars": stats.get("used_chars", 0),
                }
            )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    summary: dict[tuple[int, int, int], dict[str, float]] = defaultdict(
        lambda: {
            "cases": 0.0,
            "pack_chars": 0.0,
            "files_fully_included": 0.0,
            "files_partially_included": 0.0,
            "files_omitted": 0.0,
        }
    )
    for r in rows:
        key = (
            int(r["max_total_chars"]),
            int(r["max_chunks_per_file"]),
            int(r["small_file_max_chars"]),
        )
        s = summary[key]
        s["cases"] += 1
        s["pack_chars"] += float(r["pack_chars"])
        s["files_fully_included"] += float(r["files_fully_included"])
        s["files_partially_included"] += float(r["files_partially_included"])
        s["files_omitted"] += float(r["files_omitted"])

    print("\nReference-pack tuning summary (averages):")
    for key in sorted(summary.keys()):
        s = summary[key]
        n = max(1.0, s["cases"])
        print(
            f"- max_total={key[0]}, chunks={key[1]}, small_max={key[2]} | "
            f"pack_chars={s['pack_chars']/n:.0f}, "
            f"full={s['files_fully_included']/n:.2f}, "
            f"partial={s['files_partially_included']/n:.2f}, "
            f"omitted={s['files_omitted']/n:.2f}"
        )
    print(f"\nWrote detailed results: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
