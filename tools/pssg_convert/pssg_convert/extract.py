"""PSSG model extraction.

Faithful port of EgoEngineLibrary.Formats.Pssg.RenderDataSourceReader and the
car model traversal in CarInteriorPssgGltfConverter / PssgGltfConverter (MIT).

Operates on a pssg_unpack.PssgFile (already parsed).  Resolves referenced
objects by their string ``id`` attribute, decodes vertex/index buffers, and
walks the scene node tree to produce per-mesh primitives plus shader->texture
bindings.  Emits plain, dependency-free mesh data for downstream OBJ writers.
"""

from __future__ import annotations

import struct

from pssg_unpack import PssgElement, PssgFile


class PssgConvertError(Exception):
    pass


# ---------------------------------------------------------------------------
# helpers


def _attr(elem, name, default=None):
    for a in elem.attributes:
        if a.name == name:
            return a.value
    return default


def _attr_str(elem, name, default=""):
    v = _attr(elem, name, default)
    if isinstance(v, bytes):
        # Schema-type mismatches surface as raw bytes (size-authoritative read).
        return v.decode("utf-8", errors="replace").rstrip("\x00")
    return v if isinstance(v, str) else str(v)


def _attr_int(elem, name, default=0):
    v = _attr(elem, name, default)
    return int(v) if isinstance(v, (int, float)) else default


def _child(elem, name):
    for c in elem.children:
        if c.name == name:
            return c
    return None


def _children(elem, name):
    return [c for c in elem.children if c.name == name]


def _children_any(elem, names):
    names = set(names)
    return [c for c in elem.children if c.name in names]


def get_id(elem):
    return _attr_str(elem, "id", "")


class ObjectIndex:
    """Flat lookup of elements by their string ``id`` attribute."""

    def __init__(self, root):
        self._objects = {}
        for el in root.iter_all():
            ident = get_id(el)
            if ident:
                self._objects.setdefault(ident, el)

    def get(self, ref):
        ref = ref[1:] if ref.startswith("#") else ref
        return self._objects.get(ref)


def resolve_ref(elem, ref, index):
    if not ref or ref == "#":
        raise PssgConvertError(f"{elem.name} has an empty reference")
    if not ref.startswith("#"):
        raise PssgConvertError(
            f"{elem.name} references '{ref}' which points outside this pssg file")
    target = index.get(ref)
    if target is None:
        raise PssgConvertError(f"object '{ref}' referenced by {elem.name} not found")
    return target


# ---------------------------------------------------------------------------
# binary primitives (all big-endian)


_F32 = struct.Struct(">f")
_U16 = struct.Struct(">H")
_U32 = struct.Struct(">I")


def _read_f32(data, off):
    return _F32.unpack_from(data, off)[0]


def _read_u16(data, off):
    return _U16.unpack_from(data, off)[0]


def _read_u32(data, off):
    return _U32.unpack_from(data, off)[0]


def _half_to_float(h):
    s = (h >> 15) & 0x1
    e = (h >> 10) & 0x1F
    m = h & 0x3FF
    if e == 0:
        val = (m * 2 ** -24) if m != 0 else 0.0
    elif e != 31:
        val = (1 + m / 1024.0) * 2 ** (e - 15)
    else:
        val = float("inf") if m == 0 else float("nan")
    return -val if s else val


def _read_vec3_f32(data, off):
    return (_read_f32(data, off), _read_f32(data, off + 4), _read_f32(data, off + 8))


def _read_vec3_half(data, off):
    return (_half_to_float(_read_u16(data, off)),
            _half_to_float(_read_u16(data, off + 2)),
            _half_to_float(_read_u16(data, off + 4)))


def _read_hend3n(data, off):
    """11 11 10 bit signed packed normal."""
    i = _read_u32(data, off)
    y = i >> 11
    z = i >> 22
    x = (((i & 0x7FF) << 21) >> 21) / float(0x3FF)
    yy = (((y & 0x7FF) << 21) >> 21) / float(0x3FF)
    zz = (((z & 0x3FF) << 22) >> 22) / float(0x1FF)
    return (x, yy, zz)


def _unpack_argb(color):
    return ((color >> 8) & 0xFF) / 255.0, \
           ((color >> 16) & 0xFF) / 255.0, \
           ((color >> 24) & 0xFF) / 255.0, \
           ((color >> 0) & 0xFF) / 255.0


def _unpack_rgba(color):
    return ((color >> 0) & 0xFF) / 255.0, \
           ((color >> 8) & 0xFF) / 255.0, \
           ((color >> 16) & 0xFF) / 255.0, \
           ((color >> 24) & 0xFF) / 255.0


def _index_stride(index_format):
    if index_format == "ushort":
        return 2
    if index_format == "uint":
        return 4
    raise PssgConvertError(f"index format '{index_format}' not implemented")


# ---------------------------------------------------------------------------
# RenderDataSourceReader (vertex/index decoding)


class VertexAttribute:
    __slots__ = ("name", "data_type", "element_count", "offset", "stride", "data")

    def __init__(self, name, data_type, element_count, offset, stride, data):
        self.name = name
        self.data_type = data_type
        self.element_count = element_count
        self.offset = offset
        self.stride = stride
        self.data = data


class RenderDataSourceReader:
    def __init__(self, rds, index):
        index_source = _child(rds, "RENDERINDEXSOURCE")
        if index_source is None:
            raise PssgConvertError(
                f"RENDERDATASOURCE '{get_id(rds)}' must have RENDERINDEXSOURCE "
                f"as its first child")

        self.index_format = _attr_str(index_source, "format")
        self.index_stride = _index_stride(self.index_format)
        self.primitive = _attr_str(index_source, "primitive")
        self.index_count = _attr_int(index_source, "count")
        index_data_el = _child(index_source, "INDEXSOURCEDATA")
        self.index_data = index_data_el.value if index_data_el is not None else b""

        self.vertex_attributes = {}
        self.tex_coord_sets = []
        self.vertex_count = 0

        for stream in _children(rds, "RENDERSTREAM"):
            block_ref = _attr_str(stream, "dataBlock")
            sub_stream = _attr_int(stream, "subStream", 0)
            db = resolve_ref(stream, block_ref, index)
            db_streams = _children(db, "DATABLOCKSTREAM")
            if sub_stream >= len(db_streams):
                raise PssgConvertError(
                    f"dataBlock '{get_id(db)}' has no substream #{sub_stream}")
            db_stream = db_streams[sub_stream]

            size = _attr_int(db, "size")
            elem_count = _attr_int(db, "elementCount")
            dd = _child(db, "DATABLOCKDATA")
            data = dd.value if (dd is not None and dd.is_data) else b""
            if len(data) != size:
                raise PssgConvertError(
                    f"data block size ({size}) differs from data ({len(data)})")

            render_type = _attr_str(db_stream, "renderType")
            offset = _attr_int(db_stream, "offset")
            stride = _attr_int(db_stream, "stride")
            data_type = _attr_str(db_stream, "dataType")

            attr = VertexAttribute(render_type, data_type, elem_count, offset,
                                   stride, data)
            if attr.name == "ST":
                self.tex_coord_sets.extend(self._split_st(attr))
            else:
                self.vertex_attributes[attr.name] = attr
                if attr.name == "Vertex":
                    self.vertex_count = attr.element_count

    @staticmethod
    def _split_st(attr):
        t = attr.data_type
        if t in ("float2", "half2"):
            return [attr]
        if t in ("float4", "half4"):
            # second set begins at offset + vec2 size (4 bytes for half2,
            # 8 bytes for float2)
            base = "float" if t == "float4" else "half"
            inner = 4 if t == "half4" else 8
            a1 = VertexAttribute(attr.name, base + "2", attr.element_count,
                                 attr.offset, attr.stride, attr.data)
            a2 = VertexAttribute(attr.name, base + "2", attr.element_count,
                                 attr.offset + inner, attr.stride, attr.data)
            return [a1, a2]
        raise PssgConvertError(f"unsupported ST data type '{t}'")

    @property
    def tex_coord_set_count(self):
        return len(self.tex_coord_sets)

    def get_triangles(self, start_index=0, index_count=None):
        if self.primitive != "triangles":
            raise PssgConvertError(
                f"primitive type '{self.primitive}' is not triangles")
        if index_count is None:
            index_count = self.index_count
        data = self.index_data[start_index * self.index_stride:
                               (start_index + index_count) * self.index_stride]
        stride = self.index_stride
        for i in range(index_count // 3):
            off = i * stride * 3
            if stride == 2:
                yield (_read_u16(data, off), _read_u16(data, off + 2),
                       _read_u16(data, off + 4))
            else:
                yield (_read_u32(data, off), _read_u32(data, off + 4),
                       _read_u32(data, off + 8))

    def _loc(self, name):
        attr = self.vertex_attributes.get(name)
        return attr

    def get_position(self, index):
        attr = self.vertex_attributes.get("Vertex")
        if attr is None:
            return (0.0, 0.0, 0.0)
        off = attr.stride * index + attr.offset
        t = attr.data_type
        if t == "float3":
            return _read_vec3_f32(attr.data, off)
        if t == "half4":
            return _read_vec3_half(attr.data, off)
        raise PssgConvertError(f"unhandled Vertex data type '{t}'")

    def get_normal(self, index):
        attr = self.vertex_attributes.get("Normal")
        if attr is None:
            return (0.0, 0.0, 0.0)
        off = attr.stride * index + attr.offset
        t = attr.data_type
        if t == "float3":
            return _read_vec3_f32(attr.data, off)
        if t == "half4":
            return _read_vec3_half(attr.data, off)
        if t == "hend3n":
            return _read_hend3n(attr.data, off)
        raise PssgConvertError(f"unhandled Normal data type '{t}'")

    def get_tex_coord(self, index, set_index):
        if 0 <= set_index < len(self.tex_coord_sets):
            attr = self.tex_coord_sets[set_index]
        else:
            if set_index <= 0:
                return (0.0, 0.0)
            return self.get_tex_coord(index, len(self.tex_coord_sets) - 1)
        off = attr.stride * index + attr.offset
        t = attr.data_type
        if t in ("half2", "half4"):
            return (_half_to_float(_read_u16(attr.data, off)),
                    _half_to_float(_read_u16(attr.data, off + 2)))
        if t in ("float2", "float4"):
            return (_read_f32(attr.data, off), _read_f32(attr.data, off + 4))
        raise PssgConvertError(f"unhandled ST data type '{t}'")

    def get_color(self, index):
        attr = self.vertex_attributes.get("Color")
        if attr is None:
            return (1.0, 1.0, 1.0, 1.0)
        off = attr.stride * index + attr.offset
        t = attr.data_type
        if t == "uint_color_argb":
            return _unpack_argb(_read_u32(attr.data, off))
        if t == "uchar4":
            return _unpack_rgba(_read_u32(attr.data, off))
        raise PssgConvertError(f"unhandled Color data type '{t}'")


# ---------------------------------------------------------------------------
# scene traversal -> mesh primitives


class MeshPrimitive:
    __slots__ = ("node_name", "node_id", "shader_id", "positions", "normals",
                 "colors", "uv_sets", "triangles")

    def __init__(self, node_name, node_id, shader_id):
        self.node_name = node_name
        self.node_id = node_id
        self.shader_id = shader_id
        self.positions = []
        self.normals = []
        self.colors = []
        self.uv_sets = []
        self.triangles = []

    def vertex_count(self):
        return len(self.positions)


_NODE_TYPE_NAMES = frozenset({
    "NODE",
    "ROOTNODE",
    "VISIBLERENDERNODE",
    "RENDERNODE",
    "MATRIXPALETTENODE",
    "MATRIXPALETTEJOINTNODE",
    "MATRIXPALETTEBUNDLENODE",
})

_RENDER_NODE_NAMES = frozenset({
    "RENDERNODE",
    "VISIBLERENDERNODE",
    "MATRIXPALETTEJOINTNODE",
})


def collect_meshes(root, index, node_predicate=None):
    """Walk the scene NODE libraries and convert render nodes to primitives.

    Mirrors CarInteriorPssgGltfConverter.Convert / CarExteriorPssgGltfConverter:
    find a LIBRARY of type NODE (or YYY for F1) and recurse its PssgNode
    children; render nodes are converted to meshes, other nodes are descended.
    """
    library = _find_node_library(root)
    if library is None:
        raise PssgConvertError("could not find NODE (or YYY) library")

    if node_predicate is None:
        node_predicate = lambda elem: True
    meshes = []

    def walk(node):
        for child in node.children:
            if child.name in _NODE_TYPE_NAMES:
                if child.name in _RENDER_NODE_NAMES and node_predicate(child):
                    meshes.extend(_convert_node(child, index))
                walk(child)

    for child in library.children:
        if child.name in _NODE_TYPE_NAMES:
            walk(child)
    return meshes


def _find_node_library(root):
    node_lib = None
    yyy_lib = None
    for el in root.iter_all():
        if el.name == "LIBRARY":
            t = _attr_str(el, "type", "")
            if t == "NODE" and node_lib is None:
                node_lib = el
            elif t == "YYY" and yyy_lib is None:
                yyy_lib = el
    return node_lib if node_lib is not None else yyy_lib


RENDER_STREAM_INSTANCE_NAMES = (
    "RENDERSTREAMINSTANCE",
    "MATRIXPALETTERENDERINSTANCE",
    "MATRIXPALETTEJOINTRENDERINSTANCE",
)


def _convert_node(node, index):
    outs = []
    for instance in _children_any(node, RENDER_STREAM_INSTANCE_NAMES):
        shader_ref = _attr_str(instance, "shader")
        shader = index.get(shader_ref)
        shader_id = get_id(shader) if shader is not None else shader_ref

        rds_ref = _attr_str(instance, "indices")
        rds = index.get(rds_ref)
        if rds is None:
            raise PssgConvertError(
                f"RENDERSTREAMINSTANCE '{get_id(node)}' refs '{rds_ref}' not found")
        reader = RenderDataSourceReader(rds, index)

        start = _attr_int(instance, "indexOffset", 0)
        count_attr = _attr_int(instance, "indicesCountFromOffset", -1)
        index_count = reader.index_count - start if count_attr < 0 else count_attr

        prim = MeshPrimitive(get_id(node), get_id(node), shader_id)
        for a, b, c in reader.get_triangles(start, index_count):
            prim.positions.append(reader.get_position(a))
            prim.positions.append(reader.get_position(b))
            prim.positions.append(reader.get_position(c))
            prim.normals.append(reader.get_normal(a))
            prim.normals.append(reader.get_normal(b))
            prim.normals.append(reader.get_normal(c))
            prim.colors.append(reader.get_color(a))
            prim.colors.append(reader.get_color(b))
            prim.colors.append(reader.get_color(c))
            for s in range(reader.tex_coord_set_count):
                while len(prim.uv_sets) <= s:
                    prim.uv_sets.append([])
                prim.uv_sets[s].extend([reader.get_tex_coord(a, s),
                                        reader.get_tex_coord(b, s),
                                        reader.get_tex_coord(c, s)])
            base = len(prim.positions) - 3
            prim.triangles.append((base, base + 1, base + 2))
        if prim.triangles:
            outs.append(prim)
    return outs