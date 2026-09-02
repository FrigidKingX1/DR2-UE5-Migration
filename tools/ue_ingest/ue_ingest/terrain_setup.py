"""In-editor automation: terrain glTF import + placement in the level."""

import json
import os
import traceback

import unreal

RESULT = {"steps": {}, "errors": []}

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(HERE, "terrain_manifest.json")
LEVEL_PATH = "/Game/Import/Fiat131/L_CarShowroom"


def log(msg: str) -> None:
    unreal.log_warning(f"[terrain] {msg}")


def main() -> None:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    gltf_path = manifest["gltf_file"]
    dest = "/Game/Import/Fiat131/Terrain"

    try:
        task = unreal.AssetImportTask()
        task.filename = gltf_path
        task.destination_path = dest
        task.automated = True
        task.save = True
        task.replace_existing = True
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        al = unreal.EditorAssetLibrary
        # Interchange's pipeline is asynchronous in commandlets: poll the
        # registry for the imported mesh before giving up.
        import time
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        deadline = time.time() + 120.0
        mesh = None
        while time.time() < deadline and mesh is None:
            if al.does_directory_exist(dest):
                for ad in registry.get_assets_by_path(dest, recursive=True):
                    obj = ad.get_asset()
                    if isinstance(obj, unreal.StaticMesh):
                        mesh = obj
                        break
            if mesh is None:
                time.sleep(2.0)
        if mesh is None:
            raise RuntimeError("terrain import produced no static mesh "
                               "(waited 120s)")
        RESULT["steps"]["import"] = mesh.get_path_name()

        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        les.load_level(LEVEL_PATH)
        # spawn_actor_from_object AVs in commandlets; use class+component.
        actor = unreal.get_editor_subsystem(
            unreal.EditorActorSubsystem).spawn_actor_from_class(
                unreal.StaticMeshActor, unreal.Vector(0, 0, 0))
        if actor is not None:
            comp = actor.get_editor_property("static_mesh_component")
            comp.set_static_mesh(mesh)
            actor.set_actor_label("Terrain_AustraliaRally01")
        RESULT["steps"]["spawn"] = (actor.get_actor_label()
                                    if actor is not None else "spawn failed")
        saved = les.save_current_level()
        RESULT["steps"]["save"] = bool(saved)
    except Exception as exc:
        RESULT["errors"].append(f"{exc}")
        unreal.log_warning(traceback.format_exc())

    with open(os.path.join(HERE, "terrain_result.json"), "w",
              encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2)
    log(f"done: {RESULT['steps']} errors={len(RESULT['errors'])}")


main()
