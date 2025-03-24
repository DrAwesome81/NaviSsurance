import fitz
import sys
sys.path.append(r'C:\Users\adamo\Dropbox\_Consulting\NaviSsurance') 
import pytesseract
from PIL import Image
import os
import tempfile
from dropbox import Dropbox
from core.api import get_dropbox_client
print("All imports good!")
dbx = get_dropbox_client()
print("Dropbox connected!")