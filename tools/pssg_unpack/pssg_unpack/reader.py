"""PSSG binary reader (big-endian).

Faithful port of EgoEngineLibrary's PssgFile.ReadPssg / PssgElement.ReadBinary /
PssgSchema.LoadFromPssg (MIT).
"""

from __future__ import annotations

import struct

from .constants import (
    ATTR_FLOAT,
    ATTR_FLOAT2,
    ATTR_FLOAT3,
    ATTR_FLOAT4,
    ATTR_INT,
    ATTR_STRING,
    ATTR_UNKNOWN,
    ATTRIBUTE_TYPE_BY_NAME,
    DATA_ELEMENT_NAME_OVERRIDES,
    ELEMENT_NONE,
    ELEMENT_TYPE_BY_NAME,
    ENCODING,
    MAGIC,
)
from .model import PssgAttribute, PssgElement, PssgFile


class PssgFormatError(Exception):
    pass


class _Reader:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.pos = 0
        self.element_table: list = []          # name by id-1
        self.attribute_table: list = []        # (name, type) by id-1
        self.use_data_element_check = False

    # ---- primitives (big-endian) ----
    def _u32(self) -> int:
        v = struct.unpack_from(">I", self.raw, self.pos)[0]
        self.pos += 4
        return v

    def _i32(self) -> int:
        v = struct.unpack_from(">i", self.raw, self.pos)[0]
        self.pos += 4
        return v

    def _f32(self) -> float:
        v = struct.unpack_from(">f", self.raw, self.pos)[0]
        self.pos += 4
        return v

    def _bytes(self, n: int) -> bytes:
        if self.pos + n > len(self.raw):
            raise PssgFormatError("Unexpected end of PSSG stream.")
        v = self.raw[self.pos:self.pos + n]
        self.pos += n
        return v

    def _pssg_string(self) -> str:
        length = self._i32()
        return self._bytes(length).decode(ENCODING)

    # ---- schema ----
    def load_schema(self) -> int:
        """Read element/attribute tables. Returns the stream position after."""
        attribute_count = self._i32()
        element_count = self._i32()
        element_table: list = [None] * element_count
        attribute_table: list = [None] * attribute_count

        for i in range(element_count):
            n_id = self._i32()
            element_name = self._pssg_string()
            # default type: unknown unless a known schema element is present
            element_table[n_id - 1] = (element_name, ELEMENT_TYPE_BY_NAME.get(element_name, 0))
            sub_attr_count = self._i32()
            for _ in range(sub_attr_count):
                attr_id = self._i32()
                attr_name = self._pssg_string()
                attr_type = ATTRIBUTE_TYPE_BY_NAME.get(attr_name, ATTR_UNKNOWN)
                attribute_table[attr_id - 1] = (attr_name, attr_type)

        for i, name_t in enumerate(element_table):
            if name_t is None:
                raise PssgFormatError(f"Schema element id {i + 1} was not defined.")
            self.element_table.append(name_t)
        for i, name_t in enumerate(attribute_table):
            if name_t is None:
                raise PssgFormatError(f"Schema attribute id {i + 1} was not defined.")
            self.attribute_table.append(name_t)
        return self.pos

    # ---- elements ----
    def _read_attributes(self, attr_end: int, element: PssgElement) -> None:
        while self.pos < attr_end:
            attr_id = self._i32() - 1
            if not (0 <= attr_id < len(self.attribute_table)):
                raise PssgFormatError(f"Attribute id out of range: {attr_id + 1}")
            name, pssg_type = self.attribute_table[attr_id]
            size = self._i32()
            element.attributes.append(PssgAttribute(
                name, pssg_type, size, self._read_attribute_value(pssg_type, size)))

    def _read_attribute_value(self, pssg_type: int, size: int):
        # The declared size is authoritative for stream consumption; typed
        # interpretation applies only when the size matches the encoding.
        # This mirrors EgoEngineLibrary, where binary-schema attributes default
        # to Unknown -> ReadBytes(size), and guards against real DR2 files in
        # which a name-guessed Int attribute actually carries a length-prefixed
        # string (size 11-14), which previously desynced the stream.
        raw = self._bytes(size)
        if pssg_type == ATTR_INT and size == 4:
            return struct.unpack_from(">i", raw)[0]
        if pssg_type == ATTR_FLOAT and size == 4:
            return struct.unpack_from(">f", raw)[0]
        if pssg_type == ATTR_FLOAT2 and size == 8:
            return struct.unpack_from(">2f", raw)
        if pssg_type == ATTR_FLOAT3 and size == 12:
            return struct.unpack_from(">3f", raw)
        if pssg_type == ATTR_FLOAT4 and size == 16:
            return struct.unpack_from(">4f", raw)
        if pssg_type == ATTR_STRING:
            if size >= 4:
                n = struct.unpack_from(">i", raw)[0]
                if 0 <= n and 4 + n == size:
                    return raw[4:].decode(ENCODING, errors="replace")
            if 0 < size < 4:
                return raw.decode(ENCODING, errors="replace")
        # Unknown type, or size/type mismatch: keep the raw bytes.
        return raw

    def _read_element(self, parent: PssgElement | None) -> PssgElement:
        elem_id = self._i32() - 1
        if not (0 <= elem_id < len(self.element_table)):
            raise PssgFormatError(f"Element id out of range: {elem_id + 1}")
        name, data_type = self.element_table[elem_id]
        element = PssgElement(name=name)
        size = self._i32()
        element.size = size
        end = self.pos + size

        attr_size = self._i32()
        element.attribute_size = attr_size
        attr_end = self.pos + attr_size
        if attr_end > len(self.raw) or end > len(self.raw):
            raise PssgFormatError("Improperly saved PSSG (block runs past end of file).")
        self._read_attributes(attr_end, element)

        is_data = data_type not in (ELEMENT_NONE, 0)  # 0 == Unknown
        if not is_data and name in DATA_ELEMENT_NAME_OVERRIDES:
            is_data = True

        if not is_data and self.use_data_element_check and self.pos < end:
            save = self.pos
            while self.pos < end:
                temp_id = struct.unpack_from(">i", self.raw, self.pos)[0]
                if temp_id < 0 or temp_id > len(self.element_table):
                    is_data = True
                    break
                temp_size = struct.unpack_from(">i", self.raw, self.pos + 4)[0]
                new_pos = self.pos + 8 + temp_size
                if new_pos > end or (temp_size == 0 and temp_id == 0) or temp_size < 0:
                    is_data = True
                    break
                if new_pos == end:
                    break
                self.pos = new_pos
            self.pos = save

        if is_data:
            element.is_data = True
            element.value = self._bytes(end - self.pos)
        else:
            while self.pos < end:
                element.children.append(self._read_element(element))
        return element


def read_pssg(raw: bytes | bytearray | memoryview) -> PssgFile:
    raw = bytes(raw)
    if len(raw) < 8:
        raise PssgFormatError("File too small to be a PSSG file.")
    if not raw.startswith(MAGIC):
        raise PssgFormatError("Not a PSSG file (bad magic).")

    file_size = struct.unpack_from(">i", raw, 4)[0]

    reader = _Reader(raw)
    reader.pos = 8
    reader.load_schema()
    position_after_info = reader.pos

    reader.use_data_element_check = True
    reader.pos = position_after_info
    root = reader._read_element(None)
    if reader.pos < len(raw):
        reader.pos = position_after_info
        reader.use_data_element_check = False
        root = reader._read_element(None, )
        if reader.pos < len(raw):
            raise PssgFormatError(
                "This file is improperly saved; trailing bytes could not be parsed.")

    return PssgFile(
        file_size=file_size,
        element_table=[name for name, _ in reader.element_table],
        attribute_table=list(reader.attribute_table),
        root=root,
    )