"""Tests for pbr_synth.reconcile (pure math, no GPU / no server)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pytest

from pbr_synth import reconcile


def test_specular_to_gloss_from_alpha():
    # specular-glossiness: RGB tint + gloss in alpha
    spec = np.zeros((4, 4, 4), dtype=np.uint8)
    spec[..., 0] = 200          # specular tint (ignored for gloss)
    spec[..., 3] = np.linspace(0, 255, 16).reshape(4, 4)
    gloss = reconcile.specular_to_gloss(spec)
    assert gloss.shape == (4, 4)
    assert gloss[0, 0] == pytest.approx(0.0, abs=1e-3)
    assert gloss[3, 3] == pytest.approx(1.0, abs=1e-3)


def test_specular_to_gloss_luminance_fallback():
    # flat alpha -> luminance heuristic (1 - luminance)
    spec = np.zeros((2, 2, 4), dtype=np.uint8)
    spec[..., :3] = 255          # white specular
    spec[..., 3] = 128           # flat
    gloss = reconcile.specular_to_gloss(spec)
    assert gloss[0, 0] == pytest.approx(0.0, abs=1e-3)

    spec[..., :3] = 0            # black specular -> rough
    gloss = reconcile.specular_to_gloss(spec)
    assert gloss[0, 0] == pytest.approx(1.0, abs=1e-3)


def test_legacy_roughness_sqrt_identity():
    gloss = np.array([0.0, 0.25, 0.64, 1.0], dtype=np.float32)
    rough = reconcile.legacy_roughness(gloss)
    np.testing.assert_allclose(rough, [1.0, np.sqrt(0.75), 0.6, 0.0],
                               rtol=1e-5)


def test_blend_roughness_default_weight():
    chord = np.full((2, 2), 0.8, dtype=np.float32)
    legacy = np.full((2, 2), 0.2, dtype=np.float32)
    blended = reconcile.blend_roughness(chord, legacy)
    expected = 0.7 * 0.8 + 0.3 * 0.2
    np.testing.assert_allclose(blended, expected, rtol=1e-5)


def test_blend_roughness_custom_weight():
    chord = np.full((1, 1), 1.0, dtype=np.float32)
    legacy = np.zeros((1, 1), dtype=np.float32)
    assert reconcile.blend_roughness(chord, legacy, weight=0.0)[0, 0] == 0.0
    assert reconcile.blend_roughness(chord, legacy, weight=1.0)[0, 0] == 1.0


def test_invert_green_directx():
    normal = np.zeros((1, 2, 3), dtype=np.uint8)
    normal[0, 0] = [128, 255, 255]   # OpenGL: green up
    normal[0, 1] = [128, 0, 255]     # green down
    out = reconcile.invert_green(normal)
    assert out[0, 0, 1] == 0         # 255 - 255
    assert out[0, 1, 1] == 255       # 255 - 0
    assert out[0, 0, 0] == 128       # R untouched
    assert out[0, 0, 2] == 255       # B untouched


def test_pack_orm_channels():
    ao = np.full((2, 2), 1.0, dtype=np.float32)        # white
    rough = np.full((2, 2), 0.5, dtype=np.float32)     # mid gray
    metal = np.zeros((2, 2), dtype=np.float32)         # black
    orm = reconcile.pack_orm(ao, rough, metal)
    assert orm.shape == (2, 2, 3) and orm.dtype == np.uint8
    assert np.all(orm[..., 0] == 255)
    assert np.all(orm[..., 1] == 128) or np.all(orm[..., 1] == 127)
    assert np.all(orm[..., 2] == 0)


def test_height_to_uint16_normalizes():
    height = np.zeros((4, 4, 3), dtype=np.float32)
    height[0, 0] = 1.0
    h16 = reconcile.height_to_uint16(height)
    assert h16.dtype == np.uint16
    assert h16[0, 0] == 65535
    assert h16[3, 3] == 0


def test_package_naming():
    assert reconcile.package_name("131", "main", "D") == "T_Fiat131_Body_D.png"
    assert reconcile.package_name("131", "cabin", "ORM") == "T_Fiat131_Cabin_ORM.png"
    assert reconcile.package_name("131", "lights", "H") == "T_Fiat131_Lights_H.png"
    assert reconcile.package_name("abc", "disc", "N") == "T_CarABC_Disc_N.png"
    assert reconcile.package_name("131", "custom", "D") == "T_Fiat131_Custom_D.png"


def test_workflow_graph_shape():
    from pbr_synth import chord_workflow as cw

    g = cw.build_image_to_material("pbr_synth/x.png")
    assert g["1"]["class_type"] == "LoadImage"
    assert g["2"]["class_type"] == "ChordLoadModel"
    assert g["3"]["class_type"] == "ChordMaterialEstimation"
    assert g["3"]["inputs"]["image"] == ["1", 0]
    assert g["3"]["inputs"]["chord_model"] == ["2", 0]
    assert g[cw.NODE_HEIGHT]["class_type"] == "ChordNormalToHeight"
    assert g[cw.NODE_HEIGHT]["inputs"]["normal"] == ["3", 1]
    for slot, node in cw.OUTPUT_NODES.items():
        assert g[node]["class_type"] == "SaveImage"
    # each SaveImage consumes a distinct output slot of the estimation node
    slots = {g[n]["inputs"]["images"][1] for n in cw.OUTPUT_NODES.values()
             if n != cw.NODE_HEIGHT_SAVE}
    assert slots == {0, 1, 2, 3}