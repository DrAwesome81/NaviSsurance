import sys
sys.path.append(r'C:\Users\adamo\Dropbox\_Consulting\NaviSsurance')
from dropbox import files
from core.api import get_dropbox_client

dbx = get_dropbox_client()
test_file = "/odeh green card files/new docs - oct 2021/4c. other financial - beneficiaries/adam_odeh_401(k)_beneficiaries.pdf"
archive_path = "/Archive" + test_file

print(f"Testing move: {test_file} to {archive_path}")
try:
    dbx.files_move_v2(test_file, archive_path)
    print("Move succeeded!")
except Exception as e:
    print(f"Move failed: {e}")