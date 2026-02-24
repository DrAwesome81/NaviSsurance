"""Convert requirements.txt from UTF-16 to UTF-8 for pip compatibility."""
import pathlib

path = pathlib.Path("requirements.txt")
raw = path.read_bytes()

# Detect and decode
for enc in ["utf-16-le", "utf-16", "utf-16-be", "utf-8"]:
    try:
        text = raw.decode(enc)
        break
    except UnicodeDecodeError:
        continue
else:
    text = raw.decode("utf-8", errors="replace")

# Write as UTF-8
path.write_text(text, encoding="utf-8")
print("Converted requirements.txt to UTF-8. Run: pip install -r requirements.txt")
