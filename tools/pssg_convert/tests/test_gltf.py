"""Tests for the glTF 2.0 exporter (pssg_convert.gltf)."""

from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest

from _fixture import build_car, write_fixture
from pssg_unpack import write_pssg


@pytest.fixture(scope="module")
def car_pssg_path(tmp_path_factory):
    path = os.path.join(tmp_path_factory.mktemp("gltf_car"), "car.pssg")
    write_fixture(path)
    return path


def _export(tmp_path, car_pssg_path, *extra):
    from pssg_convert.__main__ import main

    out = os.path.join(str(tmp_path), "gltf_out")
    rc = main(["gltf", car_pssg_path, "--out", out,
               "--texture-pssg", car_pssg_path, *extra])
    assert rc is None
    with open(os.path.join(out, "car_gltf.gltf"), "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    with open(os.path.join(out, "car_gltf.bin"), "rb") as fh:
        blob = fh.read()
    return out, doc, blob


def _read_accessor(doc, blob, index):
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view["byteOffset"]
    comp = {"5126": 4, "5123": 2, "5125": 4}[str(acc["componentType"])]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    size = acc["count"] * comp * n
    data = blob[start:start + size]
    fmt = {5126: "f", 5123: "H", 5125: "I"}[acc["componentType"]]
    return [struct.unpack_from("<" + fmt * n, data, i * comp * n)
            for i in range(acc["count"])]


def test_gltf_document_structure(tmp_path, car_pssg_path):
    out, doc, blob = _export(tmp_path, car_pssg_path)

    assert doc["asset"]["version"] == "2.0"
    assert len(doc["buffers"]) == 1
    assert doc["buffers"][0]["byteLength"] == len(blob)
    # fixture: body + seat + wheel meshes
    assert len(doc["meshes"]) == 3
    assert len(doc["nodes"]) == 3
    assert len(doc["scenes"][0]["nodes"]) == 3


def test_gltf_body_attributes(tmp_path, car_pssg_path):
    out, doc, blob = _export(tmp_path, car_pssg_path)

    body = next(m for m in doc["meshes"] if m["name"] == "body")
    prim = body["primitives"][0]
    attrs = prim["attributes"]
    assert "POSITION" in attrs and "NORMAL" in attrs
    assert "TEXCOORD_0" in attrs and "COLOR_0" in attrs

    pos = _read_accessor(doc, blob, attrs["POSITION"])
    assert len(pos) == 3
    assert pos[0] == (0.0, 0.0, 0.0)
    assert pos[1] == (1.0, 0.0, 0.0)
    assert pos[2] == (0.0, 1.0, 0.0)
    # POSITION accessors must carry min/max per spec
    acc = doc["accessors"][attrs["POSITION"]]
    assert acc["min"] == [0.0, 0.0, 0.0]
    assert acc["max"] == [1.0, 1.0, 0.0]

    # half2 ST round trips through float32
    uv = _read_accessor(doc, blob, attrs["TEXCOORD_0"])
    assert uv[0] == (0.0, 0.0)
    assert uv[2] == (1.0, 1.0)

    # uchar4 colors normalized to 0..1 floats
    col = _read_accessor(doc, blob, attrs["COLOR_0"])
    assert col[0] == (1.0, 0.0, 0.0, 1.0)
    assert col[2] == (0.0, 0.0, 1.0, 1.0)

    idx = _read_accessor(doc, blob, prim["indices"])
    assert len(idx) == 3 and idx[0][0] == 0


def test_gltf_float4_st_splits_into_two_uv_sets(tmp_path, car_pssg_path):
    out, doc, blob = _export(tmp_path, car_pssg_path)

    seat = next(m for m in doc["meshes"] if m["name"] == "seatmesh")
    attrs = seat["primitives"][0]["attributes"]
    assert "TEXCOORD_0" in attrs and "TEXCOORD_1" in attrs
    uv1 = _read_accessor(doc, blob, attrs["TEXCOORD_1"])
    assert uv1[0] == (0.5, 0.5)


def test_gltf_shared_rds_subset(tmp_path, car_pssg_path):
    out, doc, blob = _export(tmp_path, car_pssg_path)

    wheel = next(m for m in doc["meshes"] if m["name"] == "wheel_fl")
    prim = wheel["primitives"][0]
    pos = _read_accessor(doc, blob, prim["attributes"]["POSITION"])
    # subset indices[3:6] of the shared blob -> verts 1,2,3
    assert len(pos) == 3
    assert pos[0] == (1.0, 0.0, 0.0)
    assert pos[2] == (1.0, 1.0, 0.0)


def test_gltf_materials_and_png_textures(tmp_path, car_pssg_path):
    imagecodecs = pytest.importorskip("imagecodecs")

    out, doc, blob = _export(tmp_path, car_pssg_path)

    # s_car binds diffuse + normal via fixture SHADERINPUTs
    s_car = next(m for m in doc["materials"] if m["name"] == "s_car")
    pbr = s_car["pbrMetallicRoughness"]
    assert "baseColorTexture" in pbr and "normalTexture" in s_car

    # images point at PNG files that must exist on disk
    assert doc["images"], "expected PNG images for decodable textures"
    for img in doc["images"]:
        assert img["uri"].startswith("textures/")
        path = os.path.join(out, img["uri"])
        assert os.path.isfile(path) and os.path.getsize(path) > 8
        with open(path, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"


def test_gltf_neg_z_option(tmp_path, car_pssg_path):
    out, doc, blob = _export(tmp_path, car_pssg_path, "--neg-z")

    body = next(m for m in doc["meshes"] if m["name"] == "body")
    pos = _read_accessor(doc, blob, body["primitives"][0]["attributes"]["POSITION"])
    assert pos[2][2] == pytest.approx(-0.0, abs=1e-6) or pos[2][2] == 0.0
    # winding reversed: first triangle indices become (0, 2, 1)
    idx = _read_accessor(doc, blob, body["primitives"][0]["indices"])
    assert idx == [(0,), (2,), (1,)]


# ---------------------------------------------------------------------------
# unit tests: convention binder + nmap swizzle


def test_bind_material_convention():
    from pssg_convert.gltf import bind_material

    ids = ["131_main_d.tga", "131_main_n.tga", "131_main_s.tga",
           "131_main_o.tga", "131_lights_d.tga", "131_lights_on.tga"]
    b = bind_material("bodywork", ids)
    assert b["diffuse"] == "131_main_d.tga"
    assert b["normal"] == "131_main_n.tga"
    assert b["occlusion"] == "131_main_o.tga"
    assert "emissive" not in b

    lights = bind_material("lights_alpha", ids)
    assert lights["diffuse"] == "131_lights_d.tga"
    assert lights["emissive"] == "131_lights_on.tga"

    assert bind_material("unknown_shader", ids) == {}
    assert bind_material("bodywork", []) == {}


def test_dxt5_nmap_swizzle():
    imagecodecs = pytest.importorskip("imagecodecs")
    import numpy as np

    from _fixture import texture_element
    from pssg_convert.gltf import texture_to_png_bytes

    # 4x4 BC3 encoding a flat DXT5nmap.  imagecodecs expects the alpha block
    # first, then the color block (matching real DR2 DXT5 data).  alpha block
    # a0=a1=128 (X flat), color block c0=c1=RGB565 green ~128 (Y flat) -> Z~255.
    alpha = struct.pack("<BB", 128, 128) + bytes(6)
    color = struct.pack("<HHI", 1024, 1024, 0)   # c0=c1=32<<5, indices 0
    tex = texture_element("panel_n.tga", "dxt5", 4, 4, alpha + color)
    png = texture_to_png_bytes(tex)
    assert png is not None
    rgba = np.asarray(imagecodecs.png_decode(png))
    assert rgba.shape == (4, 4, 4)
    # reconstructed Z (blue) must dominate; X (red) ~ 128
    assert rgba[..., 2].mean() > 200
    assert 100 < rgba[..., 0].mean() < 160


def test_u8_texture_decode():
    imagecodecs = pytest.importorskip("imagecodecs")
    import numpy as np

    from _fixture import texture_element
    from pssg_convert.gltf import texture_to_png_bytes

    tex = texture_element("mask.tga", "u8", 4, 4, bytes(range(16)))
    png = texture_to_png_bytes(tex)
    assert png is not None
    rgba = np.asarray(imagecodecs.png_decode(png))
    assert rgba.shape == (4, 4, 4)
    assert rgba[0, 0, 0] == 0
    assert rgba[3, 3, 0] == 15
