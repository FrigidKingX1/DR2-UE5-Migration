"""In-editor automation: make L_CarShowroom drivable.

Strategy: Blueprint graph authoring is impossible headlessly, so we reuse
the engine's Vehicle Advanced template assets (copied into Content by the
CLI runner) whose input wiring is pre-built:

- /Game/VehicleTemplate/Blueprints/VehiclePlayerController  (adds
  IMC_Default + binds IA_Throttle/Brake/Steering/Handbrake to the Chaos
  movement component in pre-authored graphs)
- /Game/VehicleTemplate/Blueprints/OffroadCar/OffroadCar_Pawn (Chaos
  vehicle pawn with skeletal mesh + physics asset + camera rig)

This pass duplicates OffroadCar_Pawn as BP_Vehicle131_Drivable, creates
GM_Vehicle131 (GameMode with the template controller + our pawn), spawns
a PlayerStart in L_CarShowroom, and best-effort retargets the pawn's
engine audio to MS_Engine131.  The Fiat 131 body swap (static mesh ->
skeletal mesh + physics asset) is a documented residual.

Writes drivable_result.json next to this script.
"""

import json
import os
import traceback

import unreal

RESULT = {"steps": {}, "errors": {}, "assets": {}}
HERE = os.path.dirname(os.path.abspath(__file__))

TEMPLATE_DIR = "/Game/VehicleTemplate"
PAWN_SRC = f"{TEMPLATE_DIR}/Blueprints/OffroadCar/OffroadCar_Pawn"
CTRL_SRC = f"{TEMPLATE_DIR}/Blueprints/VehiclePlayerController"
LEVEL_PATH = "/Game/Import/Fiat131/L_CarShowroom"
ENGINE_MS = "/Game/Import/Fiat131/Audio/MS_Engine131"


def log(msg: str) -> None:
    unreal.log_warning(f"[drivable] {msg}")


def _al():
    return unreal.EditorAssetLibrary


def duplicate_pawn() -> str:
    al = _al()
    path = "/Game/Import/Vehicle/BP_Vehicle131_Drivable"
    if al.does_asset_exist(path):
        RESULT["steps"]["pawn"] = f"exists: {path}"
        return path
    if not al.does_asset_exist(PAWN_SRC):
        RESULT["errors"]["pawn"] = f"template pawn missing: {PAWN_SRC}"
        return ""
    dup = al.duplicate_asset(PAWN_SRC, path)
    if dup is None or not al.does_asset_exist(path):
        RESULT["errors"]["pawn"] = "duplicate failed"
        return ""
    al.save_loaded_asset(dup)
    RESULT["steps"]["pawn"] = f"duplicated: {path}"
    RESULT["assets"]["pawn"] = path
    return path


def make_game_mode(pawn_path: str) -> str:
    al = _al()
    path = "/Game/Import/Vehicle/GM_Vehicle131"
    if not _al().does_asset_exist(path):
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", unreal.GameModeBase)
        gm = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "GM_Vehicle131", "/Game/Import/Vehicle", None, factory)
        if gm is None:
            RESULT["errors"]["game_mode"] = "create failed"
            return ""
    gm = al.load_asset(path)
    cdo = unreal.get_default_object(gm.generated_class())
    pawn_cls = al.load_asset(pawn_path).generated_class()
    ctrl_cls = al.load_asset(CTRL_SRC).generated_class()
    # modify() marks the CDO for serialization; compile_blueprint after the
    # writes RESETS the CDO from the stored template (writes lost), so save
    # WITHOUT compiling - a graph-less GameMode needs no recompile.
    cdo.modify()
    cdo.set_editor_property("default_pawn_class", pawn_cls)
    cdo.set_editor_property("player_controller_class", ctrl_cls)
    al.save_loaded_asset(gm)
    RESULT["steps"]["game_mode"] = (
        f"created+tuned: {path} pawn={pawn_cls.get_name()} "
        f"ctrl={ctrl_cls.get_name()}")
    RESULT["assets"]["game_mode"] = path
    return path


def retarget_engine_audio(pawn_path: str) -> None:
    """Best-effort: point any AudioComponent sound on the pawn CDO at
    MS_Engine131.  The template pawn may bind engine sound via its AnimBP
    instead, in which case we record that and leave the template sound."""
    try:
        al = _al()
        ms = al.load_asset(ENGINE_MS)
        if ms is None:
            RESULT["errors"]["engine_audio"] = "MS_Engine131 missing"
            return
        cdo = unreal.get_default_object(
            al.load_asset(pawn_path).generated_class())
        comps = []
        try:
            comps = unreal.ComponentUtils.get_components_of_class(
                cdo, unreal.AudioComponent, recursive=True)
        except Exception:
            pass
        if not comps:
            RESULT["steps"]["engine_audio"] = (
                "no AudioComponent on pawn CDO (sound likely driven by "
                "AnimBP); template engine sound kept")
            return
        applied = 0
        for comp in comps:
            try:
                cur = comp.get_editor_property("sound")
                comp.set_editor_property("sound", ms)
                applied += 1
                log(f"audio comp {comp.get_name()} "
                    f"was={cur} -> MS_Engine131")
            except Exception as exc:
                RESULT["errors"][f"audio_{comp.get_name()}"] = str(exc)
        RESULT["steps"]["engine_audio"] = f"rebound {applied} audio comps"
    except Exception:
        RESULT["errors"]["engine_audio"] = traceback.format_exc()[-400:]


def spawn_engine_ambient() -> None:
    """Static looping MS_Engine131 at the showroom centre (the pawn has no
    attachable AudioComponent; positional audio placeholder until the body
    swap lands)."""
    try:
        ms = _al().load_asset(ENGINE_MS)
        if ms is None:
            RESULT["errors"]["engine_ambient"] = "MS_Engine131 missing"
            return
        actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        world = unreal.EditorLevelLibrary.get_editor_world()
        for old in unreal.GameplayStatics.get_all_actors_of_class(
                world, unreal.AmbientSound):
            try:
                actor_sub.destroy_actor(old)
            except Exception:
                pass
        amb = actor_sub.spawn_actor_from_class(
            unreal.AmbientSound, unreal.Vector(0.0, 0.0, 200.0))
        if amb is None:
            RESULT["errors"]["engine_ambient"] = "spawn failed"
            return
        amb.set_actor_label("EngineLoop131")
        comp = amb.get_editor_property("audio_component")
        if comp is not None:
            comp.set_editor_property("sound", ms)
        RESULT["steps"]["engine_ambient"] = "spawned (positional loop)"
    except Exception as exc:
        RESULT["errors"]["engine_ambient"] = str(exc)


def setup_level() -> None:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    les.load_level(LEVEL_PATH)

    # PlayerStart above the ground plane (dedupe: one per run accumulates)
    actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = unreal.EditorLevelLibrary.get_editor_world()
    for old in unreal.GameplayStatics.get_all_actors_of_class(
            world, unreal.PlayerStart):
        try:
            actor_sub.destroy_actor(old)
        except Exception:
            pass
    ps = actor_sub.spawn_actor_from_class(
        unreal.PlayerStart, unreal.Vector(0.0, 0.0, 150.0))
    if ps is not None:
        ps.set_actor_label("PlayerStart131")
        RESULT["steps"]["player_start"] = "spawned"
    else:
        RESULT["errors"]["player_start"] = "spawn failed"

    # level-wide GameMode override on WorldSettings
    try:
        ws = world.get_world_settings()
        gm_cls = unreal.load_asset(
            "/Game/Import/Vehicle/GM_Vehicle131").generated_class()
        ws.set_editor_property("default_game_mode", gm_cls)
        RESULT["steps"]["game_mode_override"] = "world settings set"
    except Exception as exc:
        RESULT["errors"]["game_mode_override"] = str(exc)

    saved = bool(les.save_current_level())
    RESULT["steps"]["save_level"] = saved


def main() -> None:
    pawn_path = duplicate_pawn()
    if not pawn_path:
        _write()
        return
    gm_path = make_game_mode(pawn_path)
    if gm_path:
        try:
            setup_level()
        except Exception as exc:
            RESULT["errors"]["level"] = str(exc)
            unreal.log_warning(traceback.format_exc())
        try:
            retarget_engine_audio(pawn_path)
        except Exception as exc:
            RESULT["errors"]["engine_audio"] = str(exc)
        try:
            spawn_engine_ambient()
            # re-save so the ambient actor persists
            try:
                les = unreal.get_editor_subsystem(
                    unreal.LevelEditorSubsystem)
                les.save_current_level()
            except Exception:
                pass
        except Exception as exc:
            RESULT["errors"]["engine_ambient"] = str(exc)
    _write()


def _write() -> None:
    with open(os.path.join(HERE, "drivable_result.json"), "w",
              encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2)
    log(f"done: steps={list(RESULT['steps'])} "
        f"errors={list(RESULT['errors'])}")


main()
