"""Tests for heightfield_extract (synthetic LAND files)."""

from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pytest

from heightfield_extract import (
    HeightfieldFormatError,
    heightmap_png_bytes,
    parse_heightfield,
)


def build_land(width: int, height: int, elevations) -> bytes:
    """Build a LAND file matching the reverse-engineered layout:
    LAND | ver | tag_size(12) | HMAP | hmap_hdr(12) | total | layers | w | h |
    u16 samples."""
    grid = bytearray()
    for row in elevations:
        for v in row:
            grid += struct.pack("<H", v)
    total = 12 + len(grid)
    out = b"LAND" + struct.pack("<I", 1)
    out += struct.pack("<I", 12) + b"HMAP"
    out += struct.pack("<I", 12)          # HMAP header size
    out += struct.pack("<I", total)
    out += struct.pack("<I", 2)           # num layers
    out += struct.pack("<I", width) + struct.pack("<I", height)
    out += bytes(grid)
    return out


def test_parse_roundtrip():
    rows = [[100 * (x + y) for x in range(6)] for y in range(4)]
    data = build_land(6, 4, rows)
    parsed = parse_heightfield(data)
    assert parsed["width"] == 6 and parsed["height"] == 4
    assert parsed["num_layers"] == 2
    assert parsed["min_height"] == 0
    assert parsed["max_height"] == 800
    assert parsed["grid"][1][2] == 300


def test_parse_bad_magic():
    with pytest.raises(HeightfieldFormatError):
        parse_heightfield(b"NOPE" + b"\x00" * 64)


def test_parse_truncated_grid():
    data = build_land(6, 4, [[1] * 6 for _ in range(4)])
    with pytest.raises(HeightfieldFormatError):
        parse_heightfield(data[: len(data) - 40])


def test_png_roundtrip(tmp_path):
    imagecodecs = pytest.importorskip("imagecodecs")
    rows = [[100 * (x + y) for x in range(8)] for y in range(8)]
    data = build_land(8, 8, rows)
    path = os.path.join(str(tmp_path), "landscape.heightfield")
    with open(path, "wb") as fh:
        fh.write(data)
    from heightfield_extract import extract_to_png
    manifest_path = extract_to_png(path, str(tmp_path))
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    png_path = os.path.join(str(tmp_path), manifest["heightmap_png"])
    with open(png_path, "rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
    img = np.asarray(imagecodecs.png_decode(open(png_path, "rb").read()))
    assert img.dtype == np.uint16
    assert img.max() > 60000 and img.min() < 6000  # normalised


def test_png_none_without_imagecodecs(monkeypatch):
    import heightfield_extract as he
    monkeypatch.setattr(he, "imagecodecs", None)
    rows = [[10] * 4 for _ in range(4)]
    parsed = parse_heightfield(build_land(4, 4, rows))
    assert he.heightmap_png_bytes(parsed) is None