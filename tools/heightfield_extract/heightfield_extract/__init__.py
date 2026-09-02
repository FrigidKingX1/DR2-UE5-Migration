"""EGO landscape.heightfield parser and UE heightmap PNG exporter.

The DR2 ``landscape.heightfield`` layout (reverse engineered from
australia_rally_01):

    "LAND" u32 version(=1)
    u32 tag_size(=12) "HMAP"
    u32 total_payload_size        (points to end of file)
    u32 num_layers(=2)
    u32 width                     e.g. 300
    u32 height                    e.g. 287
    [remaining bytes: u16 LE height samples, width*height grid,
     row-major, centimetres; trailing padding / extra layer samples]

The exporter writes a 16-bit grayscale PNG (UE Landscape-compatible) plus a
JSON manifest with the parsed dimensions and elevation range.
"""

from __future__ import annotations

import json
import os
import struct

try:
    import imagecodecs
except Exception:  # pragma: no cover
    imagecodecs = None


class HeightfieldFormatError(ValueError):
    pass


def parse_heightfield(data: bytes) -> dict:
    if len(data) < 40 or data[:4] != b"LAND":
        raise HeightfieldFormatError("not a LAND heightfield file")
    (version,) = struct.unpack_from("<I", data, 4)
    (tag_size,) = struct.unpack_from("<I", data, 8)
    tag = data[12:16].decode("ascii", "replace")
    if tag != "HMAP" or tag_size != 12:
        raise HeightfieldFormatError(f"unexpected chunk {tag!r} ({tag_size})")
    # HMAP body: u32 header_size(=12), u32 total_size, u32 num_layers,
    # u32 width, u32 height, then the u16 LE height grid at offset 36.
    (hmap_hdr,) = struct.unpack_from("<I", data, 16)
    (total_size,) = struct.unpack_from("<I", data, 20)
    (num_layers,) = struct.unpack_from("<I", data, 24)
    width, height = struct.unpack_from("<II", data, 28)
    if hmap_hdr != 12:
        raise HeightfieldFormatError(f"unexpected HMAP header {hmap_hdr}")
    if width == 0 or height == 0 or width * height > 64_000_000:
        raise HeightfieldFormatError(f"implausible dimensions {width}x{height}")

    samples_offset = 36
    needed = width * height * 2
    available = len(data) - samples_offset
    if available < needed:
        raise HeightfieldFormatError(
            f"grid {width}x{height} needs {needed}B, only {available}B present")

    samples = struct.unpack_from(f"<{width * height}H", data, samples_offset)
    grid = [samples[y * width:(y + 1) * width] for y in range(height)]
    lo = min(min(row) for row in grid)
    hi = max(max(row) for row in grid)
    return {
        "version": version,
        "num_layers": num_layers,
        "width": width,
        "height": height,
        "min_height": lo,
        "max_height": hi,
        "grid": grid,
        "extra_bytes": available - needed,
    }


def heightmap_png_bytes(parsed: dict) -> bytes | None:
    """16-bit grayscale PNG for UE Landscape import.

    Normalises over the *valid* samples only: DR2 encodes water/void as 0,
    which would otherwise crush the real relief (~1000-unit band around the
    mean elevation).  Voids map to 0 (black).
    """
    if imagecodecs is None:
        return None
    import numpy as np

    grid = np.asarray(parsed["grid"], dtype=np.float32)
    valid = grid[grid > 0]
    if valid.size == 0:
        return imagecodecs.png_encode(np.zeros_like(grid, dtype=np.uint16))
    lo = float(valid.min())
    hi = float(valid.max())
    img = np.zeros_like(grid, dtype=np.uint16)
    mask = grid > 0
    if hi > lo:
        img[mask] = ((grid[mask] - lo) / (hi - lo) * 65535.0 + 0.5)
    else:
        img[mask] = 65535
    return imagecodecs.png_encode(np.ascontiguousarray(img))


def extract_to_png(heightfield_path: str, out_dir: str,
                   base_name: str | None = None) -> str:
    """Parse a .heightfield and write <base>_heightmap.png + manifest."""
    with open(heightfield_path, "rb") as fh:
        data = fh.read()
    parsed = parse_heightfield(data)
    os.makedirs(out_dir, exist_ok=True)
    base = base_name or os.path.splitext(
        os.path.basename(heightfield_path))[0]

    manifest = {k: v for k, v in parsed.items() if k != "grid"}
    if imagecodecs is not None:
        png = heightmap_png_bytes(parsed)
        png_path = os.path.join(out_dir, f"{base}_heightmap.png")
        with open(png_path, "wb") as fh:
            fh.write(png)
        manifest["heightmap_png"] = os.path.basename(png_path)
        manifest["heightmap_range_note"] = (
            "16-bit PNG normalised to the file's min/max elevation")
    manifest_path = os.path.join(out_dir, f"{base}_heightmap.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest_path
