"""Vehicle config generation from decoded AI statistics XMLs.

DR2's binary CTF files are encrypted with a scheme separate from the NeFS
archive key (verified: the archive AES key does not decrypt them; breaking
it would require reversing the executable, which is out of scope for the
autonomous pipeline).  However every car archive ships two BinXml files with
real handling physics - ``ai_vehicle_statistics.xml`` (per-surface grip
curves vs speed) and ``ai_vehicle_cornering_statistics.xml`` (per-surface x
tyre cornering curves) - which this module converts into a UE-friendly
``vehicle_config.json``.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET

# surface short names observed in DR2 AI statistics
SURFACE_NAMES = {
    "GVLD": "gravel",
    "TRMD": "tarmac",
    "SNOW": "snow",
    "MUD": "mud",
    "TRWT": "tarmac_wet",
}


def _floats(elem, count_attr, prefix):
    n = int(elem.attrib.get(count_attr, "0"))
    return [float(elem.attrib[f"{prefix}_{i}"]) for i in range(n)]


def _parse_stats(path: str) -> dict:
    root = ET.parse(path).getroot()
    out = {}
    for vt in root.iter("vehicle_type"):
        car = vt.attrib.get("name", "unknown")
        surfaces = out.setdefault(car, {})
        for gp in vt.iter("grip_performance"):
            name = gp.attrib.get("name", "?")
            entry = surfaces.setdefault(name, {})
            entry["tyre"] = gp.attrib.get("tyre")
            entry["max_speed_mps"] = float(gp.attrib.get("max_speed", 0.0))
            entry["grip_curve"] = _floats(gp, "num_curve_parameters", "param")
            distances = []
            for sd in gp.iter("speed_distance"):
                distances.append({
                    "speed_mps": float(sd.attrib.get("speed", 0.0)),
                    "distance_m": float(sd.attrib.get("distance", 0.0)),
                })
            if distances:
                entry["speed_distances"] = distances
    return out


def _parse_cornering(path: str) -> dict:
    root = ET.parse(path).getroot()
    out = {}
    for vt in root.iter("vehicle_type"):
        car = vt.attrib.get("name", "unknown")
        surfaces = out.setdefault(car, {})
        for cp in vt.iter("cornering_performance"):
            name = cp.attrib.get("name", "?")
            entry = surfaces.setdefault(name, {})
            entry.setdefault("tyres", {})[cp.attrib.get("tyre", "?")] = {
                "corner_curve": _floats(cp, "num_curve_parameters", "param"),
                "handling": int(cp.attrib.get("handling", 0)),
            }
    return out


def build_config(stats_xml: str, cornering_xml: str,
                 car: str | None = None) -> dict:
    stats = _parse_stats(stats_xml)
    cornering = _parse_cornering(cornering_xml)
    car = car or next(iter(stats), "unknown")
    surfaces = {}
    for code in sorted(set(stats.get(car, {})) | set(cornering.get(car, {}))):
        pretty = SURFACE_NAMES.get(code, code.lower())
        surfaces[code] = {
            "surface_name": pretty,
            "grip": stats.get(car, {}).get(code, {}),
            "cornering": cornering.get(car, {}).get(code, {}),
        }
    return {
        "car": car,
        "source": "ai_vehicle_statistics + ai_vehicle_cornering_statistics",
        "ctf_note": ("binary CTF is encrypted with a non-archive key; "
                     "physics derived from AI statistics XMLs"),
        "num_surfaces": len(surfaces),
        "surfaces": surfaces,
    }


def write_config(stats_xml: str, cornering_xml: str, out_path: str,
                 car: str | None = None) -> str:
    config = build_config(stats_xml, cornering_xml, car)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    return out_path
