"""In-editor automation: vehicle physics setup from vehicle_config.json.

Creates per-surface PhysicalMaterials (friction scaled by the surface grip
coefficient), authors the Chaos vehicle Blueprint movement tuning on
BP_Vehicle131, and creates the BP_Wheel131 wheel blueprint.  All scalar
setup structs (engine / transmission / differential / steering / wheel
setups) are Python-reflected on 5.5 and settable headlessly; only the
TorqueCurve FRuntimeFloatCurve is not (documented limitation).
The vehicle_config.json also carries the DR2 per-surface grip data
(AI statistics) as a DataTable-like reference.
"""

import json
import os
import traceback

import unreal

RESULT = {"steps": {}, "errors": {}, "assets": {}}

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "vehicle_config.json")
DEST = "/Game/Import/Vehicle"

# ---------------------------------------------------------------------------
# Fiat 131 Abarth (car 131) movement tuning.
# PROVENANCE: the encrypted CTF cannot be decoded (non-archive key), and
# ai_vehicle_statistics.xml carries only AI grip/braking/cornering data - no
# engine/gear/mass specs.  These values are real-world Fiat 131 Abarth
# Group 4 specifications (publicly documented) as an honest approximation:
# ~1000 kg, 2.0 L ~140-160 hp, 5-speed RWD, 2340 mm wheelbase, 1440 mm track,
# 185/70R13 wheels (~0.31 m radius).
TUNING = {
    "mass": 1000.0,
    "engine": {
        "max_rpm": 7000.0,
        "engine_idle_rpm": 1100.0,
        "max_torque": 190.0,      # Nm (crank), ~145 hp @ 6500 rpm
        "engine_brake_effect": 0.05,
        "engine_rev_up_moi": 3.0,
        "engine_rev_down_rate": 600.0,
    },
    "transmission": {
        "final_ratio": 3.7,
        "forward_gear_ratios": [3.17, 2.05, 1.46, 1.13, 0.92],
        "reverse_gear_ratios": [-3.17],
        "change_up_rpm": 6800.0,
        "change_down_rpm": 2400.0,
        "gear_change_time": 0.25,
        "transmission_efficiency": 0.92,
    },
    "differential": "Rear",       # RWD: rear-wheel drive
    "steering": {"angle_ratio": 0.7, "max_steer_angle": 35.0},
    "wheel": {
        "radius": 0.31, "width": 0.185, "mass": 18.0,
        "cornering_stiffness": 10.0, "friction_force_multiplier": 2.0,
        "spring_rate": 300.0, "suspension_damping_ratio": 1.2,
        "suspension_max_raise": 8.0, "suspension_max_drop": 12.0,
    },
    # wheel offsets (m) from vehicle origin: [x, y, z]
    "wheel_positions": [
        [1.17, -0.72, -0.15], [1.17, 0.72, -0.15],
        [-1.17, -0.72, -0.15], [-1.17, 0.72, -0.15],
    ],
}


def log(msg: str) -> None:
    unreal.log_warning(f"[vehicle] {msg}")


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _set_struct_fields(obj, mapping) -> list:
    """set_editor_property each key on a USTRUCT; returns applied keys.
    Bool b-prefixed names fall back to their no-b variant (reflection
    inconsistency between 5.5 struct versions)."""
    applied = []
    for k, v in mapping.items():
        try:
            obj.set_editor_property(k, v)
            applied.append(k)
        except Exception:
            try:
                alt = k[2:] if k.startswith("b_") else k
                obj.set_editor_property(alt, v)
                applied.append(alt)
            except Exception as exc:
                RESULT["errors"][f"struct_{k}"] = str(exc)
    return applied


def _find_enum_value(enum_cls, substrings):
    """Pick the first enum member whose name contains any substring."""
    for name in dir(enum_cls):
        if name.startswith("_"):
            continue
        for s in substrings:
            if s.lower() in name.lower():
                return getattr(enum_cls, name), name
    return None, None


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


def make_wheel_blueprint() -> str:
    """Create BP_Wheel131 (ChaosVehicleWheel parent) with 131 Abarth wheel
    tuning; all wheel properties are Python-reflected scalars."""
    al = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    wheel_cls = getattr(unreal, "ChaosVehicleWheel", None)
    if wheel_cls is None:
        RESULT["errors"]["wheel_bp"] = "ChaosVehicleWheel class missing"
        return ""
    path = f"{DEST}/BP_Wheel131"
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", wheel_cls)
    created = False
    if not al.does_asset_exist(path):
        bp = at.create_asset("BP_Wheel131", DEST, None, factory)
        if bp is None:
            RESULT["errors"]["wheel_bp"] = "create failed"
            return ""
        al.save_loaded_asset(bp)
        created = True
    # tune the wheel CDO
    wbp = al.load_asset(path)
    cdo = unreal.get_default_object(wbp.generated_class())
    t = TUNING["wheel"]
    applied = _set_struct_fields(cdo, {
        "wheel_radius": t["radius"],
        "wheel_width": t["width"],
        "wheel_mass": t["mass"],
        "cornering_stiffness": t["cornering_stiffness"],
        "friction_force_multiplier": t["friction_force_multiplier"],
        "spring_rate": t["spring_rate"],
        "suspension_damping_ratio": t["suspension_damping_ratio"],
        "suspension_max_raise": t["suspension_max_raise"],
        "suspension_max_drop": t["suspension_max_drop"],
        "max_steer_angle": 35.0,
    })
    bel = getattr(unreal, "BlueprintEditorLibrary", None)
    if bel is not None and hasattr(bel, "compile_blueprint"):
        bel.compile_blueprint(wbp)
    al.save_loaded_asset(wbp)
    RESULT["steps"]["wheel_bp"] = (
        f"{'created' if created else 'updated'}: {path} "
        f"fields={len(applied)}")
    RESULT["assets"]["wheel_bp"] = path
    return path


def tune_chaos_movement() -> None:
    """Author the ChaosWheeledVehicleMovementComponent tuning on
    BP_Vehicle131's class defaults (CDO): engine, transmission,
    differential, steering, mass and 4 wheel setups.

    The movement component is a native subobject inherited from
    WheeledVehiclePawn; mutating its CDO properties and saving the BP
    persists the overrides exactly like editor Class Defaults edits.
    Provenance for all values: real-world Fiat 131 Abarth Group 4 specs
    (see TUNING above) - the encrypted CTF could not be decoded.
    """
    al = unreal.EditorAssetLibrary
    path = f"{DEST}/BP_Vehicle131"
    bp = al.load_asset(path)
    if bp is None:
        RESULT["errors"]["movement"] = "BP_Vehicle131 not found"
        return
    try:
        cdo = unreal.get_default_object(bp.generated_class())
        mv = cdo.get_editor_property("vehicle_movement_component")
        if mv is None:
            RESULT["errors"]["movement"] = "no vehicle_movement_component"
            return
        steps = {}

        mv.set_editor_property("mass", TUNING["mass"])

        eng = mv.get_editor_property("engine_setup")
        steps["engine"] = _set_struct_fields(eng, TUNING["engine"])
        mv.set_editor_property("engine_setup", eng)

        tr = mv.get_editor_property("transmission_setup")
        steps["transmission"] = _set_struct_fields(tr, {
            "final_ratio": TUNING["transmission"]["final_ratio"],
            "forward_gear_ratios":
                TUNING["transmission"]["forward_gear_ratios"],
            "reverse_gear_ratios":
                TUNING["transmission"]["reverse_gear_ratios"],
            "change_up_rpm": TUNING["transmission"]["change_up_rpm"],
            "change_down_rpm": TUNING["transmission"]["change_down_rpm"],
            "gear_change_time": TUNING["transmission"]["gear_change_time"],
            "transmission_efficiency":
                TUNING["transmission"]["transmission_efficiency"],
            "b_use_automatic_gears": True,
            "b_use_auto_reverse": True,
        })
        mv.set_editor_property("transmission_setup", tr)

        dif = mv.get_editor_property("differential_setup")
        val, name = _find_enum_value(unreal.VehicleDifferential,
                                     ["Rear"])
        if val is not None:
            dif.set_editor_property("differential_type", val)
            steps["differential"] = f"{name} (+front_rear_split 0.0)"
            dif.set_editor_property("front_rear_split", 0.0)
        else:
            steps["differential"] = "enum not found"
        mv.set_editor_property("differential_setup", dif)

        st = mv.get_editor_property("steering_setup")
        val, name = _find_enum_value(unreal.SteeringType, ["AngleRatio"])
        if val is not None:
            st.set_editor_property("steering_type", val)
            steps["steering"] = name
        st.set_editor_property("angle_ratio",
                               TUNING["steering"]["angle_ratio"])
        mv.set_editor_property("steering_setup", st)

        # 4 wheel setups bound to BP_Wheel131
        wheel_bp = al.load_asset(f"{DEST}/BP_Wheel131")
        wheel_class = wheel_bp.generated_class() if wheel_bp else None
        wcls = mv.get_editor_property("wheel_setups")
        arr = []
        for x, y, z in TUNING["wheel_positions"]:
            ws = unreal.ChaosWheelSetup()
            if wheel_class is not None:
                ws.set_editor_property("wheel_class", wheel_class)
            ws.set_editor_property("bone_name", "")
            ws.set_editor_property("additional_offset",
                                   unreal.Vector(x, y, z))
            arr.append(ws)
        mv.set_editor_property("wheel_setups", arr)
        steps["wheel_setups"] = f"{len(arr)} wheels (BP_Wheel131)"

        bel = getattr(unreal, "BlueprintEditorLibrary", None)
        if bel is not None and hasattr(bel, "compile_blueprint"):
            bel.compile_blueprint(bp)
        al.save_loaded_asset(bp)

        # round-trip verification
        chk = unreal.get_default_object(
            al.load_asset(path).generated_class())
        cmv = chk.get_editor_property("vehicle_movement_component")
        ceng = cmv.get_editor_property("engine_setup")
        ctr = cmv.get_editor_property("transmission_setup")
        cws = cmv.get_editor_property("wheel_setups")
        verify = {
            "mass": cmv.get_editor_property("mass"),
            "max_rpm": ceng.get_editor_property("max_rpm"),
            "max_torque": ceng.get_editor_property("max_torque"),
            "gears": len(ctr.get_editor_property("forward_gear_ratios")),
            "wheels": len(cws),
        }
        RESULT["steps"]["movement"] = f"tuned: {steps}"
        RESULT["steps"]["movement_verify"] = verify
        RESULT["assets"]["vehicle_bp"] = path
        log(f"movement tuned: {verify}")
    except Exception as exc:
        RESULT["errors"]["movement"] = str(exc)
        unreal.log_warning(traceback.format_exc())


def attempt_vehicle_blueprint() -> None:
    """Tier 1: Chaos vehicle Blueprint with a WheeledVehiclePawn parent."""
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
    try:
        make_wheel_blueprint()
    except Exception as exc:
        RESULT["errors"]["wheel_bp"] = f"{exc}"
        unreal.log_warning(traceback.format_exc())
    try:
        tune_chaos_movement()
    except Exception as exc:
        RESULT["errors"]["movement"] = f"{exc}"
        unreal.log_warning(traceback.format_exc())

    with open(os.path.join(HERE, "vehicle_result.json"), "w",
              encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2)
    log(f"done: {RESULT['steps']} errors={list(RESULT['errors'])}")


main()
