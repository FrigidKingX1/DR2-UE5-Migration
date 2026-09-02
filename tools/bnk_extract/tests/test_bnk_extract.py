"""Tests for bnk_extract (synthetic banks, no real game assets)."""

from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest

from bnk_extract import (
    BnkFormatError,
    extract_bank,
    extract_wems,
    parse_didx,
    read_sections,
)


def build_bank(wems: dict, include_hirc=True) -> bytes:
    """wems: {source_id: payload bytes}."""
    didx = b"".join(struct.pack(">III", 0, 0, 0) for _ in wems)  # patched later
    data = bytearray()
    entries = []
    for src, payload in wems.items():
        entries.append(struct.pack(">III", src, len(data), len(payload)))
        data += payload
    didx = b"".join(entries)
    out = b"BKHD" + struct.pack(">I", 8) + b"\x00" * 8
    out += b"DIDX" + struct.pack(">I", len(didx)) + didx
    out += b"DATA" + struct.pack(">I", len(data)) + bytes(data)
    if include_hirc:
        out += b"HIRC" + struct.pack(">I", 4) + b"\x00" * 4
    return out


def test_read_sections():
    bank = build_bank({1: b"AAAA", 2: b"BB"})
    sections = read_sections(bank)
    assert set(sections) == {"BKHD", "DIDX", "DATA", "HIRC"}
    assert sections["DATA"] == b"AAAABB"


def test_read_sections_truncated():
    with pytest.raises(BnkFormatError):
        read_sections(b"BKHD" + struct.pack(">I", 100) + b"short")


def test_parse_didx():
    didx = struct.pack(">III", 7, 16, 32)
    entries = parse_didx(didx)
    assert entries == [{"id": 7, "offset": 16, "size": 32}]


def test_parse_didx_bad_size():
    with pytest.raises(BnkFormatError):
        parse_didx(b"\x00" * 10)


def test_extract_wems():
    bank = build_bank({42: b"RIFFxxxxWAVE", 43: b"BKHD2payload"})
    wems = extract_wems(bank)
    assert wems[42] == b"RIFFxxxxWAVE"
    assert wems[43] == b"BKHD2payload"


def test_extract_wems_missing_data():
    with pytest.raises(BnkFormatError):
        extract_wems(b"BKHD" + struct.pack(">I", 4) + b"\x00" * 4)


def test_extract_bank_roundtrip(tmp_path):
    bank = build_bank({101: b"\x00\x01RIFF", 202: b"Z" * 40})
    path = os.path.join(str(tmp_path), "test.bnk")
    with open(path, "wb") as fh:
        fh.write(bank)
    out = os.path.join(str(tmp_path), "out")
    manifest_path = extract_bank(path, out)
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert set(manifest["wems"]) == {"101", "202"}
    assert manifest["wems"]["202"]["size"] == 40
    with open(os.path.join(out, "101.wem"), "rb") as fh:
        assert fh.read() == b"\x00\x01RIFF"
    with open(os.path.join(out, "202.wem"), "rb") as fh:
        assert fh.read() == b"Z" * 40


def test_extract_bank_no_media(tmp_path):
    path = os.path.join(str(tmp_path), "empty.bnk")
    with open(path, "wb") as fh:
        fh.write(b"BKHD" + struct.pack(">I", 4) + b"\x00" * 4)
    out = os.path.join(str(tmp_path), "out2")
    manifest_path = extract_bank(path, out)
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["wems"] == {}
