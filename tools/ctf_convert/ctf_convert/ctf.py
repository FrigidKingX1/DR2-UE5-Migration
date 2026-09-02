import struct
from typing import BinaryIO

from .model import FloatList
from .schema import CtfSchema


class CtfFormatError(ValueError):
    pass


LE_I32 = struct.Struct("<i")
LE_F32 = struct.Struct("<f")
LE_F64 = struct.Struct("<d")


class _Reader:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.pos = 0

    def take(self, n):
        if self.pos + n > len(self.raw):
            raise CtfFormatError(f"unexpected end of ctf data at offset {self.pos} (need {n} bytes)")
        out = self.raw[self.pos : self.pos + n]
        self.pos += n
        return out

    def i32(self):
        return LE_I32.unpack(self.take(4))[0]

    def f32(self):
        return LE_F32.unpack(self.take(4))[0]

    def f64(self):
        return LE_F64.unpack(self.take(8))[0]

    def bool(self):
        return bool(self.i32())

    def string(self):
        out = bytearray()
        while True:
            b = self.take(1)[0]
            if b == 0:
                break
            out.append(b)
        return out.decode("utf-8")

    def float_list(self):
        count = self.i32()
        step = self.f32()
        items = [self.f32() for _ in range(count)]
        return FloatList(count, step, items)


class _Writer:
    def __init__(self):
        self.buf = bytearray()

    def raw(self, data):
        self.buf += data

    def i32(self, v):
        self.buf += LE_I32.pack(int(v))

    def f32(self, v):
        self.buf += LE_F32.pack(float(v))

    def f64(self, v):
        self.buf += LE_F64.pack(float(v))

    def bool(self, v):
        self.i32(1 if v else 0)

    def string(self, s):
        self.buf += s.encode("utf-8")
        self.buf += b"\x00"

    def float_list(self, fl):
        self.i32(fl.count)
        self.f32(fl.step)
        if len(fl.items) < fl.count:
            raise CtfFormatError(f"float-list has {len(fl.items)} items but count is {fl.count}")
        for v in fl.items[: fl.count]:
            self.f32(v)


def _bytes(entry, value):
    return (entry.type, value)


def read_ctf(raw: bytes, schema: CtfSchema, *, strict=True):
    """Parse a binary CarTuningFile.

    Returns ``(entries, flag)`` where ``entries`` is an ordered dict
    ``{schema_id: value}`` of the entries that were present in the file.
    Mirrors ``CtfFile``/``CtfBinaryReader`` (little-endian, sequential,
    schema-gated reads).

    With ``strict=False`` the reader tolerates files that carry extra entries
    gated out of the current ``flag`` value (e.g. ctf files rebuilt from an
    EGO CTF csv, which lists every column regardless of gates).  The trailing
    bytes are reconciled against the gate-skipped entries in schema order and
    are only accepted if the walk lands exactly at end-of-file.
    """
    reader = _Reader(raw)
    entries = {}
    flag = -1

    for info in schema.entries:
        if info.name == "magic":
            entries[info.id] = reader.i32()
            continue
        if info.name == "flag":
            flag = reader.i32()
            entries[info.id] = flag
            continue
        if not info.is_used(flag):
            continue
        if info.link_id != -1:
            linked = schema.find_ref(info.link_id)
            if not entries.get(linked.id):
                continue
        entries[info.id] = _read_entry(reader, info.type)

    if not strict and reader.pos < len(raw) - 1:
        candidates = [i for i in schema.entries if not i.is_used(flag)]
        if not _reconcile_trailing(reader, raw, candidates, entries):
            raise CtfFormatError(
                f"reader stopped at {reader.pos} but file is {len(raw)} bytes long"
            )

    last = schema.last_required()
    if last.id not in entries:
        raise CtfFormatError(f"schema-required entry {last.name!r} not present")

    if reader.pos < len(raw) - 1:
        raise CtfFormatError(
            f"reader stopped at {reader.pos} but file is {len(raw)} bytes long"
        )
    return entries, flag


def _reconcile_trailing(reader, raw, candidates, entries):
    """Try to consume the trailing bytes by re-reading gate-skipped entries.

    Reads each non-linked candidate in schema order; accepts the run that
    lands exactly at end-of-file (or within one trailing byte).
    """
    work = {}
    pos = reader.pos
    accepted = None
    try:
        for info in candidates:
            if info.link_id != -1:
                continue
            r = _Reader(raw)
            r.pos = pos
            work[info.id] = _read_entry(r, info.type)
            pos = r.pos
            if pos >= len(raw) - 1:
                accepted = dict(work)
                break
    except CtfFormatError:
        return False
    if accepted is None:
        return False
    entries.update(accepted)
    reader.pos = pos
    return True


def _read_entry(reader, type):
    if type == "int":
        return reader.i32()
    if type == "float":
        return reader.f32()
    if type == "double":
        return reader.f64()
    if type == "bool":
        return reader.bool()
    if type == "string":
        return reader.string()
    if type == "float-list":
        return reader.float_list()
    raise CtfFormatError(f"unsupported ctf entry type {type!r}")


def write_ctf(entries, schema: CtfSchema):
    """Serialize parsed entries back to binary, in schema order.

    ``entries`` must be the mapping returned by :func:`read_ctf` (ids are the
    schema indexes).  Mirrors ``CtfFile.Write``/``CtfBinaryWriter``.
    """
    writer = _Writer()
    for id in sorted(entries):
        info = schema.entries[id]
        value = entries[id]
        if value is None or (isinstance(value, str) and value == ""):
            value = info.default_value()
        _write_entry(writer, info.type, value)
    return bytes(writer.buf)


def _write_entry(writer, type, value):
    if type == "int":
        writer.i32(value)
    elif type == "float":
        writer.f32(value)
    elif type == "double":
        writer.f64(value)
    elif type == "bool":
        writer.bool(value)
    elif type == "string":
        writer.string(value)
    elif type == "float-list":
        writer.float_list(value)
    else:
        raise CtfFormatError(f"unsupported ctf entry type {type!r}")