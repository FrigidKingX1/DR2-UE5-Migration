"""EGO Resource Package (.erp) format constants.

DiRT Rally 2.0 uses ERP version 4.
Reference: EgoEngineLibrary/Archive/Erp (Ego-Engine-Modding, MIT).
"""

from __future__ import annotations

ERP_MAGIC = 1263555141  # 0x4B504152 -> ASCII "KPAR"
SUPPORTED_VERSION = 4

HEADER_SIZE = 48


class Compression:
    NONE = 0x00
    ZLIB = 0x01
    ZSTD2 = 0x03
    ZSTD = 0x10
    ZSTD3 = 0x11
    NONE2 = 0x81
    NONE3 = 0x90
    NONE4 = 0x91

    # Compression byte values that mean "not compressed"
    NONE_VALUES = {NONE, NONE2, NONE3, NONE4}
    ZLIB_VALUES = {ZLIB}
    ZSTD_VALUES = {ZSTD, ZSTD2, ZSTD3}

    @staticmethod
    def is_compressed(value: int) -> bool:
        return value not in Compression.NONE_VALUES
