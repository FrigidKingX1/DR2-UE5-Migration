"""CLI: prepare the project + run the headless Unreal import."""

from __future__ import annotations

import argparse
import json
import os
import sys


def main(argv=None) -> None:
    p = argparse.ArgumentParser(
        prog="ue_ingest",
        description="Headless UE5 ingest of the DR2 migration output")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("prepare", help="write manifest.json into the project")
    pp.add_argument("--project", required=True,
                    help="project dir containing <Name>.uproject")
    pp.add_argument("--gltf-dir", required=True,
                    help="pssg_convert gltf output folder")
    pp.add_argument("--pbr-dir", required=True,
                    help="pbr_synth output folder")
    pp.add_argument("--car", default=None, help="car prefix (default: derive)")

    pi = sub.add_parser("import", help="run headless UnrealEditor-Cmd import")
    pi.add_argument("--project", required=True)
    pi.add_argument("--ue-root", required=True,
                    help="engine root, e.g. G:\\UE5\\UE_5.5")
    pi.add_argument("--script", default=None,
                    help="python script (default: <project>/Content/Python/ue_script.py)")
    pi.add_argument("--log", default=None)
    pi.add_argument("--timeout", type=float, default=3600.0)

    pa = sub.add_parser("assemble", help="assemble the car in a Lumen level")
    pa.add_argument("--project", required=True)
    pa.add_argument("--ue-root", required=True,
                    help="engine root, e.g. G:\\UE5\\UE_5.5")
    pa.add_argument("--script", default=None,
                    help="python script (default: <project>/Content/Python/assemble_level.py)")
    pa.add_argument("--log", default=None)
    pa.add_argument("--timeout", type=float, default=3600.0)

    pv = sub.add_parser("vehicle", help="import vehicle physics config")
    pv.add_argument("--project", required=True)
    pv.add_argument("--ue-root", required=True,
                    help="engine root, e.g. G:\\UE5\\UE_5.5")
    pv.add_argument("--config", required=True,
                    help="vehicle_config.json from ctf_convert ai-to-config")
    pv.add_argument("--script", default=None)
    pv.add_argument("--log", default=None)
    pv.add_argument("--timeout", type=float, default=3600.0)

    pau = sub.add_parser("audio", help="import WAVs + attempt MetaSound")
    pau.add_argument("--project", required=True)
    pau.add_argument("--ue-root", required=True,
                     help="engine root, e.g. G:\\UE5\\UE_5.5")
    pau.add_argument("--wav-dir", required=True,
                     help="folder of transcoded .wav files")
    pau.add_argument("--car", default="131")
    pau.add_argument("--engine-wave", default=None,
                     help="WAV file stem of the user-picked engine loop "
                          "(by-ear choice from Listen_Here); overrides the "
                          "longest-wave heuristic")
    pau.add_argument("--script", default=None)
    pau.add_argument("--log", default=None)
    pau.add_argument("--timeout", type=float, default=3600.0)

    pt = sub.add_parser("terrain", help="import terrain glTF + place in level")
    pt.add_argument("--project", required=True)
    pt.add_argument("--ue-root", required=True,
                    help="engine root, e.g. G:\\UE5\\UE_5.5")
    pt.add_argument("--gltf", required=True,
                    help="terrain glTF from heightfield_extract --gltf")
    pt.add_argument("--script", default=None)
    pt.add_argument("--log", default=None)
    pt.add_argument("--timeout", type=float, default=3600.0)

    pd = sub.add_parser("drivable",
                        help="make L_CarShowroom drivable (template pawn + "
                             "GameMode + PlayerStart)")
    pd.add_argument("--project", required=True)
    pd.add_argument("--ue-root", required=True,
                    help="engine root, e.g. G:\\UE5\\UE_5.5")
    pd.add_argument("--script", default=None)
    pd.add_argument("--log", default=None)
    pd.add_argument("--timeout", type=float, default=3600.0)

    args = p.parse_args(argv)

    if args.cmd == "prepare":
        from ue_ingest import prepare

        project_dir = args.project
        out = prepare(project_dir, args.gltf_dir, args.pbr_dir, args.car)
        print(f"manifest written: {out}")
        return

    from ue_ingest import run_import

    project_dir = os.path.dirname(os.path.abspath(args.project))
    python_dir = os.path.join(project_dir, "Content", "Python")
    os.makedirs(python_dir, exist_ok=True)

    if args.cmd == "vehicle":
        import shutil
        shutil.copyfile(os.path.abspath(args.config),
                        os.path.join(python_dir, "vehicle_config.json"))
        shutil.copyfile(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "vehicle_config.py"),
            os.path.join(python_dir, "vehicle_config.py"))
        # generate per-surface curve CSVs (curve-editor export format) for
        # ReimportCurveFactory automated import
        with open(os.path.join(python_dir, "vehicle_config.json"), "r",
                  encoding="utf-8") as fh:
            config = json.load(fh)
        surfaces = {code: s.get("grip", {}).get("speed_distances") or []
                    for code, s in config.get("surfaces", {}).items()}
        surfaces = {c: s for c, s in surfaces.items() if s}
        if surfaces:
            csv_dir = os.path.join(python_dir, "curves_csv")
            os.makedirs(csv_dir, exist_ok=True)
            for code, samples in surfaces.items():
                csv_path = os.path.join(csv_dir, f"CF_Brake_{code}.csv")
                with open(csv_path, "w", encoding="utf-8") as fh:
                    fh.write(",X,Y\n")
                    for smp in sorted(samples,
                                      key=lambda x: x["speed_mps"]):
                        fh.write(f",{smp['speed_mps']},{smp['distance_m']}\n")
        script = args.script or os.path.join(python_dir, "vehicle_config.py")
    elif args.cmd == "audio":
        import shutil
        tools_dir = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        sibling = os.path.join(tools_dir, "pbr_synth")
        if os.path.isdir(sibling) and sibling not in sys.path:
            sys.path.insert(0, sibling)
        from ue_ingest.audio_prep import write_audio_manifest
        from pbr_synth import reconcile
        manifest = write_audio_manifest(
            args.wav_dir, os.path.join(python_dir, "audio_manifest.json"),
            bank_name="s_mech")
        with open(manifest, "r", encoding="utf-8") as fh:
            audio = json.load(fh)
        audio["car_display"] = reconcile.display_car_name(args.car)
        if args.engine_wave:
            audio["engine_wave"] = args.engine_wave
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(audio, fh, indent=2)
        shutil.copyfile(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "audio_setup.py"),
            os.path.join(python_dir, "audio_setup.py"))
        script = args.script or os.path.join(python_dir, "audio_setup.py")
    elif args.cmd == "terrain":
        import shutil
        gltf_abs = os.path.abspath(args.gltf)
        gltf_name = os.path.basename(gltf_abs)
        bin_name = os.path.splitext(gltf_name)[0] + ".bin"
        shutil.copyfile(gltf_abs, os.path.join(python_dir, gltf_name))
        shutil.copyfile(os.path.splitext(gltf_abs)[0] + ".bin",
                        os.path.join(python_dir, bin_name))
        with open(os.path.join(python_dir, "terrain_manifest.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"gltf_file": os.path.join(python_dir, gltf_name)},
                      fh)
        shutil.copyfile(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "terrain_setup.py"),
            os.path.join(python_dir, "terrain_setup.py"))
        script = args.script or os.path.join(python_dir, "terrain_setup.py")
    elif args.cmd == "drivable":
        import shutil
        # copy the engine Vehicle Advanced template assets if not present
        template_root = os.path.join(args.ue_root, "Templates")
        content_root = os.path.join(project_dir, "Content")
        src_veh = os.path.join(template_root, "TemplateResources",
                               "Standard", "Vehicles", "Content")
        src_tpl = os.path.join(template_root, "TP_VehicleAdvBP", "Content",
                               "VehicleTemplate")
        if not os.path.isdir(os.path.join(content_root, "Vehicles",
                                           "OffroadCar")):
            # the FeaturePack's internal refs expect /Game/Vehicles/...
            # (SharedContentPacks MountName="Vehicles" in TemplateDefs.ini)
            os.makedirs(os.path.join(content_root, "Vehicles"),
                        exist_ok=True)
            shutil.copytree(os.path.join(src_veh, "OffroadCar"),
                            os.path.join(content_root, "Vehicles",
                                         "OffroadCar"))
            shutil.copytree(os.path.join(src_veh, "PhysicsMaterials"),
                            os.path.join(content_root, "Vehicles",
                                         "PhysicsMaterials"))
        if not os.path.isdir(os.path.join(content_root, "VehicleTemplate")):
            shutil.copytree(src_tpl,
                            os.path.join(content_root, "VehicleTemplate"))
        # guaranteed GameMode fallback (world-settings override may fail)
        ini_path = os.path.join(project_dir, "Config", "DefaultGame.ini")
        line = ("[/Script/EngineSettings.GameMapsSettings]\n"
                "GlobalDefaultGameMode=/Game/Import/Vehicle/GM_Vehicle131"
                ".GM_Vehicle131_C\n")
        if not (os.path.exists(ini_path) and line.splitlines()[1]
                in open(ini_path, encoding="utf-8").read()):
            with open(ini_path, "a", encoding="utf-8") as fh:
                fh.write(("\n" if os.path.exists(ini_path) else "") + line)
        shutil.copyfile(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "drivable_setup.py"),
            os.path.join(python_dir, "drivable_setup.py"))
        script = args.script or os.path.join(python_dir, "drivable_setup.py")
    else:
        default_script = {"assemble": "assemble_level.py",
                          "import": "ue_script.py"}[args.cmd]
        script = args.script or os.path.join(python_dir, default_script)
    rc = run_import(args.ue_root, args.project, script,
                    log_path=args.log, timeout=args.timeout)
    print(f"editor exit code: {rc}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
