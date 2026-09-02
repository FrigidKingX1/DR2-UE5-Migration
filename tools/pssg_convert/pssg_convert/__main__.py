import argparse
import json
import os
import sys


def _bootstrap_pssg_unpack():
    """Locate the sibling pssg_unpack package and add it to sys.path."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        here,
        os.path.join(here, "..", "..", "pssg_unpack"),
        os.path.join(here, "..", "pssg_unpack"),
    ]
    for cand in candidates:
        if os.path.isdir(cand) and os.path.isfile(os.path.join(cand, "pssg_unpack", "__init__.py")):
            if cand not in sys.path:
                sys.path.insert(0, cand)
            return cand
    raise SystemExit(
        "pssg_convert requires the sibling 'pssg_unpack' package on sys.path")


_bootstrap_pssg_unpack()

from pssg_unpack import PssgFormatError, read_pssg  # noqa: E402


def _load(path):
    try:
        with open(path, "rb") as fh:
            return read_pssg(fh.read())
    except PssgFormatError as exc:
        sys.exit(f"error: {exc}")
    except OSError as exc:
        sys.exit(f"error reading {path}: {exc}")


def cmd_info(args):
    pssg = _load(args.file)
    root = pssg.root
    counts = {}
    for el in root.iter_all():
        counts[el.name] = counts.get(el.name, 0) + 1
    print(f"file size : {pssg.file_size}")
    print(f"elements  : {sum(counts.values())}")
    print(f"element types:")
    for name in sorted(counts):
        print(f"  {name:<34}{counts[name]}")


def cmd_extract(args):
    from . import dds as _dds
    from . import tbindings as _tb
    from .extract import ObjectIndex, collect_meshes
    from .obj import write_mtl, write_obj

    pssg = _load(args.file)
    root = pssg.root
    index = ObjectIndex(root)

    try:
        meshes = collect_meshes(root, index)
    except Exception as exc:
        sys.exit(f"error extracting meshes: {exc}")

    if not meshes:
        sys.exit("no render meshes found in this pssg file")

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    # texture pass
    resolver = _tb.TextureResolver(index)
    textures = _tb.collect_textures(root, index)
    tex_dir = os.path.join(out_dir, "textures")
    os.makedirs(tex_dir, exist_ok=True)
    writes = {}
    for tid, tex in textures.items():
        try:
            blob = _dds.texture_to_dds_bytes(tex)
            fname = _safe(tid) + ".dds"
            with open(os.path.join(tex_dir, fname), "wb") as fh:
                fh.write(blob)
            writes[tid] = fname
        except Exception:
            continue
    print(f"textures: {len(writes)}/{len(textures)} exported")

    # shader material binding map
    material_map = {}
    for el in root.iter_all():
        if el.name == "SHADERINSTANCE":
            ident = _attr_str(el, "id", "")
            if not ident:
                continue
            sg = index.get(_attr_str(el, "shaderGroup", "#"))
            if sg is None or sg.name != "SHADERGROUP":
                sg = None
            res = {
                "diffuse": _tex_of(resolver.get_diffuse(el, sg), writes),
                "specular": _tex_of(resolver.get_specular(el, sg), writes),
                "occlusion": _tex_of(resolver.get_occlusion(el, sg), writes),
                "emissive": _tex_of(resolver.get_emissive(el, sg), writes),
                "normal": _tex_of(resolver.get_normal(el, sg), writes),
            }
            material_map[ident] = res

    obj_dir = os.path.join(out_dir, "meshes")
    os.makedirs(obj_dir, exist_ok=True)
    seen_mtl = {}
    for i, prim in enumerate(meshes):
        name = f"{_safe(prim.node_id or prim.node_name or 'mesh')}_{i}"
        shader_binding = material_map.get(prim.shader_id, {})
        mtl_path = None
        if shader_binding:
            mtl_name = _safe(prim.shader_id or name) + ".mtl"
            mtl_path = os.path.join(obj_dir, mtl_name)
            if mtl_name not in seen_mtl:
                write_mtl(prim.shader_id or name, mtl_path, shader_binding)
                seen_mtl[mtl_name] = True
            write_obj(prim, os.path.join(obj_dir, name + ".obj"),
                      mtl_name=mtl_name, mtl_path=mtl_path)
        else:
            write_obj(prim, os.path.join(obj_dir, name + ".obj"))

    # manifest
    manifest = {
        "shaders": material_map,
        "textures": writes,
        "meshCount": len(meshes),
    }
    with open(os.path.join(out_dir, "pssg_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"meshes: {len(meshes)} exported to {obj_dir}")


def _attr_str(el, name, default=""):
    for a in el.attributes:
        if a.name == name:
            v = a.value
            if isinstance(v, bytes):
                return v.decode("utf-8", errors="replace").rstrip("\x00")
            return v if isinstance(v, str) else str(v)
    return default


def _safe(name):
    out = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return out or "tex"


def _tex_of(texel, writes):
    if texel is None:
        return None
    ident = _attr_str(texel, "id", "")
    return writes.get(ident)


def cmd_gltf(args):
    import json as _json

    from . import gltf as _gltf
    from .extract import ObjectIndex, collect_meshes
    from .tbindings import collect_textures

    pssg = _load(args.file)
    root = pssg.root
    index = ObjectIndex(root)

    try:
        meshes = collect_meshes(root, index)
    except Exception as exc:
        sys.exit(f"error extracting meshes: {exc}")
    if not meshes:
        sys.exit("no render meshes found in this pssg file")

    # texture container(s): ids -> TEXTURE elements, decode to PNG
    texture_ids = {}
    texture_pngs = {}
    container_paths = list(args.texture_pssg or [])
    if not container_paths:
        # default: sibling textures_high container next to the mesh file
        import glob as _glob
        here = os.path.dirname(os.path.abspath(args.file))
        car_dir = os.path.basename(os.path.dirname(here)) or ""
        for pattern in (
                os.path.join(here, "..", "textures_high", f"{car_dir}_tex_high*.pssg"),
                os.path.join(os.path.dirname(here), "textures_high", "*.pssg"),
        ):
            container_paths.extend(sorted(_glob.glob(pattern)))
            if container_paths:
                break
    for cpath in container_paths[:1]:
        tpssg = _load(cpath)
        tindex = ObjectIndex(tpssg.root)
        for tid, tex in collect_textures(tpssg.root, tindex).items():
            texture_ids[tid] = tex
            png = _gltf.texture_to_png_bytes(tex)
            if png is not None:
                texture_pngs[tid] = png
    print(f"texture container: {len(texture_ids)} textures, "
          f"{len(texture_pngs)} decodable to PNG")

    material_bindings = _gltf.collect_material_bindings(root, index,
                                                        texture_ids.keys())

    base_name = os.path.splitext(os.path.basename(args.file))[0] + "_gltf"
    manifest = _gltf.write_gltf(meshes, material_bindings, texture_pngs,
                                args.out, base_name, neg_z=args.neg_z)
    manifest["materialBindings"] = material_bindings
    with open(os.path.join(args.out, "gltf_manifest.json"), "w",
              encoding="utf-8") as fh:
        _json.dump(manifest, fh, indent=2)
    print(f"glTF: {manifest['meshes']} meshes, {manifest['materials']} "
          f"materials, {len(manifest['textures'])} textures -> {args.out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="pssg_convert",
                                description="EGO PSSG mesh + texture extractor")
    sub = p.add_subparsers(dest="cmd", required=True)

    si = sub.add_parser("info", help="summarize a pssg file's element tree")
    si.add_argument("file")

    se = sub.add_parser("extract", help="extract meshes (obj/mtl) and textures (dds)")
    se.add_argument("file")
    se.add_argument("--out", default="pssg_out")

    sg = sub.add_parser("gltf", help="export meshes + materials as glTF 2.0")
    sg.add_argument("file")
    sg.add_argument("--out", default="pssg_gltf_out")
    sg.add_argument("--texture-pssg", action="append",
                    help="texture container PSSG (repeatable)")
    sg.add_argument("--neg-z", action="store_true",
                    help="negate Z and reverse winding (D3D LH -> glTF RH)")

    args = p.parse_args(argv)
    {"info": cmd_info, "extract": cmd_extract, "gltf": cmd_gltf}[args.cmd](args)


if __name__ == "__main__":
    main()