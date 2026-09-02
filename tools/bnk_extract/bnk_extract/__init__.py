"""Wwise .bnk bank reader and WEM payload extractor.

Wwise banks are a chain of sections (BKHD, DIDX, DATA, HIRC, ...):
    [4-byte tag][4-byte big-endian size][payload]
DIDX holds the media index: one 12-byte entry per embedded WEM:
    [u32 source id][u32 offset into DATA][u32 size]
This module extracts the WEM payloads to disk plus a JSON manifest.

WEM files are Wwise-encoded media (usually Vorbis); converting them to
playable formats needs an external tool (e.g. wwiser + revorb / Wwise
unpack), which is out of scope here — this is the extraction prerequisite
for MetaSounds re-authoring.
"""

from __future__ import annotations

import json
import os
import struct


class BnkFormatError(ValueError):
    pass


def _parse_chain(data: bytes, endian: str) -> dict:
    sections = {}
    pos = 0
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4].decode("ascii", "replace")
        (size,) = struct.unpack_from(endian + "I", data, pos + 4)
        payload = data[pos + 8:pos + 8 + size]
        if len(payload) != size:
            raise BnkFormatError(
                f"section {tag} runs past end of file (size {size})")
        sections.setdefault(tag, payload)  # first occurrence wins
        pos += 8 + size
    if not sections:
        raise BnkFormatError("no sections found (not a bnk file?)")
    return sections


def read_sections(data: bytes) -> dict:
    """Parse the bank's section chain: {tag: bytes}.

    Endianness is auto-detected: Wwise banks come in both byte orders (DR2
    split-.dat banks are big-endian, per-car .bnk files little-endian), so we
    parse with whichever byte order makes the section chain land exactly on
    EOF.
    """
    errors = {}
    for endian in (">", "<"):
        try:
            return _parse_chain(data, endian)
        except BnkFormatError as exc:
            errors[endian] = str(exc)
    raise BnkFormatError(
        "section chain invalid in both byte orders: " + "; ".join(errors.values()))


def parse_didx(didx: bytes, endian: str = ">") -> list:
    """Parse DIDX payloads: [{id, offset, size}] (offsets are DATA-relative)."""
    if len(didx) % 12 != 0:
        raise BnkFormatError(f"DIDX size {len(didx)} not a multiple of 12")
    out = []
    for i in range(len(didx) // 12):
        src, offset, size = struct.unpack_from(endian + "III", didx, i * 12)
        out.append({"id": src, "offset": offset, "size": size})
    return out


def _detect_endian(data: bytes) -> str:
    """Return the byte order whose DIDX offsets land inside DATA."""
    sections = read_sections(data)
    if "DIDX" not in sections or "DATA" not in sections:
        return ">"
    data_len = len(sections["DATA"])
    for endian in (">", "<"):
        try:
            entries = parse_didx(sections["DIDX"], endian)
            if entries and all(
                    e["offset"] + e["size"] <= data_len for e in entries):
                return endian
        except BnkFormatError:
            continue
    return ">"


def extract_wems(data: bytes) -> dict:
    """Extract all embedded WEM payloads: {source_id: bytes}."""
    sections = read_sections(data)
    if "DIDX" not in sections or "DATA" not in sections:
        raise BnkFormatError("bank has no DIDX/DATA sections (no media)")
    endian = _detect_endian(data)
    data_payload = sections["DATA"]
    out = {}
    for entry in parse_didx(sections["DIDX"], endian):
        payload = data_payload[entry["offset"]:entry["offset"] + entry["size"]]
        if len(payload) != entry["size"]:
            raise BnkFormatError(
                f"WEM {entry['id']} truncated ({len(payload)}/{entry['size']})")
        out[entry["id"]] = payload
    return out


def extract_bank(bank_path: str, out_dir: str) -> str:
    """Extract one .bnk: writes <id>.wem files + <bank>_manifest.json."""
    with open(bank_path, "rb") as fh:
        data = fh.read()
    sections = read_sections(data)
    os.makedirs(out_dir, exist_ok=True)
    wems = {}
    if "DIDX" in sections and "DATA" in sections:
        wems = extract_wems(data)
    manifest = {
        "bank": os.path.basename(bank_path),
        "sections": {tag: len(payload) for tag, payload in sections.items()},
        "wems": {},
    }
    for src, payload in wems.items():
        name = f"{src}.wem"
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(payload)
        manifest["wems"][str(src)] = {
            "file": name,
            "size": len(payload),
            "magic": payload[:4].hex(),
        }
    manifest_path = os.path.join(
        out_dir, os.path.splitext(os.path.basename(bank_path))[0]
        + "_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest_path
