import os

# Set your project folder and output file
folder = "C:/Users/adamo/Dropbox/_Consulting/NaviSsurance"
output_file = "C:/Users/adamo/Dropbox/_Consulting/NaviSsurance/NaviSsurance_Code.txt"  # Dropbox root

# Open the output file to write
with open(output_file, "w", encoding="utf-8") as out:
    # Section 1: Source Code Files (.py and .qss contents)
    out.write("--- Source Code Files ---\n\n")
    for root, _, files in os.walk(folder):
        for file in files:
            if file.endswith((".py", ".qss")):  # Grab .py and .qss files
                # Get relative path from the root folder
                relative_path = os.path.relpath(os.path.join(root, file), folder)
                # Write header with relative path
                out.write(f"--- {relative_path} ---\n")
                # Write file contents
                with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                    out.write(f.read())
                out.write("\n\n")  # Space between files
    
    # Section 2: All Other Files (titles only, full structure)
    out.write("--- Other Files (Across All Folders) ---\n\n")
    other_files = []
    for root, _, files in os.walk(folder):
        for file in files:
            if not file.endswith((".py", ".qss")):  # Exclude .py and .qss
                # Get relative path for clarity
                relative_path = os.path.relpath(os.path.join(root, file), folder)
                other_files.append(relative_path)
    
    if other_files:
        for file in sorted(other_files):  # Sorted for readability
            out.write(f"- {file}\n")
    else:
        out.write("- No other files found—clean slate, huh?\n")

print(f"Saved to {output_file}")