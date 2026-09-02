"""ComfyUI headless service runner.

Launches ComfyUI as a subprocess, dispatches API-format workflow graphs to
``POST /prompt``, polls ``GET /history/{prompt_id}`` for completion, fetches
output images via ``GET /view``, and releases VRAM via ``POST /free``.

No websocket dependency: polling the history endpoint is sufficient for batch
orchestration and keeps the runner dependency-free (urllib stdlib only).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ComfyError(Exception):
    pass


class ComfyService:
    """Context manager around a headless ComfyUI process."""

    def __init__(self, comfy_dir: str, port: int = 8188,
                 extra_args: list | None = None,
                 python_exe: str | None = None,
                 start_timeout: float = 300.0):
        self.comfy_dir = comfy_dir
        self.port = port
        self.extra_args = extra_args or ["--highvram"]
        self.python_exe = python_exe or sys.executable
        self.start_timeout = start_timeout
        self.proc: subprocess.Popen | None = None
        self.client_id = uuid.uuid4().hex
        self._log_tail: list[str] = []

    # -- process lifecycle ---------------------------------------------------

    def start(self) -> None:
        if self.is_running():
            return
        cmd = [self.python_exe, "main.py",
               "--listen", "127.0.0.1", "--port", str(self.port),
               *self.extra_args]
        self.proc = subprocess.Popen(
            cmd, cwd=self.comfy_dir,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        # Continuously collect stdout in a daemon thread: readline() blocks
        # while the process is alive, so it can never be drained inline.
        self._log_thread = threading.Thread(target=self._pump_log, daemon=True)
        self._log_thread.start()
        self._wait_ready()

    def _pump_log(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self._log_tail.append(line.rstrip())
            if len(self._log_tail) > 200:
                self._log_tail.pop(0)

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise ComfyError(
                    "ComfyUI exited during startup:\n" + "\n".join(self._log_tail[-30:]))
            try:
                self.get("/system_stats", timeout=2.0)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(1.0)
        raise ComfyError(f"ComfyUI not ready after {self.start_timeout:.0f}s"
                         + "\n".join(self._log_tail[-30:]))

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def is_running(self) -> bool:
        try:
            self.get("/system_stats", timeout=2.0)
            return True
        except (urllib.error.URLError, OSError):
            return False

    def __enter__(self) -> "ComfyService":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- HTTP ----------------------------------------------------------------

    def _url(self, path: str, **params) -> str:
        url = f"http://127.0.0.1:{self.port}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def get(self, path: str, timeout: float = 30.0, **params):
        with urllib.request.urlopen(self._url(path, **params),
                                    timeout=timeout) as resp:
            return resp.read()

    def get_json(self, path: str, timeout: float = 30.0, **params):
        return json.loads(self.get(path, timeout=timeout, **params))

    def post_json(self, path: str, payload: dict, timeout: float = 60.0):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    # -- workflow dispatch ---------------------------------------------------

    def stage_input(self, src_path: str, name: str) -> str:
        """Copy a file into ComfyUI's input folder. Returns the staged name."""
        input_dir = os.path.join(self.comfy_dir, "input", "pbr_synth")
        os.makedirs(input_dir, exist_ok=True)
        staged = f"pbr_synth/{name}"
        shutil.copyfile(src_path, os.path.join(self.comfy_dir, "input", staged))
        return staged

    def submit(self, workflow: dict) -> str:
        payload = {"prompt": workflow, "client_id": self.client_id}
        result = self.post_json("/prompt", payload)
        if "prompt_id" not in result:
            raise ComfyError(f"prompt rejected: {result}")
        return result["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 900.0,
             poll_interval: float = 1.0) -> dict:
        """Poll /history until the prompt completes. Returns the history entry."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = self.get_json(f"/history/{prompt_id}", timeout=10.0)
            entry = history.get(prompt_id)
            if entry is not None:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", [])
                            if m and m[0] == "execution_error"]
                    raise ComfyError(f"workflow failed: {msgs or status}")
                return entry
            time.sleep(poll_interval)
        raise ComfyError(f"workflow {prompt_id} timed out after {timeout:.0f}s")

    def run(self, workflow: dict, timeout: float = 900.0,
            poll_interval: float = 1.0) -> dict:
        """Submit + wait. Returns the history entry with outputs."""
        return self.wait(self.submit(workflow), timeout=timeout,
                         poll_interval=poll_interval)

    def fetch_output(self, entry: dict, node_id: str) -> bytes:
        """Download the first output image of a SaveImage node."""
        images = entry.get("outputs", {}).get(node_id, {}).get("images", [])
        if not images:
            raise ComfyError(f"node {node_id} produced no images")
        img = images[0]
        return self.get("/view", timeout=120.0, filename=img["filename"],
                        subfolder=img.get("subfolder", ""),
                        **{"type": img.get("type", "output")})

    def free_memory(self) -> None:
        try:
            # /free may answer with an empty/non-JSON body: parse leniently.
            data = json.dumps({"unload_models": True,
                               "free_memory": True}).encode("utf-8")
            req = urllib.request.Request(
                self._url("/free"), data=data,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                resp.read()
        except (urllib.error.URLError, OSError, ValueError):
            pass
