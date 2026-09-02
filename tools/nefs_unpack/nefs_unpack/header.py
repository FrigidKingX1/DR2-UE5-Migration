"""Parsing of NeFS header structures (v1.6.0 focus, with split-header support).

Ports the layout of VictorBush.Ego.NefsLib header structs. The header is
composed of:

  Part 0 : Header intro      (NefsTocHeaderA160) - 128 bytes
  Part T : Table of contents (NefsTocHeaderB160) - 128 bytes
  Part 1 : Entry table
  Part 2 : Shared entry info table
  Part 3 : Name table
  Part 4 : Block table
  Part 5 : Volume info table
  Part 6 : Writable entry table      (secondary header block)
  Part 7 : Writable shared entry info table (secondary header block)
  Part 8 : Hash digest table

For split-header `.dat` archives, parts 0-5 and 8 live in the *primary*
header block (inside the game executable), while parts 6-7 live in the
*secondary* header block (also inside the executable).  Item data lives in
the separate `.dat` file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .binary_reader import BinaryReader
from .constants import (
    DEFAULT_BLOCK_SIZE_200,
    DEFAULT_HASH_BLOCK_SIZE,
    INTRO_SIZE,
    NefsVersion,
)


@dataclass
class HeaderIntro:
    magic: int
    hash: bytes          # 32 bytes SHA-256
    aes_key_hex: str     # 64-char ASCII hex string (the AES-256 key)
    toc_size: int
    version: int
    num_entries: int
    user_value: int
    random_padding: bytes

    @classmethod
    def read(cls, br: BinaryReader, offset: int) -> "HeaderIntro":
        br.seek(offset)
        magic = br.read_u32()
        h = br.read(0x20)
        aes_hex = br.read_ascii(0x40)
        toc_size = br.read_u32()
        version = br.read_u32()
        num_entries = br.read_u32()
        user_value = br.read_u32()
        pad1 = br.read_u32()
        pad2 = br.read_u32()
        pad3 = br.read_u16()
        unused = br.read_u16()
        # Remaining random padding bytes up to INTRO_SIZE.
        random_padding = br.read(INTRO_SIZE - br.pos + offset) \
            if br.pos < offset + INTRO_SIZE else b""
        return cls(magic, h, aes_hex, toc_size, version, num_entries,
                   user_value, random_padding)


@dataclass
class TableOfContents:
    num_volumes: int
    hash_block_size: int   # already de-shifted (<< 15)
    block_size: int        # already de-shifted (<< 15)
    split_size: int        # already de-shifted (<< 15)
    entry_table_start: int
    writable_entry_table_start: int
    shared_entry_info_table_start: int
    writable_shared_entry_info_table_start: int
    name_table_start: int
    block_table_start: int
    volume_info_table_start: int
    hash_digest_table_start: int

    @classmethod
    def read(cls, br: BinaryReader, offset: int) -> "TableOfContents":
        br.seek(offset)
        num_volumes = br.read_u16()
        hash_block_lo = br.read_u16()
        block_lo = br.read_u16()
        split_lo = br.read_u16()
        entry_table_start = br.read_u32()
        writable_entry_table_start = br.read_u32()
        shared_entry_info_table_start = br.read_u32()
        writable_shared_entry_info_table_start = br.read_u32()
        name_table_start = br.read_u32()
        block_table_start = br.read_u32()
        volume_info_table_start = br.read_u32()
        hash_digest_table_start = br.read_u32()
        return cls(
            num_volumes,
            hash_block_lo << 15,
            block_lo << 15,
            split_lo << 15,
            entry_table_start,
            writable_entry_table_start,
            shared_entry_info_table_start,
            writable_shared_entry_info_table_start,
            name_table_start,
            block_table_start,
            volume_info_table_start,
            hash_digest_table_start,
        )


@dataclass
class TableOfContents200:
    """Version 2.0.0 table of contents (NefsTocHeaderB200).

    Unlike v1.6.0 there is no BlockSize/SplitSize in the TOC; those are fixed
    constants (BlockSize = 0x10000, SplitSize = 0).  The hash block size used
    for part 8 is NefsWriter.DefaultHashBlockSize (0x800000), not a TOC field.
    """

    num_volumes: int
    hash_block_size: int   # fixed: DEFAULT_HASH_BLOCK_SIZE
    block_size: int        # fixed: DEFAULT_BLOCK_SIZE_200
    split_size: int        # fixed: 0
    entry_table_start: int
    writable_entry_table_start: int
    shared_entry_info_table_start: int
    writable_shared_entry_info_table_start: int
    name_table_start: int
    block_table_start: int
    volume_info_table_start: int
    hash_digest_table_start: int

    @classmethod
    def read(cls, br: BinaryReader, offset: int) -> "TableOfContents200":
        br.seek(offset)
        num_volumes = br.read_u16()
        _hash_block_lo = br.read_u16()  # present but unused for part 8
        entry_table_start = br.read_u32()
        writable_entry_table_start = br.read_u32()
        shared_entry_info_table_start = br.read_u32()
        writable_shared_entry_info_table_start = br.read_u32()
        name_table_start = br.read_u32()
        block_table_start = br.read_u32()
        volume_info_table_start = br.read_u32()
        hash_digest_table_start = br.read_u32()
        return cls(
            num_volumes,
            DEFAULT_HASH_BLOCK_SIZE,
            DEFAULT_BLOCK_SIZE_200,
            0,
            entry_table_start,
            writable_entry_table_start,
            shared_entry_info_table_start,
            writable_shared_entry_info_table_start,
            name_table_start,
            block_table_start,
            volume_info_table_start,
            hash_digest_table_start,
        )


@dataclass
class EntryRecord:
    start: int        # offset of item data in the data volume (64-bit)
    shared_info: int  # index into part 2
    first_block: int  # index into part 4
    next_duplicate: int


@dataclass
class SharedEntryInfo:
    parent: int
    first_child: int
    name_offset: int
    size: int         # extracted size
    first_duplicate: int


@dataclass
class BlockRecord:
    end: int            # cumulative transformed size
    transformation: int
    checksum: int


@dataclass
class VolumeInfo:
    size: int
    name_offset: int
    data_offset: int
    name: str = ""


@dataclass
class WritableEntry:
    volume: int
    flags: int


@dataclass
class WritableSharedEntryInfo:
    next_sibling: int
    patched_entry: int


@dataclass
class HashDigest:
    data: bytes


@dataclass
class NeFSHeader:
    intro: HeaderIntro
    toc: TableOfContents
    entries: List[EntryRecord] = field(default_factory=list)
    shared_entries: List[SharedEntryInfo] = field(default_factory=list)
    # name_offset -> name for directory/file names (part 3)
    names_by_offset: Dict[int, str] = field(default_factory=dict)
    names: List[str] = field(default_factory=list)
    blocks: List[BlockRecord] = field(default_factory=list)
    volumes: List[VolumeInfo] = field(default_factory=list)
    writable_entries: List[WritableEntry] = field(default_factory=list)
    writable_shared_entries: List[WritableSharedEntryInfo] = field(default_factory=list)
    hash_digests: List[HashDigest] = field(default_factory=list)

    @property
    def aes_key_bytes(self) -> Optional[bytes]:
        try:
            return bytes.fromhex(self.intro.aes_key_hex)
        except ValueError:
            return None

    @property
    def version(self) -> int:
        return self.intro.version

    @property
    def is_encrypted(self) -> bool:
        return self.aes_key_bytes is not None

    @property
    def is_little_endian(self) -> bool:
        return True

    def get_file_name(self, name_offset: int) -> str:
        return self.names_by_offset.get(name_offset, f"<name@{name_offset:#x}>")


def _read_part1(br: BinaryReader, header_base: int, start: int, size: int) -> List[EntryRecord]:
    """Entry table (part 1). Each entry is 5 x uint32 = 20 bytes."""
    br.seek(header_base + start)
    n = size // 20
    entries: List[EntryRecord] = []
    for _ in range(n):
        start_a = br.read_u32()
        start_b = br.read_u32()
        start_val = start_a | (start_b << 32)
        shared_info = br.read_u32()
        first_block = br.read_u32()
        next_duplicate = br.read_u32()
        entries.append(EntryRecord(start_val, shared_info, first_block, next_duplicate))
    return entries


def _read_part2(br: BinaryReader, header_base: int, start: int, size: int) -> List[SharedEntryInfo]:
    """Shared entry info table (part 2). Each entry is 5 x uint32 = 20 bytes."""
    br.seek(header_base + start)
    n = size // 20
    out: List[SharedEntryInfo] = []
    for _ in range(n):
        parent = br.read_u32()
        first_child = br.read_u32()
        name_offset = br.read_u32()
        size_val = br.read_u32()
        first_duplicate = br.read_u32()
        out.append(SharedEntryInfo(parent, first_child, name_offset, size_val, first_duplicate))
    return out


def _read_part3(br: BinaryReader, header_base: int, start: int, size: int) -> Dict[int, str]:
    """Name table (part 3): NUL-terminated ASCII strings, keyed by offset."""
    names_by_offset: Dict[int, str] = {}
    br.seek(header_base + start)
    blob = br.read(size)
    offset = 0
    while offset < size:
        end = blob.find(b"\x00", offset)
        if end == -1:
            break
        raw = blob[offset:end]
        names_by_offset[offset] = raw.decode("ascii", errors="replace")
        offset = end + 1
    return names_by_offset


def _read_part4(br: BinaryReader, header_base: int, start: int, size: int) -> List[BlockRecord]:
    """Block table (part 4). Each entry is uint32 + ushort + ushort = 8 bytes."""
    br.seek(header_base + start)
    n = size // 8
    out: List[BlockRecord] = []
    for _ in range(n):
        end = br.read_u32()
        transformation = br.read_u16()
        checksum = br.read_u16()
        out.append(BlockRecord(end, transformation, checksum))
    return out


def _read_part4_v200(br: BinaryReader, header_base: int, start: int, size: int) -> List[BlockRecord]:
    """Version 2.0.0 block table (part 4).  Each entry is a single uint32 `End`
    (cumulative transformed size).  There is no per-block transformation or
    checksum in v2.0.0; transformation is item-level (writable-entry flags)."""
    br.seek(header_base + start)
    n = size // 4
    out: List[BlockRecord] = []
    for _ in range(n):
        end = br.read_u32()
        out.append(BlockRecord(end, 0xFFFFFFFF, 0))
    return out


def _read_part5(br: BinaryReader, header_base: int, start: int, size: int) -> List[VolumeInfo]:
    """Volume info table (part 5). Each entry is uint64 + uint32 + uint32 = 16 bytes."""
    br.seek(header_base + start)
    n = size // 16
    out: List[VolumeInfo] = []
    for _ in range(n):
        vol_size = br.read_u64()
        name_offset = br.read_u32()
        data_offset = br.read_u32()
        out.append(VolumeInfo(vol_size, name_offset, data_offset))
    return out


def _read_part6(br: BinaryReader, header_base: int, start: int, count: int) -> List[WritableEntry]:
    """Writable entry table (part 6). Each entry is ushort + ushort = 4 bytes."""
    br.seek(header_base + start)
    out: List[WritableEntry] = []
    for _ in range(count):
        volume = br.read_u16()
        flags = br.read_u16()
        out.append(WritableEntry(volume, flags))
    return out


def _read_part7(br: BinaryReader, header_base: int, start: int, count: int) -> List[WritableSharedEntryInfo]:
    """Writable shared entry info table (part 7). Each entry is uint32 + uint32 = 8 bytes."""
    br.seek(header_base + start)
    out: List[WritableSharedEntryInfo] = []
    for _ in range(count):
        next_sibling = br.read_u32()
        patched_entry = br.read_u32()
        out.append(WritableSharedEntryInfo(next_sibling, patched_entry))
    return out


def parse_header(
    br: BinaryReader,
    primary_offset: int,
    secondary_offset: int,
    primary_size: Optional[int] = None,
    num_volumes_hint: Optional[int] = None,
) -> NeFSHeader:
    """Parse a full NeFS header.

    Args:
        br: Reader positioned over the bytes containing the header (usually
            the whole archive for `.nefs`, or the game executable for split
            `.dat` headers).
        primary_offset: offset to the primary header block (intro).
        secondary_offset: offset to the secondary header block (parts 6-7).
        primary_size: number of header bytes (intro..part8) if known.
        num_volumes_hint: some callers may already know the volume count.
    """
    header = NeFSHeader(
        intro=HeaderIntro.read(br, primary_offset),
        toc=None,
    )
    is_v200 = header.intro.version == NefsVersion.VERSION_200
    if is_v200:
        header.toc = TableOfContents200.read(br, primary_offset + INTRO_SIZE)
    else:
        header.toc = TableOfContents.read(br, primary_offset + INTRO_SIZE)
    toc = header.toc

    # Part 1: entry table
    size1 = toc.shared_entry_info_table_start - toc.entry_table_start
    header.entries = _read_part1(br, primary_offset, toc.entry_table_start, size1)

    # Part 2: shared entry info table
    size2 = toc.name_table_start - toc.shared_entry_info_table_start
    header.shared_entries = _read_part2(br, primary_offset, toc.shared_entry_info_table_start, size2)

    # Part 3: name table
    size3 = toc.block_table_start - toc.name_table_start
    header.names_by_offset = _read_part3(br, primary_offset, toc.name_table_start, size3)

    # Part 4: block table
    size4 = toc.volume_info_table_start - toc.block_table_start
    if is_v200:
        header.blocks = _read_part4_v200(br, primary_offset, toc.block_table_start, size4)
    else:
        header.blocks = _read_part4(br, primary_offset, toc.block_table_start, size4)

    # Part 5: volume info table
    nvol = num_volumes_hint if num_volumes_hint is not None else toc.num_volumes
    size5 = nvol * 16
    header.volumes = _read_part5(br, primary_offset, toc.volume_info_table_start, size5)
    for v in header.volumes:
        v.name = header.names_by_offset.get(v.name_offset, "")

    # Part 6: writable entry table (secondary block)
    if len(header.entries) > 0:
        header.writable_entries = _read_part6(
            br, secondary_offset, toc.writable_entry_table_start, len(header.entries)
        )

    # Part 7: writable shared entry info table (secondary block)
    if len(header.shared_entries) > 0:
        scr = _read_part7(
            br, secondary_offset, toc.writable_shared_entry_info_table_start,
            len(header.shared_entries),
        )
        header.writable_shared_entries = scr

    # Part 8: hash digest table (primary block, after part 5)
    if len(header.volumes) > 0:
        header.hash_digests = _read_part8(
            br, primary_offset, toc.hash_digest_table_start,
            toc.hash_block_size, header.volumes[0],
        )

    return header


def _read_part8(
    br: BinaryReader,
    header_base: int,
    start: int,
    hash_block_size: int,
    volume0: VolumeInfo,
) -> List[HashDigest]:
    total_compressed_size = volume0.size - volume0.data_offset
    if hash_block_size == 0:
        hash_block_size = 0x10000  # NefsWriter default
    num_hashes = (total_compressed_size + hash_block_size - 1) // hash_block_size
    base = header_base + start
    if base < 0 or base >= br.length:
        return []
    # Bound by the bytes actually available so a malformed/odd table cannot
    # raise mid-read.  Hash digests are not required for list/extract.
    available = (br.length - base) // 0x20
    num_hashes = min(num_hashes, available)
    br.seek(base)
    out: List[HashDigest] = []
    for _ in range(num_hashes):
        out.append(HashDigest(br.read(0x20)))
    return out
