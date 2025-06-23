import os
import glob

migration_files = glob.glob('./**/migrations/*.py', recursive=True)
files_to_delete = [f for f in migration_files if not f.endswith('__init__.py')]

for file_path in files_to_delete:
    print(f"Deleting {file_path}")
    os.remove(file_path)
