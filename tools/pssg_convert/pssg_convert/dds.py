"""Texture -> DDS emitter.

Faithful port of EgoEngineLibrary GraphicsExtensions.ToDdsFile + DdsFile.Write
(MIT).  Produces standard 2D-texture DDS and cube-map DDS bytes.
"""

from __future__ import annotations

import struct

from pssg_unpack import PssgElement

MAGIC_DDS = 0x20534444          # "DDS "

# DdsPixelFormat.Flags
DDPF_ALPHAPIXELS = 0x1
DDPF_FOURCC = 0x4
DDPF_RGB = 0x40
DDPF_LUMINANCE = 0x20000

# DdsHeader.Flags
DDSD_CAPS = 0x1
DDSD_HEIGHT = 0x2
DDSD_WIDTH = 0x4
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE = 0x80000

# DdsHeader.Caps
DDSCAPS_COMPLEX = 0x8
DDSCAPS_TEXTURE = 0x1000
DDSCAPS_MIPMAP = 0x400000

# DdsHeader.Caps2 (cube map)
DDSCAPS2_CUBEMAP = 0x200
_CUBE_FACES = {
    "Raw":            (0x400, 0),   # POSITIVEX
    "RawNegativeX":   (0x800, 1),
    "RawPositiveY":   (0x1000, 2),
    "RawNegativeY":   (0x2000, 3),
    "RawPositiveZ":   (0x4000, 4),
    "RawNegativeZ":   (0x8000, 5),
}

DXGI_BC1_UNORM_SRGB = 96
DXGI_BC2_UNORM_SRGB = 99
DXGI_BC3_UNORM_SRGB = 101
DXGI_BC6H_UF16 = 95
DXGI_BC7_UNORM = 98
DXGI_BC7_UNORM_SRGB = 100

D3D10_RESOURCE_DIMENSION_TEXTURE2D = 3


class TextureConvertError(Exception):
    pass


def _attr_int(elem, name, default=0):
    for a in elem.attributes:
        if a.name == name:
            return int(a.value)
    return default


def _attr_str(elem, name, default=""):
    for a in elem.attributes:
        if a.name == name:
            return str(a.value)
    return default


def _child(elem, name):
    for c in elem.children:
        if c.name == name:
            return c
    return None


def _children(elem, name):
    return [c for c in elem.children if c.name == name]


def _fourcc_u32(fourcc):
    if fourcc is None:
        return 0
    if isinstance(fourcc, int):
        return fourcc
    return struct.unpack("<I", fourcc)[0]


def _linear_size(texel, height, width):
    t = texel.lower()
    if t in ("dxt1", "dxt1_srgb"):
        return (height * width) // 2
    if t in ("dxt2", "dxt3", "dxt4", "dxt5", "dxt3_srgb", "dxt5_srgb",
             "bc6h_uf", "bc7", "bc7_srgb"):
        return height * width
    if t in ("ui8x4", "u8x4"):
        return height * width * 4
    if t == "u8":
        return height * width
    return 0


def _pixel_format(texel):
    """Return (fourcc, fourcc_present, ddspf_flags, bitcount, r,g,b,a, dxgi)."""
    t = texel.lower()
    if t in ("dxt1", "dxt1_srgb"):
        if t == "dxt1":
            return b"DXT1", True, DDPF_FOURCC, 0, 0, 0, 0, 0, 0, False
        return b"DX10", True, DDPF_FOURCC, 0, 0, 0, 0, 0, DXGI_BC1_UNORM_SRGB, True
    if t in ("dxt2", "dxt3", "dxt4", "dxt5"):
        return t.upper().encode("latin-1"), True, DDPF_FOURCC, 0, 0, 0, 0, 0, 0, False
    if t == "dxt3_srgb":
        return b"DX10", True, DDPF_FOURCC, 0, 0, 0, 0, 0, DXGI_BC2_UNORM_SRGB, True
    if t == "dxt5_srgb":
        return b"DX10", True, DDPF_FOURCC, 0, 0, 0, 0, 0, DXGI_BC3_UNORM_SRGB, True
    if t == "bc6h_uf":
        return b"DX10", True, DDPF_FOURCC, 0, 0, 0, 0, 0, DXGI_BC6H_UF16, True
    if t == "bc7":
        return b"DX10", True, DDPF_FOURCC, 0, 0, 0, 0, 0, DXGI_BC7_UNORM, True
    if t == "bc7_srgb":
        return b"DX10", True, DDPF_FOURCC, 0, 0, 0, 0, 0, DXGI_BC7_UNORM_SRGB, True
    if t in ("ui8x4", "u8x4"):
        return None, False, DDPF_ALPHAPIXELS | DDPF_RGB, 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000, 0, False
    if t == "u8":
        return None, False, DDPF_LUMINANCE, 8, 0xFF, 0, 0, 0, 0, False
    raise TextureConvertError(f"texel format {texel!r} not supported")


def _build_dds(linear_size, height, width, mip_count, caps, caps2,
               pf_flags, fourcc, bit_count, rmask, gmask, bmask, amask,
               dxgi, requires_dx10, bdata, bdata2):
    buf = bytearray()
    buf += struct.pack("<I", MAGIC_DDS)
    buf += struct.pack("<I", 124)                       # size
    dds_flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    if mip_count > 1:
        dds_flags |= DDSD_MIPMAPCOUNT
    dds_flags |= DDSD_LINEARSIZE
    if bdata2 is not None and len(bdata2):
        dds_flags &= ~DDSD_LINEARSIZE       # cubemap clears linear size
    buf += struct.pack("<I", dds_flags)
    buf += struct.pack("<I", height)
    buf += struct.pack("<I", width)
    buf += struct.pack("<I", linear_size if (bdata2 is None or not len(bdata2)) else 0)
    buf += struct.pack("<I", 0)                          # depth
    buf += struct.pack("<I", mip_count)
    buf += struct.pack("<44x")                           # reserved1
    buf += struct.pack("<I", 32)                         # ddspf size
    buf += struct.pack("<I", pf_flags)
    buf += struct.pack("<I", _fourcc_u32(fourcc))
    buf += struct.pack("<I", bit_count)
    buf += struct.pack("<I", rmask)
    buf += struct.pack("<I", gmask)
    buf += struct.pack("<I", bmask)
    buf += struct.pack("<I", amask)
    buf += struct.pack("<I", caps)
    buf += struct.pack("<I", caps2)
    buf += struct.pack("<I", 0)                          # caps3
    buf += struct.pack("<I", 0)                          # caps4
    buf += struct.pack("<I", 0)                          # reserved2
    if requires_dx10:
        buf += struct.pack("<I", dxgi)
        buf += struct.pack("<I", D3D10_RESOURCE_DIMENSION_TEXTURE2D)
        buf += struct.pack("<I", 0)                      # miscFlag
        buf += struct.pack("<I", 1)                      # arraySize
        buf += struct.pack("<I", 0)                      # miscFlags2
    if bdata2 is not None and len(bdata2):
        for i in range(6):
            if i in bdata2:
                buf += bdata2[i]
    else:
        buf += bdata
    return bytes(buf)


def texture_to_dds_bytes(texture: PssgElement) -> bytes:
    """Convert a PSSG TEXTURE element to a serialized .dds file (bytes)."""
    height = _attr_int(texture, "height")
    width = _attr_int(texture, "width")
    texel = _attr_str(texture, "texelFormat", "u8")
    auto_mipmap = _attr_int(texture, "automipmap", 0)
    mip_levels = _attr_int(texture, "numberMipMapLevels", 0)
    image_block_count = _attr_int(texture, "imageBlockCount", 0)

    fourcc, fourcc_present, pf_flags, bit_count, rmask, gmask, bmask, amask, \
        dxgi, requires_dx10 = _pixel_format(texel)

    linear_size = _linear_size(texel, height, width)

    mip_count = 1
    if not auto_mipmap and mip_levels > 0:
        mip_count = mip_levels + 1

    caps = DDSCAPS_TEXTURE
    if mip_count > 1:
        caps |= DDSCAPS_MIPMAP | DDSCAPS_COMPLEX

    bdata = b""
    bdata2 = None
    caps2 = 0

    if image_block_count > 0:
        faces = {}
        for block in _children(texture, "TEXTUREIMAGEBLOCK"):
            type_name = _attr_str(block, "type", "")
            if type_name not in _CUBE_FACES:
                continue
            caps_bit, face_idx = _CUBE_FACES[type_name]
            data_img = _child(block, "TEXTUREIMAGEBLOCKDATA")
            payload = data_img.value if (data_img is not None and data_img.is_data) else b""
            faces[face_idx] = payload
        if len(faces) == 6:
            caps2 = DDSCAPS2_CUBEMAP
            for _caps_bit, _face_idx in _CUBE_FACES.values():
                caps2 |= _caps_bit
            caps |= DDSCAPS_COMPLEX
            bdata2 = {i: faces.get(i, b"") for i in range(6)}
        elif len(faces) == 1:
            bdata = next(iter(faces.values()))
        else:
            raise TextureConvertError(
                f"cubemap with {len(faces)}/6 faces found (need all six)")
    else:
        image = _child(texture, "TEXTUREIMAGE")
        if image is not None and image.is_data:
            mips = b"".join(m.value for m in _children(texture, "TEXTUREMIPMAP")
                            if m.is_data)
            bdata = image.value + mips
        else:
            raise TextureConvertError("texture has no TEXTUREIMAGE data")

    return _build_dds(linear_size, height, width, mip_count, caps, caps2,
                      pf_flags, fourcc, bit_count, rmask, gmask, bmask, amask,
                      dxgi, requires_dx10, bdata, bdata2)