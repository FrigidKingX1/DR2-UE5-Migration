"""End-to-end test: run extract_archive on the synthetic .nefs and verify the
directory tree and file contents land on disk correctly (including nested
directories and each transform type)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from nefs_unpack import read_standard_archive
from nefs_unpack.extract import extract_archive

from _fixture import build_nefs

EXPECTED = {
    "a.txt": b"hello, world",
    "b.bin": b"compressible " * 40,
    "c.bin": bytes(range(256)) * 2,
    "nested.txt": b"nested file contents here",
}


def test_extract_tree(tmp_path):
    path = os.path.join(tmp_path, "archive.nefs")
    with open(path, "wb") as f:
        f.write(build_nefs())

    archive = read_standard_archive(path)
    archive.items.volume_paths = [path]

    out = os.path.join(tmp_path, "out")
    extract_archive(archive, out)

    # Root files
    for name in ("a.txt", "b.bin", "c.bin"):
        with open(os.path.join(out, name), "rb") as f:
            assert f.read() == EXPECTED[name]

    # Nested file under sub/
    with open(os.path.join(out, "sub", "nested.txt"), "rb") as f:
        assert f.read() == EXPECTED["nested.txt"]

    assert os.path.isdir(os.path.join(out, "sub"))


def test_cli_list_and_unpack(tmp_path, capsys):
    path = os.path.join(tmp_path, "archive.nefs")
    with open(path, "wb") as f:
        f.write(build_nefs())

    from nefs_unpack.__main__ import main

    # list
    rc = main(["list", path])
    out = capsys.readouterr().out
    assert rc == 0
    assert "a.txt" in out
    assert "sub" in out

    # unpack
    out_dir = os.path.join(tmp_path, "cli_out")
    rc = main(["unpack", path, "--out", out_dir])
    assert rc == 0
    for name, content in EXPECTED.items():
        target = os.path.join(out_dir, name) if name != "nested.txt" else os.path.join(out_dir, "sub", name)
        with open(target, "rb") as f:
            assert f.read() == content
