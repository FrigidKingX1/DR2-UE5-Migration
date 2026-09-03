"""In-editor automation: assemble the car in a Lumen-lit showroom level.

Runs inside ``UnrealEditor-Cmd.exe -run=pythonscript`` after the import pass
(``ue_script.py``).  Steps:
1. create (or load) the level ``/Game/Import/Fiat131/L_L_CarShowroom``;
2. spawn a ground plane with the engine grid material;
3. spawn every imported primary StaticMesh at the origin — the glTF exporter
   flattened vertices without node transforms, so origin placement
   reassembles the car (hash-suffixed duplicates are skipped);
4. build the Lumen lighting rig: movable DirectionalLight with
   atmosphere-sun enabled, SkyAtmosphere, VolumetricCloud, real-time-capture
   SkyLight, ExponentialHeightFog and an unbounded PostProcessVolume;
5. save the level and write assemble_result.json next to the manifest.

The pass is idempotent: it first deletes its own previously-spawned actors
(display meshes under MESH_DIR + ground + lighting rig), so re-runs never
stack duplicate layers.  NOTE the showroom does NOT spawn a vehicle here -
the drivable car comes from the GameMode/PlayerStart setup in
``ue_ingest drivable`` (an obsolete BP_Vehicle131 shell at the origin once
broke PIE pawn spawn by its collision).

Every step is defensive (feature-detected across 5.4-5.6 APIs) and reports
into assemble_result.json for headless verification.
"""

import json
import os
import re
import traceback

import unreal

RESULT = {"steps": {}, "errors": [], "actors": {}}

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT_PATH = os.path.join(HERE, "assemble_result.json")

LEVEL_PATH = "/Game/Import/Fiat131/L_CarShowroom"
MESH_DIR = "/Game/Import/Fiat131/Meshes"
GROUND_PATH = "/Game/Import/Fiat131/L_CarShowroom_Ground"

_DUP_SUFFIX = re.compile(r"_[0-9a-f]{32}$")

# Actors this pass owns (mesh/rig/ground/vehicle) get deleted before a
# re-run so the pass is idempotent and never stacks duplicate layers.
_RIG_LABELS = {"Ground", "Sun", "SkyAtmosphere", "VolumetricCloud",
               "SkyLight", "HeightFog", "PostProcess"}
# NOTE: the showroom level no longer spawns the obsolete BP_Vehicle131 shell.
# The drivable car is provided by the GameMode/PlayerStart setup from
# `ue_ingest drivable` (BP_Vehicle131_Drivable); spawning the old shell here
# re-introduced a collision-blocker at the origin that broke PIE spawn.


def log(msg: str) -> None:
    unreal.log_warning(f"[assemble] {msg}")


def fail(step: str, exc: Exception) -> None:
    RESULT["errors"].append(f"{step}: {exc}")
    log(f"FAILED {step}: {exc}")
    unreal.log_warning(traceback.format_exc())


def step_ok(step: str, detail=None) -> None:
    RESULT["steps"][step] = detail if detail is not None else "ok"
    log(f"OK {step}: {detail}")


def _actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def clear_managed_actors() -> int:
    """Delete every actor this pass creates so a re-run is idempotent.

    Without this, re-running assemble (e.g. after a migration or a tweak)
    spawns a whole second layer of 105 overlapping meshes at the origin.
    Matched defensively: display meshes resolve by their asset path under
    MESH_DIR; rig/ground by fixed label.
    """
    sub = _actor_subsystem()
    world = unreal.EditorLevelLibrary.get_editor_world()
    removed = 0
    for actor in unreal.GameplayStatics.get_all_actors_of_class(
            world, unreal.Actor):
        label = actor.get_actor_label() if hasattr(actor, "get_actor_label") \
            else ""
        if label in _RIG_LABELS:
            sub.destroy_actor(actor)
            removed += 1
            continue
        if isinstance(actor, unreal.StaticMeshActor):
            comps = actor.get_components_by_class(unreal.StaticMeshComponent)
            if comps:
                mesh = comps[0].get_editor_property("static_mesh")
                if mesh is not None and mesh.get_path_name().startswith(
                        MESH_DIR):
                    sub.destroy_actor(actor)
                    removed += 1
    if removed:
        log(f"removed {removed} stale actor(s) before rebuild")
    return removed


def _level_subsystem():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def ensure_level() -> str:
    les = _level_subsystem()
    ell = unreal.EditorLevelLibrary
    exists = unreal.EditorAssetLibrary.does_asset_exist(LEVEL_PATH)
    if exists:
        if hasattr(les, "load_level"):
            les.load_level(LEVEL_PATH)
        else:
            ell.load_level(LEVEL_PATH)
        mode = "loaded"
    else:
        if hasattr(les, "new_level"):
            ok = les.new_level(LEVEL_PATH)
        else:
            ok = ell.new_level(LEVEL_PATH)
        mode = f"created={ok}"
    step_ok("level", mode)
    return LEVEL_PATH


def _spawn(actor_class, location, name=None):
    actor = _actor_subsystem().spawn_actor_from_class(actor_class, location)
    if actor is not None and name:
        actor.set_actor_label(name)
    return actor


def spawn_ground() -> object:
    # 3 km plane: the same level doubles as the drivable showroom, and a
    # small floor lets a driven car fall off the edge mid-test (observed).
    ground = _spawn(unreal.StaticMeshActor,
                    unreal.Vector(0, 0, -1.0), "Ground")
    if ground is None:
        raise RuntimeError("ground actor spawn failed")
    mesh = unreal.EditorAssetLibrary.load_asset(
        "/Engine/BasicShapes/Cube.Cube")
    ground.set_actor_scale3d(unreal.Vector(3000.0, 3000.0, 0.05))
    if hasattr(ground, "set_static_mesh_asset"):
        ground.set_static_mesh_asset(mesh)
    comp = ground.get_editor_property("static_mesh_component")
    if comp is not None:
        comp.set_static_mesh(mesh)
        grid = unreal.EditorAssetLibrary.load_asset(
            "/Engine/EngineMaterials/WorldGridMaterial")
        if grid is not None:
            comp.set_material(0, grid)
    step_ok("ground", ground.get_actor_label())
    return ground


def spawn_car(meshes) -> list:
    """Spawn every primary mesh at the origin.

    NOTE: ``spawn_actor_from_object(mesh, ...)`` access-violates inside the
    pythonscript commandlet (EditorFramework AV, observed on 5.5.4), so we
    spawn an empty StaticMeshActor from class and set the mesh on its
    component instead - which is verified safe in the same context.
    """
    spawned = []
    origin = unreal.Vector(0.0, 0.0, 0.0)
    actor_sub = _actor_subsystem()
    seen_paths = set()
    for mesh in meshes:
        name = mesh.get_name()
        if _DUP_SUFFIX.search(name):
            continue  # hash-suffixed duplicates overlap the primary mesh
        path = mesh.get_path_name()
        if path in seen_paths:
            continue  # idempotent even without the hash-suffix convention
        seen_paths.add(path)
        try:
            actor = actor_sub.spawn_actor_from_class(
                unreal.StaticMeshActor, origin)
            if actor is None:
                continue
            comp = actor.get_editor_property("static_mesh_component")
            comp.set_static_mesh(mesh)
            actor.set_actor_label(name)
            spawned.append(actor)
        except Exception as exc:
            log(f"spawn failed for {name}: {exc}")
    step_ok("car", len(spawned))
    return spawned


def spawn_lighting_rig() -> dict:
    rig = {}
    sun = _spawn(unreal.DirectionalLight, unreal.Vector(0, 0, 500),
                 "Sun")
    if sun is not None:
        sun.set_actor_rotation(
            unreal.Rotator(pitch=-40.0, yaw=35.0, roll=0.0), False)
        comp = sun.get_editor_property("light_component")
        comp.set_editor_property("intensity", 10.0)          # lux x1000
        try:
            comp.set_editor_property("use_atmosphere_sun_light", True)
        except Exception:
            pass
        try:
            comp.set_editor_property("cast_shadows", True)
        except Exception:
            pass
        rig["DirectionalLight"] = True

    sky_atmos = _spawn(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0),
                       "SkyAtmosphere")
    rig["SkyAtmosphere"] = sky_atmos is not None

    clouds = _spawn(unreal.VolumetricCloud, unreal.Vector(0, 0, 0),
                    "VolumetricCloud")
    rig["VolumetricCloud"] = clouds is not None

    sky_light = _spawn(unreal.SkyLight, unreal.Vector(0, 0, 300),
                       "SkyLight")
    if sky_light is not None:
        comp = sky_light.get_editor_property("light_component")
        try:
            comp.set_editor_property("real_time_capture", True)
        except Exception:
            pass
        rig["SkyLight"] = True

    fog = _spawn(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0),
                 "HeightFog")
    rig["ExponentialHeightFog"] = fog is not None

    pp = _spawn(unreal.PostProcessVolume, unreal.Vector(0, 0, 0),
                "PostProcess")
    if pp is not None:
        try:
            pp.set_editor_property("unbound", True)
        except Exception:
            pass
        settings = pp.get_editor_property("settings")
        # Lumen GI + reflections are project-default; nudge exposure + bloom
        try:
            settings.set_editor_property(
                "auto_exposure_min_brightness", 0.5)
            settings.set_editor_property(
                "auto_exposure_max_brightness", 2.0)
            pp.set_editor_property("settings", settings)
        except Exception:
            pass
        rig["PostProcessVolume"] = True

    step_ok("lighting_rig", rig)
    return rig


def save_level() -> bool:
    saved = False
    les = _level_subsystem()
    if hasattr(les, "save_current_level"):
        try:
            saved = bool(les.save_current_level())
        except Exception as exc:
            log(f"save_current_level raised: {exc}")
    if not saved:
        try:
            unreal.EditorLevelLibrary.save_current_level()
            saved = True
        except Exception as exc:
            log(f"EditorLevelLibrary.save_current_level raised: {exc}")
    if not saved:
        world = unreal.EditorLevelLibrary.get_editor_world()
        saved = unreal.EditorLoadingAndSavingUtils.save_map(world, LEVEL_PATH)
    step_ok("save", saved)
    return saved


def main() -> None:
    try:
        ensure_level()
        clear_managed_actors()
    except Exception as exc:
        fail("level", exc)
        return

    try:
        spawn_ground()
    except Exception as exc:
        fail("ground", exc)

    meshes = []
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = registry.get_assets_by_path(MESH_DIR, recursive=True)
        for ad in assets:
            obj = ad.get_asset()
            if obj is not None and isinstance(obj, unreal.StaticMesh):
                meshes.append(obj)
    except Exception as exc:
        fail("scan_meshes", exc)
    log(f"found {len(meshes)} static meshes")

    try:
        spawn_car(meshes)
        RESULT["actors"]["car"] = len(meshes)
    except Exception as exc:
        fail("car", exc)

    try:
        spawn_lighting_rig()
    except Exception as exc:
        fail("lighting_rig", exc)

    try:
        save_level()
    except Exception as exc:
        fail("save", exc)

    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2)
    log(f"done: actors={RESULT['actors']} errors={len(RESULT['errors'])}")


main()
