"""Shader -> texture resolution.

Port of PssgGltfConverter.GetDiffuseTexture / GetSpecularTexture / etc. and
PssgShaderInput / PssgShaderInputDefinition (MIT).
"""

from __future__ import annotations

from pssg_unpack import PssgElement

from .extract import (
    ObjectIndex,
    _attr_int,
    _attr_str,
    _child,
    _children,
    get_id,
)


class TextureResolver:
    """Resolves the texture bindings of a SHADERGROUP for a SHADERINSTANCE."""

    DIFFUSE_PREFIX = "TDiffuseAlphaMap"
    SPECULAR_PREFIX = "TSpecularMap"
    EMISSIVE_PREFIX = "TEmissiveMap"
    OCCLUSION_PREFIX = "TOcclusionMap"
    NORMAL_PREFIX = "TNormalMap"

    def __init__(self, index):
        self._index = index

    def _find_texture(self, shader_instance, shader_group, prefix):
        """Return the PssgTexture element bound to an input named `prefix*`, or None."""
        if shader_group is None:
            return None
        definitions = _children(shader_group, "SHADERINPUTDEFINITION")
        texture_inputs = [c for c in _children(shader_instance, "SHADERINPUT")
                          if _attr_str(c, "type", "") == "texture"]
        for ti in texture_inputs:
            param_id = _attr_int(ti, "parameterID", -1)
            if param_id < 0 or param_id >= len(definitions):
                continue
            texture_ref = _attr_str(ti, "texture")
            if not texture_ref.startswith("#"):
                continue  # references another pssg file
            sid = definitions[param_id]
            if _attr_str(sid, "name", "").startswith(prefix):
                tex = self._index.get(texture_ref)
                if tex is not None and tex.name == "TEXTURE":
                    return tex
        return None

    def get_diffuse(self, si, sg):
        return self._find_texture(si, sg, self.DIFFUSE_PREFIX)

    def get_specular(self, si, sg):
        return self._find_texture(si, sg, self.SPECULAR_PREFIX)

    def get_emissive(self, si, sg):
        return self._find_texture(si, sg, self.EMISSIVE_PREFIX)

    def get_occlusion(self, si, sg):
        return self._find_texture(si, sg, self.OCCLUSION_PREFIX)

    def get_normal(self, si, sg):
        return self._find_texture(si, sg, self.NORMAL_PREFIX)


def resolve_shader_and_group(instance, index):
    """Given a RENDERSTREAMINSTANCE, return (shader_instance, shader_group)."""
    shader_ref = _attr_str(instance, "shader")
    shader = index.get(shader_ref)
    if shader is None or shader.name != "SHADERINSTANCE":
        return None, None
    group_ref = _attr_str(shader, "shaderGroup")
    group = index.get(group_ref)
    if group is None or group.name != "SHADERGROUP":
        group = None
    return shader, group


def collect_textures(root, index):
    """Return {texture_id: PssgElement} for every TEXTURE element in the tree."""
    out = {}
    for el in root.iter_all():
        if el.name == "TEXTURE":
            ident = get_id(el)
            if ident:
                out[ident] = el
    return out