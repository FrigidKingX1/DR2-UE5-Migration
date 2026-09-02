"""EGO JPK archive reader and extractor.

JPK ("JPAK") packages are a flat container of named byte blobs used by
EGO Engine titles (DiRT Rally 2.0 `.jpk`).  No compression on entry data.

Reference port of EgoEngineLibrary/Archive/Jpk/ (MIT).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from .constants import ENTRY_SIZE, HEADER_SIZE, JPK_MAGIC


class JpkFormatError(Exception):
    pass


@dataclass
class JpkEntry:
    name: str
    name_offset: int
    size: int
    file_offset: int
    data_offset: int = 0

    def read_data(self, raw: bytes) -> bytes:
        return raw[self.data_offset:self.data_offset + self.size]


@dataclass
class JpkFile:
    alignment: int = 16
    entries: List[JpkEntry] = field(default_factory=list)


def _read_cstring(raw: bytes, offset: int) -> str:
    end = raw.find(b"\x00", offset)
    if end == -1:
        end = len(raw)
    return raw[offset:end].decode("utf-8", errors="replace")


def read_jpk(file_path: str) -> tuple[JpkFile, bytes]:
    """Parse a JPK archive.  Returns (JpkFile, whole-file bytes)."""
    with open(file_path, "rb") as f:
        raw = f.read()

    if len(raw) < HEADER_SIZE:
        raise JpkFormatError("File too small to be a JPK archive.")

    magic = int.from_bytes(raw[0:4], "little")
    if magic != JPK_MAGIC:
        raise JpkFormatError("Not a JPK file (bad magic).")

    num_entries = int.from_bytes(raw[8:12], "little")
    alignment = int.from_bytes(raw[12:16], "little")

    if num_entries < 0 or HEADER_SIZE + num_entries * ENTRY_SIZE > len(raw):
        raise JpkFormatError(f"Truncated JPK archive ({num_entries} entries).")

    jpk = JpkFile(alignment=alignment)
    base = HEADER_SIZE
    for i in range(num_entries):
        pos = base + i * ENTRY_SIZE
        name_offset = int.from_bytes(raw[pos:pos + 4], "little")
        size = int.from_bytes(raw[pos + 4:pos + 8], "little")
        file_offset = int.from_bytes(raw[pos + 8:pos + 12], "little")

        if name_offset < 0 or name_offset >= len(raw):
            name = ""
        else:
            name = _read_cstring(raw, name_offset)

        data_offset = file_offset if 0 <= file_offset < len(raw) else 0
        jpk.entries.append(JpkEntry(name, name_offset, size, file_offset, data_offset))

    return jpk, raw


def extract_entry(entry: JpkEntry, raw: bytes) -> bytes:
    return entry.read_data(raw)


def extract_jpk(file_path: str, out_dir: str) -> List[str]:
    """Extract all entries in a JPK archive to ``out_dir``.

    Returns the list of relative paths written."""
    jpk, raw = read_jpk(file_path)
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    for entry in jpk.entries:
        data = extract_entry(entry, raw)
        # Names may contain '/' separators -> reconstruct a folder tree.
        norm = entry.name.replace("\\", "/")
        rel = norm.lstrip("/")
        target = os.path.join(out_dir, rel)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        written.append(rel)

    return written
