$ErrorActionPreference = "Stop"

$script = @'
from pathlib import Path
import shutil
import base64

bundle_name = "QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30"
root = Path.cwd()
ext = root / "docs" / "external_review"
staging = ext / bundle_name
zip_path = ext / f"{bundle_name}.zip"
base64_path = ext / f"{bundle_name}.zip.base64.txt"
molchat_root = Path(r"C:\Users\user\Desktop\molcaht\molchat\v3")

def ignore_patterns(dirpath, names):
    skipped = []
    for name in names:
        if name == "__pycache__":
            skipped.append(name)
        elif name.endswith(".pyc") or name.endswith(".pyo"):
            skipped.append(name)
        elif name in {".pytest_cache", ".mypy_cache", ".ruff_cache"}:
            skipped.append(name)
    return skipped

for path in [staging]:
    if path.exists():
        shutil.rmtree(path)
for path in [zip_path, base64_path]:
    if path.exists():
        path.unlink()

(staging / "QCViz").mkdir(parents=True)
(staging / "MolChat").mkdir(parents=True)

shutil.copy2(root / "pyproject.toml", staging / "QCViz" / "pyproject.toml")
if (root / "README.md").exists():
    shutil.copy2(root / "README.md", staging / "QCViz" / "README.md")
shutil.copytree(root / "src" / "qcviz_mcp", staging / "QCViz" / "src" / "qcviz_mcp", ignore=ignore_patterns)
shutil.copytree(root / "tests", staging / "QCViz" / "tests", ignore=ignore_patterns)

shutil.copytree(molchat_root / "backend" / "app", staging / "MolChat" / "backend" / "app", ignore=ignore_patterns)
if (molchat_root / "tests").exists():
    shutil.copytree(molchat_root / "tests", staging / "MolChat" / "tests", ignore=ignore_patterns)
if (molchat_root / "backend" / "requirements.txt").exists():
    (staging / "MolChat" / "backend").mkdir(parents=True, exist_ok=True)
    shutil.copy2(molchat_root / "backend" / "requirements.txt", staging / "MolChat" / "backend" / "requirements.txt")
if (molchat_root / "README.md").exists():
    shutil.copy2(molchat_root / "README.md", staging / "MolChat" / "README.md")

archive_base = ext / bundle_name
shutil.make_archive(str(archive_base), "zip", root_dir=staging)
encoded = base64.b64encode(zip_path.read_bytes()).decode("ascii")
base64_path.write_text(encoded, encoding="utf-8")

print(f"Created: {zip_path}")
print(f"Created: {base64_path}")
'@

$script | python -
