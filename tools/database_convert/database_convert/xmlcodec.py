"""EGO binary XML codec (port of EgoEngineLibrary/Xml/XmlFile.cs).

Two binary XML formats are supported alongside plain text XML:

* ``BinXml`` — magic ``1A 22 52 72`` (``'."Rr'``), little-endian string-table
  format used for ``.xml`` assets.  Sections:
    1. magic + total file size
    2. section-2 magic + size of sections 3+4 (+16)
    3. NUL-terminated UTF-8 string data
    4. string-location table (i32 offsets)
    5. element definitions (6 x i32 = 24 bytes each)
    6. attribute definitions (2 x i32 = 8 bytes each)
* ``BXML`` (``'BXML'``, big/little) — node-length-prefixed tree.

Text XML round-trips through a small dependency-free DOM, with a leading
comment recording the source/target flavour.
"""

from __future__ import annotations

import io
import struct

from .binio import EndianBinaryReader, EndianBinaryWriter

BINXML_MAGIC = b"\x1A\x22\x52\x72"     # '."Rr'
BXML_MAGIC = b"BXML"

S3 = 0x7252221D                        # section 3 magic
S4 = 0x7252221E                        # section 4 magic
S5 = 0x7252221B                        # section 5 magic
S6 = 0x7252221C                        # section 6 magic

TEXT = "Text"
BINXML = "BinXml"
BXML_BIG = "BxmlBig"
BXML_LITTLE = "BxmlLittle"


class XmlError(Exception):
    pass


class XmlDoc:
    """Minimal DOM: name, attrs [(k,v)], text (str|None), children [XmlDoc]."""

    __slots__ = ("name", "attrs", "text", "children", "source_type")

    def __init__(self, name, attrs=None, text=None, children=None,
                 source_type=TEXT):
        self.name = name
        self.attrs = list(attrs or [])
        self.text = text
        self.children = list(children or [])
        self.source_type = source_type

    def has_children(self):
        return bool(self.children)


# ---------------------------------------------------------------------------
# detection


def get_xml_type(data: bytes) -> str:
    if len(data) < 5:
        return TEXT
    if data[:4] == BINXML_MAGIC:
        return BINXML
    if data[1:5] == BXML_MAGIC:
        return BXML_BIG if data[0] == 0 else BXML_LITTLE
    return TEXT


# ---------------------------------------------------------------------------
# text XML


def _escape_attr(v):
    return (v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _escape_text(v):
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def _unescape(v):
    return (v.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&apos;", "'").replace("&amp;", "&"))


class _TextParser:
    def __init__(self, text):
        self.t = text
        self.pos = 0

    def parse(self):
        self._skip_ws()
        self._skip_prolog()
        return self._element()

    def _skip_ws(self):
        while self.pos < len(self.t) and self.t[self.pos] in " \t\r\n":
            self.pos += 1

    def _skip_prolog(self):
        while True:
            self._skip_ws()
            if self.t.startswith("<?", self.pos):
                end = self.t.find("?>", self.pos)
                if end < 0:
                    raise XmlError("unterminated processing instruction")
                self.pos = end + 2
            elif self.t.startswith("<!--", self.pos):
                end = self.t.find("-->", self.pos)
                if end < 0:
                    raise XmlError("unterminated comment")
                self.pos = end + 3
            elif self.t.startswith("<!DOCTYPE", self.pos) or self.t.startswith("<!", self.pos):
                end = self.t.find(">", self.pos)
                self.pos = end + 1 if end > 0 else len(self.t)
            else:
                break

    def _name(self):
        start = self.pos
        while self.pos < len(self.t) and (self.t[self.pos].isalnum()
                                          or self.t[self.pos] in "._-:"):
            self.pos += 1
        if start == self.pos:
            raise XmlError(f"expected a name at offset {self.pos}")
        return self.t[start:self.pos]

    def _attr_value(self):
        self._skip_in_ws()
        if self.t[self.pos] == "=":
            self.pos += 1
        else:
            raise XmlError("expected '=' in attribute")
        self._skip_in_ws()
        q = self.t[self.pos]
        if q not in "\"'":
            raise XmlError("expected a quoted attribute value")
        self.pos += 1
        end = self.t.find(q, self.pos)
        if end < 0:
            raise XmlError("unterminated attribute value")
        value = _unescape(self.t[self.pos:end])
        self.pos = end + 1
        return value

    def _skip_in_ws(self):
        while self.pos < len(self.t) and self.t[self.pos] in " \t\r\n":
            self.pos += 1

    def _element(self):
        if self.t[self.pos] != "<":
            raise XmlError("expected '<'")
        self.pos += 1
        name = self._name()
        attrs = []
        while True:
            self._skip_in_ws()
            if self.t.startswith("/>", self.pos):
                self.pos += 2
                return XmlDoc(name, attrs)
            if self.t[self.pos] == ">":
                self.pos += 1
                break
            key = self._name()
            value = self._attr_value()
            attrs.append((key, value))
        # body
        children = []
        buf = []
        text_mode = True
        while True:
            if self.pos >= len(self.t):
                raise XmlError(f"unterminated element <{name}>")
            if self.t.startswith("</", self.pos):
                self.pos += 2
                close = self._name()
                self._skip_in_ws()
                if self.t[self.pos] == ">":
                    self.pos += 1
                if close != name:
                    raise XmlError(f"mismatched tag </{close}> for <{name}>")
                break
            if self.t.startswith("<!--", self.pos):
                end = self.t.find("-->", self.pos)
                self.pos = end + 3 if end > 0 else len(self.t)
                continue
            if self.t.startswith("<", self.pos):
                if buf:
                    buf = []
                children.append(self._element())
                text_mode = False
                continue
            c = self.t[self.pos]
            if c == "&":
                semi = self.t.find(";", self.pos)
                ent = self.t[self.pos + 1:semi]
                buf.append(_ENTITIES.get(ent, c))
                self.pos = semi + 1
            else:
                buf.append(c)
                self.pos += 1
        raw_text = "".join(buf).strip()
        if children:
            return XmlDoc(name, attrs, children=children)
        if raw_text:
            return XmlDoc(name, attrs, text=raw_text)
        return XmlDoc(name, attrs)


def from_text(data: bytes) -> XmlDoc:
    text = data.decode("utf-8-sig")
    return _TextParser(text).parse()


def to_text(doc: XmlDoc) -> bytes:
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    out.write(f"<!--{doc.source_type}-->\n")
    _emit(doc, out, 0)
    return out.getvalue().encode("utf-8")


def _emit(node, out, indent):
    pad = "  " * indent
    attr = "".join(f' {k}="{_escape_attr(v)}"' for k, v in node.attrs)
    if node.children:
        out.write(f"{pad}<{node.name}{attr}>\n")
        for ch in node.children:
            _emit(ch, out, indent + 1)
        out.write(f"{pad}</{node.name}>\n")
    elif node.text is not None:
        out.write(f"{pad}<{node.name}{attr}>{_escape_text(node.text)}</{node.name}>\n")
    else:
        out.write(f"{pad}<{node.name}{attr}/>\n")


# ---------------------------------------------------------------------------
# BinXml


def _collect_strings(doc):
    order = [""]
    seen = {""}
    def add(s):
        if s not in seen:
            seen.add(s)
            order.append(s)
    def walk(n):
        add(n.name)
        if n.text is not None:
            add(n.text)
        for k, v in n.attrs:
            add(k)
            add(v)
        for ch in n.children:
            walk(ch)
    walk(doc)
    return order


def _serialize_binxml(doc: XmlDoc) -> bytearray:
    """Write the full BinXml file, returning the final bytes (port of BuildBinXml)."""
    strings = _collect_strings(doc)
    index = {s: i for i, s in enumerate(strings)}

    elems: list = []
    attrs: list = []

    # reserve root placeholder (mirrors C# BuildBinXml childElemIndex==0 path)
    elems.append(None)

    def build(node, elem_idx: int):
        e = {
            "elementNameId": index[node.name],
            "elementValueId": index[node.text] if node.text is not None else 0,
            "attributeCount": len(node.attrs),
            "attributeStartId": len(attrs) if node.attrs else 0,
            "childElementCount": 0,
            "childElementStartId": len(elems),
        }
        for k, v in node.attrs:
            attrs.append((index[k], index[v]))
        if node.children:
            # element has child elements — reserve contiguous block
            e["childElementStartId"] = len(elems)
            e["childElementCount"] = len(node.children)
            # keep value id 0 for branch nodes (already 0)
            elems.extend([None] * len(node.children))
            start = e["childElementStartId"]
            for i, ch in enumerate(node.children):
                build(ch, start + i)
        elif node.text is not None:
            # leaf with text keeps elementValueId already set
            e["childElementCount"] = 0
            e["childElementStartId"] = len(elems)
        else:
            e["childElementStartId"] = len(elems)
        elems[elem_idx] = e

    build(doc, 0)

    value_locations = [0]
    string_bytes = 0
    for i, s in enumerate(strings):
        b = len(s.encode("utf-8")) + 1
        string_bytes += b
        value_locations.append(value_locations[-1] + b)

    pad_len = 0
    rem = string_bytes % 16
    if rem:
        pad_len = 24 - rem if rem > 8 else 8 - rem

    buf = bytearray()
    buf += BINXML_MAGIC
    buf += struct.pack("<i", 0)                 # sec1 total (backpatch)
    buf += b"\x17\x22\x52\x72"
    buf += struct.pack("<i", 0)                 # sec2 size (backpatch)

    # section 3
    len3_pos = len(buf) + 4
    buf += struct.pack("<I", S3)
    buf += struct.pack("<i", 0)                 # len3 (backpatch)
    for s in strings:
        buf += s.encode("utf-8")
        buf.append(0)
    buf += b"\x00" * pad_len
    len3 = string_bytes + pad_len
    struct.pack_into("<i", buf, len3_pos, len3)

    # section 4
    buf += struct.pack("<I", S4)
    buf += struct.pack("<i", 4 * len(strings))
    for i in range(len(strings)):
        buf += struct.pack("<i", value_locations[i])

    # section 5
    buf += struct.pack("<I", S5)
    buf += struct.pack("<i", 24 * len(elems))
    for e in elems:
        buf += struct.pack("<6i", e["elementNameId"], e["elementValueId"],
                           e["attributeCount"], e["attributeStartId"],
                           e["childElementCount"], e["childElementStartId"])

    # section 6
    buf += struct.pack("<I", S6)
    buf += struct.pack("<i", 8 * len(attrs))
    for a in attrs:
        buf += struct.pack("<2i", a[0], a[1])

    # backpatch
    total = len(buf) - 8
    struct.pack_into("<i", buf, 4, total)
    sec2 = value_locations[-1] + 4 * len(strings) + 16 + pad_len
    struct.pack_into("<i", buf, 12, sec2)
    struct.pack_into("<i", buf, 20, len3)
    return buf


def _deserialize_binxml(data: bytes) -> XmlDoc:
    r = EndianBinaryReader(data, big_endian=False)
    if r.read_bytes(4) != BINXML_MAGIC:
        raise XmlError("not a BinXml file")
    r.read_i32()                     # sec1
    r.read_bytes(4)                  # sec2 magic
    r.read_i32()                     # sec2 size
    if r.read_i32() != S3:
        raise XmlError("missing section 3")
    len3 = r.read_i32()
    end3 = r.pos + len3
    strings = []
    while r.pos < end3:
        strings.append(r.read_terminated_string(0))
    if r.read_i32() != S4:
        raise XmlError("missing section 4")
    len4 = r.read_i32()
    r.read_bytes(len4)
    if r.read_i32() != S5:
        raise XmlError("missing section 5")
    len5 = r.read_i32()
    elems = []
    for _ in range(len5 // 24):
        elems.append(tuple(r.read_i32() for _ in range(6)))
    if r.read_i32() != S6:
        raise XmlError("missing section 6")
    len6 = r.read_i32()
    attrs = [tuple(r.read_i32() for _ in range(2)) for _ in range(len6 // 8)]

    def build(idx):
        (name_id, value_id, acount, astart, ccount, cstart) = elems[idx]
        node = XmlDoc(strings[name_id])
        for i in range(astart, astart + acount):
            node.attrs.append((strings[attrs[i][0]], strings[attrs[i][1]]))
        for i in range(cstart, cstart + ccount):
            node.children.append(build(i))
        if value_id > 0 and ccount == 0:
            node.text = strings[value_id]
        return node

    return build(0)


# ---------------------------------------------------------------------------
# BXML


def _read_bxml_element(r):
    r.read_i16()                     # node length (unused)
    node_type = r.read_u8()
    r.read_u8()                      # pad
    attr_count = r.read_i16()
    if node_type == 0:
        name = r.read_terminated_string(0)
        node = XmlDoc(name)
        for _ in range(attr_count):
            k = r.read_terminated_string(0)
            v = r.read_terminated_string(0)
            node.attrs.append((k, v))
        while True:
            child = _read_bxml_element(r)
            if child is None:
                break
            node.children.append(child)
        return node
    if node_type == 1:
        return XmlDoc(None, text=r.read_terminated_string(0))
    if node_type == 5:
        return None
    raise XmlError(f"unsupported bxml node type {node_type}")


def _write_bxml_element(w, node, big_endian):
    # element
    attr_count = len(node.attrs)
    elem_length = 4
    # length placeholder (patched after)
    w.write_i16(0)
    w.write_u8(0)                    # node type 0 (element)
    w.write_u8(0)                    # pad
    w.write_i16(attr_count)
    w.write_terminated_string(node.name, 0)

    if big_endian:
        raise XmlError("BXML_BIG element write not implemented")
    # attributes
    for k, v in node.attrs:
        w.write_terminated_string(k, 0)
        w.write_terminated_string(v, 0)
    # children
    for ch in node.children:
        _write_bxml_element(w, ch, big_endian)
    # closing tag "0004 05000000"
    w.write_i16(4)
    w.write_i16(5)
    w.write_i16(0)


def _to_bxml(doc: XmlDoc, big_endian: bool) -> bytes:
    if big_endian:
        raise XmlError("BXML_BIG write not implemented")
    w = EndianBinaryWriter(big_endian=False)
    w.write_u8(1)
    w.write_bytes(BXML_MAGIC)
    _write_bxml_element(w, doc, big_endian)
    w.write_i16(4)
    w.write_i16(6)
    w.write_i16(0)
    w.write_i16(4)
    w.write_i16(6)
    w.write_i16(0)
    return w.getvalue()


# ---------------------------------------------------------------------------
# public API


def load(data: bytes) -> XmlDoc:
    kind = get_xml_type(data)
    if kind == TEXT:
        return from_text(data)
    if kind == BINXML:
        doc = _deserialize_binxml(data)
    elif kind == BXML_LITTLE:
        r = EndianBinaryReader(data, big_endian=False)
        r.read_bytes(5)
        doc = _read_bxml_element(r)
    elif kind == BXML_BIG:
        r = EndianBinaryReader(data, big_endian=True)
        r.read_bytes(5)
        doc = _read_bxml_element(r)
    else:
        raise XmlError(f"unsupported xml type {kind}")
    doc.source_type = kind
    return doc


def dump(doc: XmlDoc, kind: str = TEXT) -> bytes:
    doc.source_type = kind
    if kind == TEXT:
        return to_text(doc)
    if kind == BINXML:
        return bytes(_serialize_binxml(doc))
    if kind == BXML_LITTLE:
        return _to_bxml(doc, big_endian=False)
    if kind == BXML_BIG:
        return _to_bxml(doc, big_endian=True)
    raise XmlError(f"unsupported xml type {kind}")
