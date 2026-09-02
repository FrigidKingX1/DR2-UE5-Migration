"""Little/big-endian binary reader/writer primitives (port of EndianBinaryReader/Writer)."""

from __future__ import annotations

import struct


class EndianBinaryReader:
    def __init__(self, data: bytes | bytearray | memoryview, big_endian: bool = False,
                 encoding: str = "utf-8"):
        self.data = bytes(data)
        self.pos = 0
        self.big_endian = big_endian
        self.encoding = encoding

    def _u(self, fmt):
        self._need(struct.calcsize(fmt))
        v = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += struct.calcsize(fmt)
        return v

    def _need(self, n):
        if self.pos + n > len(self.data):
            raise EOFError("unexpected end of stream")

    def read_u8(self):
        return self._u(">B" if self.big_endian else "<B")

    def read_i8(self):
        return self._u(">b" if self.big_endian else "<b")

    def read_u16(self):
        return self._u(">H" if self.big_endian else "<H")

    def read_i16(self):
        return self._u(">h" if self.big_endian else "<h")

    def read_u32(self):
        return self._u(">I" if self.big_endian else "<I")

    def read_i32(self):
        return self._u(">i" if self.big_endian else "<i")

    def read_f32(self):
        return self._u(">f" if self.big_endian else "<f")

    def read_u64(self):
        return self._u(">Q" if self.big_endian else "<Q")

    def read_bytes(self, n):
        self._need(n)
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def read_byte(self):
        return self.read_u8()

    def read_terminated_string(self, terminator=0):
        out = bytearray()
        while True:
            b = self.data[self.pos]
            self.pos += 1
            if b == terminator:
                break
            out.append(b)
        return out.decode(self.encoding)

    def seek(self, offset, whence=0):
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        elif whence == 2:
            self.pos = len(self.data) + offset
        else:
            raise ValueError(f"unknown whence {whence}")

    @property
    def stream_position(self):
        return self.pos

    @property
    def stream_length(self):
        return len(self.data)


class EndianBinaryWriter:
    def __init__(self, big_endian: bool = False, encoding: str = "utf-8"):
        self.buf = bytearray()
        self.big_endian = big_endian
        self.encoding = encoding
        self.pos = 0

    def _w(self, fmt, value):
        self.buf += struct.pack(fmt, value)
        self.pos += struct.calcsize(fmt)

    def write_u8(self, v):
        self._w(">B" if self.big_endian else "<B", v)

    def write_i8(self, v):
        self._w(">b" if self.big_endian else "<b", v)

    def write_u16(self, v):
        self._w(">H" if self.big_endian else "<H", v)

    def write_i16(self, v):
        self._w(">h" if self.big_endian else "<h", v)

    def write_u32(self, v):
        self._w(">I" if self.big_endian else "<I", v)

    def write_i32(self, v):
        self._w(">i" if self.big_endian else "<i", v)

    def write_f32(self, v):
        self._w(">f" if self.big_endian else "<f", v)

    def write_u64(self, v):
        self._w(">Q" if self.big_endian else "<Q", v)

    def write_bytes(self, b):
        self.buf += b
        self.pos += len(b)

    def write_terminated_string(self, s, terminator=0):
        self.buf += s.encode(self.encoding)
        self.buf.append(terminator)
        self.pos += len(s.encode(self.encoding)) + 1

    def fill_at(self, offset):
        """Return a placeholder offset that can be backpatched via write_at.""" 
        return offset

    def write_at(self, offset, fmt, value):
        packed = struct.pack(fmt, value)
        self.buf[offset:offset + len(packed)] = packed

    def getvalue(self):
        return bytes(self.buf)