"""Round-trip tests for jpk_unpack."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jpk_unpack import JpkFormatError, extract_entry, extract_jpk, read_jpk
import pytest

from _fixture import EXPECTED, build_jpk


def _write_blob(tmp_path, name="test.jpk"):
    path = os.path.join(tmp_path, name)
    with open(path, "wb") as f:
        f.write(build_jpk())
    return path


def test_roundtrip(tmp_path):
    path = _write_blob(tmp_path)
    jpk, raw = read_jpk(path)
    assert jpk.alignment == 16
    assert len(jpk.entries) == 3

    by_name = {e.name: e for e in jpk.entries}
    for name, content in EXPECTED.items():
        assert extract_entry(by_name[name], raw) == content


def test_extract(tmp_path):
    path = _write_blob(tmp_path)
    out = os.path.join(tmp_path, "out")
    written = extract_jpk(path, out)

    for rel, content in EXPECTED.items():
        with open(os.path.join(out, rel), "rb") as f:
            assert f.read() == content
    assert {w.replace(os.sep, "/") for w in written} == set(EXPECTED.keys())


def test_bad_magic(tmp_path):
    p = os.path.join(tmp_path, "bad.jpk")
    with open(p, "wb") as f:
        f.write(b"JUNK" * 16)
    with pytest.raises(JpkFormatError):
        read_jpk(p)