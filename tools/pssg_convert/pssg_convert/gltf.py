"""glTF 2.0 exporter for pssg_convert.

Writes ``.gltf`` + ``.bin`` + PNG textures (external files), suitable for
drag-and-drop import into Unreal Engine 5 (Interchange) and standard glTF
viewers.

Texture handling
----------------
glTF cannot carry DDS payloads, so textures are decoded to RGBA8 PNG via
``imagecodecs`` (BC1/BC2/BC3/BC7).  Without ``imagecodecs`` the exporter still
writes the document but leaves texture slots unbound (reported in the
manifest).  DXT5 normal maps (``_n`` ids) are re-swizzled from the DXT5nmap
convention (X in alpha, Y in green) to RGB.

Material binding
----------------
Two paths, in order:
1. Explicit: SHADERINSTANCE texture inputs resolved through TextureResolver
   (same-file ``#ref`` textures).
2. Conventional (real DR2 cars): exterior shaders carry no texture inputs;
   textures bind by naming convention from a texture-container PSSG:
   ``<car>_<part><suffix>.tga`` where the part alias maps shader ids
   (``bodywork`` -> ``main`` ...) and the suffix maps the slot
   (``_d`` diffuse, ``_n`` normal, ``_s`` specular, ``_o`` occlusion,
   ``_on`` emissive).

Coordinates are passed through unchanged from the PSSG (EGO is Y-up like
glTF); the ``--neg-z`` flag applies the D3D left-handed -> glTF right-handed
conversion (negate Z, reverse triangle winding) for content that needs it.
"""

from __future__ import annotations

import json
import os
import struct

from pssg_unpack import PssgElement

from .extract import ObjectIndex, _attr_int, _attr_str, get_id

try:
    import imagecodecs

    _BCN = {
        "dxt1": imagecodecs.BCN.FORMAT.BC1,
        "dxt3": imagecodecs.BCN.FORMAT.BC2,
        "dxt5": imagecodecs.BCN.FORMAT.BC3,
        "bc7": imagecodecs.BCN.FORMAT.BC7,
    }
except Exception:  # pragma: no cover - optional dependency
    imagecodecs = None
    _BCN = {}

SUFFIX_BY_SLOT = {
    "diffuse": "_d",
    "specular": "_s",
    "normal": "_n",
    "occlusion": "_o",
    "emissive": "_on",
}

# shader id -> texture part alias used in car texture containers
PART_ALIASES = {
    "bodywork": ["main"],
    "cabin": ["cabin"],
    "interior": ["cabin"],
    "glass_exterior": ["glass"],
    "glass_interior": ["glass"],
    "rear_glass_interior": ["glass"],
    "caliper": ["caliper"],
    "discs": ["disc"],
    "car_disc_blur": ["disc"],
    "lights_opaque": ["lights"],
    "lights_alpha": ["lights"],
}

NORMAL_SUFFIX = "_n"


class GltfExportError(Exception):
    pass


# ---------------------------------------------------------------------------
# texture decode


def _texture_data(texel: PssgElement):
    """Return (width, height, texel_format, mip0_bytes) for a TEXTURE element."""
    width = _attr_int(texel, "width", 0)
    height = _attr_int(texel, "height", 0)
    fmt = _attr_str(texel, "texelFormat", "")
    blob = None
    for block in texel.children:
        if block.name != "TEXTUREIMAGEBLOCK":
            continue
        data_el = None
        for c in block.children:
            if c.is_data:
                data_el = c
                break
        if data_el is not None and data_el.value:
            blob = data_el.value
            break
    if blob is None:
        img = None
        for c in texel.children:
            if c.name == "TEXTUREIMAGE" and c.is_data:
                img = c
                break
        if img is not None:
            blob = img.value
    if width <= 0 or height <= 0 or blob is None:
        return None
    return width, height, fmt.lower(), blob


def _mip0_size(width: int, height: int, fmt: str) -> int:
    fmt = fmt.replace("_srgb", "")
    if fmt == "u8":
        return width * height
    if fmt in ("ui8x4", "rgba8"):
        return width * height * 4
    blocks = ((width + 3) // 4) * ((height + 3) // 4)
    if fmt in ("dxt1", "bc1"):
        return blocks * 8
    if fmt in ("dxt3", "bc2", "dxt5", "bc3", "bc5", "bc7"):
        return blocks * 16
    return 0


def texture_to_png_bytes(texel: PssgElement):
    """Decode a TEXTURE element's mip 0 to PNG bytes (RGBA8).  None if unable."""
    parsed = _texture_data(texel)
    if parsed is None or imagecodecs is None:
        return None
    width, height, fmt, blob = parsed
    size = _mip0_size(width, height, fmt)
    if size == 0 or len(blob) < size:
        return None
    mip0 = blob[:size]

    # sRGB variants share the block encoding; the suffix only marks gamma.
    bcn = _BCN.get(fmt.replace("_srgb", ""))
    if bcn is not None:
        try:
            rgba = imagecodecs.bcn_decode(mip0, bcn, shape=(height, width, 4))
        except Exception:
            return None
        arr = _as_rgba(rgba, fmt, texel)
    elif fmt == "u8":
        import numpy as np

        g = np.frombuffer(mip0, dtype=np.uint8, count=width * height)
        arr = np.empty((height, width, 4), dtype=np.uint8)
        arr[..., 0] = arr[..., 1] = arr[..., 2] = g.reshape(height, width)
        arr[..., 3] = 255
    elif fmt in ("ui8x4", "rgba8"):
        import numpy as np

        raw = np.frombuffer(mip0, dtype=np.uint8, count=width * height * 4)
        arr = raw.reshape(height, width, 4)
    else:
        return None

    try:
        return imagecodecs.png_encode(arr)
    except Exception:
        return None


def _as_rgba(rgba, fmt: str, texel: PssgElement):
    """Apply DXT5nmap swizzle for normal maps; pass everything else through."""
    import numpy as np

    ident = get_id(texel) or ""
    if isinstance(ident, bytes):
        ident = ident.decode("utf-8", "replace")
    stem = ident.rsplit(".", 1)[0]
    if fmt.startswith("dxt5") and stem.endswith(NORMAL_SUFFIX):
        # DXT5nmap: X in alpha, Y in green -> rebuild RGB
        x = rgba[..., 3].astype(np.float32) / 255.0 * 2.0 - 1.0
        y = rgba[..., 1].astype(np.float32) / 255.0 * 2.0 - 1.0
        z = np.sqrt(np.clip(1.0 - x * x - y * y, 0.0, 1.0))
        out = np.empty_like(rgba)
        out[..., 0] = ((x * 0.5 + 0.5) * 255.0).astype(np.uint8)
        out[..., 1] = ((y * 0.5 + 0.5) * 255.0).astype(np.uint8)
        out[..., 2] = ((z * 0.5 + 0.5) * 255.0).astype(np.uint8)
        out[..., 3] = 255
        return out
    return rgba


# ---------------------------------------------------------------------------
# material binding


def derive_car_prefix(texture_ids):
    """Derive the car prefix ('131' from '131_main_d.tga' style ids)."""
    prefixes = set()
    for tid in texture_ids:
        if isinstance(tid, bytes):
            tid = tid.decode("utf-8", "replace")
        head = tid.split("_", 1)[0]
        if head:
            prefixes.add(head)
    if len(prefixes) == 1:
        return next(iter(prefixes))
    return None


def bind_material(shader_id, texture_ids):
    """Convention-based binding: return {slot: texture_id} or {}."""
    aliases = PART_ALIASES.get(shader_id)
    if not aliases:
        return {}
    prefix = derive_car_prefix(texture_ids)
    if prefix is None:
        return {}
    lowered = {}
    for tid in texture_ids:
        key = tid.decode("utf-8", "replace") if isinstance(tid, bytes) else tid
        lowered[key.lower()] = key
    binding = {}
    for slot, suffix in SUFFIX_BY_SLOT.items():
        for alias in aliases:
            candidate = f"{prefix}_{alias}{suffix}.tga".lower()
            if candidate in lowered:
                binding[slot] = lowered[candidate]
                break
    return binding


# ---------------------------------------------------------------------------
# document assembly


class _Buffer:
    """Accumulates little-endian, 4-byte aligned bufferViews."""

    def __init__(self):
        self.data = bytearray()
        self.views = []

    def add(self, blob: bytes, target: int) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        offset = len(self.data)
        self.data += blob
        self.views.append({
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(blob),
            "target": target,
        })
        return len(self.views) - 1


def _vec2_blob(pairs):
    return b"".join(struct.pack("<2f", *p) for p in pairs)


def _vec3_blob(triples):
    return b"".join(struct.pack("<3f", *t) for t in triples)


def _vec4_blob(quads):
    return b"".join(struct.pack("<4f", *q) for q in quads)


def build_gltf(meshes, material_bindings, texture_pngs, neg_z=False):
    """Assemble the glTF document.

    meshes: list of MeshPrimitive (positions/normals/colors/uv_sets/triangles).
    material_bindings: {shader_id: {slot: texture_id}}.
    texture_pngs: {texture_id: png_bytes} for textures referenced by bindings.
    Returns (doc, bin_bytes) with images referencing files in 'textures/'.
    """
    buffer = _Buffer()
    accessors = []
    materials = []
    images = []
    textures = []
    samplers = [{"magFilter": 9729, "minFilter": 9987,
                 "wrapS": 10497, "wrapT": 10497}]

    def ensure_texture(texture_id):
        png = texture_pngs.get(texture_id)
        if png is None:
            return None
        fname = _safe(texture_id) + ".png"
        for i, img in enumerate(images):
            if img["uri"] == "textures/" + fname:
                return i
        images.append({"uri": "textures/" + fname})
        textures.append({"sampler": 0, "source": len(images) - 1})
        return len(textures) - 1

    def slot_index(binding, slot):
        tid = binding.get(slot)
        if tid is None:
            return None
        if tid in texture_pngs:
            return ensure_texture(tid)
        # Explicit refs often use the logical base name ('131_glass.tga')
        # while containers store suffixed ids ('131_glass_d.tga').
        stem, dot, ext = tid.rpartition(".")
        if dot:
            candidate = f"{stem}{SUFFIX_BY_SLOT[slot]}.{ext}"
            if candidate in texture_pngs:
                return ensure_texture(candidate)
        return None

    shader_ids = []
    for mesh in meshes:
        if mesh.shader_id not in shader_ids:
            shader_ids.append(mesh.shader_id)
    for shader_id in shader_ids:
        binding = material_bindings.get(shader_id, {})
        mat = {
            "name": _safe(shader_id or "material"),
            "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1],
                                     "metallicFactor": 0.0,
                                     "roughnessFactor": 0.5},
        }
        base = slot_index(binding, "diffuse")
        if base is not None:
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": base}
        normal = slot_index(binding, "normal")
        if normal is not None:
            mat["normalTexture"] = {"index": normal}
        occlusion = slot_index(binding, "occlusion")
        if occlusion is not None:
            mat["occlusionTexture"] = {"index": occlusion}
        emissive = slot_index(binding, "emissive")
        if emissive is not None:
            mat["emissiveTexture"] = {"index": emissive}
            mat["emissiveFactor"] = [1.0, 1.0, 1.0]
        materials.append(mat)
    material_index = {sid: i for i, sid in enumerate(shader_ids)}

    meshes_json = []
    nodes_json = []
    for i, mesh in enumerate(meshes):
        positions = mesh.positions
        normals = mesh.normals
        if neg_z:
            positions = [(x, y, -z) for (x, y, z) in positions]
            normals = [(x, y, -z) for (x, y, z) in normals]

        pos_blob = _vec3_blob(positions)
        pos_min = [min(p[0] for p in positions), min(p[1] for p in positions),
                   min(p[2] for p in positions)]
        pos_max = [max(p[0] for p in positions), max(p[1] for p in positions),
                   max(p[2] for p in positions)]
        pos_acc = {
            "bufferView": buffer.add(pos_blob, 34962),
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
            "min": pos_min,
            "max": pos_max,
        }
        accessors.append(pos_acc)
        attrs = {"POSITION": len(accessors) - 1}

        if normals:
            accessors.append({
                "bufferView": buffer.add(_vec3_blob(normals), 34962),
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            })
            attrs["NORMAL"] = len(accessors) - 1

        for s, uv in enumerate(mesh.uv_sets):
            accessors.append({
                "bufferView": buffer.add(_vec2_blob(uv), 34962),
                "componentType": 5126,
                "count": len(uv),
                "type": "VEC2",
            })
            attrs[f"TEXCOORD_{s}"] = len(accessors) - 1

        if mesh.colors:
            accessors.append({
                "bufferView": buffer.add(_vec4_blob(mesh.colors), 34962),
                "componentType": 5126,
                "count": len(mesh.colors),
                "type": "VEC4",
            })
            attrs["COLOR_0"] = len(accessors) - 1

        tris = mesh.triangles
        if neg_z:
            tris = [(a, c, b) for (a, b, c) in tris]
        if max(v for t in tris for v in t) < 65536:
            index_blob = struct.pack(f"<{len(tris) * 3}H",
                                     *[v for t in tris for v in t])
            comp_type = 5123
        else:
            index_blob = struct.pack(f"<{len(tris) * 3}I",
                                     *[v for t in tris for v in t])
            comp_type = 5125
        accessors.append({
            "bufferView": buffer.add(index_blob, 34963),
            "componentType": comp_type,
            "count": len(tris) * 3,
            "type": "SCALAR",
        })

        prim = {
            "attributes": attrs,
            "indices": len(accessors) - 1,
            "mode": 4,
        }
        mi = material_index.get(mesh.shader_id)
        if mi is not None:
            prim["material"] = mi
        name = _safe(mesh.node_id or mesh.node_name or f"mesh_{i}")
        meshes_json.append({
            "name": name,
            "primitives": [prim],
        })
        nodes_json.append({"mesh": i, "name": name})

    doc = {
        "asset": {"version": "2.0",
                  "generator": "pssg_convert gltf exporter"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes_json)))}],
        "nodes": nodes_json,
        "meshes": meshes_json,
        "materials": materials,
        "samplers": samplers,
        "images": images,
        "textures": textures,
        "accessors": accessors,
        "bufferViews": buffer.views,
        "buffers": [{"byteLength": len(buffer.data)}],
    }
    return doc, bytes(buffer.data)


def _safe(name):
    out = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return out or "tex"


def write_gltf(meshes, material_bindings, texture_pngs, out_dir, base_name,
               neg_z=False):
    """Write <base>.gltf, <base>.bin and textures/*.png.  Returns manifest."""
    os.makedirs(out_dir, exist_ok=True)
    tex_dir = os.path.join(out_dir, "textures")
    os.makedirs(tex_dir, exist_ok=True)

    doc, bin_data = build_gltf(meshes, material_bindings, texture_pngs,
                               neg_z=neg_z)
    with open(os.path.join(out_dir, base_name + ".bin"), "wb") as fh:
        fh.write(bin_data)
    doc["buffers"][0]["uri"] = base_name + ".bin"
    with open(os.path.join(out_dir, base_name + ".gltf"), "w",
              encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)

    written = []
    for texture_id, png in texture_pngs.items():
        fname = _safe(texture_id) + ".png"
        with open(os.path.join(tex_dir, fname), "wb") as fh:
            fh.write(png)
        written.append(fname)
    return {
        "gltf": base_name + ".gltf",
        "bin": base_name + ".bin",
        "textures": written,
        "meshes": len(meshes),
        "materials": len(doc["materials"]),
    }


def collect_material_bindings(root, index, texture_ids):
    """Build {shader_id: {slot: texture_id}} for all SHADERINSTANCEs.

    Uses explicit SHADERINPUT texture refs when present (same-file ids),
    otherwise the car naming convention against ``texture_ids`` (the ids of a
    texture-container PSSG).
    """
    from .tbindings import TextureResolver

    resolver = TextureResolver(index)
    bindings = {}
    for el in root.iter_all():
        if el.name != "SHADERINSTANCE":
            continue
        shader_id = get_id(el)
        if not shader_id:
            continue
        sg = index.get(_attr_str(el, "shaderGroup", "#"))
        if sg is None or sg.name != "SHADERGROUP":
            sg = None
        binding = {}
        for slot, getter in (("diffuse", resolver.get_diffuse),
                             ("specular", resolver.get_specular),
                             ("normal", resolver.get_normal),
                             ("occlusion", resolver.get_occlusion),
                             ("emissive", resolver.get_emissive)):
            tex = getter(el, sg)
            if tex is not None:
                tid = get_id(tex)
                if tid is not None:
                    binding[slot] = tid
        if not binding:
            binding = bind_material(shader_id, texture_ids)
        bindings[shader_id] = binding
    return bindings
