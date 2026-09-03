"""ue_live: connect to a RUNNING Unreal editor via Python Remote Execution.

Implements the PythonScriptPlugin remote-execution protocol (UE 5.5):
- UDP multicast discovery on 239.0.0.1:6766 (magic "ue_py", version 1)
- open_connection asks the editor to dial back to our TCP listener
- command messages execute Python in the live editor (incl. during PIE)

CLI:
  python -m ue_live state          # dump PIE/vehicle diagnostics
  python -m ue_live run <file.py>  # execute a script in the live editor
"""

import json
import socket
import struct
import sys
import threading
import time
import uuid

MULTICAST_GROUP = "239.0.0.1"
MULTICAST_PORT = 6766
MAGIC = "ue_py"
VERSION = 1


def _msg(type_, source, dest=None, data=None):
    m = {"version": VERSION, "magic": MAGIC, "type": type_, "source": source}
    if dest:
        m["dest"] = dest
    if data is not None:
        m["data"] = data
    return json.dumps(m).encode("utf-8")


class LiveEditor:
    """Discover + connect to a running UE editor, execute Python live."""

    def __init__(self, timeout=8.0):
        self.source = "opencode-" + uuid.uuid4().hex[:8]
        self.editor = None       # pong data
        self.editor_id = None
        self.sock = None         # accepted TCP command channel
        self.timeout = timeout

    # ---- discovery -------------------------------------------------------
    def discover(self):
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx.bind(("127.0.0.1", MULTICAST_PORT))
        mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton("127.0.0.1")
        rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        rx.settimeout(0.5)

        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        deadline = time.time() + self.timeout
        while time.time() < deadline and self.editor is None:
            tx.sendto(_msg("ping", self.source),
                      (MULTICAST_GROUP, MULTICAST_PORT))
            try:
                while True:
                    raw, _ = rx.recvfrom(65536)
                    msg = json.loads(raw.decode("utf-8", "replace"))
                    if msg.get("type") == "pong" and \
                            msg.get("dest") == self.source:
                        self.editor = msg.get("data") or {}
                        self.editor_id = msg.get("source")
                        break
            except socket.timeout:
                continue
        tx.close()
        rx.close()
        return self.editor is not None

    # ---- command channel -------------------------------------------------
    def connect(self, listen_port=0):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", listen_port))
        srv.listen(1)
        port = srv.getsockname()[1]
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.sendto(_msg("open_connection", self.source, dest=self.editor_id,
                       data={"command_ip": "127.0.0.1",
                             "command_port": port}),
                  (MULTICAST_GROUP, MULTICAST_PORT))
        tx.close()
        srv.settimeout(10.0)
        conn, addr = srv.accept()
        srv.close()
        conn.settimeout(30.0)
        self.sock = conn
        self.addr = addr
        return True

    def execute(self, code, mode="ExecuteFile", timeout=30.0):
        payload = _msg("command", self.source, data={
            "command": code, "unattended": True, "exec_mode": mode})
        self.sock.sendall(payload)
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            try:
                msg = json.loads(buf.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "command_result":
                return msg.get("data") or {}
        raise TimeoutError("no command_result within %ss" % timeout)

    def close(self):
        if self.sock:
            try:
                tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                tx.sendto(_msg("close_connection", self.source,
                               dest=self.editor_id),
                          (MULTICAST_GROUP, MULTICAST_PORT))
                tx.close()
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


STATE_SNIPPET = r'''
import json
import unreal

out = {"errors": []}
def safe(name, fn):
    try:
        return fn()
    except Exception as e:
        out["errors"].append("%s: %s" % (name, e))
        return None

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
w_game = safe("get_game_world", lambda: ues.get_game_world())
out["pie_running"] = w_game is not None
if w_game:
    out["pie_world"] = safe("name", w_game.get_name)
    pawns = safe("pawns", lambda: unreal.GameplayStatics.get_all_actors_of_class(w_game, unreal.Pawn)) or []
    out["pawns"] = []
    for p in pawns:
        info = {"name": p.get_name(), "class": p.get_class().get_name(),
                "label": p.get_actor_label()}
        mv = None
        try:
            mv = p.get_editor_property("vehicle_movement_component")
        except Exception:
            pass
        info["movement_component"] = (mv.get_class().get_name()
                                      if mv is not None else None)
        try:
            pc = p.get_controller()
            info["controller"] = pc.get_class().get_name() if pc else None
        except Exception:
            info["controller"] = "?"
        out["pawns"].append(info)
    def _pc():
        pc = unreal.GameplayStatics.get_player_controller(w_game, 0)
        return {"class": pc.get_class().get_name(),
                "pawn": (pc.get_controlled_pawn().get_class().get_name()
                         if pc.get_controlled_pawn() else None)} if pc else None
    out["player_controller"] = safe("player_controller", _pc)
w_ed = safe("get_editor_world", lambda: ues.get_editor_world())
if w_ed:
    acts = safe("editor actors", lambda: unreal.GameplayStatics.get_all_actors_of_class(w_ed, unreal.Actor)) or []
    out["editor_vehicle_actors"] = [
        a.get_actor_label() for a in acts
        if "vehicle" in a.get_class().get_name().lower()]
print("LIVE_STATE_JSON " + json.dumps(out))
'''


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    sess = LiveEditor()
    if not sess.discover():
        print("NO EDITOR FOUND (is the editor running with Remote "
              "Execution enabled?)")
        return 1
    print("editor:", json.dumps(sess.editor))
    sess.connect()
    if argv[0] == "state":
        code, mode = STATE_SNIPPET, "ExecuteFile"
    elif argv[0] == "run":
        with open(argv[1], "r", encoding="utf-8") as fh:
            code, mode = fh.read(), "ExecuteFile"
    else:
        code, mode = argv[0], "ExecuteStatement"
    res = sess.execute(code, mode)
    sess.close()
    logtext = "\n".join(
        e.get("output", "") for e in (res.get("log") or []))
    print("success:", res.get("success"))
    for line in logtext.splitlines():
        if "LIVE_STATE_JSON" in line:
            try:
                parsed = json.loads(line.split("LIVE_STATE_JSON ", 1)[1])
                print(json.dumps(parsed, indent=2))
                return 0
            except json.JSONDecodeError:
                pass
    print(logtext or res.get("result", ""))
    return 0 if res.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
