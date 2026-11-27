"""The cloud must be able to import what the code imports (18 Nov 2026: the cloud test run failed twice because
the map code needed `pyshp`, which was never added to requirements-cloud.txt). Every third-party import in engine/
must be in requirements-cloud.txt or on the PC-only list below (with the reason)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# import name -> pip name (when they differ)
PIP = {"PIL": "pillow", "cv2": "opencv-python-headless", "yaml": "pyyaml", "sklearn": "scikit-learn",
       "shapefile": "pyshp", "sentence_transformers": "sentence-transformers", "faster_whisper": "faster-whisper",
       "huggingface_hub": "huggingface-hub", "sqlite_vec": "sqlite-vec", "freetype": "freetype-py",
       "uharfbuzz": "uharfbuzz", "onnxruntime": "onnxruntime"}
PC_ONLY = {
    "fitz": "PyMuPDF: KDP / store PDF previews run on the PC helper",
    "websockets": "Chrome DevTools control of the PC's HookHouse browser",
    "chatterbox": "optional local voice, PC only, guarded import",
    "parler_tts": "optional local voice, PC only, guarded import",
    "torch": "installed by the workflow from the CPU index before the requirements",
    "dotenv": "PC .env loading; the cloud gets the environment from secrets",
    "starlette": "Control Center (engine/console), runs on the owner's PC only",
    "uvicorn": "Control Center (engine/console), runs on the owner's PC only",
    "jinja2": "Control Center (engine/console), runs on the owner's PC only",
    "gradio_client": "listed with a version pin",
    "huggingface_hub": "listed with a version pin",
}
LOCAL = {"engine", "tests", "scripts", "cli"}


def _third_party_imports() -> set[str]:
    std = set(sys.stdlib_module_names)
    found = set()
    for p in (ROOT / "engine").rglob("*.py"):
        for m in re.finditer(r"^\s*(?:import\s+([a-z_][A-Za-z0-9_]*)\s*(?:$|,|\bas\b|#)|"
                             r"from\s+([A-Za-z_][A-Za-z0-9_]*)[\w.]*\s+import\s)",
                             p.read_text(encoding="utf-8"), re.M):
            name = m.group(1) or m.group(2)
            if name not in std and name not in LOCAL and name != "__future__":
                found.add(name)
    return found


def test_every_cloud_import_is_in_the_cloud_requirements():
    req = (ROOT / "requirements-cloud.txt").read_text(encoding="utf-8").lower()
    listed = {re.split(r"[<>=\[\s#]", ln.strip())[0] for ln in req.splitlines() if ln.strip() and not ln.startswith("#")}
    missing = sorted(n for n in _third_party_imports()
                     if n not in PC_ONLY and PIP.get(n, n).lower().replace("_", "-") not in
                     {x.replace("_", "-") for x in listed})
    assert not missing, f"add to requirements-cloud.txt (or PC_ONLY with a reason): {missing}"
