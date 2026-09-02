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
    p.add_argument("--gltf", action="store_true",
                   help="also export the terrain as a glTF 2.0 mesh")
    args = p.parse_args(argv)
    manifest = extract_to_png(args.file, args.out, args.name)
    print(f"heightmap -> {manifest}")
    if args.gltf:
        from . import terrain_to_gltf_files
        base = args.name or os.path.splitext(
            os.path.basename(args.file))[0]
        gltf = terrain_to_gltf_files(args.file, args.out, base)
        print(f"terrain glTF -> {gltf}")


if __name__ == "__main__":
    main()
