"""Command-line interface for jpk_unpack."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .archive import JpkFormatError, extract_jpk, read_jpk


def _cmd_info(args) -> int:
    try:
        jpk, raw = read_jpk(args.archive)
    except JpkFormatError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"alignment     : {jpk.alignment}")
    print(f"entries       : {len(jpk.entries)}")
    for e in jpk.entries:
        print(f"  {e.name!r}  size={e.size}")
    return 0


def _cmd_unpack(args) -> int:
    out_dir = args.out or "extracted"
    try:
        written = extract_jpk(args.archive, out_dir)
    except JpkFormatError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"extracted {len(written)} entries to {out_dir}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jpk_unpack",
                                     description="EGO JPK (JPAK) archive extractor")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="show archive structure")
    p_info.add_argument("archive")
    p_info.set_defaults(func=_cmd_info)

    p_unpack = sub.add_parser("unpack", help="extract all entries")
    p_unpack.add_argument("archive")
    p_unpack.add_argument("--out")
    p_unpack.set_defaults(func=_cmd_unpack)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())