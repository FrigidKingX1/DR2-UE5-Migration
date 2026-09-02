"""Wavefront OBJ/MTL writer for PSSG mesh primitives."""

from __future__ import annotations

import os

from pssg_unpack import PssgFile

from .extract import MeshPrimitive


def _fmt(v):
    return f"{v:.6f}"


def write_obj(prim: MeshPrimitive, path, mtl_name=None, mtl_path=None):
    """Write a single primitive's mesh to a Wavefront OBJ file."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        name = _safe_name(prim.node_id or prim.node_name or "mesh")
        if mtl_name:
            fh.write(f"mtllib {mtl_name}\n")
        fh.write(f"o {name}\n")

        for p in prim.positions:
            fh.write(f"v {_fmt(p[0])} {_fmt(p[1])} {_fmt(p[2])}\n")

        have_n = any(n != (0.0, 0.0, 0.0) for n in prim.normals)
        if have_n:
            for n in prim.normals:
                fh.write(f"vn {_fmt(n[0])} {_fmt(n[1])} {_fmt(n[2])}\n")

        for uvs in prim.uv_sets:
            for u in uvs:
                fh.write(f"vt {_fmt(u[0])} {_fmt(1.0 - u[1])}\n")

        if mtl_path:
            fh.write(f"usemtl {os.path.basename(mtl_path)}\n")

        has_vt = len(prim.uv_sets) > 0
        has_vn = have_n
        for a, b, c in prim.triangles:
            ia, ib, ic = a + 1, b + 1, c + 1
            if has_vt and has_vn:
                fh.write(f"f {ia}/{ia}/{ia} {ib}/{ib}/{ib} {ic}/{ic}/{ic}\n")
            elif has_vt:
                fh.write(f"f {ia}/{ia} {ib}/{ib} {ic}/{ic}\n")
            elif has_vn:
                fh.write(f"f {ia}//{ia} {ib}//{ib} {ic}//{ic}\n")
            else:
                fh.write(f"f {ia} {ib} {ic}\n")


def write_mtl(shader_id, path, textures=None):
    """Write a minimal MTL for a shader with optional texture references."""
    textures = textures or {}
    base_name = os.path.splitext(os.path.basename(path))[0]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"newmtl {_safe_name(shader_id or base_name)}\n")
        diffuse = textures.get("diffuse")
        normal = textures.get("normal")
        if diffuse:
            fh.write(f"map_Kd {os.path.basename(diffuse)}\n")
        if normal:
            fh.write(f"map_Bump {os.path.basename(normal)}\n")


def _safe_name(name):
    out = []
    for ch in name:
        if ch.isalnum() or ch in "._-":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "mesh"