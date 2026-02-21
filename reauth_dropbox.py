from dropbox import DropboxOAuth2FlowNoRedirect
from core.api import DROPBOX_APP_KEY, DROPBOX_APP_SECRET

auth_flow = DropboxOAuth2FlowNoRedirect(DROPBOX_APP_KEY, DROPBOX_APP_SECRET, token_access_type='offline')
authorize_url = auth_flow.start()
print(f"1. Go to: {authorize_url}")
print("2. Click 'Allow' (log in if needed).")
print("3. Copy the authorization code.")
code = input("Enter the code here: ").strip()
try:
    oauth_result = auth_flow.finish(code)
    print(f"New access_token: {oauth_result.access_token}")
    print(f"New refresh_token: {oauth_result.refresh_token}")
except Exception as e:
    print(f"Error: {e}")