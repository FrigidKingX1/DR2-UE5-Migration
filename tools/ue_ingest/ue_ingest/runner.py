"""Headless UnrealEditor-Cmd invocation."""

from __future__ import annotations

import glob
import os
import subprocess


def find_unreal_editor_cmd(ue_root: str) -> str:
    """Locate UnrealEditor-Cmd.exe under an engine root (or glob hint)."""
    for pattern in (
        os.path.join(ue_root, "Engine", "Binaries", "Win64",
                     "UnrealEditor-Cmd.exe"),
        os.path.join(ue_root, "*", "Engine", "Binaries", "Win64",
                     "UnrealEditor-Cmd.exe"),
    ):
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    raise FileNotFoundError(f"UnrealEditor-Cmd.exe not found under {ue_root}")


def run_import(ue_root: str, project_file: str, script_path: str,
               log_path: str | None = None, timeout: float = 3600.0) -> int:
    """Run a python script inside a headless editor commandlet."""
    exe = find_unreal_editor_cmd(ue_root)
    project_file = os.path.abspath(project_file)
    script_path = os.path.abspath(script_path)
    if log_path is None:
        log_path = os.path.join(os.path.dirname(project_file), "Saved",
                                "Logs", "ue_ingest.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    cmd = [
        exe, project_file,
        "-run=pythonscript",
        f"-script={script_path}",
        "-unattended", "-nopause", "-nosplash", "-nocompile",
        "-stdout", "-ForceLogFlush",
        f"-ABSLOG={log_path}",
    ]
    print("running:", " ".join(cmd))
    proc = subprocess.run(cmd, timeout=timeout)
    return proc.returncode
