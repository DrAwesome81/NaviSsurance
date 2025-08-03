import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from exchangelib import Credentials, Account, Configuration, OAuth2Credentials, DELEGATE, Message
from oauthlib.oauth2.rfc6749.tokens import OAuth2Token

# Load environment variables from config/.env
env_path = Path('config') / '.env'
load_dotenv(env_path)

def get_mailbird_token(email):
    """Get OAuth token from Mailbird's stored configuration for a specific email address"""
    try:
        token_path = Path('config/mailbird_tokens.json')
        if not token_path.exists():
            print("No token file found. Please run read_mailbird_config.py first.")
            return None
        with open(token_path, 'r') as f:
            tokens = json.load(f)
        for token in tokens:
            # Match email (case-insensitive, strip whitespace)
            if str(token.get('email', '')).strip().lower() != email.strip().lower():
                continue
            expires_at = datetime.fromisoformat(token['expires_at'].replace('Z', '+00:00'))
            current_time = datetime.now(timezone.utc)
            if expires_at > current_time:
                print(f"Found valid token for {email} (ID: {token['id']})")
                return token
            else:
                print(f"Token for {email} (ID: {token['id']}) has expired")
        print(f"No valid token found for {email}")
        return None
    except Exception as e:
        print(f"Error getting token: {e}")
        return None

def fetch_recent_ews_emails(email, hours=24):
    """Fetch recent emails using Mailbird's OAuth token via EWS"""
    token_data = get_mailbird_token(email)
    if not token_data:
        print(f"Could not get valid token for {email}")
        return []
    try:
        # Construct the OAuth2Token object
        token_obj = OAuth2Token({
            'access_token': token_data['access_token'],
            'token_type': 'Bearer',
            'expires_in': 3600,  # Dummy value; exchangelib doesn't use it for Mailbird tokens
        })
        oauth2_creds = OAuth2Credentials(
            client_id=None,  # Not needed for Mailbird token
            client_secret=None,  # Not needed for Mailbird token
            tenant_id=None,  # Not needed for Mailbird token
            access_token=token_obj,
        )
        config = Configuration(
            credentials=oauth2_creds,
            server='outlook.office365.com',
        )
        account = Account(
            primary_smtp_address=email,
            config=config,
            autodiscover=False,
            access_type=DELEGATE,
        )
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)
        print(f"\nFetching emails for {email} via EWS...")
        messages = list(account.inbox.filter(datetime_received__gte=start_time).order_by('-datetime_received')[:10])
        print(f"\nFound {len(messages)} recent messages:")
        for msg in messages:
            print(f"\nSubject: {msg.subject}")
            print(f"From: {msg.sender.email_address if msg.sender else 'Unknown'}")
            print(f"Received: {msg.datetime_received}")
            print(f"Preview: {msg.text_body[:100] if msg.text_body else 'No preview'}...")
        return messages
    except Exception as e:
        print(f"Error in fetch_recent_ews_emails: {e}")
        return []

def main():
    email1 = os.getenv('MSN_EMAIL_1')
    email2 = os.getenv('MSN_EMAIL_2')
    if not email1 and not email2:
        print("No email addresses found in environment variables")
        return
    accounts = [email1, email2]
    for email in accounts:
        if not email:
            continue
        print(f"\n{'='*50}")
        print(f"Testing EWS email fetch for: {email}")
        print(f"{'='*50}")
        fetch_recent_ews_emails(email)

if __name__ == "__main__":
    main() 