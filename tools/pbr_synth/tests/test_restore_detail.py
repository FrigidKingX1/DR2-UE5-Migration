"""Tests for detail restoration (legacy HF onto CHORD basecolor)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pytest

from pbr_synth import reconcile


def test_box_blur_flat_stays_flat():
    arr = np.full((8, 8, 3), 0.5, dtype=np.float32)
    out = reconcile._box_blur(arr, radius=2)
    np.testing.assert_allclose(out, 0.5, atol=1e-5)


def test_box_blur_shape_and_normalization():
    rng = np.random.default_rng(7)
    arr = rng.random((16, 16, 3), dtype=np.float32)
    out = reconcile._box_blur(arr, radius=2)
    assert out.shape == arr.shape
    # mean should be approximately preserved (edge-clamped)
    assert abs(out.mean() - arr.mean()) < 0.02


def test_restore_detail_identity_at_zero_strength():
    chord = np.full((8, 8, 3), 128, dtype=np.uint8)
    legacy = np.zeros((8, 8, 3), dtype=np.uint8)
    legacy[2, 2] = 255  # sharp spike = high-frequency residual
    out = reconcile.restore_detail(chord, legacy, strength=0.0)
    np.testing.assert_array_equal(out, chord)


def test_restore_detail_reinjects_edges():
    # legacy has a sharp vertical edge; CHORD is flat mid-gray
    chord = np.full((16, 16, 3), 128, dtype=np.uint8)
    legacy = np.full((16, 16, 3), 128, dtype=np.uint8)
    legacy[:, 8:] = 255
    out = reconcile.restore_detail(chord, legacy, strength=1.0)
    # high-pass detail exists within the blur radius of the edge (col 8)
    band = out[8, 4:13, 0].astype(int)
    assert int(band.max()) - int(band.min()) > 80


def test_restore_detail_resamples_legacy():
    chord = np.full((8, 8, 3), 100, dtype=np.uint8)
    legacy = np.full((16, 16, 3), 100, dtype=np.uint8)
    legacy[4, 4] = 200  # high-frequency dot
    out = reconcile.restore_detail(chord, legacy, strength=1.0)
    assert out.shape == chord.shape
    assert out.max() > 110  # some detail transferred


def test_restore_detail_output_range():
    rng = np.random.default_rng(3)
    chord = rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)
    legacy = rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)
    out = reconcile.restore_detail(chord, legacy, strength=0.5)
    assert out.dtype == np.uint8
    assert out.min() >= 0 and out.max() <= 255