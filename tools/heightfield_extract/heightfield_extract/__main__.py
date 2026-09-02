"""CLI: convert EGO landscape.heightfield to UE heightmap PNG."""

from __future__ import annotations

import argparse

from . import extract_to_png


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="heightfield_extract",
        description="EGO landscape.heightfield -> UE Landscape heightmap PNG")
    p.add_argument("file", help="landscape.heightfield file")
    p.add_argument("--out", default="heightfield_out")
    p.add_argument("--name", default=None,
                   help="base name (default: input stem)")
    args = p.parse_args(argv)
    manifest = extract_to_png(args.file, args.out, args.name)
    print(f"heightmap -> {manifest}")


if __name__ == "__main__":
    main()
