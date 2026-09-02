"""PBR reconciliation and UE5 packaging math.

Pure numpy functions, no I/O dependencies beyond imagecodecs helpers, so the
whole module is unit-testable without a GPU or a ComfyUI server.

Conventions
-----------
* Images are HxWx(3|4) uint8 (or uint16 for height) arrays.
* Legacy EGO ``_s`` maps are specular-glossiness: RGB = specular tint,
  A = glossiness.  The modern roughness equivalent is ``sqrt(1 - gloss)``.
* CHORD predictions are trained on MatSynth (OpenGL normal convention);
  Unreal Engine expects DirectX normals, i.e. the green channel inverted:
  ``G_ue = 255 - G_chord``.
* ORM packing (UE5 `TC_Masks`): R = ambient occlusion, G = roughness,
  B = metallic.
"""

from __future__ import annotations

import numpy as np

# Weight of the CHORD micro-roughness prediction in the blend with the legacy
# gloss derivation.  0.7 keeps CHORD's micro-surface detail while retaining
# 30% of the original livery gloss levels (per the migration plan).
CHORD_ROUGHNESS_WEIGHT = 0.7

# Display naming for Phase C packaging.
CAR_DISPLAY = {
    "131": "Fiat131",
}
PART_DISPLAY = {
    "main": "Body",
    "cabin": "Cabin",
    "glass": "Glass",
    "lights": "Lights",
    "caliper": "Caliper",
    "disc": "Disc",
    "wheel": "Wheel",
    "tread": "Tread",
}


def specular_to_gloss(spec_rgba: np.ndarray) -> np.ndarray:
    """Extract glossiness from a legacy ``_s`` map.

    Uses the alpha channel when it carries variation; otherwise falls back to
    a luminance heuristic (1 - luminance), since low-intensity speculars read
    as rough surfaces.
    """
    rgba = _as_float(spec_rgba)
    if rgba.shape[-1] == 4:
        alpha = rgba[..., 3]
        if float(alpha.max()) - float(alpha.min()) > 1.0 / 255.0:
            return alpha
    rgb = rgba[..., :3]
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return 1.0 - lum


def legacy_roughness(gloss: np.ndarray) -> np.ndarray:
    """Linear roughness approximation from glossiness: sqrt(1 - gloss)."""
    g = _as_float(gloss)
    if g.ndim == 3:
        g = g[..., 0]
    return np.sqrt(np.clip(1.0 - g, 0.0, 1.0))


def blend_roughness(chord_rough: np.ndarray, legacy_rough: np.ndarray,
                    weight: float = CHORD_ROUGHNESS_WEIGHT) -> np.ndarray:
    """Weighted blend of CHORD micro-roughness and legacy gloss derivation."""
    c = _as_float(chord_rough)
    l = _as_float(legacy_rough)
    if c.ndim == 3:
        c = c[..., 0]
    if l.ndim == 3:
        l = l[..., 0]
    return np.clip(weight * c + (1.0 - weight) * l, 0.0, 1.0)


def invert_green(normal_rgb: np.ndarray) -> np.ndarray:
    """OpenGL (MatSynth) normal -> DirectX (Unreal): invert the green channel."""
    out = np.array(normal_rgb, copy=True)
    if out.dtype == np.uint16:
        out[..., 1] = 65535 - out[..., 1]
    else:
        out[..., 1] = 255 - out[..., 1]
    return out


def pack_orm(ao: np.ndarray, roughness: np.ndarray,
             metalness: np.ndarray) -> np.ndarray:
    """Pack occlusion/roughness/metalness into an RGB uint8 ORM texture."""
    chan = [_as_float(m) for m in (ao, roughness, metalness)]
    chan = [c[..., 0] if c.ndim == 3 else c for c in chan]
    h, w = chan[0].shape
    orm = np.zeros((h, w, 3), dtype=np.uint8)
    for ch, arr in enumerate(chan):
        orm[..., ch] = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return orm


def grayscale_or_orm_fallback(maps: list[np.ndarray], shape: tuple) -> np.ndarray:
    """Return the first usable map broadcast to shape (e.g. AO fallback)."""
    for m in maps:
        if m is not None:
            return m
    return np.ones(shape, dtype=np.uint8) * 255


def height_to_uint16(height: np.ndarray) -> np.ndarray:
    """CHORD height (HxW float image, possibly 3-channel) -> 16-bit grayscale."""
    arr = _as_float(height)
    if arr.ndim == 3:
        arr = arr[..., 0]
    lo, hi = float(arr.min()), float(arr.max())
    if hi - lo > 1e-6:
        arr = (arr - lo) / (hi - lo)
    return np.clip(arr * 65535.0 + 0.5, 0, 65535).astype(np.uint16)


def display_car_name(car_prefix: str) -> str:
    if car_prefix in CAR_DISPLAY:
        return CAR_DISPLAY[car_prefix]
    return "Car" + car_prefix.upper()


def display_part_name(part: str) -> str:
    if part in PART_DISPLAY:
        return PART_DISPLAY[part]
    return part.capitalize()


def package_name(car_prefix: str, part: str, suffix: str) -> str:
    """Phase C packaging nomenclature: T_<Car>_<Part>_<SUFFIX>.png."""
    return (f"T_{display_car_name(car_prefix)}_"
            f"{display_part_name(part)}_{suffix}.png")


# ---------------------------------------------------------------------------
# detail restoration


def restore_detail(chord_base: np.ndarray, legacy_base: np.ndarray,
                   strength: float = 0.5) -> np.ndarray:
    """Re-inject legacy high-frequency detail into CHORD's de-lit basecolor.

    CHORD de-lits the albedo but diffusion softens decal edges and text (the
    livery number/sponsor text comes back blurry).  The legacy ``_d`` map
    keeps crisp high frequencies but carries baked lighting.  Combine both:
    keep CHORD's low-frequency (de-lit) content and overlay the legacy map's
    high-frequency residual (legacy - gaussian(legacy)), scaled by strength.

    strength 0 -> pure CHORD basecolor, 1 -> adds the full legacy detail
    residual.  Both inputs are HxWx3 uint8; the legacy map is resampled by
    simple nearest indexing if sizes differ.
    """
    if chord_base.shape[:2] != legacy_base.shape[:2]:
        legacy_base = _nearest_resize(legacy_base, chord_base.shape[:2])
    c = _as_float(chord_base)[..., :3]
    l = _as_float(legacy_base)[..., :3]

    low = _box_blur(l, radius=2)
    detail = l - low
    out = np.clip(c + detail * strength, 0.0, 1.0)
    return (out * 255.0 + 0.5).astype(np.uint8)


def _nearest_resize(arr: np.ndarray, shape: tuple) -> np.ndarray:
    yi = np.linspace(0, arr.shape[0] - 1, shape[0]).astype(int)
    xi = np.linspace(0, arr.shape[1] - 1, shape[1]).astype(int)
    return arr[np.ix_(yi, xi)]


def _box_blur(arr: np.ndarray, radius: int = 2) -> np.ndarray:
    """Separable box blur via cumulative sums, O(n) per axis, edge-clamped."""
    w = 2 * radius + 1

    def _blur_axis(x, axis):
        x = np.pad(x, [(radius, radius) if ax == axis else (0, 0)
                       for ax in range(x.ndim)], mode="edge")
        c = np.cumsum(x, axis=axis, dtype=np.float32)
        zeros_shape = list(c.shape)
        zeros_shape[axis] = 1
        c = np.concatenate([np.zeros(zeros_shape, dtype=np.float32), c],
                           axis=axis)
        lo = [slice(None)] * c.ndim
        hi = [slice(None)] * c.ndim
        lo[axis] = slice(w, None)
        hi[axis] = slice(None, -w)
        return (c[tuple(lo)] - c[tuple(hi)]) / np.float32(w)

    return _blur_axis(_blur_axis(arr.astype(np.float32), 0), 1)


# ---------------------------------------------------------------------------
# helpers


def _as_float(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr)
    if arr.dtype == np.uint16:
        return arr.astype(np.float32) / 65535.0
    if arr.dtype == np.uint8:
        return arr.astype(np.float32) / 255.0
    return arr.astype(np.float32)


def channel(arr: np.ndarray, index: int) -> np.ndarray:
    a = np.asarray(arr)
    return a[..., index] if a.ndim == 3 else a
