import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

def extract_mailbird_ms_tokens():
    store_path = Path(os.environ['LOCALAPPDATA']) / 'Mailbird' / 'Store' / 'Store.db'
    output_path = Path('config') / 'mailbird_tokens.json'
    print(f"Extracting Microsoft tokens from: {store_path}")
    try:
        conn = sqlite3.connect(store_path)
        cursor = conn.cursor()

        # Get only Microsoft OAuth credentials, joining with Accounts to get the Username (email)
        cursor.execute("""
            SELECT 
                oauth.Id,
                oauth.AccessToken,
                oauth.AccessTokenExpiresAt_UTC,
                oauth.RefreshToken,
                oauth.ManagerScope,
                oauth.ProviderScope,
                acc.Username as Email
            FROM OAuth2Credentials oauth
            JOIN Accounts acc ON acc.OAuth2CredentialsId = oauth.Id
        """)

        tokens = []
        for row in cursor.fetchall():
            provider_scope = row[5] or ''
            # Only keep Microsoft/Outlook/Office tokens
            if not any(x in provider_scope.lower() for x in ['outlook', 'office', 'microsoft']):
                continue
            email = row[6]  # This is the Username field from Accounts
            token_data = {
                'id': row[0],
                'access_token': row[1],
                'expires_at': row[2],
                'refresh_token': row[3],
                'manager_scope': row[4],
                'provider_scope': row[5],
                'email': email,
                'extracted_at': datetime.now(timezone.utc).isoformat()
            }
            tokens.append(token_data)
            print(f"\nFound Microsoft token for: {email}")
            print(f"Expires at: {token_data['expires_at']}")

        # Save tokens to JSON file
        output_path.parent.mkdir(exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(tokens, f, indent=2)
        print(f"\nMicrosoft tokens saved to: {output_path}")

        conn.close()
        return tokens
    except Exception as e:
        print(f"Error extracting tokens: {e}")
        return None

if __name__ == "__main__":
    extract_mailbird_ms_tokens() 