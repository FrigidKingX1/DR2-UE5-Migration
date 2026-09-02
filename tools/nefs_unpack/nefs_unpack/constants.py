"""NeFS format constants, ported from VictorBush.Ego.NefsLib."""

from __future__ import annotations

FOUR_CC = 0x5346654E  # "NeFS"

INTRO_SIZE = 128
AES_BLOCK_SIZE = 16  # bytes (128 bits)

# Block-table index used to denote that an entry has no blocks.
NO_BLOCKS_INDEX = 0xFFFFFFFF

# Default AES/RSA keysize-related constants.
DEFAULT_RSA_EXPONENT = 0x10001

# Version 2.0.0 fixed sizes (NefsHeader200 / NefsWriter).
DEFAULT_BLOCK_SIZE_200 = 0x10000       # NefsHeader200.DefaultBlockSize
DEFAULT_HASH_BLOCK_SIZE = 0x800000     # NefsWriter.DefaultHashBlockSize


class NefsVersion:
    VERSION_010 = 0x00100
    VERSION_020 = 0x00200
    VERSION_130 = 0x10300
    VERSION_140 = 0x10400
    VERSION_150 = 0x10500
    VERSION_151 = 0x10501
    VERSION_160 = 0x10600
    VERSION_200 = 0x20000

    _NAMES = {
        VERSION_010: "0.1.0",
        VERSION_020: "0.2.0",
        VERSION_130: "1.3.0",
        VERSION_140: "1.4.0",
        VERSION_150: "1.5.0",
        VERSION_151: "1.5.1",
        VERSION_160: "1.6.0",
        VERSION_200: "2.0.0",
    }

    @staticmethod
    def pretty(version: int) -> str:
        return NefsVersion._NAMES.get(version, f"0x{version:X}")


# Per-archive data chunk transformation codes used in the block table.
class DataTransformType:
    NONE = 0
    LZSS = 1
    AES = 4
    ZLIB = 7


# Flags for v1.5.0+ entry (writable) records.
class EntryFlags:
    NONE = 0
    TRANSFORMED = 1 << 0
    DIRECTORY = 1 << 1
    DUPLICATED = 1 << 2
    CACHEABLE = 1 << 3
    LAST_SIBLING = 1 << 4
    PATCHED = 1 << 5

    ALL = (TRANSFORMED | DIRECTORY | DUPLICATED | CACHEABLE |
           LAST_SIBLING | PATCHED)


# Flags for v2.0.0 writable-entry records (NefsTocEntryFlags200).  Note these
# differ from the 1.5/1.6 layout: transform kind is encoded directly.
class EntryFlags200:
    NONE = 0
    IS_ZLIB = 1 << 0
    IS_AES = 1 << 1
    IS_DIRECTORY = 1 << 2
    IS_DUPLICATED = 1 << 3
    LAST_SIBLING = 1 << 4

    ALL = IS_ZLIB | IS_AES | IS_DIRECTORY | IS_DUPLICATED | LAST_SIBLING
