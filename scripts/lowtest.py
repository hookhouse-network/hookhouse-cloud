"""Run pytest at below-normal priority (Windows), so a test run never starves the PC's video making: 26 Nov, local
pictures timed out (600 s each, ~5x normal) while a normal-priority test run used the CPU.
python scripts/lowtest.py <pytest args...>"""
import ctypes
import os
import sys

if os.name == "nt":
    BELOW_NORMAL = 0x00004000
    k32 = ctypes.windll.kernel32
    k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL)

import pytest  # noqa: E402

sys.exit(pytest.main(sys.argv[1:]))
