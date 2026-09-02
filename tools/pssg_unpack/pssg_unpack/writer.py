"""PSSG binary writer (big-endian).

Faithful port of EgoEngineLibrary's PssgFile.WritePssg / PssgElement.Write /
UpdateSize / PssgSchema.SaveToPssg (MIT).
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
    ENCODING,
    MAGIC,
)
from .model import PssgElement, PssgFile


class _Writer:
    def __init__(self):
        self.buf = bytearray()
        self.element_index: dict[str, int] = {}   # element name -> table index
        self.attribute_index: dict[str, int] = {} # (elem name, attr name) -> index
        self.element_attrs: dict[str, list[tuple[str, int]]] = {}
        # ^ element name -> [(attr name, table index)] in table order

    # ---- primitives ----
    def _u32(self, v: int) -> None:
        self.buf += struct.pack(">I", v & 0xFFFFFFFF)

    def _i32(self, v: int) -> None:
        self.buf += struct.pack(">i", v)

    def _f32(self, v: float) -> None:
        self.buf += struct.pack(">f", v)

    def _pssg_string(self, s: str) -> None:
        b = s.encode(ENCODING)
        self._i32(len(b))
        self.buf += b

    # ---- tables ----
    def _gather_tables(self, root: PssgElement) -> None:
        for element in root.iter_all():
            if element.name not in self.element_index:
                self.element_index[element.name] = len(self.element_index)
            for attr in element.attributes:
                key = (element.name, attr.name)
                if key not in self.attribute_index:
                    self.attribute_index[key] = len(self.attribute_index)
        # attribute names referenced by each element, ordered by table index
        for element in root.iter_all():
            if element.name not in self.element_attrs:
                names = [(e, a) for (e, a) in self.attribute_index if e == element.name]
                names.sort(key=lambda t: self.attribute_index[t])
                self.element_attrs[element.name] = [(a, self.attribute_index[(e, a)])
                                                    for (e, a) in names]

    def _write_schema(self) -> None:
        self._i32(len(self.attribute_index))
        self._i32(len(self.element_index))
        for name, idx in sorted(self.element_index.items(), key=lambda t: t[1]):
            self._i32(idx + 1)
            self._pssg_string(name)
            attrs = self.element_attrs.get(name, [])
            self._i32(len(attrs))
            for attr_name, _table_idx in attrs:
                self._i32(_table_idx + 1)
                self._pssg_string(attr_name)

    # ---- attributes / elements ----
    @staticmethod
    def _attr_size(attr) -> int:
        t = attr.pssg_type
        if t == ATTR_INT:
            return 4
        if t == ATTR_STRING:
            return 4 + len(str(attr.value).encode(ENCODING))
        if t == ATTR_FLOAT:
            return 4
        if t == ATTR_FLOAT2:
            return 8
        if t == ATTR_FLOAT3:
            return 12
        if t == ATTR_FLOAT4:
            return 16
        return len(attr.value)

    def _write_attr_value(self, attr) -> None:
        t = attr.pssg_type
        v = attr.value
        if t == ATTR_INT:
            self._i32(v)
        elif t == ATTR_STRING:
            self._pssg_string(v)
        elif t == ATTR_FLOAT:
            self._f32(v)
        elif t == ATTR_FLOAT2:
            self._f32(v[0]); self._f32(v[1])
        elif t == ATTR_FLOAT3:
            self._f32(v[0]); self._f32(v[1]); self._f32(v[2])
        elif t == ATTR_FLOAT4:
            self._f32(v[0]); self._f32(v[1]); self._f32(v[2]); self._f32(v[3])
        else:
            self.buf += v

    def _emit_element(self, element: PssgElement) -> None:
        self._i32(self.element_index[element.name] + 1)
        self._i32(element.size)
        self._i32(element.attribute_size)
        for attr in element.attributes:
            self._i32(self.attribute_index[(element.name, attr.name)] + 1)
            self._i32(self._attr_size(attr))
            self._write_attr_value(attr)
        if element.is_data:
            self.buf += element.value
        else:
            for child in element.children:
                self._emit_element(child)

    @staticmethod
    def _update_size(element: PssgElement) -> None:
        attr_size = 0
        for attr in element.attributes:
            attr_size += 8 + _Writer._attr_size(attr)
        element.attribute_size = attr_size
        size = 4 + attr_size
        if element.is_data:
            size += len(element.value)
        else:
            for child in element.children:
                _Writer._update_size(child)
                size += 8 + child.size
        element.size = size

    def build(self, root: PssgElement) -> bytes:
        self._gather_tables(root)
        self.buf += MAGIC
        self._i32(0)  # size placeholder
        self._write_schema()
        _Writer._update_size(root)
        self._emit_element(root)
        total_size = len(self.buf) - 8
        self.buf[4:8] = struct.pack(">i", total_size)
        return bytes(self.buf)


def write_pssg(pssg: PssgFile) -> bytes:
    if pssg.root is None:
        raise ValueError("Cannot write a PSSG file without a root element.")
    return _Writer().build(pssg.root)