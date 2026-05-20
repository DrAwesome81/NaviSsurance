#!/usr/bin/env python3
"""
Workspace Diagnostic Tool (Phase 0 – Foundation & Cleanup)

Unified diagnostic and visibility tool for the Consultant OS.

- Dropbox mode (default): duplicate detection + safe --move/--dry-run for extracted files.
- Google Drive mode (--gdrive): thin symmetric reporting that exercises the new GDrive connector
  and feeds results through the unified DocumentRecord pipeline (cloud pointers only, rich metadata).

Usage examples:
    # Dropbox (existing)
    python scripts/diagnose_dropbox_duplicates.py --path "/Representative Folder" --dry-run

    # Google Drive (new Phase 0 symmetric capability)
# Diagnostic supports clean data for Pulse private memory, Intel RAG, and Shield compliance files (data hygiene coordination)
# Additional: ensures clean data for private memory reflections and Shield (new data hygiene spot)
# Pulse private memory + Shield (diagnose dropbox duplicates surface)
    python scripts/diagnose_dropbox_duplicates.py --gdrive
    python scripts/diagnose_dropbox_duplicates.py --gdrive --gdrive-folder-id "YOUR_FOLDER_ID"

    # End-to-end smoke (both sources -> DocumentRecords)
    python scripts/diagnose_dropbox_duplicates.py --smoke --gdrive-folder-id "..." --path "..."

The tool now gives identical visibility and safety tooling for both sources without creating any duplicate artifacts.
"""

import csv
import os
import re
import argparse
import difflib
from collections import defaultdict
from datetime import datetime, timedelta
import time
from typing import List, Dict, Any, Tuple

from dropbox import Dropbox
from dropbox.exceptions import ApiError
from dropbox.files import FileMetadata

# Add project root to path so we can import from core
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.api import get_dropbox_client, list_gdrive_files, get_gdrive_service
from core.file_handler import build_unified_document_record, DocumentRecord


# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

# Where to save the report
REPORT_DIR = os.path.join("data", "cleanup_reports")
os.makedirs(REPORT_DIR, exist_ok=True)

# Archive base for extracted duplicates. Year-based subfolders are created under this (e.g. /_Archives/_Extracted_Text/2025)
ARCHIVE_BASE = "/_Archives/_Extracted_Text"


def get_dropbox_path_from_local(local_path: str) -> str:
    r"""
    Convert a local Windows Dropbox path into a Dropbox API path.
    Example:
        C:\Users\adamo\Dropbox\Overjet Files  →  /Overjet Files
    """
    # Normalize and convert all backslashes to forward slashes first
    local_path = os.path.normpath(local_path).replace("\\", "/")

    # Common Dropbox root locations on Windows
    home = os.path.expanduser("~").replace("\\", "/")
    possible_roots = [
        f"{home}/Dropbox",
        f"{home}/Dropbox (Personal)",
    ]

    for root in possible_roots:
        if local_path.lower().startswith(root.lower()):
            relative = local_path[len(root):].strip("/")
            result = "/" + relative if relative else ""
            print(f"  Converted local path → Dropbox path: {result}")
            return result

    # Fallback: take everything after the last "Dropbox" folder
    if "dropbox" in local_path.lower():
        idx = local_path.lower().rfind("dropbox")
        relative = local_path[idx + len("Dropbox"):].strip("/")
        result = "/" + relative if relative else ""
        print(f"  Converted local path → Dropbox path: {result}")
        return result

    # Last resort - just take the last folder name
    parts = [p for p in local_path.split("/") if p]
    if parts:
        result = "/" + parts[-1]
        print(f"  Using last folder as Dropbox path: {result}")
        return result

    return ""


# -------------------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Create a normalized key for grouping similar files."""
    base = os.path.splitext(name)[0].lower()
    # Remove common suffixes that indicate extraction
    base = re.sub(r'[_.\-\s]*(text|txt|extracted|extract|ocr|plain|raw|cleaned)$', '', base, flags=re.IGNORECASE)
    base = re.sub(r'[_.\-\s]+', ' ', base).strip()
    return base


def is_likely_extracted(filename: str) -> bool:
    """Heuristic: does this filename look like a text/OCR/extracted version?"""
    lower = filename.lower()
    keywords = ['text', 'txt', 'extract', 'ocr', 'plain', 'raw', 'cleaned', 'extracted', 'fulltext', 'plaintext']
    return any(kw in lower for kw in keywords)


def _normalize_for_comparison(name: str) -> str:
    """Aggressive normalization for duplicate matching."""
    base = os.path.splitext(name)[0].lower()
    # Remove common extraction suffixes
    base = re.sub(r'[_.\-\s]*(text|txt|extracted|extract|ocr|plain|raw|cleaned|fulltext|plaintext)$', '', base)
    # Remove common version/date suffixes
    base = re.sub(r'[_.\-\s]*(v\d+|final|draft|copy|backup|\d{4}[-_]\d{2}[-_]\d{2})$', '', base)
    base = re.sub(r'[_.\-\s]+', ' ', base).strip()
    return base


def _find_best_original(candidates: List[Dict], extracted_file: Dict) -> Tuple[Dict, float]:
    """Find the most likely original for a given extracted file using multiple signals."""
    best = None
    best_score = 0.0

    ext_name = _normalize_for_comparison(extracted_file["name"])
    ext_time = extracted_file.get("client_modified") or extracted_file.get("server_modified")

    for cand in candidates:
        if is_likely_extracted(cand["name"]):
            continue

        cand_name = _normalize_for_comparison(cand["name"])
        score = 0.0

        # 1. Name similarity (strongest signal)
        name_sim = difflib.SequenceMatcher(None, ext_name, cand_name).ratio()
        score += name_sim * 60

        # 2. One is PDF and the other is text-based (very strong)
        ext_lower = extracted_file["name"].lower()
        cand_lower = cand["name"].lower()
        if cand_lower.endswith('.pdf') and any(ext_lower.endswith(ext) for ext in ('.txt', '.text', '.md')):
            score += 35
        elif cand_lower.endswith('.pdf') and is_likely_extracted(extracted_file["name"]):
            score += 25

        # 3. Time difference (extracted version is usually newer)
        if ext_time:
            cand_time = cand.get("client_modified") or cand.get("server_modified")
            if cand_time and ext_time > cand_time:
                days_diff = (ext_time - cand_time).days
                if days_diff <= 30:
                    score += 15
                elif days_diff <= 90:
                    score += 8

        # 4. Size difference (text version is usually much smaller)
        size_ratio = extracted_file["size"] / max(cand["size"], 1)
        if size_ratio < 0.1:  # extracted is < 10% the size of candidate
            score += 12
        elif size_ratio < 0.3:
            score += 6

        if score > best_score:
            best_score = score
            best = cand

    return best, best_score


def list_all_files(dbx: Dropbox, path: str = "") -> List[Dict[str, Any]]:
    """
    Recursively list files starting from a given Dropbox path.
    Empty string = root of Dropbox (full scan).
    """
    start_time = time.time()
    last_update = start_time

    if path == "":
        print("Starting full Dropbox scan... (this can take a while)")
    else:
        print(f"Scanning folder: {path}")

    all_files = []
    cursor = None
    update_interval = 1.5  # seconds between progress updates

    while True:
        try:
            if cursor is None:
                result = dbx.files_list_folder(path=path, recursive=True)
            else:
                result = dbx.files_list_folder_continue(cursor)

            for entry in result.entries:
                if isinstance(entry, FileMetadata):
                    all_files.append({
                        "id": entry.id,
                        "path": entry.path_display,
                        "name": entry.name,
                        "size": entry.size,
                        "client_modified": entry.client_modified,
                        "server_modified": entry.server_modified,
                    })

            # Progress update
            now = time.time()
            if now - last_update >= update_interval or not result.has_more:
                elapsed = now - start_time
                count = len(all_files)
                rate = count / elapsed if elapsed > 0 else 0
                elapsed_str = str(timedelta(seconds=int(elapsed)))
                msg = f"\rScanned {count:,} files | {rate:.1f} files/sec | Elapsed: {elapsed_str}"
                print(msg, end="", flush=True)
                last_update = now

            if not result.has_more:
                break
            cursor = result.cursor

        except ApiError as e:
            print(f"\nError during listing: {e}")
            break

    elapsed = time.time() - start_time
    print(f"\nScan complete. Found {len(all_files):,} files in '{path or '/'}'.")
    print(f"Total time: {str(timedelta(seconds=int(elapsed)))}")
    return all_files


def group_files(files: List[Dict]) -> Dict[str, List[Dict]]:
    """Group files by normalized base name."""
    groups = defaultdict(list)
    for f in files:
        key = normalize_name(f["name"])
        groups[key].append(f)
    return groups


def detect_duplicates(all_files: List[Dict]) -> List[Dict[str, Any]]:
    """
    Find likely original <-> extracted pairs using multiple strong signals.
    Much improved version that works across folders and with inconsistent naming.
    """
    candidates = []
    seen_extracted_ids = set()

    # First pass: group by normalized name for fast lookup
    name_groups = defaultdict(list)
    for f in all_files:
        key = _normalize_for_comparison(f["name"])
        name_groups[key].append(f)

    for f in all_files:
        if not is_likely_extracted(f["name"]):
            continue
        if f["id"] in seen_extracted_ids:
            continue

        # Find best original candidate
        best_original, score = _find_best_original(all_files, f)

        if best_original and score >= 55:  # Threshold tuned for quality
            confidence = "High" if score >= 75 else "Medium"
            reason = f"Score: {score:.0f}/100"

            candidates.append({
                "likely_original_path": best_original["path"],
                "likely_original_id": best_original["id"],
                "likely_extracted_path": f["path"],
                "likely_extracted_id": f["id"],
                "confidence": confidence,
                "reason": reason,
                "suggested_action": "Move extracted version to archive",
            })
            seen_extracted_ids.add(f["id"])

    # Sort by confidence (High first) then by score if available
    def sort_key(item):
        conf = 100 if item["confidence"] == "High" else 50
        # Try to extract numeric score from reason for secondary sort
        match = re.search(r"Score:\s*(\d+)", item["reason"])
        score = int(match.group(1)) if match else 0
        return (-conf, -score)

    candidates.sort(key=sort_key)
    return candidates


def write_csv_report(candidates: List[Dict], output_path: str, scan_path: str = ""):
    """Write the results to a CSV file. Always generates a file, even if no duplicates are found."""
    fieldnames = [
        "likely_original_path",
        "likely_original_id",
        "likely_extracted_path",
        "likely_extracted_id",
        "confidence",
        "reason",
        "suggested_action",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        if candidates:
            writer.writerows(candidates)
            print(f"\nReport written to: {output_path}")
            print(f"Found {len(candidates)} potential duplicate pairs / candidates.")
        else:
            # Write a summary row when nothing is found
            writer.writerow({
                "likely_original_path": "SCAN SUMMARY",
                "likely_original_id": "",
                "likely_extracted_path": f"No likely duplicates found in: {scan_path or 'Full Dropbox'}",
                "likely_extracted_id": "",
                "confidence": "",
                "reason": f"Scanned on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "suggested_action": "No action needed from this scan",
            })
            print(f"\nReport written to: {output_path}")
            print("No likely duplicates were detected.")


# -------------------------------------------------------------------------
# Move / Archive Helpers (Phase 0 hardened functionality)
# -------------------------------------------------------------------------

def ensure_folder(dbx: Dropbox, path: str) -> bool:
    """
    Create a Dropbox folder and all missing parent folders incrementally.
    Returns True if the folder exists (created or already present).
    Fixes parent-creation limitation of Dropbox API (no auto-parents).
    Uses improved error classification (addresses review Issues 1 + 8).
    """
    if not path or path == "/":
        return True
    parts = [p for p in path.strip("/").split("/") if p]
    current = ""
    for part in parts:
        current = (current + "/" + part) if current else ("/" + part)
        try:
            dbx.files_create_folder_v2(current)
            # Successfully created this level
        except ApiError as e:
            err_str = str(e).lower()
            # Robust existence check (conflict, already exists, path/conflict)
            if any(x in err_str for x in ("conflict", "already", "path/conflict")):
                continue  # already present; proceed to child
            print(f"  Warning: could not create folder {current}: {e}")
            return False
    return True


def get_year_subfolder(modified_dt: Any) -> str:
    """Return year string from a datetime (for year-based archive layout)."""
    if modified_dt is None:
        return str(datetime.now().year)
    try:
        return str(modified_dt.year)
    except Exception:
        return str(datetime.now().year)


def perform_moves(dbx: Dropbox, candidates: List[Dict[str, Any]], dry_run: bool = True, only_high: bool = True) -> None:
    """
    Safely move (or simulate) high-confidence extracted duplicates to year-based archive.
    - Only High confidence by default for safety.
    - Creates year subfolders under ARCHIVE_BASE.
    - Uses autorename on target in case of name collision.
    - Conservative rate-limit backoff and per-file error isolation.
    - Detailed console logging for full live visibility.
    """
    to_move = [c for c in candidates if (c.get("confidence") == "High" or not only_high)]
    if only_high:
        to_move = [c for c in to_move if c.get("confidence") == "High"]

    if not to_move:
        print("No qualifying files (High confidence) to move.")
        return

    action = "DRY-RUN (no changes)" if dry_run else "LIVE MOVE"
    print(f"\n{'='*60}")
    print(f"{action}: {len(to_move)} candidate(s) selected for archive relocation")
    print(f"Archive base: {ARCHIVE_BASE}")
    print(f"{'='*60}")

    moved_count = 0
    error_count = 0
    skipped_count = 0

    for idx, cand in enumerate(to_move, 1):
        src_path = cand["likely_extracted_path"]
        filename = os.path.basename(src_path)
        print(f"\n[{idx}/{len(to_move)}] Processing: {src_path}")
        print(f"   Original match: {cand['likely_original_path']}")
        print(f"   Confidence: {cand['confidence']} | {cand['reason']}")

        try:
            # Fetch fresh metadata for accurate modified date (candidates may be stale)
            meta = dbx.files_get_metadata(src_path)
            mod_dt = getattr(meta, "server_modified", None) or getattr(meta, "client_modified", None)
            year = get_year_subfolder(mod_dt)
            year_folder = f"{ARCHIVE_BASE}/{year}"
            target_path = f"{year_folder}/{filename}"

            # Ensure year folder (and base)
            ensure_folder(dbx, ARCHIVE_BASE)
            ensure_folder(dbx, year_folder)

            print(f"   Target: {target_path} (year={year})")

            if dry_run:
                print("   [DRY RUN] Would execute files_move_v2 here.")
                moved_count += 1  # count as would-be
                continue

            # LIVE MOVE
            try:
                dbx.files_move_v2(from_path=src_path, to_path=target_path, autorename=True)
                print("   ✓ Moved successfully.")
                moved_count += 1
                # Conservative pacing to respect Dropbox rate limits
                time.sleep(0.6)
            except ApiError as api_err:
                err_str = str(api_err).lower()
                if "rate_limit" in err_str or "429" in err_str or "too_many_requests" in err_str:
                    print("   ! Rate limit encountered. Backing off 6 seconds and retrying once...")
                    time.sleep(6)
                    try:
                        dbx.files_move_v2(from_path=src_path, to_path=target_path, autorename=True)
                        print("   ✓ Retry succeeded.")
                        moved_count += 1
                    except ApiError as retry_err:
                        print(f"   ✗ Retry also failed: {retry_err}")
                        error_count += 1
                    except Exception as retry_exc:
                        print(f"   ✗ Retry unexpected error: {retry_exc}")
                        error_count += 1
                else:
                    print(f"   ✗ Move API error: {api_err}")
                    error_count += 1
            except Exception as move_exc:
                print(f"   ✗ Unexpected move error: {move_exc}")
                error_count += 1

        except ApiError as meta_err:
            if "not_found" in str(meta_err).lower():
                print("   - Skipped (file no longer at source path, possibly already moved).")
                skipped_count += 1
            else:
                print(f"   ✗ Metadata error: {meta_err}")
                error_count += 1
        except Exception as e:
            print(f"   ✗ Error preparing move: {e}")
            error_count += 1

    print(f"\n{'='*60}")
    print(f"{action} SUMMARY")
    print(f"  Moves performed (or simulated): {moved_count}")
    print(f"  Errors: {error_count}")
    print(f"  Skipped (not found): {skipped_count}")
    print(f"{'='*60}\n")


# -------------------------------------------------------------------------
# Google Drive Diagnostic / Reporting (Phase 0 symmetric thin tool)
# -------------------------------------------------------------------------

def run_gdrive_diagnostic(folder_id: str = "root", smoke_mode: bool = False, persist: bool = False) -> None:
    """
    Thin symmetric GDrive diagnostic.
    Uses the Phase 0 GDrive connector + unified DocumentRecord pipeline.
    Generates a CSV report of enriched records (cloud pointers only, no duplicates created).
    With --persist: also saves to DB for Phase 1 retrieval.
    """
    from core.file_handler import format_compact_historical_context, build_unified_document_record
    print("\n--- Google Drive Diagnostic Mode ---")
    try:
        service = get_gdrive_service()
    except Exception as e:
        print(f"Failed to get Google Drive service: {e}")
        print("Ensure GOOGLE_* variables are set in config/.env")
        return

    print(f"Listing files (folder_id={folder_id}, recursive=True)...")
    try:
        files = list_gdrive_files(service=service, folder_id=folder_id, recursive=True, max_files=2000)
    except Exception as e:
        print(f"GDrive listing failed: {e}")
        return

    if not files:
        print("No files returned from Google Drive.")
        return

    print(f"Building unified DocumentRecords for {len(files)} files (enrichment pipeline)...")
    records: List[Dict[str, Any]] = []
    for f in files:
        try:
            rec: DocumentRecord = build_unified_document_record(
                source="gdrive",
                source_id=f["id"],
                source_path=f.get("path", f["name"]),
                name=f["name"],
                mime_type=f.get("mimeType", ""),
                size=f.get("size", 0),
                modified_time=f.get("modifiedTime"),
                created_time=f.get("createdTime"),
                raw_meta=f,
            )
            compact = format_compact_historical_context([rec], max_items=1).strip()
            records.append({
                "source": rec.source,
                "source_id": rec.source_id,
                "name": rec.name,
                "source_path": rec.source_path,
                "mime_type": rec.mime_type,
                "size": rec.size,
                "modified_time": rec.modified_time,
                "doc_type": rec.doc_type or "",
                "client_hint": rec.client_hint or "",
                "project_hint": rec.project_hint or "",
                "year": rec.year or "",
                "regulatory_tags": ",".join(rec.regulatory_tags) if rec.regulatory_tags else "",
                "compact_ref": compact,
            })
        except Exception as ex:
            print(f"  Warning: failed to build record for {f.get('name')}: {ex}")

    # Write GDrive report (symmetric to Dropbox CSV)
    report_dir = os.path.join("data", "cleanup_reports")
    os.makedirs(report_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_name = f"gdrive_diagnostic_report_{folder_id.replace('/', '_')}_{ts}.csv"
    report_path = os.path.join(report_dir, report_name)

    fieldnames = list(records[0].keys()) if records else ["source", "name"]
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if records:
            writer.writerows(records)

    print(f"\nGDrive report written: {report_path}")
    print(f"  Enriched {len(records)} DocumentRecords via unified pipeline.")

    if persist and records:
        print("Persisting records to DB (Phase 1)...")
        from core.file_handler import save_document_record, build_unified_document_record
        saved = 0
        for rdict in records[:100]:  # safety cap
            try:
                # Rebuild minimal rec for save (source_id etc. present)
                rec = build_unified_document_record(
                    source=rdict["source"], source_id=rdict["source_id"],
                    source_path=rdict.get("source_path", rdict["name"]),
                    name=rdict["name"], mime_type=rdict.get("mime_type", ""),
                    size=rdict.get("size", 0),
                    modified_time=rdict.get("modified_time"),
                    created_time=rdict.get("created_time")
                )
                if save_document_record(rec):
                    saved += 1
            except Exception:
                pass
        print(f"  Persisted {saved} records.")

    if smoke_mode or len(records) > 0:
        print("\nSample DocumentRecords (first 3):")
        for r in records[:3]:
            compact = r.get("compact_ref", "")
            if compact:
                print(f"  - {compact}")
            else:
                print(f"  - {r['name']} | type={r['doc_type']} | client={r['client_hint']} | project={r['project_hint']} | year={r['year']}")

    print("--- GDrive diagnostic complete ---\n")


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Workspace Diagnostic Tool – Dropbox cleanup + Google Drive reporting + unified DocumentRecord pipeline (Phase 0).")
    parser.add_argument(
        "--path", 
        type=str, 
        default="", 
        help='Path to scan. Examples:\n'
             '  --path "/Overjet Files"\n'
             '  --path "C:\\Users\\adamo\\Dropbox\\Overjet Files"\n\n'
             'Leave empty (or omit) to scan your entire Dropbox.'
    )
    parser.add_argument(
        "--move", 
        action="store_true",
        help="Actually move high-confidence extracted files into the archive folder (use --dry-run first!)"
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true",
        help="Preview moves without actually doing anything (recommended before using --move)"
    )
    parser.add_argument(
        "--include-medium", 
        action="store_true",
        help="Also consider Medium-confidence duplicates for move (DANGEROUS - review CSV first; default is High only)"
    )
    # Phase 0 GDrive symmetric reporting (thin diagnostic, read-only)
    parser.add_argument(
        "--gdrive",
        action="store_true",
        help="Run Google Drive diagnostic/reporting mode (uses list_gdrive_files + unified DocumentRecord pipeline)"
    )
    parser.add_argument(
        "--gdrive-folder-id",
        type=str,
        default="root",
        help="Google Drive folder ID to scan when using --gdrive (default: root / My Drive)"
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a small end-to-end smoke that exercises both connectors and prints sample DocumentRecords (no moves)"
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persist generated DocumentRecords to the main DB (Phase 1 storage, safe additive)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Workspace Diagnostic Tool (Phase 0)")
    print("=" * 60)

    if args.gdrive or args.smoke:
        print("Mode: Google Drive + Unified DocumentRecord pipeline")
        if args.gdrive_folder_id != "root":
            print(f"  GDrive folder ID: {args.gdrive_folder_id}")
    else:
        # Dropbox mode (original behavior)
        scan_path = get_dropbox_path_from_local(args.path) if args.path else ""
        if scan_path:
            print(f"Target folder (Dropbox path): {scan_path}")
        else:
            print("Target: Full Dropbox (root)")

    # Branch for GDrive / smoke modes (Phase 0 symmetric foundation)
    if args.gdrive or args.smoke:
        run_gdrive_diagnostic(folder_id=args.gdrive_folder_id, smoke_mode=args.smoke, persist=args.persist)

        # For --smoke, also show a quick Dropbox example if path provided (no full scan)
        if args.smoke and args.path:
            print("\n[Smoke] Also exercising Dropbox path conversion (no full scan):")
            try:
                dp = get_dropbox_path_from_local(args.path) if args.path else ""
                print(f"  Dropbox path conversion: {dp or '(root)'}")
            except Exception as ex:
                print(f"  Dropbox path conversion note: {ex}")

        print("Smoke / GDrive phase complete.")
        return   # skip original Dropbox duplicate/move logic

    # --- Original Dropbox flow (unchanged behavior when not using --gdrive/--smoke) ---
    try:
        dbx = get_dropbox_client()
    except Exception as e:
        print(f"Failed to get Dropbox client: {e}")
        print("Make sure your DROPBOX_* variables are set correctly in .env")
        return

    # 1. Scan
    all_files = list_all_files(dbx, path=scan_path)

    if not all_files:
        print("No files found or scan failed.")
        return

    # 2. Detect duplicates with improved logic
    print("Analyzing files for likely duplicates (improved detection)...")
    candidates = detect_duplicates(all_files)

    # 3. Report filename (include folder name if scanning a subfolder)
    if scan_path:
        safe_name = scan_path.strip("/").replace("/", "_").replace(" ", "_")
        report_name = f"dropbox_duplicate_report_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    else:
        report_name = f"dropbox_duplicate_report_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    report_path = os.path.join(REPORT_DIR, report_name)

    # 4. Write report (always generates a file now)
    write_csv_report(candidates, report_path, scan_path=scan_path)

    # 5. Phase 0 hardened move logic (only if --move or --dry-run supplied)
    if args.move or args.dry_run:
        only_high = not args.include_medium
        perform_moves(dbx, candidates, dry_run=args.dry_run, only_high=only_high)
        print("Move phase complete. Review output above and the CSV for audit trail.")
    else:
        print("\nNext steps:")
        print("1. Open the CSV report.")
        print("2. Review the results carefully (focus on High confidence rows first).")
        print("3. Re-run with --move --dry-run (on a specific --path if desired) to preview.")
        print("4. Then run with --move (no --dry-run) to safely relocate only High-confidence extracted files.")
        print("   Add --include-medium ONLY after thorough manual review of the report.")


if __name__ == "__main__":
    main()
