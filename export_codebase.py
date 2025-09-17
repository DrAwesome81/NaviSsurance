import os

def export_codebase_to_txt(root_dir, output_file='codebase_export.txt', extensions=('.py',), subfolders=None):
    """
    Exports files with specified extensions from the root directory and selected subfolders
    into a single text file, with clear separators between files.
    
    Args:
    - root_dir (str): The root directory of your codebase (e.g., your project folder in Cursor).
    - output_file (str): The name/path of the output text file.
    - extensions (tuple): File extensions to include (default: Python files only).
    - subfolders (list or None): List of subfolder names to include (e.g., ['core', 'gui', 'docs']). If None, includes all.
    """
    with open(output_file, 'w', encoding='utf-8') as outfile:
        # Always include the root directory
        for file in os.listdir(root_dir):
            if file.endswith(extensions):
                file_path = os.path.join(root_dir, file)
                relative_path = os.path.relpath(file_path, root_dir)
                
                # Write separator and file info
                outfile.write(f"--- {relative_path} ---\n\n")
                
                # Write file content
                try:
                    with open(file_path, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                        outfile.write("\n\n")  # Add spacing after content
                except Exception as e:
                    outfile.write(f"Error reading {relative_path}: {e}\n\n")
        
        # Include specified subfolders if provided
        if subfolders:
            for subfolder in subfolders:
                subdir_path = os.path.join(root_dir, subfolder)
                if os.path.isdir(subdir_path):
                    for file in os.listdir(subdir_path):
                        if file.endswith(extensions):
                            file_path = os.path.join(subdir_path, file)
                            relative_path = os.path.relpath(file_path, root_dir)
                            
                            # Write separator and file info
                            outfile.write(f"--- {relative_path} ---\n\n")
                            
                            # Write file content
                            try:
                                with open(file_path, 'r', encoding='utf-8') as infile:
                                    outfile.write(infile.read())
                                    outfile.write("\n\n")  # Add spacing after content
                            except Exception as e:
                                outfile.write(f"Error reading {relative_path}: {e}\n\n")

    print(f"Codebase exported to {output_file}")

# Use the directory where this script is located as the project root
project_root = os.path.dirname(os.path.abspath(__file__))
export_codebase_to_txt(project_root, subfolders=['core', 'gui'])