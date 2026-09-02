"""CLI: prepare the project + run the headless Unreal import."""

from __future__ import annotations

import argparse
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

    args = p.parse_args(argv)

    if args.cmd == "prepare":
        from ue_ingest import prepare

        project_dir = args.project
        out = prepare(project_dir, args.gltf_dir, args.pbr_dir, args.car)
        print(f"manifest written: {out}")
        return

    from ue_ingest import run_import

    project_dir = os.path.dirname(os.path.abspath(args.project))
    default_script = {"assemble": "assemble_level.py",
                      "import": "ue_script.py"}[args.cmd]
    script = args.script or os.path.join(project_dir, "Content", "Python",
                                         default_script)
    rc = run_import(args.ue_root, args.project, script,
                    log_path=args.log, timeout=args.timeout)
    print(f"editor exit code: {rc}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
