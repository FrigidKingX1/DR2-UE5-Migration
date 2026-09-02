"""Synthetic ERP (v4) fixture builder, mirroring EgoEngineLibrary's writer."""

from __future__ import annotations

import struct
import zlib

from erp_unpack.constants import ERP_MAGIC, Compression

VERSION = 4


def _frag_name(raw: bytes, name: str) -> bytes:
    nm = name.encode("utf-8")
    assert len(nm) <= 4, "test fragment name must be <= 4 chars"
    return nm.ljust(4, b"\x00")


def _resource_info_len(identifier_len: int, frag_count: int) -> int:
    # v4: 33*fragCount + idLen + 24 + 2 + 16
    return 33 * frag_count + identifier_len + 24 + 2 + 16


def build_erp() -> bytes:
    """Return a synthetic v4 `.erp` archive.

    Resource 1: "textures/foo.dds", type "texture", 1 zlib fragment
    Resource 2: "data/config.xml",  type "xml",    1 raw fragment
    """
    frag1_data = b"this is a compressible texture payload " * 10

    # resource 1: zlib fragment
    frag1_comp = zlib.compress(frag1_data, 9)
    frag1_size = len(frag1_data)
    frag1_packed = len(frag1_comp)

    # resource 2: raw fragment
    frag2_data = b"<xml><test>1</test></xml>"
    frag2_size = len(frag2_data)
    frag2_packed = frag2_size

    # identifier strings
    id1 = b"textures/foo.dds"
    id2 = b"data/config.xml"
    type_tex = b"texture"
    type_xml = b"xml"

    # ---- Compute resource info block size ----
    # Fragment offsets relative to resource_offset, data written sequentially.
    # We compute the info block first, then derive resource_offset.
    frag1_rel = 0
    frag2_rel = frag1_packed

    # ---- Build resource info entries ----
    def frag_block(name: str, rel_off: int, size: int, comp: int, packed: int) -> bytes:
        return (
            _frag_name(b"", name)
            + struct.pack("<QQi", rel_off, size, 16)
            + struct.pack("<BQ", comp, packed)
        )

    entry1_info_len = _resource_info_len(len(id1), 1)
    entry2_info_len = _resource_info_len(len(id2), 1)

    part1 = struct.pack("<Ih", entry1_info_len, len(id1)) + id1
    part1 += type_tex.ljust(16, b"\x00")
    part1 += struct.pack("<Ih", 1, 0)      # unknown, unknown2
    part1 += struct.pack("<B", 1)          # num fragments
    part1 += frag_block("DATA", frag1_rel, frag1_size, Compression.ZLIB, frag1_packed)
    part1 += struct.pack("<16s", b"\x00" * 16)  # hash

    part2 = struct.pack("<Ih", entry2_info_len, len(id2)) + id2
    part2 += type_xml.ljust(16, b"\x00")
    part2 += struct.pack("<Ih", 1, 0)
    part2 += struct.pack("<B", 1)
    part2 += frag_block("DATA", frag2_rel, frag2_size, Compression.NONE, frag2_packed)
    part2 += struct.pack("<16s", b"\x00" * 16)

    info_block = part1 + part2
    resource_offset = 0x38 + len(info_block)

    # ---- Header ----
    header = bytearray(0x38)
    struct.pack_into("<I", header, 0, ERP_MAGIC)
    struct.pack_into("<i", header, 4, VERSION)
    struct.pack_into("<Q", header, 0x10, 48)       # info offset
    struct.pack_into("<Q", header, 0x18, len(info_block))  # info size
    struct.pack_into("<Q", header, 0x20, resource_offset)
    struct.pack_into("<i", header, 0x30, 2)        # num files
    struct.pack_into("<i", header, 0x34, 2)        # num temp files

    data = bytes(header) + info_block + frag1_comp + frag2_data
    assert len(data) == resource_offset + frag1_packed + frag2_packed
    return data

EXPECTED = {
    "textures/foo.dds": b"this is a compressible texture payload " * 10,
    "data/config.xml": b"<xml><test>1</test></xml>",
}
