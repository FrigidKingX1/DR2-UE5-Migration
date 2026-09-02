"""Round-trip test: build a synthetic v1.6.0 `.nefs`, parse it, and verify
extraction reproduces the exact original bytes for every item (including the
Zlib- and Aes-transformed files).
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

import pytest

from nefs_unpack import read_standard_archive
from nefs_unpack.transformer import extract_item

from _fixture import AES_KEY, build_nefs


def _load(tmp_path):
    blob = build_nefs()
    path = os.path.join(tmp_path, "archive.nefs")
    with open(path, "wb") as f:
        f.write(blob)
    archive = read_standard_archive(path)
    # Volume path must point back at the same file (contains header + data).
    archive.items.volume_paths = [path]
    return archive, blob


EXPECTED = {
    "a.txt": b"hello, world",
    "b.bin": b"compressible " * 40,
    "c.bin": bytes(range(256)) * 2,
    "nested.txt": b"nested file contents here",
}


def test_roundtrip_all_items(tmp_path):
    archive, blob = _load(tmp_path)
    assert archive.version == 0x10600
    assert archive.aes_key == AES_KEY

    found = {}
    with open(archive.items.volume_path(0), "rb") as f:
        volume = f.read()
    for item in archive.items.items:
        if item.is_directory:
            continue
        data = extract_item(volume, item, archive.aes_key)
        found[item.file_name] = data

    assert found == EXPECTED


def test_paths_and_directories(tmp_path):
    archive, blob = _load(tmp_path)
    names = {i.file_name: i for i in archive.items.items}
    assert "sub" in names and names["sub"].is_directory
    assert "nested.txt" in names
    assert names["nested.txt"].directory_id == names["sub"].id
