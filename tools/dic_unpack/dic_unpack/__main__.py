"""Command-line interface for dic_unpack."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .archive import DicFormatError, extract_dic, read_dic
from .constants import FORMAT_NAMES


def _cmd_info(args) -> int:
    try:
        dic, raw = read_dic(args.dic)
    except DicFormatError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    sku = f"{dic.sku:08X}"
    print(f"sku          : DIC (0x{sku})  endian={'big' if dic.big_endian else 'little'}")
    print(f"unique id    : 0x{dic.unique_id:08X}")
    print(f"version      : {dic.version}")
    print(f"banks        : {len(dic.banks)}")
    for bank in dic.banks:
        print(f"  {bank.name}  samples={bank.num_samples}  ext={bank.extension}")
        accum = 0
        for s in bank.samples:
            accum += s.length
            print(f"    {s.name:16s} rate={s.sample_rate:6d} ch={s.num_channels} "
                  f"fmt={FORMAT_NAMES.get(s.audio_format, '?')} "
                  f"loop={int(s.loop)} bytes={s.length}")
        print(f"    -> {accum} sample bytes")
    return 0


def _cmd_extract(args) -> int:
    out_dir = args.out or "extracted"
    try:
        written = extract_dic(args.dic, out_dir, wav=args.wav)
    except DicFormatError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"extracted {len(written)} samples to {out_dir}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="dic_unpack",
        description="EGO Neon Sound Dictionary (.dic) extractor")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="show dictionary structure")
    p_info.add_argument("dic")
    p_info.set_defaults(func=_cmd_info)

    p_extract = sub.add_parser("extract", help="extract audio samples")
    p_extract.add_argument("dic")
    p_extract.add_argument("--out")
    p_extract.add_argument("--wav", action="store_true",
                           help="wrap uncompressed PCM16-LE/float32 in WAV")
    p_extract.set_defaults(func=_cmd_extract)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())