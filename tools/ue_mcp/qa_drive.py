"""Live-editor drive QA for the drivable showroom.

Runs OUTSIDE the editor: drives the possessed pawn through acceleration,
braking and steering via the RallyMigrationToolset MCP toolset, using the
template controller's own accumulator API (``IncreaseThrottleInput``).

Key constraint: every tool call runs on the game thread, so ``time.sleep``
inside a call would freeze physics ticking.  All delays therefore happen
BETWEEN tool calls.  Also, while a controller possesses the pawn,
``SetThrottleInput`` is reset to 0 every tick
(``RequiresControllerForInputs=True``) - the Increase/Decrease accumulator
API is what the template controller itself uses and what persists.

Usage (from tools/ue_mcp):
    python qa_drive.py            # full test: accel + brake + steer
"""
import json
import subprocess
import sys
import time

TOOLSET = "rally_mcp.RallyMigrationToolset"

PRE = (
    "import unreal\n"
    "w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)"
    ".get_game_world()\n"
    "p = unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Pawn)[0]\n"
    "mv = p.get_editor_property('vehicle_movement_component')\n"
)


def call(code: str) -> str:
    payload = json.dumps({
        "toolset_name": TOOLSET,
        "tool_name": "run_python",
        "arguments": {"code": code},
    })
    r = subprocess.run(
        [sys.executable, "-m", "ue_mcp", "call", TOOLSET, "--stdin"],
        input=payload, capture_output=True, text=True, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        if "returnValue" in line:
            try:
                d = json.loads(line)
                return d.get("returnValue", "")
            except json.JSONDecodeError:
                pass
    return out.strip()


def ensure_pie(seconds: float = 10.0) -> None:
    call(
        "import unreal\n"
        "les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)\n"
        "les.load_level('/Game/Import/Fiat131/L_CarShowroom')\n"
        "les.editor_request_begin_play()\n"
        "print('pie requested')\n")
    time.sleep(seconds)


def end_pie() -> None:
    call(
        "import unreal\n"
        "les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)\n"
        "les.editor_request_end_play()\n"
        "print('pie ended')\n")
    time.sleep(3.0)


def telemetry() -> str:
    return call(PRE + (
        "l = p.get_actor_location()\n"
        "print('TELEM speed=%.0f kmh=%.0f rpm=%.0f gear=%s "
        "pos=(%.0f,%.0f,z=%.1f)' % (\n"
        "    mv.get_forward_speed(), mv.get_forward_speed()*0.036,\n"
        "    mv.get_engine_rotation_speed(), mv.get_current_gear(),\n"
        "    l.x, l.y, l.z))\n"))


def hold_input(action: str, seconds: float, period: float = 0.35) -> None:
    """Re-apply the input periodically with real (non-PIE) delays.

    With ``requires_controller_for_inputs`` disabled on the live instance,
    ``SetThrottleInput`` persists between calls; the period just keeps it
    topped up across any residual decay.
    """
    body = {
        "accel": "mv.set_throttle_input(1.0)\n",
        "brake": "mv.set_brake_input(1.0)\nmv.set_throttle_input(0.0)\n",
        "release": "mv.set_throttle_input(0.0)\n",
        "steer_left": "mv.set_steering_input(-0.7)\n",
        "steer_straight": "mv.set_steering_input(0.0)\n",
    }[action]
    t_end = time.time() + seconds
    while time.time() < t_end:
        call(PRE + body)
        time.sleep(period)


def reset_car() -> None:
    call(PRE + (
        "p.set_actor_location(unreal.Vector(600, 300, 120), False, False)\n"
        "mv.set_editor_property('requires_controller_for_inputs', False)\n"
        "mv.set_throttle_input(0.0)\n"
        "mv.set_brake_input(0.0)\n"
        "mv.set_steering_input(0.0)\n"
        "print('car reset, requires_controller off (this PIE instance "
        "only)')\n"))
    time.sleep(2.0)


def main() -> int:
    print("=== fresh PIE ===")
    end_pie()
    ensure_pie()
    reset_car()
    print("  ", telemetry())

    print("=== acceleration 10s ===")
    hold_input("accel", 10.0)
    print("  ", telemetry())

    print("=== braking 4s ===")
    hold_input("brake", 4.0)
    call(PRE + "mv.set_brake_input(0.0)\nprint('brake released')\n")
    print("  ", telemetry())

    print("=== steering 4s ===")
    hold_input("accel", 4.0)
    hold_input("steer_left", 2.0)
    call(PRE + "mv.set_steering_input(0.0)\n")
    print("  ", telemetry())
    call(PRE + "mv.set_throttle_input(0.0)\nprint('released')\n")

    print("=== done ===")
    end_pie()
    return 0


if __name__ == "__main__":
    sys.exit(main())
