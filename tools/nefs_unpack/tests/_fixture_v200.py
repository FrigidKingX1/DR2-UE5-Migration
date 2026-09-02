"""Synthetic fixture builder for v2.0.0 NeFS archives.

Builds a valid `.nefs` file using v2.0.0 format whose item data uses a mix of
transform types (None, Zlib, Aes).  Used by the round-trip tests to prove
the v2.0.0 parser and detransformer are correct.
"""

from __future__ import annotations

import struct
import zlib

from nefs_unpack.constants import (
    AES_BLOCK_SIZE,
    FOUR_CC,
    INTRO_SIZE,
    NO_BLOCKS_INDEX,
    DataTransformType,
    EntryFlags200,
    NefsVersion,
)

AES_KEY = bytes(range(32))

ENTRY_SIZE = 20      # part1
SHARED_SIZE = 20     # part2
BLOCK_V200_SIZE = 4  # part4 v2.0.0 (just u32 End)
VOLUME_SIZE = 16     # part5
WRITABLE_ENTRY_SIZE = 4
WRITABLE_SHARED_SIZE = 8

BLOCK_SIZE_VAL = 0x10000  # v2.0.0 fixed block size


def _raw_deflate_compress(data: bytes) -> bytes:
    """Raw DEFLATE (RFC 1951, no zlib header) -- matches .NET DeflateStream."""
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def _aes_encrypt(data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    pad = (-len(data)) % AES_BLOCK_SIZE
    padded = data + b"\x00" * pad
    enc = Cipher(algorithms.AES(AES_KEY), modes.ECB()).encryptor()
    return enc.update(padded) + enc.finalize()


def build_nefs_v200() -> bytes:
    """Return a synthetic v2.0.0 `.nefs` archive as bytes.

    Items (in entry-index order):
      id 0  "/"              dir
      id 1  "a.txt"          raw (untransformed)
      id 2  "b.bin"          raw-deflate compressed
      id 3  "c.bin"          AES-ECB encrypted
      id 4  "sub/"           dir
      id 5  "nested.txt"     raw (child of "sub")
    """
    a_data = b"hello, world"
    b_data = b"compressible " * 40
    c_data = bytes(range(256)) * 2
    n_data = b"nested file contents here"

    # Transform each file's bytes to on-disk form.
    a_on_disk = a_data                           # raw
    b_on_disk = _raw_deflate_compress(b_data)    # raw-deflate
    c_on_disk = _aes_encrypt(c_data)             # AES-ECB
    n_on_disk = n_data                           # raw

    # Per-file on-disk cumulative sizes (single block each).
    a_block_end = len(a_on_disk)
    b_block_end = len(b_on_disk)
    c_block_end = len(c_on_disk)
    n_block_end = len(n_on_disk)

    # ---- Data volume (appended after the header) ----
    data = bytearray()
    a_off = len(data); data += a_on_disk
    b_off = len(data); data += b_on_disk
    c_off = len(data); data += c_on_disk
    n_off = len(data); data += n_on_disk

    # ---- Names ----
    name_bytes = bytearray()
    name_off = {}
    for nm in ("a.txt", "b.bin", "c.bin", "sub", "nested.txt"):
        name_off[nm] = len(name_bytes)
        name_bytes += nm.encode("ascii") + b"\x00"
    name_table_size = len(name_bytes)

    # ---- Header part placement ----
    # Intro(128) + TOC(128) are fixed; parts follow.
    part1_start = 2 * INTRO_SIZE   # =256
    n_entries = 6
    n_shared = 6
    n_volumes = 1
    # Blocks: only b.bin (zlib) and c.bin (aes) reference the block table.
    # a.txt and nested.txt are untransformed (FirstBlock == NoBlocksIndex).
    n_blocks = 2

    part2_start = part1_start + n_entries * ENTRY_SIZE
    part3_start = part2_start + n_shared * SHARED_SIZE
    part4_start = part3_start + name_table_size
    part5_start = part4_start + n_blocks * BLOCK_V200_SIZE
    # Part 8: hash digests.  For a tiny synthetic archive, place it after part 5
    # with zero-length table (num_hashes computed from volume size, but we put
    # part 8 at the end with empty data -- the reader is defensive).
    part8_start = part5_start + n_volumes * VOLUME_SIZE
    part6_start = part8_start  # no hash data (volume size = data size, 0 compressed - data_offset)
    part7_start = part6_start + n_entries * WRITABLE_ENTRY_SIZE
    endpoint = part7_start + n_shared * WRITABLE_SHARED_SIZE

    # Data section begins at `endpoint`; entry.Start is absolute.
    D = endpoint

    # ---- Part 1: entry table (20 bytes each) ----
    part1 = struct.pack(
        "<" + "I" * (5 * n_entries),
        # id0 dir: start=0, sharedInfo=0, firstBlock=NO_BLOCKS_INDEX, nextDup=0
        0, 0, 0, NO_BLOCKS_INDEX, 0,
        # id1 a.txt: raw, firstBlock=NO_BLOCKS_INDEX
        D + a_off, 0, 1, NO_BLOCKS_INDEX, 0,
        # id2 b.bin: zlib, firstBlock=0
        D + b_off, 0, 2, 0, 0,
        # id3 c.bin: aes, firstBlock=1
        D + c_off, 0, 3, 1, 0,
        # id4 sub: dir, firstBlock=NO_BLOCKS_INDEX
        0, 0, 4, NO_BLOCKS_INDEX, 0,
        # id5 nested.txt: raw, firstBlock=NO_BLOCKS_INDEX
        D + n_off, 0, 5, NO_BLOCKS_INDEX, 0,
    )

    # ---- Part 2: shared entries (20 bytes each) ----
    part2 = struct.pack(
        "<" + "I" * (5 * n_shared),
        # id0 root: parent=0, firstChild=1, nameOffset=0, size=0, firstDup=0
        0, 1, 0, 0, 0,
        # id1 a.txt: parent=0, firstChild=0, name=a.txt, size, firstDup=1
        0, 0, name_off["a.txt"], len(a_data), 1,
        # id2 b.bin
        0, 0, name_off["b.bin"], len(b_data), 2,
        # id3 c.bin
        0, 0, name_off["c.bin"], len(c_data), 3,
        # id4 sub: parent=0, firstChild=5
        0, 5, name_off["sub"], 0, 4,
        # id5 nested: parent=4
        4, 0, name_off["nested.txt"], len(n_data), 5,
    )

    # ---- Part 3: name table ----
    part3 = bytes(name_bytes)

    # ---- Part 4: block table v2.0.0 (4 bytes each, just u32 End) ----
    part4 = struct.pack(
        "<" + "I" * n_blocks,
        b_block_end,
        c_block_end,
    )

    # ---- Part 5: volume info (16 bytes each) ----
    part5 = struct.pack("<QII", len(data), 0, 0)

    # ---- Part 8: hash digests (empty -- zero-length for synthetic) ----
    part8 = b""

    # ---- Part 6: writable entries v2.0.0 (4 bytes: u16 volume + u16 flags) ----
    part6 = struct.pack(
        "<" + "HH" * n_entries,
        0, EntryFlags200.IS_DIRECTORY,          # root dir
        0, 0,                                    # a.txt: raw (no transform flag)
        0, EntryFlags200.IS_ZLIB,               # b.bin: raw-deflate
        0, EntryFlags200.IS_AES,                # c.bin: AES-ECB
        0, EntryFlags200.IS_DIRECTORY,          # sub dir
        0, 0,                                    # nested.txt: raw
    )

    # ---- Part 7: writable shared entries (8 bytes each) ----
    part7 = struct.pack(
        "<" + "II" * n_shared,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    )

    # ---- Intro (128 bytes) ----
    intro = bytearray(INTRO_SIZE)
    struct.pack_into("<I", intro, 0, FOUR_CC)
    struct.pack_into("<I", intro, 100, endpoint - INTRO_SIZE)  # toc_size
    struct.pack_into("<I", intro, 104, NefsVersion.VERSION_200)
    struct.pack_into("<I", intro, 108, n_entries)
    intro[0x24:0x24 + 64] = AES_KEY.hex().encode("ascii")

    # ---- TOC B v2.0.0 (128 bytes) ----
    toc = bytearray(128)
    struct.pack_into("<H", toc, 0, n_volumes)
    struct.pack_into("<H", toc, 2, 0)                    # hash_block_lo (unused)
    struct.pack_into("<I", toc, 4, part1_start)           # entry table start
    struct.pack_into("<I", toc, 8, part6_start)           # writable entry table start
    struct.pack_into("<I", toc, 12, part2_start)          # shared entry start
    struct.pack_into("<I", toc, 16, part7_start)          # writable shared start
    struct.pack_into("<I", toc, 20, part3_start)          # name table start
    struct.pack_into("<I", toc, 24, part4_start)          # block table start
    struct.pack_into("<I", toc, 28, part5_start)          # volume info start
    struct.pack_into("<I", toc, 32, part8_start)          # hash digest start

    # ---- Assemble file ----
    header = (bytes(intro) + bytes(toc) + bytes(part1) + bytes(part2) +
              bytes(part3) + bytes(part4) + bytes(part5) + bytes(part8) +
              bytes(part6) + bytes(part7))

    assert len(header) == endpoint, (len(header), endpoint)
    return header + bytes(data)
