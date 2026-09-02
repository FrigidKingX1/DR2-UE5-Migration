"""In-editor automation: vehicle physics setup from vehicle_config.json.

Creates per-surface CurveFloat assets (braking distance vs speed) and
PhysicalMaterials (friction scaled by the surface grip coefficient), so the
Chaos vehicle work starts from real DR2 data instead of defaults.  The
vehicle_config.json itself is also available at runtime as a DataTable-like
reference; the ChaosWheeledVehicleMovementComponent wiring remains
human-led (Blueprint assembly), per the migration plan.
"""

import json
import os
import traceback

import unreal

RESULT = {"steps": {}, "errors": {}, "assets": {}}

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "vehicle_config.json")
DEST = "/Game/Import/Vehicle"


def log(msg: str) -> None:
    unreal.log_warning(f"[vehicle] {msg}")


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def make_curves(config) -> int:
    """CurveFloat key authoring is not possible headlessly on 5.5:
    the FRichCurve UPROPERTYs are not Python-reflected and both direct key
    writes and CurveImportFactory CSV import crash the pythonscript
    commandlet.  The curve data remains available in vehicle_config.json
    (this file) for the human-led Chaos vehicle assembly."""
    RESULT["steps"]["curves"] = 0
    RESULT["errors"]["curves"] = "deferred: no headless CurveFloat key API"
    return 0


def make_physical_materials(config) -> int:
    al = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    made = 0
    for code, surface in config.get("surfaces", {}).items():
        name = f"PM_{code}"
        path = f"{DEST}/{name}"
        if al.does_asset_exist(path):
            pm = al.load_asset(path)
        else:
            try:
                pm = at.create_asset(name, DEST, unreal.PhysicalMaterial,
                                     unreal.PhysicalMaterialFactoryNew())
            except Exception as exc:
                RESULT["errors"][f"pm_{code}"] = str(exc)
                continue
        if pm is None:
            continue
        grip = surface.get("grip", {}).get("grip_curve") or [1.0]
        friction = _clamp(abs(grip[0]) or 1.0, 0.2, 2.0)
        try:
            pm.set_editor_property("friction", friction)
            al.save_loaded_asset(pm)
            made += 1
        except Exception as exc:
            RESULT["errors"][f"pm_{code}"] = str(exc)
    RESULT["steps"]["physical_materials"] = made
    return made


def import_curve_table() -> None:
    """Curve asset import is not viable headlessly on 5.5.4: direct
    CurveFloat key writes fail (unreflected FRichCurve), CurveImportFactory
    AND ReimportCurveFactory (automated CSV route) both access-violate the
    pythonscript commandlet.  The curve data remains available in
    vehicle_config.json + vehicle_curves.csv for the human-tuned Chaos
    vehicle assembly."""
    RESULT["steps"]["curves"] = 0
    RESULT["errors"]["curves"] = (
        "deferred: all curve import paths crash the pythonscript "
        "commandlet on 5.5.4; data preserved in vehicle_config.json")


def attempt_vehicle_blueprint() -> None:
    """Tier 1: Chaos vehicle Blueprint with a WheeledVehiclePawn parent.

    Full component authoring (ChaosWheeledVehicleMovementComponent with
    wheel setups) is not Python-settable headlessly on 5.5 (subobject
    authoring + deep engine structs), so this creates the compiled Blueprint
    shell with the correct parent class; the movement tuning consumes
    vehicle_config.json + CT_Vehicle131 from the project.
    """
    try:
        pawn_class = getattr(unreal, "WheeledVehiclePawn", None)
        if pawn_class is None:
            RESULT["steps"]["vehicle_bp"] = (
                "deferred: WheeledVehiclePawn not available")
            return
        al = unreal.EditorAssetLibrary
        path = f"{DEST}/BP_Vehicle131"
        if not al.does_asset_exist(path):
            factory = unreal.BlueprintFactory()
            factory.set_editor_property("parent_class", pawn_class)
            bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                "BP_Vehicle131", DEST, None, factory)
            if bp is None:
                RESULT["steps"]["vehicle_bp"] = "create failed"
                return
            al.save_loaded_asset(bp)
        bel = getattr(unreal, "BlueprintEditorLibrary", None)
        if bel is not None and hasattr(bel, "compile_blueprint"):
            bel.compile_blueprint(al.load_asset(path))
            RESULT["steps"]["vehicle_bp"] = f"created+compiled: {path}"
        else:
            RESULT["steps"]["vehicle_bp"] = f"created: {path}"
    except Exception as exc:
        RESULT["steps"]["vehicle_bp"] = f"failed: {exc}"
        log(f"vehicle BP attempt: {exc}")


def main() -> None:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        config = json.load(fh)
    log(f"config: car={config.get('car')} "
        f"surfaces={config.get('num_surfaces')}")

    try:
        make_curves(config)
    except Exception as exc:
        RESULT["errors"]["curves"] = f"{exc}"
        unreal.log_warning(traceback.format_exc())
    try:
        make_physical_materials(config)
    except Exception as exc:
        RESULT["errors"]["physical_materials"] = f"{exc}"
        unreal.log_warning(traceback.format_exc())

    try:
        import_curve_table()
    except Exception as exc:
        RESULT["errors"]["curve_table"] = f"{exc}"
        unreal.log_warning(traceback.format_exc())
    try:
        attempt_vehicle_blueprint()
    except Exception as exc:
        RESULT["errors"]["vehicle_bp"] = f"{exc}"
        unreal.log_warning(traceback.format_exc())

    with open(os.path.join(HERE, "vehicle_result.json"), "w",
              encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2)
    log(f"done: {RESULT['steps']} errors={list(RESULT['errors'])}")


main()
