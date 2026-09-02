import argparse
import json
import sys

from .ctf import CtfFormatError, read_ctf, write_ctf
from .csvcodec import csv_to_entries, entries_to_csv
from .jsoncodec import entries_to_json, json_to_entries
from .schema import CtfSchema, SchemaError


def _load_schema(path):
    try:
        return CtfSchema.from_file(path)
    except (SchemaError, OSError) as exc:
        sys.exit(f"error loading schema: {exc}")


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        sys.exit(f"error reading {path}: {exc}")


def cmd_info(args):
    schema = _load_schema(args.schema)
    entries, flag = read_ctf(_read(args.file), schema, strict=not args.lenient)
    print(f"schema   : {schema.ext} ({len(schema.entries)} entries, line={schema.line})")
    for i, e in enumerate(schema.entries):
        marker = "*" if e.id in entries else " "
        gated = ""
        if e.link_id != -1:
            gated = f" link={e.link_id}"
        elif e.min_flag != -1 or e.max_flag != -1:
            lo = f" [flag{'>=' if e.min_operator in (None, 'gte') and e.min_flag else '=='}{int(e.min_flag)}]" if e.min_flag != -1 else ""
            hi = f" [flag{'>=' if e.max_operator == 'gte' else '<'}{int(e.max_flag)}]" if e.max_flag != -1 else ""
            gated = (lo + hi)
        present = entries[e.id] if e.id in entries else "-"
        print(f"{marker}{e.id:>3} {e.name:<34}{e.type:<10}{present!r}{gated}")


def cmd_to_csv(args):
    schema = _load_schema(args.schema)
    entries, flag = read_ctf(_read(args.file), schema, strict=not args.lenient)
    out = entries_to_csv(entries, schema)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(out)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(out)


def cmd_from_csv(args):
    schema = _load_schema(args.schema)
    with open(args.file, encoding="utf-8") as fh:
        entries = csv_to_entries(fh.read(), schema)
    write(args.out, entries, schema)


def cmd_read_for_convert(args):
    schema = _load_schema(args.schema)
    return read_ctf(_read(args.file), schema, strict=not args.lenient)


def cmd_to_json(args):
    schema = _load_schema(args.schema)
    entries, flag = read_ctf(_read(args.file), schema, strict=not args.lenient)
    doc = entries_to_json(entries, schema, flag)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        print(f"wrote {args.out}")
    else:
        json.dump(doc, sys.stdout, indent=2)
        sys.stdout.write("\n")


def cmd_from_json(args):
    schema = _load_schema(args.schema)
    with open(args.file, encoding="utf-8") as fh:
        doc = json.load(fh)
    entries = json_to_entries(doc, schema)
    write(args.out, entries, schema)


def write(out, entries, schema):
    blobs = write_ctf(entries, schema)
    if not out:
        sys.exit("missing required --out")
    with open(out, "wb") as fh:
        fh.write(blobs)
    print(f"wrote {out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ctf_convert", description="EGO CarTuningFile (ctf) toolkit")
    sub = p.add_subparsers(dest="cmd", required=True)

    si = sub.add_parser("info", help="describe a binary ctf file")
    si.add_argument("file")
    si.add_argument("--schema", required=True)
    si.add_argument("--lenient", action="store_true",
                    help="tolerate extra entries gated out by the flag value")

    tc = sub.add_parser("to-csv", help="convert ctf to csv")
    tc.add_argument("file")
    tc.add_argument("--schema", required=True)
    tc.add_argument("--out")
    tc.add_argument("--lenient", action="store_true",
                    help="tolerate extra entries gated out by the flag value")

    fc = sub.add_parser("from-csv", help="convert csv to ctf")
    fc.add_argument("file")
    fc.add_argument("--schema", required=True)
    fc.add_argument("--out", required=True)

    tj = sub.add_parser("to-json", help="convert ctf to full-fidelity json")
    tj.add_argument("file")
    tj.add_argument("--schema", required=True)
    tj.add_argument("--out")
    tj.add_argument("--lenient", action="store_true",
                    help="tolerate extra entries gated out by the flag value")

    fj = sub.add_parser("from-json", help="convert json to ctf")
    fj.add_argument("file")
    fj.add_argument("--schema", required=True)
    fj.add_argument("--out", required=True)

    ac = sub.add_parser(
        "ai-to-config",
        help="build vehicle_config.json from decoded AI statistics XMLs")
    ac.add_argument("--stats", required=True,
                    help="ai_vehicle_statistics.xml (decoded to text)")
    ac.add_argument("--cornering", required=True,
                    help="ai_vehicle_cornering_statistics.xml (decoded)")
    ac.add_argument("--out", required=True)
    ac.add_argument("--car", default=None)

    args = p.parse_args(argv)
    try:
        if args.cmd == "ai-to-config":
            from .aistats import write_config
            out = write_config(args.stats, args.cornering, args.out,
                               car=args.car)
            print(f"vehicle config -> {out}")
            return
        {"info": cmd_info, "to-csv": cmd_to_csv, "from-csv": cmd_from_csv,
         "to-json": cmd_to_json, "from-json": cmd_from_json}[args.cmd](args)
    except (CtfFormatError, SchemaError) as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()