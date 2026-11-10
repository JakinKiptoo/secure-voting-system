import os, zipfile
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
             "node_modules", "staticfiles", "media"}
SKIP_EXT = {".pyc", ".sqlite3", ".log"}
with zipfile.ZipFile("evoting_slim.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f == ".env" or f == "evoting_slim.zip" or os.path.splitext(f)[1] in SKIP_EXT:
                continue
            p = os.path.join(root, f)
            z.write(p, os.path.join("evoting_system", os.path.relpath(p, ".")))
print("done")