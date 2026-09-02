"""dic_unpack — EGO Neon Sound Dictionary (.dic) extractor.

Reference: 010 Template dic.bt (Ego-Engine-Modding, MIT).
"""

from __future__ import annotations

from .archive import (
    DicBank,
    DicFile,
    DicFormatError,
    DicSample,
    extract_dic,
    read_dic,
    sample_data,
)

__all__ = [
    "DicBank",
    "DicFile",
    "DicSample",
    "DicFormatError",
    "read_dic",
    "sample_data",
    "extract_dic",
]

__version__ = "0.1.0"