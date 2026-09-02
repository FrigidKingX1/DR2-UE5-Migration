"""Command-line interface for pssg_unpack."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def _load(path: str):
    from .reader import PssgFormatError, read_pssg
    with open(path, "rb") as f:
        raw = f.read()
    return read_pssg(raw)


def _fmt_attr(attr) -> str:
    from . import constants as C
    name = C._INT_TO_ATTR.get(attr.pssg_type, "?")
    v = attr.value
    if isinstance(v, bytes):
        shown = f"<{len(v)} bytes>"
    elif isinstance(v, tuple):
        shown = " ".join(f"{x:g}" for x in v)
    elif isinstance(v, float):
        shown = f"{v:g}"
    else:
        shown = str(v)
    return f"{name} {attr.name}={shown}"


def _cmd_info(args) -> int:
    try:
        pssg = _load(args.file)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    root = pssg.root
    print(f"elements in schema : {len(pssg.element_table)}")
    print(f"attributes in schema: {len(pssg.attribute_table)}")
    print(f"root element       : {root.name}  size={root.size}")

    def walk(elem, depth):
        pad = "  " * depth
        print(f"{pad}<{elem.name}>")
        for attr in elem.attributes:
            print(f"{pad}  @{_fmt_attr(attr)}")
        for child in elem.children:
            walk(child, depth + 1)
        if elem.is_data:
            print(f"{pad}  [data {len(elem.value)} bytes]")

    walk(root, 0)
    return 0


def _cmd_dump(args) -> int:
    import json

    from .model import PssgElement

    try:
        pssg = _load(args.file)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    def to_json(elem: PssgElement):
        node = {"name": elem.name}
        if elem.attributes:
            node["attributes"] = {a.name: _json_attr(a) for a in elem.attributes}
        if elem.is_data:
            node["data"] = elem.value.hex()
        if elem.children:
            node["children"] = [to_json(c) for c in elem.children]
        return node

    print(json.dumps(to_json(pssg.root), indent=2))
    return 0


def _json_attr(attr):
    if isinstance(attr.value, bytes):
        return {"type": "bytes", "size": len(attr.value), "hex": attr.value.hex()}
    return attr.value


def _cmd_extract(args) -> int:
    """Extract data elements as raw files."""
    import os

    from .reader import PssgFormatError, read_pssg

    with open(args.file, "rb") as f:
        raw = f.read()
    try:
        pssg = read_pssg(raw)
    except PssgFormatError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for elem in pssg.root.iter_all():
        if not elem.is_data or not elem.value:
            continue
        for attr in elem.attributes:
            if attr.name == "id" and isinstance(attr.value, str) and attr.value:
                name = attr.value
                break
        else:
            name = f"{elem.name}_{count}"
        target = os.path.join(out_dir, name.lstrip("/\\").replace("/", os.sep))
        os.makedirs(os.path.dirname(target) or out_dir, exist_ok=True)
        with open(target, "wb") as f:
            f.write(elem.value)
        count += 1
    print(f"extracted {count} data elements to {out_dir}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pssg_unpack",
                                     description="EGO PSSG binary scene graph tool")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="print the element/attribute tree")
    p_info.add_argument("file")
    p_info.set_defaults(func=_cmd_info)

    p_dump = sub.add_parser("dump", help="dump the tree as JSON")
    p_dump.add_argument("file")
    p_dump.set_defaults(func=_cmd_dump)

    p_extract = sub.add_parser("extract", help="extract data elements to files")
    p_extract.add_argument("file")
    p_extract.add_argument("--out", default="extracted")
    p_extract.set_defaults(func=_cmd_extract)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())