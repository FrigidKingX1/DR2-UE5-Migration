"""In-editor automation: DR2 vehicle audio import + MetaSound authoring.

1. Import the transcoded WAV set as SoundWaves (/Game/Import/<Car>/Audio).
2. Author the MS_Engine131 MetaSoundSource graph headlessly: one looping
   Wave Player bound to the longest (engine) SoundWave, wired from the
   source On Play trigger to the wave player and its stereo output to the
   root Output.  Writes audio_result.json.

Headless-landmine notes (UE 5.5.4 commandlet):
- MetaSoundEditorSubsystem.find_or_begin_building returns a (builder,
  result) TUPLE - unpacking it was the step the earlier attempt missed.
- build_to_asset crashes (Slate overwrite dialog) if the target name
  already exists, and rename_asset/delete_asset on a built MetaSound
  access-violates in UnrealEd.  So we seed the builder from a throwaway
  'MS_Seed' skeleton and build directly into the free 'MS_Engine131' slot,
  never renaming or deleting the built asset afterward.
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


def _make_literal(text: str):
    """Build a typed FMetasoundFrontendLiteral from its serialized text.

    The literal struct stores its payload in protected (non-EditAnywhere)
    UPROPERTY fields, so Python cannot set them directly; import_text parses
    the canonical struct-export form, e.g.
    "(Type=Boolean,AsBoolean=(True))" or an object reference
    "(Type=UObject,AsUObject=(\"/Script/Engine.SoundWave'/Game/...'\"))".
    Round-trip verified: set_node_input_default stores the typed value.
    """
    lit = unreal.MetasoundFrontendLiteral()
    lit.import_text(text)
    return lit


def _wave_asset_literal(soundwave_path: str):
    return _make_literal(
        '(Type=UObject,AsUObject=("/Script/Engine.SoundWave\'%s\'"))'
        % soundwave_path)


def author_engine_metasound(engine_wave_path: str, dest: str) -> str:
    """Build MS_Engine131 with one looping Wave Player on the engine WAV.

    The builder is seeded from the throwaway 'MS_Seed' skeleton created by
    the caller, and the graph is committed via build_to_asset DIRECTLY into
    the free 'MS_Engine131' name.  build_to_asset crashes headlessly (Slate
    overwrite dialog) if the target name already exists, and rename/delete
    of a built MetaSound also crashes (UnrealEd AV), so we avoid both:
    the skeleton never occupies the canonical name, and we never rename or
    delete the built asset.
    Returns the final asset path on success, else "".
    """
    mes = unreal.get_editor_subsystem(unreal.MetaSoundEditorSubsystem)
    al = unreal.EditorAssetLibrary
    builder, _ = mes.find_or_begin_building(
        al.load_asset(f"{dest}/MS_Seed"))

    ok_steps = []
    wp, res = builder.add_node_by_class_name(
        unreal.MetasoundFrontendClassName("UE", "Wave Player", "Stereo"))
    ok_steps.append(("add WavePlayer", res == unreal.MetaSoundBuilderResult.SUCCEEDED))

    # source On Play trigger -> Wave Player Play
    onplay_nodes, _ = builder.find_interface_input_nodes("UE.Source")
    onplay_out, res = builder.find_node_output_by_name(
        onplay_nodes[0], "UE.Source.OnPlay")
    ok_steps.append(("OnPlay out", res == unreal.MetaSoundBuilderResult.SUCCEEDED))

    # stereo audio -> root Output Left/Right
    builder.add_graph_output_node("Output Left", "Audio",
                                  unreal.MetasoundFrontendLiteral(), False)
    builder.add_graph_output_node("Output Right", "Audio",
                                  unreal.MetasoundFrontendLiteral(), False)

    wp_play, _ = builder.find_node_input_by_name(wp, "Play")
    wp_wave, _ = builder.find_node_input_by_name(wp, "Wave Asset")
    wp_loop, _ = builder.find_node_input_by_name(wp, "Loop")
    wp_outl, _ = builder.find_node_output_by_name(wp, "Out Left")
    wp_outr, _ = builder.find_node_output_by_name(wp, "Out Right")

    ok_steps.append(("OnPlay->Play",
        builder.connect_nodes(onplay_out, wp_play) ==
        unreal.MetaSoundBuilderResult.SUCCEEDED))
    ok_steps.append(("OutLeft",
        builder.connect_node_output_to_graph_output("Output Left", wp_outl) ==
        unreal.MetaSoundBuilderResult.SUCCEEDED))
    ok_steps.append(("OutRight",
        builder.connect_node_output_to_graph_output("Output Right", wp_outr) ==
        unreal.MetaSoundBuilderResult.SUCCEEDED))
    ok_steps.append(("Loop=True",
        builder.set_node_input_default(
            wp_loop, _make_literal("(Type=Boolean,AsBoolean=(True))")) ==
        unreal.MetaSoundBuilderResult.SUCCEEDED))
    ok_steps.append(("Wave Asset",
        builder.set_node_input_default(
            wp_wave, _wave_asset_literal(engine_wave_path)) ==
        unreal.MetaSoundBuilderResult.SUCCEEDED))

    # commit directly into the free canonical name (no collision, no rename)
    ret = mes.build_to_asset(builder, "DR2 Migration",
                             "MS_Engine131", dest)
    new_object = ret[0] if isinstance(ret, tuple) else ret
    out_res = ret[1] if isinstance(ret, tuple) else None
    summary = ",".join(f"{n}:{'y' if s else 'n'}" for n, s in ok_steps)
    if out_res is None or out_res != unreal.MetaSoundBuilderResult.SUCCEEDED:
        RESULT["steps"]["metasound"] = f"build_to_asset FAILED; {summary}"
        return ""
    al.save_loaded_asset(new_object)
    RESULT["steps"]["metasound"] = "graph authored: " + summary
    return new_object.get_path_name()


def try_meta_sound(imported: dict) -> None:
    """Create MS_Engine131 + author the engine WavePlayer graph."""
    al = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()

    # Free the canonical slot AND seed the builder from a throwaway skeleton.
    # Do NOT delete/rename built MetaSounds (crashes headlessly in UnrealEd).
    if al.does_asset_exist(f"{DEST}/Audio/MS_Engine131"):
        al.delete_asset(f"{DEST}/Audio/MS_Engine131")
    factory = getattr(unreal, "MetaSoundSourceFactory", None)
    if factory is None:
        RESULT["steps"]["metasound"] = "no MetaSoundSourceFactory"
        return
    if not al.does_asset_exist(f"{DEST}/Audio/MS_Seed"):
        seed = at.create_asset("MS_Seed", f"{DEST}/Audio",
                               unreal.MetaSoundSource, factory())
        if seed is None:
            RESULT["steps"]["metasound"] = "seed create failed"
            return

    # pick the engine candidate: prefer the longest SoundWave in the Audio dir
    engine_wave = None
    longest = -1
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    for ad in reg.get_assets_by_path(f"{DEST}/Audio", recursive=True):
        obj = ad.get_asset()
        if obj is None or obj.get_class().get_name() != "SoundWave":
            continue
        try:
            dur = float(obj.get_duration())
        except Exception:
            dur = float(getattr(obj, "duration", 0) or 0)
        if dur > longest:
            longest, engine_wave = dur, obj
    if engine_wave is None:
        RESULT["steps"]["metasound"] = "no SoundWave to bind"
        return
    log(f"engine candidate: {engine_wave.get_path_name()} "
        f"(duration {longest:.2f}s)")
    author_engine_metasound(engine_wave.get_path_name(), f"{DEST}/Audio")


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
