"""In-editor automation: DR2 vehicle audio import + MetaSound authoring.

1. Import the transcoded WAV set as SoundWaves (/Game/Import/<Car>/Audio).
2. Attempt a MetaSound Source via MetaSoundBuilderSubsystem (5.4+): the
   builder API is feature-detected; the graph built here is deliberately
   minimal - one Wave Player bound to the longest engine-candidate wave
   feeding the audio output, so the asset exists and is extendable by the
   human-tuned layer.  Writes audio_result.json.
"""

import json
import os
import traceback

import unreal

RESULT = {"steps": {}, "errors": [], "assets": {}}

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(HERE, "audio_manifest.json")
DEST = None  # set in main from the manifest car


def log(msg: str) -> None:
    unreal.log_warning(f"[audio] {msg}")


def step_ok(step: str, detail=None) -> None:
    RESULT["steps"][step] = detail if detail is not None else "ok"
    log(f"OK {step}: {detail}")


def fail(step: str, exc: Exception) -> None:
    RESULT["errors"].append(f"{step}: {exc}")
    log(f"FAILED {step}: {exc}")
    unreal.log_warning(traceback.format_exc())


def import_soundwaves(manifest) -> dict:
    al = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.SoundFactory()
    dest = DEST + "/Audio"
    imported = {}
    for sound in manifest["sounds"]:
        name = "SM131_" + sound["name"][-12:]  # keep ids bounded
        path = f"{dest}/{name}"
        if al.does_asset_exist(path):
            imported[sound["name"]] = path
            continue
        try:
            task = unreal.AssetImportTask()
            task.filename = sound["file"]
            task.destination_path = dest
            task.destination_name = name
            task.automated = True
            task.save = True
            task.replace_existing = True
            at.import_asset_tasks([task])
            if al.does_asset_exist(path):
                imported[sound["name"]] = path
        except Exception as exc:
            log(f"import failed for {name}: {exc}")
    step_ok("soundwaves", len(imported))
    return imported


def try_meta_sound(imported: dict) -> None:
    """Create the MS_Engine131 MetaSoundSource asset.

    Asset creation via MetaSoundSourceFactory works headlessly.  Graph
    authoring via MetaSoundEditorSubsystem.find_or_begin_building is not
    usable in 5.5.4 commandlets: the returned builder exposes only
    ['count', 'index'] (an unusable Python wrapper), so the engine graph is
    deferred - the asset is in place for the human-tuned layer.
    """
    al = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    path = f"{DEST}/Audio/MS_Engine131"
    if not al.does_asset_exist(path):
        factory = getattr(unreal, "MetaSoundSourceFactory", None)
        if factory is None:
            RESULT["steps"]["metasound"] = "no MetaSoundSourceFactory"
            return
        doc = at.create_asset("MS_Engine131", f"{DEST}/Audio",
                              unreal.MetaSoundSource, factory())
        if doc is None:
            RESULT["steps"]["metasound"] = "create failed"
            return
        al.save_loaded_asset(doc)
    else:
        doc = al.load_asset(path)
    RESULT["steps"]["metasound"] = (
        f"asset created: {doc.get_path_name()} (graph authoring deferred: "
        "builder API unusable in 5.5.4 commandlets)")


def main() -> None:
    global DEST
    with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    DEST = f"/Game/Import/{manifest.get('car_display', 'Fiat131')}"
    log(f"manifest: {manifest['count']} sounds bank={manifest['bank']}")

    try:
        imported = import_soundwaves(manifest)
        RESULT["assets"]["soundwaves"] = len(imported)
    except Exception as exc:
        fail("soundwaves", exc)
        imported = {}

    try:
        try_meta_sound(imported)
    except Exception as exc:
        fail("metasound", exc)

    with open(os.path.join(HERE, "audio_result.json"), "w",
              encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2)
    log(f"done: {RESULT['assets']} errors={len(RESULT['errors'])}")


main()
