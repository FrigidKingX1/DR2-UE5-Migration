"""Tests for the ComfyUI service runner against a fake in-process server.

Covers the HTTP protocol contract (prompt/history/view/free) and input
staging without launching real ComfyUI or touching the GPU.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))

import pytest

from pbr_synth import chord_workflow
from pbr_synth.comfy import ComfyError, ComfyService

FAKE_PNG = b"\x89PNG\r\n\x1a\nFAKE"


class _FakeComfy(BaseHTTPRequestHandler):
    prompt_count = 0

    def log_message(self, *args):  # silence
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/system_stats"):
            self._send(200, b"{}")
        elif self.path.startswith("/history/"):
            if _FakeComfy.prompt_count == 0:
                # first poll: not finished yet
                self._send(200, b"{}")
                _FakeComfy.prompt_count = 1
                return
            entry = {
                "status": {"status_str": "success", "completed": True},
                "outputs": {
                    chord_workflow.NODE_BASECOLOR: {
                        "images": [{"filename": "bc_00001_.png",
                                    "subfolder": "chord", "type": "output"}]},
                },
            }
            self._send(200, json.dumps({"test_prompt": entry}).encode())
        elif self.path.startswith("/view"):
            self._send(200, FAKE_PNG, ctype="image/png")
        else:
            self._send(404, b"{}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if self.path == "/prompt":
            payload = json.loads(body)
            assert "prompt" in payload and "client_id" in payload
            self._send(200, json.dumps({"prompt_id": "test_prompt"}).encode())
        elif self.path == "/free":
            payload = json.loads(body)
            assert payload.get("unload_models") is True
            self._send(200, b"{}")
        else:
            self._send(404, b"{}")


@pytest.fixture(scope="module")
def fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeComfy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


@pytest.fixture()
def service(fake_server, tmp_path):
    (tmp_path / "input").mkdir()
    svc = ComfyService(str(tmp_path), port=fake_server)
    _FakeComfy.prompt_count = 0
    return svc


def test_is_running_and_submit_wait(service):
    assert service.is_running()
    workflow = chord_workflow.build_image_to_material("pbr_synth/x.png")
    entry = service.run(workflow, timeout=5.0, poll_interval=0.05)
    assert entry["status"]["status_str"] == "success"


def test_fetch_output(service):
    workflow = chord_workflow.build_image_to_material("pbr_synth/x.png")
    entry = service.run(workflow, timeout=5.0, poll_interval=0.05)
    blob = service.fetch_output(entry, chord_workflow.NODE_BASECOLOR)
    assert blob == FAKE_PNG


def test_fetch_output_missing_node(service):
    workflow = chord_workflow.build_image_to_material("pbr_synth/x.png")
    entry = service.run(workflow, timeout=5.0, poll_interval=0.05)
    with pytest.raises(ComfyError, match="no images"):
        service.fetch_output(entry, "999")


def test_stage_input(service, tmp_path):
    src = tmp_path / "src.png"
    src.write_bytes(FAKE_PNG)
    staged = service.stage_input(str(src), "131_main_d.png")
    assert staged == "pbr_synth/131_main_d.png"
    copied = tmp_path / "input" / "pbr_synth" / "131_main_d.png"
    assert copied.read_bytes() == FAKE_PNG


def test_free_memory(service):
    service.free_memory()  # must not raise


def test_prompt_rejection(tmp_path):
    class _Reject(_FakeComfy):
        def do_POST(self):
            if self.path == "/prompt":
                self._send(400, json.dumps({"error": "bad graph"}).encode())
            else:
                super().do_POST()

        def do_GET(self):
            if self.path.startswith("/system_stats"):
                self._send(200, b"{}")
            else:
                super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Reject)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (tmp_path / "input").mkdir()
        svc = ComfyService(str(tmp_path), port=server.server_address[1])
        with pytest.raises(Exception) as exc:
            svc.submit({"1": {}})  # rejected -> urllib raises HTTPError
        assert "400" in str(exc.value) or "Bad Request" in str(exc.value)
    finally:
        server.shutdown()
