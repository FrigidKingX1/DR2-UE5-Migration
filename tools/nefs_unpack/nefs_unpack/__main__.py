"""Command-line interface for nefs_unpack.

Usage:
    python -m nefs_unpack scan   <game.exe> [<data_dir>]
    python -m nefs_unpack unpack <archive.nefs|.nfs> [--out <dir>]
    python -m nefs_unpack unpack <archive.dat> --exe <game.exe> --primary <hex> --secondary <hex> [--out <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .archive import read_split_archive_from_exe, read_standard_archive
from .extract import extract_archive
from .exe_finder import find_headers


def _cmd_scan(args) -> int:
    sources = find_headers(args.exe, args.data_dir or ".", search_entire_exe=args.entire)
    if args.json:
        payload = [
            {
                "data_file": s.data_file_path,
                "primary_offset": s.primary_offset,
                "secondary_offset": s.secondary_offset,
            }
            for s in sources
        ]
        print(json.dumps(payload, indent=2))
    else:
        if not sources:
            print("No headers found.")
            return 1
        for s in sources:
            print(f"{s.data_file_path}")
            print(f"  primary   0x{s.primary_offset:X}")
            print(f"  secondary 0x{s.secondary_offset:X}")
    return 0


def _cmd_unpack(args) -> int:
    if args.archive.lower().endswith((".dat",)):
        if not (args.exe and args.primary is not None and args.secondary is not None):
            print("Split `.dat` archives require --exe, --primary and --secondary.", file=sys.stderr)
            return 2
        archive = read_split_archive_from_exe(
            args.archive, args.exe, args.primary, args.secondary)
    else:
        archive = read_standard_archive(args.archive)

    print(f"version : {archive.header.version:#x}")
    print(f"entries : {len(archive.items.items)}")

    out_dir = args.out or "extracted"
    extract_archive(archive, out_dir)
    print(f"extracted to {out_dir}")
    return 0


def _cmd_list(args) -> int:
    if args.archive.lower().endswith((".dat",)):
        archive = read_split_archive_from_exe(
            args.archive, args.exe, args.primary, args.secondary)
    else:
        archive = read_standard_archive(args.archive)

    for item in archive.items.items:
        kind = "dir " if item.is_directory else "file"
        size = "-" if item.is_directory else str(item.extracted_size)
        print(f"{kind}  {size:>10}  {item.file_name}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="nefs_unpack",
                                     description="EGO NeFS archive unpacker")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="find split headers in a game exe")
    p_scan.add_argument("exe")
    p_scan.add_argument("data_dir", nargs="?")
    p_scan.add_argument("--json", action="store_true")
    p_scan.add_argument("--entire", action="store_true",
                        help="search the whole exe (not just .data)")
    p_scan.set_defaults(func=_cmd_scan)

    p_unpack = sub.add_parser("unpack", help="extract an archive")
    p_unpack.add_argument("archive")
    p_unpack.add_argument("--exe")
    p_unpack.add_argument("--primary", type=lambda s: int(s, 0))
    p_unpack.add_argument("--secondary", type=lambda s: int(s, 0))
    p_unpack.add_argument("--out")
    p_unpack.set_defaults(func=_cmd_unpack)

    p_list = sub.add_parser("list", help="list archive contents")
    p_list.add_argument("archive")
    p_list.add_argument("--exe")
    p_list.add_argument("--primary", type=lambda s: int(s, 0))
    p_list.add_argument("--secondary", type=lambda s: int(s, 0))
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
