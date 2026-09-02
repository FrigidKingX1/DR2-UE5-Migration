"""Synthetic JPK fixture builder, mirroring EgoEngineLibrary's writer."""

from __future__ import annotations

import struct

JPK_MAGIC = 1262571594
ALIGNMENT = 16


def _pad(n: int, alignment: int = ALIGNMENT) -> int:
    return (-n) & (alignment - 1)


def build_jpk() -> bytes:
    """Return a synthetic '.jpk' archive with three entries.

    Mirrors JpkFile.Write (names NUL-terminated, 16-byte alignment)."""
    entries = [
        ("intro.bik", b"\x00\x01\x02\x03RIFF" + b"\xff\xfe" * 8),
        ("bin/global_safety.xml", b"<safety/>"),
        ("vehicles/car.pssg", b"PSSGBIN" ),
    ]

    count = len(entries)

    # --- Compute offsets (mirror C# UpdateOffsets) ---
    name_offsets: list[int] = []
    name_offset = 32 + count * 32 + 1
    for name, _ in entries:
        name_offsets.append(name_offset)
        name_offset += 1 + len(name)

    file_offsets: list[int] = []
    file_offset = name_offset + _pad(name_offset)
    for name, data in entries:
        file_offsets.append(file_offset)
        file_offset += len(data) + _pad(len(data))

    # --- Header ---
    header = bytearray(32)
    struct.pack_into("<I", header, 0, JPK_MAGIC)
    struct.pack_into("<i", header, 8, count)
    struct.pack_into("<i", header, 12, ALIGNMENT)
    struct.pack_into("<i", header, 20, 32 + count * 32)

    # --- Entry table ---
    table = bytearray()
    for i, (name, data) in enumerate(entries):
        table += struct.pack("<i", name_offsets[i])
        table += struct.pack("<i", len(data))
        table += struct.pack("<i", file_offsets[i])
        table += struct.pack("<i", len(data))
        table += bytes(16)

    # --- Names ---
    names = bytearray([0])  # the 1 padding byte before names
    for name, _ in entries:
        names += name.encode("utf-8") + b"\x00"

    # align names section
    names_end = len(table) + len(names)
    names += bytes(_pad(names_end))

    # --- Data ---
    data_block = bytearray()
    for name, data in entries:
        data_block += data
        data_block += bytes(_pad(len(data)))

    blob = bytes(header) + bytes(table) + bytes(names) + bytes(data_block)

    # sanity: file_offsets should line up with the actual data block start
    data_start = 32 + len(table) + len(names)
    assert data_start == min(file_offsets)
    return blob


EXPECTED = {
    "intro.bik": b"\x00\x01\x02\x03RIFF" + b"\xff\xfe" * 8,
    "bin/global_safety.xml": b"<safety/>",
    "vehicles/car.pssg": b"PSSGBIN",
}