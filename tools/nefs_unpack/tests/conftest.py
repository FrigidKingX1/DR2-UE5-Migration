"""Pytest configuration: ensure `nefs_unpack` and the local `_fixture` are
importable regardless of how pytest is invoked."""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/nefs_unpack
_TESTS = os.path.dirname(os.path.abspath(__file__))

for _p in (_ROOT, _TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
