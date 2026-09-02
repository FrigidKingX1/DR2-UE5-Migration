"""Synthetic fixture builder for v1.6.0 (DiRT Rally 2) NeFS archives.

Builds a fully valid standalone `.nefs` file in memory whose item data uses a
mix of transform types (None, Zlib, Aes).  Used by the round-trip tests to
prove the parser and detransformer are correct without needing the real game.
"""

from __future__ import annotations

import struct
import zlib

from nefs_unpack.constants import (
    AES_BLOCK_SIZE,
    FOUR_CC,
    INTRO_SIZE,
    DataTransformType,
    EntryFlags,
    NefsVersion,
)

AES_KEY = bytes(range(32))

ENTRY_SIZE = 20      # part1
SHARED_SIZE = 20     # part2
BLOCK_SIZE = 8       # part4
VOLUME_SIZE = 16     # part5
WRITABLE_ENTRY_SIZE = 4
WRITABLE_SHARED_SIZE = 8
HASH_SIZE = 0x20     # part8

BLOCK_SIZE_VAL = 0x8000  # stored lo value = BLOCK_SIZE_VAL >> 15 = 1
_BLK_LO = BLOCK_SIZE_VAL >> 15


def _zlib_compress(data: bytes) -> bytes:
    c = zlib.compressobj(9)
    return c.compress(data) + c.flush()


def _aes_encrypt(data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    pad = (-len(data)) % AES_BLOCK_SIZE
    padded = data + b"\x00" * pad
    enc = Cipher(algorithms.AES(AES_KEY), modes.ECB()).encryptor()
    return enc.update(padded) + enc.finalize()


def build_nefs() -> bytes:
    """Return a synthetic v1.6.0 `.nefs` archive as bytes.

    Items (in entry-index order):
      id 0  "/"              dir
      id 1  "a.txt"          None  transform
      id 2  "b.bin"          Zlib  transform
      id 3  "c.bin"          Aes   transform
      id 4  "sub/"           dir
      id 5  "nested.txt"     None  transform (child of "sub")
    """
    a_data = b"hello, world"
    b_data = b"compressible " * 40
    c_data = bytes(range(256)) * 2
    n_data = b"nested file contents here"

    # Transform each file's bytes (compressed->encrypted on write, so we store
    # the *on-disk* bytes as shown).
    a_on_disk = a_data                      # None  (raw)
    b_on_disk = _zlib_compress(b_data)      # Zlib
    c_on_disk = _aes_encrypt(c_data)        # Aes  (ECB -- no standing zlib)
    n_on_disk = n_data                      # None

    # Per-file on-disk cumulative sizes (single block each, since BLOCK_SIZE_VAL
    # is large relative to file sizes).
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
    part1_start = 2 * INTRO_SIZE
    # part sizes
    n_entries = 6
    n_shared = 6
    n_volumes = 1
    # blocks => one per non-dir file = 4
    n_blocks = 4
    # hashes => ceil(data_size / block_size) but at least the volume; use 1
    n_hashes = 1

    part2_start = part1_start + n_entries * ENTRY_SIZE
    part3_start = part2_start + n_shared * SHARED_SIZE
    part4_start = part3_start + name_table_size
    part5_start = part4_start + n_blocks * BLOCK_SIZE
    part8_start = part5_start + n_volumes * VOLUME_SIZE
    part6_start = part8_start + n_hashes * HASH_SIZE
    part7_start = part6_start + n_entries * WRITABLE_ENTRY_SIZE
    endpoint = part7_start + n_shared * WRITABLE_SHARED_SIZE

    # ---- Assemble header parts ----
    # Data section begins at `endpoint`; entry.Start is an absolute offset into
    # the volume file, so add `endpoint` to each file's data-relative offset.
    D = endpoint
    part1 = struct.pack(
        "<" + "I" * (5 * n_entries),
        # id0 dir: start=0, sharedInfo=0, firstBlock=0, nextDup=0
        0, 0, 0, 0, 0,
        # id1 a.txt: start=a_off, shared=1, firstBlock=0, nextDup=0
        D + a_off, 0, 1, 0, 0,
        # id2 b.bin: start=b_off, shared=2, firstBlock=1, nextDup=0
        D + b_off, 0, 2, 1, 0,
        # id3 c.bin: start=c_off, shared=3, firstBlock=2, nextDup=0
        D + c_off, 0, 3, 2, 0,
        # id4 sub: dir start=0, shared=4, firstBlock=0, nextDup=0
        0, 0, 4, 0, 0,
        # id5 nested: start=n_off, shared=5, firstBlock=3, nextDup=0
        D + n_off, 0, 5, 3, 0,
    )

    # shared entries: (parent, firstChild, nameOffset, size, firstDuplicate)
    part2 = struct.pack(
        "<" + "I" * (5 * n_shared),
        # id0 root: parent=0, firstChild=1, nameOffset=0(placeholder), size=0, firstDup=0
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

    part3 = bytes(name_bytes)

    # block records: (end u32, transformation u16, checksum u16)
    part4 = struct.pack(
        "<" + "IHH" * 4,
        a_block_end, DataTransformType.NONE, 0,
        b_block_end, DataTransformType.ZLIB, 0,
        c_block_end, DataTransformType.AES, 0,
        n_block_end, DataTransformType.NONE, 0,
    )

    # volume info: (size u64, nameOffset u32, dataOffset u32)
    part5 = struct.pack("<QII", len(data), 0, 0)

    # hash digests: one 0x20 digest (unused for our purposes)
    part8 = b"\x00" * (n_hashes * HASH_SIZE)

    # writable entries: (volume u16, flags u16)
    # flags: 0=root dir? dir=>2; files=> transformed flag(1) for zlib/aes, 0 for none
    part6 = struct.pack(
        "<" + "HHHHHHHHHHHH",
        0, EntryFlags.DIRECTORY,        # root dir
        0, 0,                           # a.txt none
        0, EntryFlags.TRANSFORMED,      # b.bin zlib
        0, EntryFlags.TRANSFORMED,      # c.bin aes
        0, EntryFlags.DIRECTORY,        # sub dir
        0, 0,                           # nested none
    )

    # writable shared: (nextSibling u32, patchedEntry u32)
    part7 = struct.pack(
        "<" + "II" * n_shared,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    )

    # ---- Intro ----
    intro = bytearray(INTRO_SIZE)
    struct.pack_into("<I", intro, 0, FOUR_CC)
    struct.pack_into("<I", intro, 100, endpoint - INTRO_SIZE)  # toc_size
    struct.pack_into("<I", intro, 104, NefsVersion.VERSION_160)
    struct.pack_into("<I", intro, 108, n_entries)
    intro[0x24:0x24 + 64] = AES_KEY.hex().encode("ascii")

    # ---- TOC B ----
    toc = bytearray(128)
    struct.pack_into("<H", toc, 0, n_volumes)
    struct.pack_into("<H", toc, 2, _BLK_LO)  # hash block size lo
    struct.pack_into("<H", toc, 4, _BLK_LO)  # block size lo
    struct.pack_into("<H", toc, 6, 0)        # split size lo
    struct.pack_into("<I", toc, 8, part1_start)
    struct.pack_into("<I", toc, 12, part6_start)  # writable entry table start
    struct.pack_into("<I", toc, 16, part2_start)  # shared entry start
    struct.pack_into("<I", toc, 20, part7_start)  # writable shared start
    struct.pack_into("<I", toc, 24, part3_start)  # name table start
    struct.pack_into("<I", toc, 28, part4_start)  # block table start
    struct.pack_into("<I", toc, 32, part5_start)  # volume info start
    struct.pack_into("<I", toc, 36, part8_start)  # hash digest start

    # ---- Assemble file ----
    header = bytes(intro) + bytes(toc) + bytes(part1) + bytes(part2) + \
        bytes(part3) + bytes(part4) + bytes(part5) + bytes(part8) + \
        bytes(part6) + bytes(part7)

    assert len(header) == endpoint, (len(header), endpoint)
    return header + bytes(data)
