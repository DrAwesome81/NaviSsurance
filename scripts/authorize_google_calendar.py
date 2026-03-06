from __future__ import annotations

import os
import pickle
from pathlib import Path


def main() -> int:
    # Local imports so this script fails gracefully if deps are missing.
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception as e:
        print("Google OAuth dependencies are not installed.")
        print("Install requirements, then retry.")
        print(f"Error: {e}")
        return 2

    from config import CONFIG_DIR

    config_dir = Path(CONFIG_DIR)
    client_secret_path = config_dir / "client_secret.json"
    token_path = config_dir / "navi_token.pkl"

    if not client_secret_path.exists():
        print("Missing Google OAuth client secret JSON.")
        print(f"Expected: {client_secret_path}")
        print("")
        print("Fix:")
        print("- Create a Google Cloud OAuth 'Desktop app' client")
        print("- Download the JSON")
        print(f"- Save it as: {client_secret_path}")
        print("- Then rerun this script")
        return 2

    # Match app usage: Gmail read-only + Calendar write.
    scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar",
    ]

    print("Starting Google OAuth flow in your browser…")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), scopes)
    creds = flow.run_local_server(port=0)

    try:
        os.makedirs(str(config_dir), exist_ok=True)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
    except Exception as e:
        print(f"Failed to write token file: {token_path}")
        print(f"Error: {e}")
        return 3

    print("")
    print("Success.")
    print(f"Wrote token: {token_path}")
    print("Restart NaviSsurance, then try scheduling again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

