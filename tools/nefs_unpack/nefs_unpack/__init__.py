"""nefs_unpack — Python port of the EGO NeFS archive unpacker.

Reads DiRT Rally 2.0 (and other EGO) `.nefs`/`.nfs` and split-header `.dat`
archives, reconstructs the directory tree, and extracts item data (decrypting
AES-256-ECB and inflating zlib where required).
"""

from __future__ import annotations

from .archive import (
    NefsArchive,
    read_split_archive,
    read_split_archive_from_exe,
    read_standard_archive,
)
from .exe_finder import HeadlessSource, find_headers
from .header import NeFSHeader
from .items import NefsItem, NeFSItemList, build_item_list

__all__ = [
    "NefsArchive",
    "NeFSHeader",
    "NefsItem",
    "NeFSItemList",
    "HeadlessSource",
    "read_standard_archive",
    "read_split_archive",
    "read_split_archive_from_exe",
    "find_headers",
    "build_item_list",
]

__version__ = "0.1.0"
