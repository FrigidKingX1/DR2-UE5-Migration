"""Read a NeFS archive from disk.

Handles two source types (mirroring VictorBush.Ego.NefsLib.ArchiveSource):

* StandardSource  - a self-contained `.nefs`/`.nfs` file where the header and
                    item data live in the same file (header at offset 0).
* HeadlessSource  - a split-header `.dat` archive where the header lives in the
                    game executable (primary + secondary header blocks) and the
                    item data lives in a separate `.dat` file.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import List, Optional

from .binary_reader import BinaryReader
from .constants import FOUR_CC, INTRO_SIZE
from .header import NeFSHeader, parse_header
from .header_decode import decode_xor_intro, try_rsa_decrypt
from .items import NeFSItemList, build_item_list, NefsDirectoryNode
from .transformer import AesDecryptor

_XOR_OFFSET = 48


@dataclass
class NefsArchive:
    header: NeFSHeader
    items: NeFSItemList
    source_kind: str = "standard"

    @property
    def tree(self) -> NefsDirectoryNode:
        return self.items.build_tree()

    @property
    def aes_key(self) -> Optional[bytes]:
        return self.header.aes_key_bytes

    @property
    def version(self) -> int:
        return self.header.version


def _magic_valid(blob: bytes, offset: int, little: bool = True) -> Optional[bool]:
    """Return True if magic matches little-endian, False if big-endian, None if
    neither."""
    if offset + 4 > len(blob):
        return None
    le = int.from_bytes(blob[offset:offset + 4], "little")
    if le == FOUR_CC:
        return True
    be = int.from_bytes(blob[offset:offset + 4], "big")
    if be == FOUR_CC:
        return False
    return None


def _is_xor_magic(blob: bytes, offset: int) -> bool:
    if offset + 52 > len(blob):
        return False
    magic = int.from_bytes(blob[offset:offset + 4], "little")
    mod = int.from_bytes(blob[offset + _XOR_OFFSET:offset + _XOR_OFFSET + 4], "little")
    return (magic ^ mod) == FOUR_CC


def _read_standard_header_region(file_path: str) -> bytes:
    """Read only the header bytes (intro + toc) of a standalone archive.

    The intro's ``toc_size`` field (offset 100) gives the length of all header
    tables that follow the 128-byte intro, so no need to pull the whole (often
    multi-GB) data volume into memory just to list/parse the archive.

    Returns a blob that is ready for ``parse_header``: plain intros are left
    untouched; XOR-obfuscated and RSA-encrypted intros are decoded and, for the
    RSA case, the AES-encrypted remainder of the header is decrypted too.
    """
    with open(file_path, "rb") as f:
        intro = f.read(INTRO_SIZE)
    if len(intro) < INTRO_SIZE:
        raise ValueError(f"File too small to be a NeFS archive: {file_path}")

    # Try plaintext magic first.
    if _magic_valid(intro, 0) is not None:
        toc_size = struct.unpack_from("<I", intro, 100)[0]
        with open(file_path, "rb") as f:
            return f.read(INTRO_SIZE + toc_size)

    # XOR-obfuscated intro (v1.5.1).  toc_size includes the 128-byte intro;
    # the tables that follow the intro are plaintext.
    if _is_xor_magic(intro, 0):
        decoded_intro = decode_xor_intro(intro)
        toc_size = struct.unpack_from("<I", decoded_intro, 100)[0]
        with open(file_path, "rb") as f:
            raw = f.read(toc_size)
        return decoded_intro + raw[INTRO_SIZE:]

    # RSA-encrypted intro.  The whole header (intro + tables) occupies the
    # first toc_size bytes of the file; the intro is RSA-"encrypted" and the
    # remainder of the header is AES-256-ECB encrypted under the intro's key.
    decoded_intro = try_rsa_decrypt(intro)
    if decoded_intro is None:
        raise ValueError("Header magic number mismatch; cannot decode header.")
    toc_size = struct.unpack_from("<I", decoded_intro, 100)[0]
    key_hex = decoded_intro[36:100].decode("ascii", errors="replace").rstrip("\x00")
    try:
        aes_key = bytes.fromhex(key_hex)
    except ValueError:
        raise ValueError(f"Invalid AES key material in decoded intro: {key_hex!r}")

    with open(file_path, "rb") as f:
        raw = f.read(toc_size)
    if len(raw) < toc_size:
        raise ValueError(f"File too small to hold the (decrypted) header: {file_path}")

    region = raw[INTRO_SIZE:toc_size]
    if len(region) % 16:
        region = region + b"\x00" * (16 - len(region) % 16)
    aes = AesDecryptor(aes_key)
    plain = aes.update(region) + aes.finalize()
    return decoded_intro + plain


def read_header_from_blob(blob: bytes, primary_offset: int, secondary_offset: int) -> NeFSHeader:
    """Decode the header intro (handling RSA/xor obfuscation) and parse tables.

    Mirrors NefsReader.ReadHeaderAsync / ReadSplitHeaderAsync.

    For RSA-encrypted intros the rest of the header (``toc_size - 128`` bytes)
    is AES-256-ECB encrypted under the intro's key and is decrypted here too.
    """
    # Try plaintext magic first (split-header `.dat` headers read from the exe).
    little = _magic_valid(blob, primary_offset)
    if little is not None:
        br = BinaryReader(blob, little_endian=(little is not False))
        return parse_header(br, primary_offset, secondary_offset)

    raw_intro = blob[primary_offset:primary_offset + INTRO_SIZE]

    # XOR-obfuscated intro: tables following it are plaintext.
    if _is_xor_magic(blob, primary_offset):
        intro_bytes = decode_xor_intro(raw_intro)
        toc_size = struct.unpack_from("<I", intro_bytes, 100)[0]
        rest_start = primary_offset + INTRO_SIZE
        header_blob = intro_bytes + blob[rest_start:rest_start + toc_size - INTRO_SIZE]
        return parse_header(BinaryReader(header_blob, little_endian=True), 0, 0)

    # RSA-encrypted intro: rest of header is AES-encrypted.
    intro_bytes = try_rsa_decrypt(raw_intro)
    if intro_bytes is None:
        raise ValueError("Header magic number mismatch; cannot decode header.")
    toc_size = struct.unpack_from("<I", intro_bytes, 100)[0]
    key_hex = intro_bytes[36:100].decode("ascii", errors="replace").rstrip("\x00")
    aes_key = bytes.fromhex(key_hex)

    rest_start = primary_offset + INTRO_SIZE
    if rest_start > len(blob) or rest_start + toc_size - INTRO_SIZE > len(blob):
        raise ValueError("Header region truncated; cannot decode archive.")
    region = blob[rest_start:rest_start + toc_size - INTRO_SIZE]
    if len(region) % 16:
        region = region + b"\x00" * (16 - len(region) % 16)
    aes = AesDecryptor(aes_key)
    plain = aes.update(region) + aes.finalize()
    header_blob = intro_bytes + plain
    return parse_header(BinaryReader(header_blob, little_endian=True), 0, 0)


def read_standard_archive(file_path: str) -> NefsArchive:
    """Read a self-contained `.nefs`/`.nfs` archive."""
    blob = _read_standard_header_region(file_path)
    header = read_header_from_blob(blob, 0, 0)
    items = build_item_list(header, [file_path])
    return NefsArchive(header, items, source_kind="standard")


def read_split_archive(data_file_path: str, header_blob: bytes,
                       primary_offset: int, secondary_offset: int) -> NefsArchive:
    """Read a headless `.dat` archive given the header from the executable."""
    header = read_header_from_blob(header_blob, primary_offset, secondary_offset)
    items = build_item_list(header, [data_file_path])
    return NefsArchive(header, items, source_kind="split")


def read_split_archive_from_exe(data_file_path: str, exe_path: str,
                                primary_offset: int, secondary_offset: int) -> NefsArchive:
    with open(exe_path, "rb") as f:
        exe_blob = f.read()
    return read_split_archive(data_file_path, exe_blob, primary_offset, secondary_offset)
