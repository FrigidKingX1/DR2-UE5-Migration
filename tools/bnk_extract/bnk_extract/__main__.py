"""CLI: extract WEM payloads from Wwise .bnk banks."""

from __future__ import annotations

import argparse
import os

from . import BnkFormatError, extract_bank


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="bnk_extract",
        description="Extract WEM media from Wwise .bnk banks")
    p.add_argument("bank", nargs="+", help=".bnk file(s) to extract")
    p.add_argument("--out", default="bnk_out",
                   help="output directory (default: bnk_out)")
    args = p.parse_args(argv)

    for bank in args.bank:
        try:
            manifest = extract_bank(bank, args.out)
            import json
            with open(manifest, "r", encoding="utf-8") as fh:
                info = json.load(fh)
            print(f"{os.path.basename(bank)}: sections="
                  f"{list(info['sections'])} wems={len(info['wems'])} "
                  f"-> {args.out}")
        except (BnkFormatError, OSError) as exc:
            print(f"error: {bank}: {exc}")


if __name__ == "__main__":
    main()
