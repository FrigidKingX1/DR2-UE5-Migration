"""Low-level binary reader over a byte slice with configurable endianness.

Ports the role of VictorBush.Ego.NefsLib.IO.EndianBinaryReader for the subset
of operations needed to parse NeFS headers and tables.
"""

from __future__ import annotations

import struct
from typing import Optional


class BinaryReader:
    def __init__(self, data: bytes, little_endian: bool = True, offset: int = 0):
        self._data = data
        self.pos = offset
        self.little_endian = little_endian

    @property
    def length(self) -> int:
        return len(self._data)

    def _fmt(self, code: str) -> str:
        endian = "<" if self.little_endian else ">"
        return endian + code

    def seek(self, offset: int) -> None:
        self.pos = offset

    def read(self, size: int) -> bytes:
        if self.pos + size > self.length:
            raise ValueError(
                f"Attempted to read {size} bytes at offset 0x{self.pos:X} "
                f"but only {self.length} bytes available."
            )
        out = self._data[self.pos:self.pos + size]
        self.pos += size
        return out

    def read_u8(self) -> int:
        return self.read(1)[0]

    def read_u16(self) -> int:
        return struct.unpack(self._fmt("H"), self.read(2))[0]

    def read_u32(self) -> int:
        return struct.unpack(self._fmt("I"), self.read(4))[0]

    def read_u64(self) -> int:
        return struct.unpack(self._fmt("Q"), self.read(8))[0]

    def read_i16(self) -> int:
        return struct.unpack(self._fmt("h"), self.read(2))[0]

    def read_ascii(self, size: int) -> str:
        raw = self.read(size)
        return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    def read_remaining(self) -> bytes:
        return self._data[self.pos:]
