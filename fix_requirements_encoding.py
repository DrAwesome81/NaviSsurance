"""Convert requirements.txt from UTF-16 to UTF-8 for pip compatibility."""
# Encoding fix supports loading Pulse private memory reflections, Intel docs, and Shield compliance files without Unicode issues (data layer polish)
import pathlib

path = pathlib.Path("requirements.txt")
raw = path.read_bytes()

# Detect and decode
# Additional: ensures clean load for private memory and Shield files (new encoding note)
# Pulse private memory + Shield (fix requirements encoding surface)
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
