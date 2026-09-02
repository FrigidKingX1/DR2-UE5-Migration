"""Synthetic PSSG fixture for pssg_convert tests.

Builds a small car-style EGO scene (NODE library) with:
  - one RENDERNODE mesh (ushort indices, float3 pos + normal, half2 ST,
    uchar4 color) bound to a SHADERINSTANCE -> TDiffuseAlphaMap texture
  - one VISIBLERENDERNODE mesh with float4 ST (split into two uv sets)
  - one MATRIXPALETTEJOINTNODE mesh using a shared RENDERDATASOURCE plus
    indexOffset / indicesCountFromOffset (exterior SUV path)
  - two 2D textures (dxt1 + u8) and a cube map (dxt5)
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_TOOLS, "pssg_unpack"))
sys.path.insert(0, os.path.dirname(_TOOLS))

from pssg_unpack import PssgAttribute, PssgElement, PssgFile, write_pssg
from pssg_unpack.constants import (
    ATTR_FLOAT3,
    ATTR_INT,
    ATTR_STRING,
)


def s(name, value):
    return PssgAttribute(name, ATTR_STRING, 0, value)


def i(name, value):
    return PssgAttribute(name, ATTR_INT, 0, value)


def f3(name, *value):
    return PssgAttribute(name, ATTR_FLOAT3, 0, tuple(value))


def half(v):
    return struct.pack(">e", v)


def stream_instance(node_id, rds_ref, shader_ref, subset=None):
    inst = PssgElement(name="RENDERSTREAMINSTANCE")
    inst.attributes.append(s("id", node_id))
    inst.attributes.append(i("sourceCount", 1))
    inst.attributes.append(s("indices", rds_ref))
    inst.attributes.append(s("shader", shader_ref))
    if subset is not None:
        offset, count = subset
        inst.attributes.append(i("indexOffset", offset))
        inst.attributes.append(i("indicesCountFromOffset", count))
    return inst


def datablock(obj_id, streams, data, element_count):
    """streams: list of (renderType, offset, stride, dataType)."""
    db = PssgElement(name="DATABLOCK")
    db.attributes.append(s("id", obj_id))
    db.attributes.append(i("size", len(data)))
    db.attributes.append(i("elementCount", element_count))
    db.attributes.append(i("streamCount", len(streams)))
    for render_type, offset, stride, data_type in streams:
        st = PssgElement(name="DATABLOCKSTREAM")
        st.attributes.append(s("renderType", render_type))
        st.attributes.append(i("offset", offset))
        st.attributes.append(i("stride", stride))
        st.attributes.append(s("dataType", data_type))
        db.children.append(st)
    dd = PssgElement(name="DATABLOCKDATA", is_data=True, value=data)
    db.children.append(dd)
    return db


def rds_element(obj_id, index_format, primitive, index_data):
    rds = PssgElement(name="RENDERDATASOURCE")
    rds.attributes.append(s("id", obj_id))
    ris = PssgElement(name="RENDERINDEXSOURCE")
    ris.attributes.append(s("format", index_format))
    ris.attributes.append(s("primitive", primitive))
    ris.attributes.append(i("count", len(index_data) // (2 if index_format == "ushort" else 4)))
    ris.attributes.append(i("minimumIndex", 0))
    ris.attributes.append(i("maximumIndex", 0xFFFF))
    data = PssgElement(name="INDEXSOURCEDATA", is_data=True, value=index_data)
    ris.children.append(data)
    rds.children.append(ris)
    return rds


def rds_stream(db_id, substream):
    rs = PssgElement(name="RENDERSTREAM")
    rs.attributes.append(s("dataBlock", "#" + db_id))
    rs.attributes.append(i("subStream", substream))
    return rs


def rds_with_streams(obj_id, index_format, primitive, index_data, streams):
    rds = rds_element(obj_id, index_format, primitive, index_data)
    for db_id, substream in streams:
        rds.children.append(rds_stream(db_id, substream))
    return rds


def texture_element(obj_id, texel_format, width, height, image_data, mip_levels=0,
                    image_block_count=0, blocks=None):
    tex = PssgElement(name="TEXTURE")
    tex.attributes.append(s("id", obj_id))
    tex.attributes.append(i("width", width))
    tex.attributes.append(i("height", height))
    tex.attributes.append(s("texelFormat", texel_format))
    tex.attributes.append(i("automipmap", 0))
    tex.attributes.append(i("numberMipMapLevels", mip_levels))
    tex.attributes.append(i("imageBlockCount", image_block_count))
    if image_block_count > 0:
        for face_type, face_data in blocks:
            block = PssgElement(name="TEXTUREIMAGEBLOCK")
            block.attributes.append(s("type", face_type))
            face = PssgElement(name="TEXTUREIMAGEBLOCKDATA", is_data=True,
                               value=face_data)
            block.children.append(face)
            tex.children.append(block)
    else:
        img = PssgElement(name="TEXTUREIMAGE", is_data=True, value=image_data)
        tex.children.append(img)
    return tex


def shader_group(obj_id, *input_names):
    sg = PssgElement(name="SHADERGROUP")
    sg.attributes.append(s("id", obj_id))
    for n in input_names:
        d = PssgElement(name="SHADERINPUTDEFINITION")
        d.attributes.append(s("name", n))
        d.attributes.append(s("type", "texture"))
        d.attributes.append(s("format", "dxt"))
        d.attributes.append(i("parameterID", 0))
        sg.children.append(d)
    return sg


def shader_instance(obj_id, group_ref, inputs):
    si = PssgElement(name="SHADERINSTANCE")
    si.attributes.append(s("id", obj_id))
    si.attributes.append(s("shaderGroup", "#" + group_ref))
    for _name, param_id, tex_ref in inputs:
        inp = PssgElement(name="SHADERINPUT", is_data=True, value=b"")
        inp.attributes.append(i("parameterID", param_id))
        inp.attributes.append(s("type", "texture"))
        inp.attributes.append(s("texture", tex_ref))
        si.children.append(inp)
    return si


def build_car() -> PssgFile:
    root = PssgElement(name="PSSGDATABASE")
    root.attributes.append(s("id", "fixture"))
    root.attributes.append(i("count", 8))

    lib = PssgElement(name="LIBRARY")
    lib.attributes.append(s("type", "NODE"))
    lib.attributes.append(s("name", "scene"))
    root.children.append(lib)

    # -------- node tree --------
    chassis = PssgElement(name="NODE")
    chassis.attributes.append(s("id", "chassis"))
    lib.children.append(chassis)

    body = PssgElement(name="RENDERNODE")
    body.attributes.append(s("id", "body"))
    body.attributes.append(f3("scale", 1.0, 1.0, 1.0))
    body.children.append(stream_instance("bpaint", "#rds_body", "#s_car"))
    chassis.children.append(body)

    seat = PssgElement(name="NODE")
    seat.attributes.append(s("id", "seat"))
    vis = PssgElement(name="VISIBLERENDERNODE")
    vis.attributes.append(s("id", "seatmesh"))
    vis.children.append(stream_instance("seatmat", "#rds_seat", "#s_seat"))
    seat.children.append(vis)
    chassis.children.append(seat)

    wheel_root = PssgElement(name="MATRIXPALETTENODE")
    wheel_root.attributes.append(s("id", "skeleton"))
    wheel = PssgElement(name="MATRIXPALETTEJOINTNODE")
    wheel.attributes.append(s("id", "wheel_fl"))
    wheel.children.append(stream_instance("wheelmat", "#rds_shared", "#s_wheel",
                                          subset=(3, 3)))
    wheel_root.children.append(wheel)
    lib.children.append(wheel_root)

    # -------- body mesh: pos(float3) + normal(float3) + ST(half2) + color --------
    stride = 12 + 12 + 4 + 4
    body_pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    body_nrm = [(0.0, 0.0, 1.0)] * 3
    body_uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    body_col = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]
    body_blob = bytearray()
    for p, n, uv, c in zip(body_pos, body_nrm, body_uv, body_col):
        body_blob += struct.pack(">3f", *p)
        body_blob += struct.pack(">3f", *n)
        body_blob += half(uv[0]) + half(uv[1])
        body_blob += struct.pack(">4B", *c)
    body_db = datablock(
        "db_body",
        [("Vertex", 0, stride, "float3"),
         ("Normal", 12, stride, "float3"),
         ("ST", 24, stride, "half2"),
         ("Color", 28, stride, "uchar4")],
        bytes(body_blob), 3)
    root.children.append(body_db)

    body_idx = struct.pack(">3H", 0, 1, 2)
    body_rds = rds_with_streams(
        "rds_body", "ushort", "triangles", body_idx,
        [("db_body", 0), ("db_body", 1), ("db_body", 2), ("db_body", 3)])
    root.children.append(body_rds)

    # -------- seat mesh: pos(float3) + ST(float4 -> two uv sets) --------
    seat_stride = 12 + 16
    seat_pos = [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 1.0, 0.0)]
    seat_uv = [(0.0, 0.0, 0.5, 0.5), (1.0, 0.0, 0.5, 0.5), (1.0, 1.0, 0.5, 0.5)]
    seat_blob = bytearray()
    for p, uv4 in zip(seat_pos, seat_uv):
        seat_blob += struct.pack(">3f", *p)
        seat_blob += struct.pack(">4f", *uv4)
    seat_db = datablock(
        "db_seat",
        [("Vertex", 0, seat_stride, "float3"),
         ("ST", 12, seat_stride, "float4")],
        bytes(seat_blob), 3)
    root.children.append(seat_db)

    seat_idx = struct.pack(">3H", 0, 1, 2)
    seat_rds = rds_with_streams(
        "rds_seat", "ushort", "triangles", seat_idx,
        [("db_seat", 0), ("db_seat", 1)])
    root.children.append(seat_rds)

    # -------- shared wheel mesh: 6 verts, 9 indices, subset (3,3) used --------
    wheel_pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                 (1.0, 1.0, 0.0), (2.0, 0.0, 0.0), (2.0, 1.0, 0.0)]
    wheel_blob = bytearray()
    for p in wheel_pos:
        wheel_blob += struct.pack(">3f", *p)
    wheel_db = datablock("db_shared",
                         [("Vertex", 0, 12, "float3")],
                         bytes(wheel_blob), 6)
    root.children.append(wheel_db)

    wheel_idx = struct.pack(">9H", 0, 1, 2, 1, 2, 3, 2, 3, 4)
    wheel_rds = rds_with_streams(
        "rds_shared", "ushort", "triangles", wheel_idx, [("db_shared", 0)])
    root.children.append(wheel_rds)

    # -------- materials --------
    sg_car = shader_group("sg_car", "TDiffuseAlphaMap", "TNormalMap")
    sg_seat = shader_group("sg_seat", "TDiffuseAlphaMap")
    sg_wheel = shader_group("sg_wheel", "TSpecularMap")
    root.children.extend([sg_car, sg_seat, sg_wheel])

    si_car = shader_instance("s_car", "sg_car", [("paint", 0, "#tex_body_paint"),
                                                 ("norm", 1, "#tex_body_normal")])
    si_seat = shader_instance("s_seat", "sg_seat", [("seat", 0, "#tex_seat")])
    si_wheel = shader_instance("s_wheel", "sg_wheel", [("wheel", 0, "#tex_wheel")])
    root.children.extend([si_car, si_seat, si_wheel])

    # -------- textures --------
    tex_paint = texture_element("tex_body_paint", "dxt1", 4, 4, b"\x88" * 8)
    tex_normal = texture_element("tex_body_normal", "dxt5", 4, 4, b"\x77" * 16)
    tex_seat = texture_element("tex_seat", "u8", 4, 4, bytes(range(16)))
    tex_wheel = texture_element("tex_wheel", "dxt5", 4, 4, b"\xaa" * 16)
    root.children.extend([tex_paint, tex_normal, tex_seat, tex_wheel])

    cubefaces = ["Raw", "RawNegativeX", "RawPositiveY", "RawNegativeY",
                 "RawPositiveZ", "RawNegativeZ"]
    tex_cube = texture_element(
        "tex_env", "dxt5", 2, 2, b"", image_block_count=6,
        blocks=[(name, bytes([i] * 4)) for i, name in enumerate(cubefaces)])
    root.children.append(tex_cube)

    return PssgFile(file_size=0, root=root)


def write_fixture(path) -> None:
    blob = write_pssg(build_car())
    with open(path, "wb") as fh:
        fh.write(blob)