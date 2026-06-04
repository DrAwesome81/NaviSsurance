import requests
from dotenv import load_dotenv, set_key
import os
from dropbox import Dropbox
from datetime import datetime, timedelta
import logging
import time
from typing import List, Dict, Any, Optional
from core.secure_logging import secure_function_logger, safe_log

logger = logging.getLogger(__name__)
# API layer (GDrive/Dropbox/email) supplies source data for Pulse private memory reflections, Intel raising, and 🛡️ Shield security scans (new data coordination)
# Pulse private memory + Shield (core api surface)

# Load environment variables using centralized paths
from config import CONFIG_DIR
load_dotenv(os.path.join(CONFIG_DIR, ".env"), override=True)

# Load from environment variables
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")
DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")

# Google Drive
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN

# Import centralized ENV_FILE path
from config import ENV_FILE

class DropboxClient:
    """Manages a Dropbox client with token refresh."""
    # New: DropboxClient now supports Pulse private memory data fetch for Shield (additional API coordination)
    def __init__(self):
        self.client = None
        self.access_token = None
        self.expires_at = None

    def get_client(self) -> Dropbox:
        """Get or refresh the Dropbox client."""
        if self.client is None or datetime.now() >= self.expires_at:
            self.refresh()
        return self.client

    def refresh(self):
        """Refresh the Dropbox access token and update .env."""
        safe_log(logger, logging.INFO, "DropboxClient: Starting token refresh...")
        new_access_token, new_refresh_token = refresh_dropbox_token()
        self.access_token = new_access_token
        self.client = Dropbox(new_access_token)
        self.expires_at = datetime.now() + timedelta(hours=4)
        # Update the .env file with the new tokens
        set_key(ENV_FILE, "DROPBOX_ACCESS_TOKEN", new_access_token)
        set_key(ENV_FILE, "DROPBOX_REFRESH_TOKEN", new_refresh_token)
        safe_log(logger, logging.INFO, "DropboxClient: Token refresh completed and saved to .env")

dropbox_client = DropboxClient()

@secure_function_logger
def refresh_dropbox_token():
    """Refresh Dropbox access token with secure logging."""
    safe_log(logger, logging.INFO, "Refreshing Dropbox token...")
    
    response = requests.post("https://api.dropbox.com/oauth2/token", data={
        "grant_type": "refresh_token",
        "refresh_token": DROPBOX_REFRESH_TOKEN,
        "client_id": DROPBOX_APP_KEY,
        "client_secret": DROPBOX_APP_SECRET
    })
    
    if response.status_code == 200:
        data = response.json()
        safe_log(logger, logging.INFO, "Dropbox token refreshed successfully")
        return data["access_token"], data.get("refresh_token", DROPBOX_REFRESH_TOKEN)
    else:
        safe_log(logger, logging.ERROR, f"Failed to refresh Dropbox token: {response.status_code}")
        response.raise_for_status()

def get_dropbox_client() -> Dropbox:
    """Creates a Dropbox client with the current or refreshed access token."""
    return dropbox_client.get_client()


# =============================================================================
# Google Drive Client
# =============================================================================

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
import re
from io import BytesIO

GOOGLE_SCOPES = ['https://www.googleapis.com/auth/drive']  # Phase 4: broadened for direct export uploads to client folders (read ops still work; upload feature optional+defensive)

class GoogleDriveClient:
    """Manages a Google Drive client with OAuth2 token refresh."""
    def __init__(self):
        self.service = None
        self.creds = None

    def get_service(self):
        """Get or refresh the Google Drive service."""
        if self.service is None or not self.creds or not self.creds.valid:
            self.refresh()
        return self.service

    def refresh(self):
        """Refresh Google credentials from refresh token."""
        safe_log(logger, logging.INFO, "GoogleDriveClient: Refreshing credentials...")

        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REFRESH_TOKEN:
            raise ValueError("Google Drive credentials not configured in .env")

        self.creds = Credentials(
            token=None,
            refresh_token=GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=GOOGLE_SCOPES
        )

        if self.creds.expired or not self.creds.token:
            self.creds.refresh(Request())

        self.service = build('drive', 'v3', credentials=self.creds)
        safe_log(logger, logging.INFO, "GoogleDriveClient: Credentials refreshed successfully")

gdrive_client = GoogleDriveClient()

def get_gdrive_service():
    """Returns an authenticated Google Drive service (with auto-refresh)."""
    return gdrive_client.get_service()


# =============================================================================
# Google Drive File Listing + Metadata (Phase 0 Connector)
# =============================================================================


def list_gdrive_files(
    service=None,
    folder_id: str = "root",
    recursive: bool = True,
    query: Optional[str] = None,
    page_size: int = 100,
    max_files: int = 5000,
) -> List[Dict[str, Any]]:
    """
    List files from Google Drive (read-only connector foundation for Phase 0/1).

    Mirrors the style and robustness of Dropbox list_all_files.
    Returns list of dicts with keys:
      - id, name, mimeType, modifiedTime, size, path (best-effort), parents, webViewLink

    folder_id="root" starts at My Drive root. Use folder id for subfolder.
    When recursive=True, performs a real (conservative) breadth-first descent over
    discovered subfolders using a queue (addresses review Issue 3). Respects max_files
    and trashed=false. Full path reconstruction remains future work.
    query: optional Drive API q filter.
    Conservative pagination + basic rate handling per folder.
    """
    if service is None:
        service = get_gdrive_service()

    all_files: List[Dict[str, Any]] = []
    start_time = time.time()
    visited_folders: set = set()
    # Queue for breadth-first folder descent
    folders_to_process = [folder_id]

    base_q = "trashed = false"
    if query:
        base_q = f"({query}) and {base_q}"

    print(f"Starting Google Drive scan from folder '{folder_id}' (recursive={recursive})...")

    try:
        while folders_to_process and len(all_files) < max_files:
            current_folder = folders_to_process.pop(0)
            if current_folder in visited_folders:
                continue
            visited_folders.add(current_folder)

            page_token = None
            while True:
                # Scope query to current folder
                current_q = f"{base_q} and '{current_folder}' in parents"

                results = service.files().list(
                    q=current_q,
                    pageSize=page_size,
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, parents, webViewLink, createdTime)",
                    pageToken=page_token,
                    orderBy="modifiedTime desc",
                ).execute()

                items = results.get("files", [])
                for item in items:
                    if len(all_files) >= max_files:
                        break
                    file_dict = {
                        "id": item["id"],
                        "name": item["name"],
                        "mimeType": item.get("mimeType", ""),
                        "modifiedTime": item.get("modifiedTime"),
                        "createdTime": item.get("createdTime"),
                        "size": int(item.get("size", 0)) if item.get("size") else 0,
                        "parents": item.get("parents", []),
                        "webViewLink": item.get("webViewLink", ""),
                        "path": item["name"],  # placeholder; full path reconstruction expensive (future)
                    }
                    all_files.append(file_dict)

                    # Collect child folders for descent (only when recursive)
                    if recursive and item.get("mimeType") == "application/vnd.google-apps.folder":
                        child_id = item["id"]
                        if child_id not in visited_folders:
                            folders_to_process.append(child_id)

                # Progress
                elapsed = time.time() - start_time
                print(f"\rGDrive scanned: {len(all_files):,} files | Elapsed: {int(elapsed)}s", end="", flush=True)

                page_token = results.get("nextPageToken")
                if not page_token:
                    break
                time.sleep(0.15)

            time.sleep(0.25)  # light pacing between folders

        print(f"\nGoogle Drive scan complete. Found {len(all_files):,} files.")
        if recursive:
            print(f"  (Recursive descent completed; visited {len(visited_folders)} folders.)")

    except HttpError as http_err:
        status = getattr(http_err, "status_code", None) or getattr(http_err, "resp", None)
        if status and int(status) in (429, 403):
            print("\n  GDrive rate/quota limit hit. Sleeping 5s (conservative).")
            time.sleep(5)
            # Let caller decide on higher-level retry; for now surface cleanly
        print(f"\nGoogle Drive listing HttpError: {http_err}")
        safe_log(logger, logging.ERROR, f"GDrive list HttpError: {http_err}")
    except Exception as e:
        print(f"\nError during Google Drive listing: {e}")
        safe_log(logger, logging.ERROR, f"GDrive list error: {e}")

    return all_files


def get_gdrive_file_metadata(file_id: str, service=None) -> Optional[Dict[str, Any]]:
    """Fetch rich metadata for a single Google Drive file by ID (for ingestion pipeline)."""
    if service is None:
        service = get_gdrive_service()
    try:
        meta = service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, modifiedTime, createdTime, size, parents, webViewLink, description, lastModifyingUser"
        ).execute()
        return dict(meta)
    except HttpError as http_err:
        print(f"Failed to fetch GDrive metadata for {file_id} (HttpError): {http_err}")
        safe_log(logger, logging.WARNING, f"GDrive metadata HttpError for {file_id}: {http_err}")
        return None
    except Exception as e:
        print(f"Failed to fetch GDrive metadata for {file_id}: {e}")
        return None


# =============================================================================
# Phase 4 Workspace Production Engine: GDrive client folder export helpers
# (Direct export into Google Drive client folders - smallest safe addition)
# Reused by workspace_tab quick/manual exports only when historical cluster + client context detected.
# Fully defensive: any failure (no creds, perms, network, scope transition, etc) -> silent fallback to local-only export. No behavior change otherwise.
# =============================================================================

def _safe_client_name(name: str) -> str:
    """Internal: match the sanitization used in workspace_tab client folder computation."""
    return re.sub(r'[^A-Za-z0-9_-]', '', str(name or "client"))[:30] or "Client"


def find_or_create_gdrive_folder(name: str, service=None) -> Optional[str]:
    """Find (or create) a folder by safe name directly under My Drive root.
    Used to locate the 'correct client subfolder' for export. Reuses query style from list_gdrive_files.
    """
    if service is None:
        try:
            service = get_gdrive_service()
        except Exception:
            return None
    safe_name = _safe_client_name(name)
    try:
        q = f"mimeType='application/vnd.google-apps.folder' and name='{safe_name}' and trashed=false and 'root' in parents"
        res = service.files().list(q=q, pageSize=1, fields="files(id)").execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]
        # create (requires write scope; will fail gracefully upstream if not)
        meta = {
            "name": safe_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": ["root"],
        }
        created = service.files().create(body=meta, fields="id").execute()
        return created.get("id")
    except Exception:
        # e.g. 403 (insufficient perms / scope), 404, rate, etc -> caller treats as unavailable
        return None


def upload_file_to_gdrive_folder(local_path: str, parent_folder_id: str, service=None) -> Optional[str]:
    """Upload a local file (docx/pdf/md/...) as-is into the given GDrive folder. Small helper."""
    if not parent_folder_id or not os.path.exists(local_path):
        return None
    if service is None:
        try:
            service = get_gdrive_service()
        except Exception:
            return None
    try:
        fn = os.path.basename(local_path)
        mime = None
        fl = fn.lower()
        if fl.endswith(".docx"):
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif fl.endswith(".pdf"):
            mime = "application/pdf"
        elif fl.endswith((".md", ".txt")):
            mime = "text/plain"
        media = MediaFileUpload(local_path, mimetype=mime, resumable=True)
        body = {"name": fn, "parents": [parent_folder_id]}
        created = service.files().create(body=body, media_body=media, fields="id").execute()
        return created.get("id")
    except Exception:
        return None


def upload_text_to_gdrive_folder(text: str, filename: str, parent_folder_id: str, service=None) -> Optional[str]:
    """Upload text content (e.g. manifest/summary) as UTF-8 file into GDrive folder. Used for Related Set artifacts."""
    if not parent_folder_id or not text or not filename:
        return None
    if service is None:
        try:
            service = get_gdrive_service()
        except Exception:
            return None
    try:
        bio = BytesIO(text.encode("utf-8"))
        media = MediaIoBaseUpload(bio, mimetype="text/plain", resumable=False)
        body = {"name": filename, "parents": [parent_folder_id]}
        created = service.files().create(body=body, media_body=media, fields="id").execute()
        return created.get("id")
    except Exception:
        return None


def copy_gdrive_file_to_folder(file_id: str, parent_folder_id: str, new_name: Optional[str] = None, service=None) -> Optional[str]:
    """Phase 4 chained micro-increment (after artifacts upload to client folders): smallest safe helper for native Drive copy of existing file (historical reference from cluster) into the target client subfolder.
    No download/re-upload roundtrip. Reuses get_gdrive_service + folder patterns exactly. Defensive: any error (scope, perms, net, missing file) returns None silently.
    Used only for gdrive-sourced refs in cluster+client export paths.
    """
    if not file_id or not parent_folder_id:
        return None
    if service is None:
        try:
            service = get_gdrive_service()
        except Exception:
            return None
    try:
        body = {"parents": [parent_folder_id]}
        if new_name:
            body["name"] = new_name
        copied = service.files().copy(fileId=file_id, body=body, fields="id").execute()
        return copied.get("id")
    except Exception:
        # silent fallback (e.g. insufficient Drive scope for writes on the source file, rate limits, 404)
        return None


def upload_workspace_artifacts_to_gdrive(
    client_name: str,
    main_local_path: Optional[str] = None,
    manifest_text: Optional[str] = None,
    summary_text: Optional[str] = None,
    billing_text: Optional[str] = None,  # Billing Depth micro: optional billing summary artifact (from workspace related-set extension) for client folder in GDrive. Defensive default; no impact on prior calls.
    cross_ref_text: Optional[str] = None,  # Phase 4 2f4c91b8 chained micro (keep going no pause after sources cross-refs extension): optional Related Document Set Cross-References subsection text (the rich "Companion to ... Other set members..." sibling listing produced inside each member's Historical Sources Used). Uploaded as dedicated artifact for full set traceability pack in client GDrive folder. Defensive; zero impact prior callers.
    consistency_report_text: Optional[str] = None,  # Phase 4 effort--5: optional Related Set Consistency Report (from ConsistencyChecker cross-document analysis). Uploaded as _Related_Set_Consistency_Report.txt for full traceability pack in client GDrive. Defensive; zero impact on prior callers.
    service=None,
) -> bool:
    """Primary small entrypoint for the Phase 4 feature.
    When a generated doc used historical ref+cluster (client context), this uploads:
      - the generated file (from its local_path)
      - Related_Set_Manifest.txt (from in-mem text if present)
      - Related_Set_Summary.md (from in-mem or built)
      - (Billing Depth) _Billing_Summary_for_Set.md (from in-mem if present; uses same cluster for style consistency with prior billing artifacts)
      - (Related Sets cross-refs) _Related_Set_Cross_References.txt (rich sibling/relationship listing from sources append block extension, when set companion)
    into the matching client subfolder in GDrive (found or created by safe name under root).
    Returns True only if uploads were attempted and at least the main succeeded (or no main).
    All errors, missing GDrive, no folder, etc. -> return False (local export unaffected).
    """
    try:
        if service is None:
            service = get_gdrive_service()
    except Exception:
        return False
    folder_id = find_or_create_gdrive_folder(client_name, service=service)
    if not folder_id:
        return False
    any_ok = False
    if main_local_path:
        fid = upload_file_to_gdrive_folder(main_local_path, folder_id, service=service)
        if fid:
            any_ok = True
    safe = _safe_client_name(client_name)
    if manifest_text:
        if upload_text_to_gdrive_folder(manifest_text, f"{safe}_Related_Set_Manifest.txt", folder_id, service=service):
            any_ok = True
    if summary_text:
        if upload_text_to_gdrive_folder(summary_text, f"{safe}_Related_Set_Summary.md", folder_id, service=service):
            any_ok = True
    if billing_text:
        # Billing Depth micro (smallest extension): upload the billing artifact alongside set manifests for complete client folder pack (local write + GDrive). Uses parallel naming convention; optional and defensive.
        if upload_text_to_gdrive_folder(billing_text, f"{safe}_Billing_Summary_for_Set.md", folder_id, service=service):
            any_ok = True
    if cross_ref_text:
        # Phase 4 2f4c91b8 chained keep-going micro (after sources extension + cr_t compute in caller): upload the Related Document Set Cross-References (the exact subsection text listing companions + "Companion to the Validation Plan via the same historical cluster for traceability and consistency" + Other set members relationships, as extended into Historical Sources Used). Provides standalone .txt artifact in client GDrive for complete traceability without opening member docs. Defensive; only for sets; naming parallel to manifest/summary.
        if upload_text_to_gdrive_folder(cross_ref_text, f"{safe}_Related_Set_Cross_References.txt", folder_id, service=service):
            any_ok = True
    if consistency_report_text:
        # Phase 4 effort--5: upload the Related Set Consistency Report (cross-document analysis from ConsistencyChecker) as standalone artifact in client GDrive folder. Completes the full set pack (docs + Manifest + Summary + Cross-Refs + Consistency Report). Defensive; only when present.
        if upload_text_to_gdrive_folder(consistency_report_text, f"{safe}_Related_Set_Consistency_Report.txt", folder_id, service=service):
            any_ok = True
    return any_ok
