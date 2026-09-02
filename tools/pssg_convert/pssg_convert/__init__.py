"""pssg_convert — mesh + texture extraction from EGO PSSG scene files.

Consumes a pssg_unpack.PssgFile and emits Wavefront OBJ meshes, DDS textures
and a shader->texture binding manifest.
"""

from __future__ import annotations

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
    return None


_bootstrap_pssg_unpack()

from .dds import TextureConvertError, texture_to_dds_bytes  # noqa: E402
from .extract import MeshPrimitive, PssgConvertError, RenderDataSourceReader, collect_meshes  # noqa: E402
from .obj import write_mtl, write_obj  # noqa: E402
from .tbindings import TextureResolver  # noqa: E402

__all__ = [
    "MeshPrimitive",
    "PssgConvertError",
    "RenderDataSourceReader",
    "TextureConvertError",
    "TextureResolver",
    "collect_meshes",
    "texture_to_dds_bytes",
    "write_mtl",
    "write_obj",
]

__version__ = "0.1.0"