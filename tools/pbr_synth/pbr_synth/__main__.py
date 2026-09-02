"""pbr_synth CLI — neural PBR synthesis + UE5 packaging.

Subcommands:
  pack    Offline pass (no GPU): package legacy maps into the Phase C
          nomenclature.  Roughness is derived purely from the legacy ``_s``
          gloss; ORM metalness falls back to a constant.
  synth   Full pipeline: launches headless ComfyUI + CHORD, estimates
          basecolor/normal/roughness/metalness (+height) per texture set,
          reconciles with the legacy ``_s`` gloss, packs ORM and stops ComfyUI.
  free    Ask a running ComfyUI instance to unload models and free VRAM.

Inputs are the PNG textures exported by ``pssg_convert gltf`` (a folder of
``<car>_<part>_<suffix>.png`` files); outputs follow
``T_<Car>_<Part>_<D|N|ORM|H>.png`` for the Unreal ingest.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

try:
    import imagecodecs
except Exception:  # pragma: no cover
    imagecodecs = None

from . import chord_workflow, reconcile  # noqa: E402
from .comfy import ComfyError, ComfyService  # noqa: E402

DEFAULT_COMFY_DIR = r"E:\ClaudeATHome\Tools\ComfyUI"

# Parts that carry a full legacy texture set worth synthesizing.
SYNTH_SUFFIXES = ("_d", "_n", "_s", "_o")


def _decode(path: str) -> np.ndarray | None:
    if imagecodecs is None:
        return None
    try:
        with open(path, "rb") as fh:
            return np.asarray(imagecodecs.png_decode(fh.read()))
    except Exception:
        return None


def _encode_png(arr: np.ndarray) -> bytes:
    return imagecodecs.png_encode(np.ascontiguousarray(arr))


def _write(out_dir: str, name: str, arr: np.ndarray) -> str:
    path = os.path.join(out_dir, name)
    with open(path, "wb") as fh:
        fh.write(_encode_png(arr))
    return name


def discover_parts(textures_dir: str) -> dict:
    """Find texture sets: {part: {suffix: path}} from <car>_<part><suffix>.png.

    Handles the double extension emitted by the glTF exporter
    (``131_main_d.tga.png``) as well as plain ``131_main_d.png``.
    """
    parts: dict[str, dict[str, str]] = {}
    for fn in sorted(os.listdir(textures_dir)):
        if not fn.lower().endswith(".png"):
            continue
        stem = fn[:-4]
        if stem.lower().endswith(".tga"):
            stem = stem[:-4]
        for suffix in SYNTH_SUFFIXES:
            if stem.endswith(suffix):
                base = stem[: -len(suffix)]
                car, _, part = base.partition("_")
                parts.setdefault(part, {})[suffix] = os.path.join(textures_dir, fn)
                break
    return parts


def car_prefix_from(textures_dir: str) -> str:
    for fn in sorted(os.listdir(textures_dir)):
        if fn.lower().endswith(".png"):
            stem = fn[:-4]
            if stem.lower().endswith(".tga"):
                stem = stem[:-4]
            return stem.split("_", 1)[0]
    return "car"


def cmd_pack(args) -> None:
    """Offline packaging: legacy maps only (no neural synthesis)."""
    parts = discover_parts(args.textures_dir)
    if not parts:
        sys.exit(f"no <car>_<part>_<d|n|s|o>.png sets found in {args.textures_dir}")
    car = args.car or car_prefix_from(args.textures_dir)
    os.makedirs(args.out, exist_ok=True)
    for part, files in sorted(parts.items()):
        if "_d" not in files:
            continue
        albedo = _decode(files["_d"])
        if albedo is None:
            print(f"  skip {part}: cannot decode {files['_d']}")
            continue
        written = [_write(args.out, reconcile.package_name(car, part, "D"),
                          albedo[..., :3])]
        normal = _decode(files.get("_n", ""))
        if normal is not None:
            written.append(_write(args.out, reconcile.package_name(car, part, "N"),
                                  reconcile.invert_green(normal[..., :3])))
        ao = _decode(files.get("_o", ""))
        gloss = _decode(files.get("_s", ""))
        rough = reconcile.legacy_roughness(
            reconcile.specular_to_gloss(gloss)) if gloss is not None else \
            np.full(albedo.shape[:2], 0.5, dtype=np.float32)
        orm = reconcile.pack_orm(
            ao if ao is not None else np.full(albedo.shape[:2], 255, np.uint8),
            rough, np.full(albedo.shape[:2], 0.0, dtype=np.float32))
        written.append(_write(args.out, reconcile.package_name(car, part, "ORM"),
                              orm))
        print(f"  {part}: {', '.join(written)}")


def _resolve_comfy_python(comfy_dir: str, explicit: str | None) -> str:
    """Prefer the ComfyUI venv interpreter; fall back to the current one."""
    if explicit:
        return explicit
    for rel in (os.path.join("venv", "Scripts", "python.exe"),
                os.path.join("venv", "bin", "python")):
        cand = os.path.join(comfy_dir, rel)
        if os.path.isfile(cand):
            return cand
    return sys.executable


def cmd_synth(args) -> None:
    """Full pipeline: ComfyUI + CHORD -> reconciled UE5-ready texture pack."""
    if imagecodecs is None:
        sys.exit("imagecodecs is required for synth (pip install imagecodecs)")
    parts = discover_parts(args.textures_dir)
    if not parts:
        sys.exit(f"no texture sets found in {args.textures_dir}")
    car = args.car or car_prefix_from(args.textures_dir)
    os.makedirs(args.out, exist_ok=True)

    only = set(args.parts.split(",")) if args.parts else None
    todo = {p: f for p, f in sorted(parts.items()) if "_d" in f
            and (only is None or p in only)}
    print(f"car={car} parts={[p for p in todo]}")

    service = ComfyService(args.comfy_dir, port=args.port,
                           python_exe=_resolve_comfy_python(args.comfy_dir,
                                                            args.comfy_python))
    service.start()
    try:
        for part, files in todo.items():
            print(f"[{part}] staging {files['_d']}")
            staged = service.stage_input(files["_d"], f"{car}_{part}_d.png")
            workflow = chord_workflow.build_image_to_material(
                staged, prefix=f"chord_{car}_{part}")
            try:
                entry = service.run(workflow, timeout=args.timeout)
            except ComfyError as exc:
                print(f"[{part}] CHORD failed: {exc}")
                continue
            maps = {slot: service.fetch_output(entry, node)
                    for slot, node in chord_workflow.OUTPUT_NODES.items()}
            _package_part(args, service.comfy_dir, car, part, files, maps)
        service.free_memory()
    finally:
        service.stop()
    print(f"done -> {args.out}")


def _package_part(args, comfy_dir: str, car: str, part: str,
                  files: dict, maps: dict) -> None:
    """Reconcile CHORD outputs with legacy maps and write the Phase C pack."""
    import io as _io

    def dec_png(blob: bytes) -> np.ndarray:
        return np.asarray(imagecodecs.png_decode(blob))

    basecolor = dec_png(maps["basecolor"])[..., :3]
    normal = reconcile.invert_green(dec_png(maps["normal"])[..., :3])
    chord_rough = dec_png(maps["roughness"])
    metalness = dec_png(maps["metalness"])
    height16 = reconcile.height_to_uint16(dec_png(maps["height"]))

    gloss = _decode(files.get("_s", ""))
    if gloss is not None:
        legacy = reconcile.legacy_roughness(reconcile.specular_to_gloss(gloss))
        if legacy.shape[:2] != basecolor.shape[:2]:
            # nearest-resample the legacy map to CHORD's output resolution
            yi = (np.linspace(0, legacy.shape[0] - 1, basecolor.shape[0])
                  ).astype(int)
            xi = (np.linspace(0, legacy.shape[1] - 1, basecolor.shape[1])
                  ).astype(int)
            legacy = legacy[np.ix_(yi, xi)]
        rough = reconcile.blend_roughness(chord_rough, legacy)
    else:
        rough = chord_rough[..., 0] if chord_rough.ndim == 3 else chord_rough

    ao = _decode(files.get("_o", ""))
    if ao is not None and ao.shape[:2] != basecolor.shape[:2]:
        ao = None  # resolution mismatch: fall back to white AO
    h, w = basecolor.shape[:2]
    orm = reconcile.pack_orm(
        ao[..., 0] if ao is not None else np.full((h, w), 255, np.uint8),
        rough,
        metalness[..., 0] if metalness.ndim == 3 else metalness)

    written = [
        _write(args.out, reconcile.package_name(car, part, "D"), basecolor),
        _write(args.out, reconcile.package_name(car, part, "N"), normal),
        _write(args.out, reconcile.package_name(car, part, "ORM"), orm),
        _write(args.out, reconcile.package_name(car, part, "H"), height16),
    ]
    print(f"[{part}] packaged: {', '.join(written)}")


def cmd_free(args) -> None:
    service = ComfyService(args.comfy_dir, port=args.port)
    if service.is_running():
        service.free_memory()
        print("free request sent")
    else:
        print("no ComfyUI instance running")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="pbr_synth",
                                description="Neural PBR synthesis + UE5 packaging")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--car", help="car prefix (default: derive from files)")
    common.add_argument("--out", default="pbr_out")

    pp = sub.add_parser("pack", parents=[common],
                        help="offline legacy-only packaging")
    pp.add_argument("textures_dir")

    ps = sub.add_parser("synth", parents=[common],
                        help="full CHORD synthesis pipeline")
    ps.add_argument("textures_dir")
    ps.add_argument("--comfy-dir", default=DEFAULT_COMFY_DIR)
    ps.add_argument("--comfy-python", default=None,
                    help="python executable for ComfyUI (default: its venv)")
    ps.add_argument("--port", type=int, default=8188)
    ps.add_argument("--parts", default=None,
                    help="comma-separated part filter (e.g. main,cabin)")
    ps.add_argument("--timeout", type=float, default=900.0,
                    help="per-part workflow timeout in seconds")

    pf = sub.add_parser("free", help="free VRAM of a running ComfyUI")
    pf.add_argument("--comfy-dir", default=DEFAULT_COMFY_DIR)
    pf.add_argument("--port", type=int, default=8188)

    args = p.parse_args(argv)
    {"pack": cmd_pack, "synth": cmd_synth, "free": cmd_free}[args.cmd](args)


if __name__ == "__main__":
    main()
