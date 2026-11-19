"""DISABLED FOR THE BUSINESS (19 Nov, owner: "make sure this will not end up in same result as github"). Kaggle's Terms
of Use limit the service to "your own internal, personal, non-commercial use", and its Acceptable Use Policy names
"server farming" as abuse. A daily picture batch for our channels is commercial and farm-like: never run it (or any
fine-tuning for the business) on Kaggle. start() refuses unless KAGGLE_PERSONAL_TEST=1 is set by hand.

Original idea: Kaggle as our free GPU (owner 19 Nov: "divide the tasks between these clouds"). GitHub Actions only orchestrates:
it uploads a jobs file as a private Kaggle dataset, starts the private notebook kaggle/hookhouse_gpu (FLUX.1-schnell,
Apache-2.0, on Kaggle's free T4), polls its status and downloads the pictures. No model runs on GitHub's runners.
Needs KAGGLE_API_TOKEN (.env, PC-made; reaches the cloud with the env sync). Kaggle allows 30 GPU hours a week.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import ROOT

USER = os.environ.get("KAGGLE_USERNAME", "hookhousemedia")
DATASET = f"{USER}/hookhouse-gpu-jobs"
KERNEL = f"{USER}/hookhouse-gpu"
KERNEL_DIR = ROOT / "kaggle" / "hookhouse_gpu"


def _kaggle(*args: str, timeout: int = 600) -> tuple[int, str]:
    exe = shutil.which("kaggle") or "kaggle"
    r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, env={**os.environ})
    return r.returncode, (r.stdout + r.stderr).strip()


def ready() -> bool:
    return bool(os.environ.get("KAGGLE_API_TOKEN") or (Path.home() / ".kaggle" / "kaggle.json").exists())


def upload_jobs(images: list[dict], note: str = "jobs") -> str:
    """Write the jobs file and create / version the private dataset."""
    d = Path(tempfile.mkdtemp(prefix="hh_gpujobs_"))
    (d / "gpu_jobs.json").write_text(json.dumps({"images": images}, ensure_ascii=False), encoding="utf-8")
    (d / "dataset-metadata.json").write_text(json.dumps({"title": "hookhouse-gpu-jobs", "id": DATASET,
                                                         "licenses": [{"name": "CC0-1.0"}]}), encoding="utf-8")
    exists = DATASET.split("/")[1] in _kaggle("datasets", "list", "--mine")[1]
    if exists:
        code, out = _kaggle("datasets", "version", "-p", str(d), "-m", note, "--dir-mode", "zip")
    else:                                              # first run (19 Nov: 'version' on a missing dataset = 403)
        code, out = _kaggle("datasets", "create", "-p", str(d), "--dir-mode", "zip")
    return out


class KaggleNotAllowed(RuntimeError):
    pass


def start() -> str:
    if os.environ.get("KAGGLE_PERSONAL_TEST") != "1":
        raise KaggleNotAllowed("Kaggle is personal/non-commercial only (Terms of Use) and bans server farming (AUP): "
                               "the business pipeline never runs there")
    meta = {"id": KERNEL, "title": "hookhouse-gpu", "code_file": "hookhouse_gpu.py", "language": "python",
            "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
            "dataset_sources": [DATASET], "competition_sources": [], "kernel_sources": [], "model_sources": []}
    (KERNEL_DIR / "kernel-metadata.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return _kaggle("kernels", "push", "-p", str(KERNEL_DIR), "--accelerator", "NvidiaTeslaT4")[1]   # name the T4


def status() -> str:
    """'running' | 'complete' | 'error' | 'queued' | 'unknown' (+ raw text)."""
    out = _kaggle("kernels", "status", KERNEL)[1].lower()
    for s in ("complete", "error", "running", "queued", "cancel"):
        if s in out:
            return s
    return "unknown: " + out[:120]


def download(dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    _kaggle("kernels", "output", KERNEL, "-p", str(dest), timeout=1200)
    return sorted(dest.rglob("*.jpg"))
