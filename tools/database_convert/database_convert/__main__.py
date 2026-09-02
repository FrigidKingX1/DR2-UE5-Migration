import argparse
import json
import os
import sys

from . import database as _db
from . import xmlcodec as _x


def _load_xml(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        sys.exit(f"error reading {path}: {exc}")
    try:
        return _x.load(data), _x.get_xml_type(data)
    except _x.XmlError as exc:
        sys.exit(f"error parsing {path}: {exc}")


def cmd_info(args):
    with open(args.file, "rb") as fh:
        data = fh.read()
    head = data[:8]
    if data[:4] == _x.BINXML_MAGIC:
        kind = "BinXml"
    elif args.file.lower().endswith((".database", ".dat")):
        if data[8:12] == b"LBT" or b"ITM" in data[:32]:
            kind = "database (legacy LBT/ITM)"
        else:
            kind = "database (string-table PRTS)"
    elif data[1:5] == _x.BXML_MAGIC:
        kind = "BXML (big)" if data[0] == 0 else "BXML (little)"
    else:
        kind = "text XML" if _is_text(data) else "unknown/binary"
    print(f"file  : {args.file}")
    print(f"size  : {len(data)}")
    print(f"type  : {kind}")
    print(f"header: {head.hex(' ')}")


def _is_text(data):
    try:
        t = data.decode("utf-8-sig").lstrip(" \t\r\n")
    except UnicodeDecodeError:
        return False
    return t.startswith("<")


def cmd_xml(args):
    doc, src = _load_xml(args.file)
    target = args.to if args.to != "auto" else _default_target(src, args.file)
    if target not in (_x.TEXT, _x.BINXML, _x.BXML_LITTLE, _x.BXML_BIG):
        sys.exit(f"unsupported target type {target}")
    try:
        out = _x.dump(doc, target)
    except _x.XmlError as exc:
        sys.exit(f"error writing: {exc}")
    with open(args.out, "wb") as fh:
        fh.write(out)
    print(f"{args.file} -> {args.out} ({target})")


def _default_target(src, path):
    if src == _x.TEXT:
        return _x.BINXML
    return _x.TEXT


def _xml_from_db(db):
    """Build a readable DataSet-style XmlDoc from a decoded Database."""
    root = _x.XmlDoc("NewDataSet")
    for table in db.tables:
        if not table.fields:
            continue
        for row in table.rows:
            node = _x.XmlDoc(table.name or "row")
            for name, value in zip([f.name for f in table.fields], row):
                child = _x.XmlDoc(name, text=str(value))
                node.children.append(child)
            root.children.append(node)
    return root


def cmd_db_decode(args):
    try:
        with open(args.database, "rb") as fh:
            data = fh.read()
        with open(args.schema, "rb") as fh:
            schema_data = fh.read()
    except OSError as exc:
        sys.exit(f"error reading input: {exc}")
    try:
        schema_xml = _x.load(schema_data)
    except _x.XmlError as exc:
        sys.exit(f"error parsing schema: {exc}")
    schema = _db.xml_to_schema(schema_xml)
    db = _db.read_database(data, schema)
    doc = _xml_from_db(db)
    doc.source_type = _x.TEXT
    with open(args.out, "wb") as fh:
        fh.write(_x.dump(doc, _x.TEXT))
    print(f"{args.database} -> {args.out} "
          f"({len(db.tables)} tables, {sum(len(t.rows) for t in db.tables)} rows)")


def cmd_db_info(args):
    try:
        with open(args.database, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        sys.exit(f"error reading {args.database}: {exc}")
    print(f"file        : {args.database}")
    print(f"size        : {len(data)}")
    if len(data) >= 4:
        print(f"schema version: {int.from_bytes(data[:4], 'little')}")
    has_st = b"PRTS" in data
    print(f"string table: {has_st}")
    count = data.count(b"ITM") + data.count(b"\x2d\x2a")
    print(f"row markers : {count} (approx)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="database_convert",
                                description="EGO binary XML + .database converter")
    sub = p.add_subparsers(dest="cmd", required=True)

    si = sub.add_parser("info", help="detect the flavour of an XML/database file")
    si.add_argument("file")

    sx = sub.add_parser("xml", help="convert XML between text / BinXml / BXML")
    sx.add_argument("file")
    sx.add_argument("out")
    sx.add_argument("--to", default="auto",
                    help="Text, BinXml, BxmlLittle, BxmlBig (default auto)")

    sd = sub.add_parser("db-decode", help="decode a .database to readable XML using a schema")
    sd.add_argument("database")
    sd.add_argument("schema")
    sd.add_argument("out")

    sd2 = sub.add_parser("db-info", help="summarize a .database file")
    sd2.add_argument("database")

    args = p.parse_args(argv)
    dispatch = {
        "info": cmd_info,
        "xml": cmd_xml,
        "db-decode": cmd_db_decode,
        "db-info": cmd_db_info,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
