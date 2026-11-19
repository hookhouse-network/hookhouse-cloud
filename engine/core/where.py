"""Where this code is running (20 Nov 2026).

HOOKHOUSE_CLOUD=1 means "cloud mode is ON" and is set on BOTH the PC (.env, by cloud setup) and the GitHub runner, so
it cannot tell them apart: the PC wrote its picture-limit marks and used-footage records into data/state, which every
pull replaces, and ran ~20-minute videos into the picture step all night. in_runner() is true only on the GitHub
Actions runner (GitHub sets GITHUB_ACTIONS=true there) or when a test says so (HOOKHOUSE_RUNNER=1).
"""
from __future__ import annotations

import os


def in_runner() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("HOOKHOUSE_RUNNER") == "1"
