"""Command-line interface for erp_unpack."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .archive import ErpFormatError, extract_erp, read_erp


def _cmd_info(args) -> int:
    try:
        erp, raw = read_erp(args.archive)
    except ErpFormatError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"version         : {erp.version}")
    print(f"resource offset : 0x{erp.resource_offset:X}")
    print(f"resources       : {len(erp.resources)}")
    for res in erp.resources:
        frags = " ".join(f"{f.name}({'C' if f.is_compressed else 'R'})" for f in res.fragments)
        print(f"  {res.identifier}  type={res.resource_type}  "
              f"size={res.size}  [{frags}]")
    return 0


def _cmd_unpack(args) -> int:
    out_dir = args.out or "extracted"
    try:
        written = extract_erp(args.archive, out_dir)
    except ErpFormatError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"extracted {len(written)} resources to {out_dir}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="erp_unpack",
                                     description="EGO ERP (KPAR) archive extractor")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="show archive structure")
    p_info.add_argument("archive")
    p_info.set_defaults(func=_cmd_info)

    p_unpack = sub.add_parser("unpack", help="extract all resources")
    p_unpack.add_argument("archive")
    p_unpack.add_argument("--out")
    p_unpack.set_defaults(func=_cmd_unpack)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
