"""Tests for pssg_convert (PSSG mesh/texture extraction)."""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_TOOLS, "pssg_unpack"))
sys.path.insert(0, os.path.dirname(_TOOLS))

import pytest

from pssg_unpack import read_pssg

from _fixture import build_car
from pssg_convert import (
    PssgConvertError,
    RenderDataSourceReader,
    collect_meshes,
    texture_to_dds_bytes,
    write_mtl,
    write_obj,
)
from pssg_convert.extract import ObjectIndex
from pssg_convert.tbindings import TextureResolver


@pytest.fixture(scope="module")
def pssg():
    blob = _serialize()
    return read_pssg(blob)


@pytest.fixture(scope="module")
def index(pssg):
    return ObjectIndex(pssg.root)


def _serialize():
    from _fixture import write_pssg
    return write_pssg(build_car())


def _rds(pssg, obj_id):
    for el in pssg.root.iter_all():
        if el.name == "RENDERDATASOURCE" and _id(el) == obj_id:
            return el
    raise AssertionError(f"no RENDERDATASOURCE {obj_id}")


def _id(el):
    for a in el.attributes:
        if a.name == "id":
            return a.value
    return ""


# ---------------------------------------------------------------------------
# RenderDataSourceReader


def test_reader_body(pssg, index):
    rds = _rds(pssg, "rds_body")
    reader = RenderDataSourceReader(rds, index)

    assert reader.primitive == "triangles"
    assert reader.index_format == "ushort"
    assert reader.index_count == 3
    assert reader.vertex_count == 3
    assert reader.tex_coord_set_count == 1

    assert reader.get_position(0) == pytest.approx((0.0, 0.0, 0.0))
    assert reader.get_position(1) == pytest.approx((1.0, 0.0, 0.0))
    assert reader.get_position(2) == pytest.approx((0.0, 1.0, 0.0))

    assert reader.get_normal(0) == pytest.approx((0.0, 0.0, 1.0))

    assert reader.get_tex_coord(0, 0) == pytest.approx((0.0, 0.0))
    assert reader.get_tex_coord(1, 0) == pytest.approx((1.0, 0.0))
    assert reader.get_tex_coord(2, 0) == pytest.approx((1.0, 1.0))

    assert reader.get_color(0) == pytest.approx((1.0, 0.0, 0.0, 1.0))
    # uchar4 stores R,G,B,A in memory and the file is big-endian throughout,
    # so the fixture bytes (0,255,0,255) round-trip as-is.
    assert reader.get_color(1) == pytest.approx((0.0, 1.0, 0.0, 1.0))

    assert list(reader.get_triangles()) == [(0, 1, 2)]


def test_uv_float4_split_into_two_sets(pssg, index):
    rds = _rds(pssg, "rds_seat")
    reader = RenderDataSourceReader(rds, index)
    assert reader.tex_coord_set_count == 2
    assert reader.get_tex_coord(0, 0) == pytest.approx((0.0, 0.0))
    assert reader.get_tex_coord(0, 1) == pytest.approx((0.5, 0.5))


def test_matrix_palette_subrange(pssg, index):
    rds = _rds(pssg, "rds_shared")
    reader = RenderDataSourceReader(rds, index)
    # whole buffer has 3 triangles; subset starts at index 3 with count 3
    tris = list(reader.get_triangles(3, 3))
    assert tris == [(1, 2, 3)]
    assert reader.get_position(2) == pytest.approx((0.0, 1.0, 0.0))
    assert reader.get_position(3) == pytest.approx((1.0, 1.0, 0.0))


# ---------------------------------------------------------------------------
# scene traversal


def test_collect_meshes(pssg, index):
    meshes = collect_meshes(pssg.root, index)
    by_name = {m.node_id: m for m in meshes}
    assert set(by_name) == {"body", "seatmesh", "wheel_fl"}

    body = by_name["body"]
    assert body.shader_id == "s_car"
    assert body.vertex_count() == 3
    assert len(body.triangles) == 1
    assert body.triangles[0] == (0, 1, 2)
    assert len(body.uv_sets) == 1
    assert body.uv_sets[0][0] == pytest.approx((0.0, 0.0))
    assert body.colors[0] == pytest.approx((1.0, 0.0, 0.0, 1.0))

    seat = by_name["seatmesh"]
    assert len(seat.uv_sets) == 2
    assert seat.shader_id == "s_seat"

    wheel = by_name["wheel_fl"]
    assert wheel.vertex_count() == 3
    assert wheel.triangles[0] == (0, 1, 2)
    assert wheel.positions[0] == pytest.approx((1.0, 0.0, 0.0))  # vertex 1
    assert wheel.positions[2] == pytest.approx((1.0, 1.0, 0.0))  # vertex 3


def test_no_library_raises():
    from pssg_unpack import PssgElement, PssgFile
    root = PssgElement(name="PSSGDATABASE")
    root.children.append(PssgElement(name="LIBRARY"))
    with pytest.raises(PssgConvertError):
        collect_meshes(root, ObjectIndex(root))


# ---------------------------------------------------------------------------
# OBJ / MTL writers


def test_obj_write(pssg, index, tmp_path):
    meshes = collect_meshes(pssg.root, index)
    body = [m for m in meshes if m.node_id == "body"][0]
    out = tmp_path / "body.obj"
    write_obj(body, str(out), mtl_name="body.mtl", mtl_path=str(tmp_path / "body.mtl"))
    text = out.read_text(encoding="utf-8")

    assert text.startswith("mtllib body.mtl\n")
    assert "o body\n" in text
    assert text.count("v ") == 3
    assert text.count("vn ") == 3
    assert text.count("vt ") == 3
    assert "f 1/1/1 2/2/2 3/3/3\n" in text
    # V is flipped for OBJ (y-up texture origin flip)
    assert "vt 0.000000 1.000000\n" in text


def test_mtl_write(tmp_path):
    path = tmp_path / "mat.mtl"
    write_mtl("s_car", str(path), {"diffuse": "tex.png", "normal": "n.png"})
    text = path.read_text(encoding="utf-8")
    assert "newmtl s_car\n" in text
    assert "map_Kd tex.png\n" in text
    assert "map_Bump n.png\n" in text


# ---------------------------------------------------------------------------
# DDS textures


def test_dds_dxt1_header(pssg):
    tex = _find(pssg, "tex_body_paint")
    blob = texture_to_dds_bytes(tex)
    assert blob[:4] == b"DDS "
    hdr = struct.unpack_from("<I", blob, 4)[0]
    assert hdr == 124                 # size
    flags = struct.unpack_from("<I", blob, 8)[0]
    assert flags & 0x80000            # LINEARSIZE
    mip_count = struct.unpack_from("<I", blob, 28)[0]
    assert mip_count == 1
    caps_v = struct.unpack_from("<I", blob, 108)[0]
    assert caps_v & 0x1000            # TEXTURE
    fourcc = blob[84:88]
    assert fourcc == b"DXT1"
    assert blob[128:] == b"\x88" * 8  # payload after 128 header


def test_dds_cubemap_layout(pssg):
    tex = _find(pssg, "tex_env")
    blob = texture_to_dds_bytes(tex)
    caps2 = struct.unpack_from("<I", blob, 112)[0]
    assert caps2 & 0x200                 # CUBEMAP
    assert caps2 & 0x7F00 == 0x7E00      # all six face bits
    payload = blob[128:]
    assert len(payload) == 6 * 4
    # faces concatenated in face-index order (Raw, RawNegativeX, ...)
    assert payload == b"".join(bytes([i] * 4) for i in range(6))


def test_dds_u8_luminance(pssg):
    tex = _find(pssg, "tex_seat")
    blob = texture_to_dds_bytes(tex)
    flags = struct.unpack_from("<I", blob, 80)[0]
    assert flags & 0x20000              # DDPF_LUMINANCE


def test_dds_unsupported_texel(pssg):
    from pssg_unpack import PssgAttribute, PssgElement
    from pssg_unpack.constants import ATTR_INT, ATTR_STRING
    from pssg_convert.dds import TextureConvertError
    tex = PssgElement(name="TEXTURE")
    tex.attributes.append(PssgAttribute("width", ATTR_INT, 0, 4))
    tex.attributes.append(PssgAttribute("height", ATTR_INT, 0, 4))
    tex.attributes.append(PssgAttribute("texelFormat", ATTR_STRING, 0, "rgb32f"))
    with pytest.raises(TextureConvertError):
        texture_to_dds_bytes(tex)


# ---------------------------------------------------------------------------
# texture binding resolution


def test_texture_resolver(pssg, index):
    resolver = TextureResolver(index)
    inst = _find(pssg, "bpaint")  # a RENDERSTREAMINSTANCE with shader ref
    from pssg_convert.tbindings import resolve_shader_and_group
    shader, group = resolve_shader_and_group(inst, index)
    assert shader is not None and shader.name == "SHADERINSTANCE"
    assert group is not None and group.name == "SHADERGROUP"
    diffuse = resolver.get_diffuse(shader, group)
    normal = resolver.get_normal(shader, group)
    assert _id(diffuse) == "tex_body_paint"
    assert _id(normal) == "tex_body_normal"

    sw_inst = _find(pssg, "wheelmat")  # RENDERSTREAMINSTANCE for the wheel
    sh, g = resolve_shader_and_group(sw_inst, index)
    assert sh is not None
    assert resolver.get_diffuse(sh, g) is None
    assert _id(resolver.get_specular(sh, g)) == "tex_wheel"


# ---------------------------------------------------------------------------
# CLI


def test_cli_extract(pssg, tmp_path, capsys):
    import json
    from pssg_convert.__main__ import main

    blob = _serialize()
    src = tmp_path / "car.pssg"
    src.write_bytes(blob)
    out = tmp_path / "out"

    main(["extract", str(src), "--out", str(out)])

    meshes = list((out / "meshes").glob("*.obj"))
    assert len(meshes) == 3
    assert (out / "textures" / "tex_body_paint.dds").exists()
    assert (out / "textures" / "tex_env.dds").exists()
    assert (out / "textures" / "tex_seat.dds").exists()
    manifest = json.loads((out / "pssg_manifest.json").read_text(encoding="utf-8"))
    assert manifest["meshCount"] == 3
    assert manifest["shaders"]["s_car"]["diffuse"] == "tex_body_paint.dds"


def test_cli_info(pssg, tmp_path, capsys):
    from pssg_convert.__main__ import main
    blob = _serialize()
    src = tmp_path / "car.pssg"
    src.write_bytes(blob)
    main(["info", str(src)])
    out = capsys.readouterr().out
    assert "RENDERDATASOURCE" in out
    assert "DDS" not in out


def _find(pssg, obj_id):
    for el in pssg.root.iter_all():
        if _id(el) == obj_id:
            return el
    raise AssertionError(f"no element with id {obj_id}")