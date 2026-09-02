"""Tests for vehicle config generation from AI statistics XMLs."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from ctf_convert.aistats import build_config

STATS = """<ai_vehicle_data><vehicle_types><vehicle_type name="t1">
<all_grip_performances num_grip_performances="1">
<grip_performance surface="1" name="GVLD" tyre="Rally Gravel Mid"
 handling="0" max_speed="46.5" num_curve_parameters="2"
 param_0="0.5" param_1="-0.1">
<speed_distance speed="10.0" distance="25.0"/>
<speed_distance speed="20.0" distance="80.0"/>
</grip_performance>
</all_grip_performances>
</vehicle_type></vehicle_types></ai_vehicle_data>"""

CORNER = """<ai_vehicle_data><vehicle_types><vehicle_type name="t1">
<all_corner_performances num_grips="1">
<cornering_performance surface="1" name="GVLD" tyre="Rally Tarmac Mid"
 handling="1" num_curve_parameters="2" param_0="3.5" param_1="0.2"/>
</all_corner_performances>
</vehicle_type></vehicle_types></ai_vehicle_data>"""


def test_build_config(tmp_path):
    s = tmp_path / "stats.xml"
    c = tmp_path / "corner.xml"
    s.write_text(STATS, encoding="utf-8")
    c.write_text(CORNER, encoding="utf-8")
    cfg = build_config(str(s), str(c))
    assert cfg["car"] == "t1"
    assert cfg["num_surfaces"] == 1
    gvld = cfg["surfaces"]["GVLD"]
    assert gvld["surface_name"] == "gravel"
    assert gvld["grip"]["max_speed_mps"] == 46.5
    assert gvld["grip"]["grip_curve"] == [0.5, -0.1]
    assert gvld["grip"]["speed_distances"] == [
        {"speed_mps": 10.0, "distance_m": 25.0},
        {"speed_mps": 20.0, "distance_m": 80.0},
    ]
    assert gvld["cornering"]["tyres"]["Rally Tarmac Mid"]["corner_curve"] == [
        3.5, 0.2]