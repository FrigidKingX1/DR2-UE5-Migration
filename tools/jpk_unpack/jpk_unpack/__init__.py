"""jpk_unpack — EGO JPK (JPAK) archive extractor.

Reference port of EgoEngineLibrary/Archive/Jpk/ (MIT).
"""

from __future__ import annotations

from .archive import (
    JpkEntry,
    JpkFile,
    JpkFormatError,
    extract_entry,
    extract_jpk,
    read_jpk,
)

__all__ = [
    "JpkEntry",
    "JpkFile",
    "JpkFormatError",
    "read_jpk",
    "extract_entry",
    "extract_jpk",
]

__version__ = "0.1.0"