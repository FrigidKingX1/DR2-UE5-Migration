"""Manifest generation and project preparation (runs in plain Python)."""

from __future__ import annotations

import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# the sibling tools/pbr_synth folder hosts the importable pbr_synth package
_SIBLING = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "pbr_synth")
if os.path.isdir(_SIBLING) and _SIBLING not in sys.path:
    sys.path.insert(0, _SIBLING)

from pbr_synth import reconcile  # noqa: E402

# shader id -> PBR pack part, mirroring gltf.py PART_ALIASES
SHADER_TO_PART = {
    "bodywork": "main",
    "cabin": "cabin",
    "interior": "cabin",
    "glass_exterior": "glass",
    "glass_interior": "glass",
    "rear_glass_interior": "glass",
    "caliper": "caliper",
    "discs": "disc",
    "car_disc_blur": "disc",
    "lights_opaque": "lights",
    "lights_alpha": "lights",
}


def _pbr_prefix(car_prefix: str, part: str) -> str:
    """'T_Fiat131_Body' style stem used by the Phase B pack."""
    return (f"T_{reconcile.display_car_name(car_prefix)}_"
            f"{reconcile.display_part_name(part)}")


def _find_gltf_outputs(gltf_dir: str) -> tuple[str, str]:
    """Locate (*_gltf.gltf, *_gltf_manifest.json) in the export folder."""
    doc = None
    mf = None
    for fn in os.listdir(gltf_dir):
        if fn.endswith("_gltf.gltf"):
            doc = os.path.join(gltf_dir, fn)
        elif fn == "gltf_manifest.json" or fn.endswith("_gltf_manifest.json"):
            mf = os.path.join(gltf_dir, fn)
    if doc is None or mf is None:
        raise SystemExit(f"no *_gltf.gltf / *_gltf_manifest.json in {gltf_dir}")
    return doc, mf


def build_manifest(gltf_dir: str, pbr_dir: str, car_prefix: str) -> dict:
    """Combine the glTF and PBR manifests into the ingest manifest."""
    doc_path, gltf_manifest_path = _find_gltf_outputs(gltf_dir)
    with open(gltf_manifest_path, "r", encoding="utf-8") as fh:
        gltf = json.load(fh)

    with open(doc_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)

    pbr_files = {fn.split(".")[0]: fn for fn in os.listdir(pbr_dir)
                 if fn.endswith(".png")}

    materials = []
    for shader_id, binding in gltf.get("materialBindings", {}).items():
        part = SHADER_TO_PART.get(shader_id)
        if part is None:
            continue
        stem = _pbr_prefix(car_prefix, part)
        if stem + "_D" not in pbr_files:
            continue  # part not synthesized
        materials.append({
            "shader": shader_id,
            "part": part,
            "basecolor": stem + "_D",
            "normal": stem + "_N",
            "orm": stem + "_ORM",
            "height": stem + "_H",
            "legacy_textures": binding,
        })

    nodes = []
    for mesh in doc.get("meshes", []):
        prim = (mesh.get("primitives") or [{}])[0]
        mat_index = prim.get("material")
        material_name = None
        if mat_index is not None and mat_index < len(doc.get("materials", [])):
            material_name = doc["materials"][mat_index].get("name")
        nodes.append({"name": mesh.get("name"), "material": material_name})

    return {
        "car": car_prefix,
        "car_display": reconcile.display_car_name(car_prefix),
        "gltf_file": os.path.abspath(doc_path),
        "pbr_dir": os.path.abspath(pbr_dir),
        "materials": materials,
        "nodes": nodes,
    }


def prepare(project_dir: str, gltf_dir: str, pbr_dir: str,
            car_prefix: str | None = None) -> str:
    """Write manifest.json into <project>/Content/Python. Returns its path."""
    if car_prefix is None:
        # derive from any PBR file name T_<Car>_<Part>_...; the token is the
        # display name, so reverse-map it to the archive prefix
        reverse = {v: k for k, v in reconcile.CAR_DISPLAY.items()}
        for fn in sorted(os.listdir(pbr_dir)):
            if fn.startswith("T_") and fn.endswith("_D.png"):
                token = fn.split("_")[1]
                car_prefix = reverse.get(token, token)
                break
        if car_prefix is None:
            raise SystemExit("could not derive car prefix from PBR pack")

    manifest = build_manifest(gltf_dir, pbr_dir, car_prefix)
    python_dir = os.path.join(project_dir, "Content", "Python")
    os.makedirs(python_dir, exist_ok=True)

    # also stage the ue-side script next to the manifest
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "ue_script.py")
    shutil.copyfile(src, os.path.join(python_dir, "ue_script.py"))

    out = os.path.join(python_dir, "manifest.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return out
