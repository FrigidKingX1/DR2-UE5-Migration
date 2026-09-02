import os
import subprocess
import sys

import pytest

from ctf_convert import (
    CtfFormatError,
    FloatList,
    csv_to_entries,
    entries_to_csv,
    entries_to_json,
    json_to_entries,
    read_ctf,
    write_ctf,
)
from ctf_convert.ctf import CtfSchema

from _fixture import CSV_LINES, SCHEMA_XML, build_fixture


@pytest.fixture(scope="module")
def schema():
    return CtfSchema.from_bytes(SCHEMA_XML.encode("utf-8"))


def names(schema):
    return {e.name: e.id for e in schema.entries}


def test_roundtrip_bytes(schema):
    blob = build_fixture(link_enabled=True)
    entries, flag = read_ctf(blob, schema)
    assert flag == 2
    assert write_ctf(entries, schema) == blob


def test_values(schema):
    entries, _ = read_ctf(build_fixture(), schema)
    n = names(schema)
    assert entries[n["magic"]] == 999
    assert entries[n["flag"]] == 2
    assert entries[n["always_float"]] == 1.5
    assert entries[n["auto_clutch"]] is True
    assert entries[n["geometry_string"]] == "AWD-1"
    assert entries[n["drivetrain"]] == 4
    assert entries[n["sc_enabled"]] is True
    curve = entries[n["sc_curve"]]
    assert isinstance(curve, FloatList)
    assert curve.count == 2
    assert curve.step == 0.25
    assert list(curve.items) == [0.0, 1.0]
    assert entries[n["weight"]] == 1240.5


def test_flag_gates(schema):
    entries, _ = read_ctf(build_fixture(), schema)
    n = names(schema)
    assert n["geometry_string"] in entries      # minFlag 1 <= 2
    assert n["drivetrain"] in entries           # minFlag 2 <= 2
    assert n["overflow_only"] not in entries    # minFlag 4 > 2


def test_linked_skip(schema):
    blob = build_fixture(link_enabled=False)
    entries, _ = read_ctf(blob, schema)
    n = names(schema)
    assert entries[n["sc_enabled"]] is False
    assert n["sc_curve"] not in entries
    out = write_ctf(entries, schema)
    entries2, _ = read_ctf(out, schema)
    assert n["sc_curve"] not in entries2        # write-back must not re-add it


def test_truncated(schema):
    with pytest.raises(CtfFormatError):
        read_ctf(build_fixture()[:6], schema)


def test_trailing_junk(schema):
    with pytest.raises(CtfFormatError):
        read_ctf(build_fixture() + b"\x00\x01\x02", schema)


def test_csv_roundtrip(schema):
    blob = build_fixture()
    entries, _ = read_ctf(blob, schema)
    text = entries_to_csv(entries, schema, lines="\r\n".join(CSV_LINES))
    parsed = csv_to_entries(text, schema)
    for id in entries:
        assert parsed[id] == entries[id], schema.entries[id].name


def test_csv_formats_floats(schema):
    blob = build_fixture()
    entries, _ = read_ctf(blob, schema)
    text = entries_to_csv(entries, schema, lines="\r\n".join(["h", "meta", ""]))
    row = text.split("\r\n")[-1]
    n = names(schema)
    assert f"{entries[n['always_float']]:.6f}" in row
    assert row.startswith("999,2,")


def test_csv_float_list_cell(schema):
    blob = build_fixture()
    entries, _ = read_ctf(blob, schema)
    text = entries_to_csv(entries, schema, lines="\r\n".join(["h", "meta", ""]))
    row = text.split("\r\n")[-1]
    n = names(schema)
    curve_cell = row.split(",")[n["sc_curve"]]
    assert curve_cell == "2;0.250000;0.000000;1.000000"
    parsed = csv_to_entries(text, schema)
    curve = parsed[n["sc_curve"]]
    assert curve.count == 2 and curve.step == 0.25 and list(curve.items) == [0.0, 1.0]


def test_csv_malformed_float_list(schema):
    row = ",".join(["999", "2", "1.5", "1", "AWD-1", "4", "1", "2;0.25",
                    "1240.5", ""])
    with pytest.raises(CtfFormatError):
        csv_to_entries("\r\n".join(["h", "meta", row]), schema)


def test_json_roundtrip(schema):
    blob = build_fixture()
    entries, flag = read_ctf(blob, schema)
    doc = entries_to_json(entries, schema, flag)
    assert doc["flag"] == 2
    assert doc["entries"]["always_float"] == 1.5
    entries2 = json_to_entries(doc, schema)
    n = names(schema)
    curve = entries2[n["sc_curve"]]
    assert curve.count == 2 and curve.step == 0.25
    assert write_ctf(entries2, schema) == blob


def test_cli_info(capsys):
    blob = build_fixture()
    with open("_demo.ctf", "wb") as fh:
        fh.write(blob)
    with open("_demo_schema.xml", "wb") as fh:
        fh.write(SCHEMA_XML.encode("utf-8"))
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ctf_convert", "info", "_demo.ctf",
             "--schema", "_demo_schema.xml"],
            capture_output=True, text=True)
        assert proc.returncode == 0
        assert "magic" in proc.stdout and "geometry_string" in proc.stdout
    finally:
        for f in ("_demo.ctf", "_demo_schema.xml"):
            if os.path.exists(f):
                os.unlink(f)


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "ctf_convert", *args],
        capture_output=True, text=True)


def test_lenient_reads_csv_rebuilt_file(tmp_path):
    with open(tmp_path / "schema.xml", "w", encoding="utf-8") as fh:
        fh.write(SCHEMA_XML)
    with open(tmp_path / "in.ctf", "wb") as fh:
        fh.write(build_fixture())
    r = run_cli("to-csv", str(tmp_path / "in.ctf"),
                "--schema", str(tmp_path / "schema.xml"),
                "--out", str(tmp_path / "out.csv"))
    assert r.returncode == 0
    r = run_cli("from-csv", str(tmp_path / "out.csv"),
                "--schema", str(tmp_path / "schema.xml"),
                "--out", str(tmp_path / "rebuilt.ctf"))
    assert r.returncode == 0
    r = run_cli("info", str(tmp_path / "rebuilt.ctf"),
                "--schema", str(tmp_path / "schema.xml"))
    assert r.returncode != 0          # strict read rejects it (like the C# tool)
    r = run_cli("info", str(tmp_path / "rebuilt.ctf"),
                "--schema", str(tmp_path / "schema.xml"),
                "--lenient")
    assert r.returncode == 0
    assert "overflow_only" in r.stdout
    assert "float" in r.stdout