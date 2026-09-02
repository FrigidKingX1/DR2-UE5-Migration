"""EGO ``.database`` binary DataSet codec (port of Data/DatabaseFile.cs).

The database is a little-endian binary holding named tables of typed rows
(float / int / string / bool).

Modern (string-table) layout::

    [u32 schemaVersion][u32 0]            # 8-byte header
    per table:   [u16 index][u16 0x2A2B][i32 rowCount]
    per row:     [u16 0x2A2D][u16 index][ fields... ]
    trailer:     "PRTS"[u32 count][ string bytes... ]

String fields are stored as a 4-byte index into the ``PRTS`` string pool.
Legacy layout uses ``LBT``/``ITM`` markers and fixed-width padded strings.
Decoding requires the describing EGO schema XML.
"""

from __future__ import annotations

from .binio import EndianBinaryReader, EndianBinaryWriter

DB_JBT = 0x2A2B    # table marker
DB_ITM = 0x2A2D    # row marker

_NO_STR_TABLE = {1313096275, 3934935529}


class DatabaseError(Exception):
    pass


class Field:
    __slots__ = ("name", "type", "size", "key")

    def __init__(self, name, type_, size=None, key=None):
        self.name = name
        self.type = type_            # "float"/"int"/"string"/"bool"
        self.size = size
        self.key = key


class Table:
    __slots__ = ("name", "fields", "rows")

    def __init__(self, fields, name=""):
        self.name = name
        self.fields = list(fields)
        self.rows = []

    def add_row(self, values):
        self.rows.append(list(values))


class Database:
    __slots__ = ("schema_version", "tables")

    def __init__(self, schema_version=0):
        self.schema_version = schema_version
        self.tables = []

    @property
    def has_string_table(self):
        return self.schema_version not in _NO_STR_TABLE


def _str_total(max_length):
    num = max_length % 4
    return (max_length + 5) if num == 3 else (max_length + (4 - num))


def _write_database_string(w, s, max_length):
    b = s.encode("utf-8")
    w.write_bytes(b)
    total = max(_str_total(max_length), len(b))
    w.write_bytes(b"\x00" * (total - len(b)))


def _read_database_string(r, max_length):
    raw = r.read_bytes(_str_total(max_length))
    return raw.split(b"\x00")[0].decode("utf-8").rstrip()


def write_database(db: Database) -> bytes:
    w = EndianBinaryWriter(big_endian=False)
    has_st = db.has_string_table
    pool = bytearray()
    pool_count = 0
    dictionary = {}

    w.write_u32(db.schema_version & 0xFFFFFFFF)
    w.write_u32(0)  # second DataSetName part

    for i, table in enumerate(db.tables):
        if has_st:
            w.write_u16(i & 0xFFFF)
            w.write_u16(DB_JBT)
        else:
            w.write_u8(i & 0xFF)
            w.write_bytes(b"LBT")
        w.write_i32(len(table.rows))

        for row in table.rows:
            if has_st:
                w.write_u16(DB_ITM)
                w.write_u16(i & 0xFFFF)
            else:
                w.write_bytes(b"ITM")
                w.write_u8(i & 0xFF)

            for j, field in enumerate(table.fields):
                val = row[j]
                if field.type == "float":
                    w.write_f32(float(val))
                elif field.type == "int":
                    w.write_i32(int(val))
                elif field.type == "string":
                    val = "" if val is None else str(val)
                    if has_st:
                        if val in dictionary:
                            w.write_i32(dictionary[val])
                        else:
                            w.write_i32(pool_count)
                            dictionary[val] = pool_count
                            pool += val.encode("utf-8")
                            pool.append(0)
                            pool_count += len(val.encode("utf-8")) + 1
                    else:
                        _write_database_string(w, val, field.size or 0)
                elif field.type == "bool":
                    w.write_u8(1 if val else 0)
                    w.write_bytes(b"\x00\x00\x00")

    if has_st:
        w.write_bytes(b"PRTS")
        w.write_i32(pool_count)
        w.write_bytes(bytes(pool))
    return w.getvalue()


def _find_prts(data: bytes):
    """Return the string-pool content offset, or None if absent."""
    idx = data.find(b"PRTS")
    if idx < 0:
        return None
    return idx + 8


def read_database(data: bytes, schema: "Database") -> Database:
    r = EndianBinaryReader(data, big_endian=False)
    db = Database()
    db.schema_version = r.read_u32()
    has_st = db.has_string_table

    pool_offset = _find_prts(data) if has_st else None
    r.seek(8)
    table_index = 0
    while r.pos < len(data):
        if has_st and len(data) - r.pos >= 4 and data[r.pos:r.pos + 4] == b"PRTS":
            break
        r.seek(2, 1)
        table_id = r.read_u16()
        if has_st and table_id != DB_JBT:
            raise DatabaseError(f"bad table marker 0x{table_id:04X}")
        item_num = r.read_i32()
        if table_index >= len(schema.tables):
            break
        fields = schema.tables[table_index].fields
        table = Table(fields, name=schema.tables[table_index].name)
        for _ in range(item_num):
            itm_id = r.read_u16()
            r.seek(2, 1)
            values = []
            for field in fields:
                if field.type == "float":
                    values.append(r.read_f32())
                elif field.type == "int":
                    values.append(r.read_i32())
                elif field.type == "string":
                    if has_st:
                        ret = r.pos + 4
                        idx = r.read_i32()
                        r.seek(pool_offset + idx)
                        values.append(r.read_terminated_string(0))
                        r.seek(ret)
                    else:
                        values.append(_read_database_string(r, field.size or 0))
                elif field.type == "bool":
                    values.append(bool(r.read_u8()))
                    r.read_bytes(3)
            table.add_row(values)
        db.tables.append(table)
        table_index += 1
    return db


def xml_to_schema(schema_xml) -> Database:
    """Build a Database (tables/fields) from an EGO schema XmlDoc."""
    db = Database()
    for child in schema_xml.children:
        if child.name == "schemaVersion":
            db.schema_version = int(dict(child.attrs).get("version", "0"))
            continue
        fa = dict(child.attrs)
        table_name = fa.get("name", child.name)
        fields = []
        for field in child.children:
            fa2 = dict(field.attrs)
            fields.append(Field(fa2.get("name", ""), fa2.get("type", "int"),
                                int(fa2["size"]) if fa2.get("size") else None,
                                fa2.get("key")))
        db.tables.append(Table(fields, name=table_name))
    return db
