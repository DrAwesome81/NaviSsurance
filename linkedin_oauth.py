import requests
import os
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer
from core import settings

load_dotenv(settings.env_file_path())
client_id = os.getenv('LINKEDIN_CLIENT_ID')
client_secret = os.getenv('LINKEDIN_CLIENT_SECRET')
redirect_uri = os.getenv('LINKEDIN_REDIRECT_URI')

if not all([client_id, client_secret, redirect_uri]):
    print("Error: Missing LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, or LINKEDIN_REDIRECT_URI in .env")
    exit(1)

auth_url = f"https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&scope=r_dma_portability_3rd_party"
print(f"Open this URL in your browser: {auth_url}")

class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        try:
            code = self.path.split('code=')[1].split('&')[0]
            token_url = 'https://www.linkedin.com/oauth/v2/accessToken'
            data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'client_id': client_id,
                'client_secret': client_secret
            }
            response = requests.post(token_url, data=data, timeout=15)
            response.raise_for_status()
            token = response.json().get('access_token')
            token_path = settings.data_dir() / "linkedin_token.txt"
            with open(token_path, 'w') as f:
                f.write(token)
            self.wfile.write(b"Access token saved to linkedin_token.txt")
        except Exception as e:
            self.wfile.write(f"Error: {e}".encode())
        server.socket.close()

try:
    server = HTTPServer(('localhost', 8080), OAuthHandler)
    server.serve_forever()
except Exception as e:
    print(f"Server error: {e}")