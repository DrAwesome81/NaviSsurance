import sys
sys.path.append(r'C:\Users\adamo\Dropbox\_Consulting\NaviSsurance')
from core.api import get_dropbox_client
from dropbox import files
dbx = get_dropbox_client()
try:
    dbx.files_create_folder_v2("/TestFolder")
    print("Write access confirmed!")
    dbx.files_delete_v2("/TestFolder")
except Exception as e:
    print(f"Still no write access: {e}")