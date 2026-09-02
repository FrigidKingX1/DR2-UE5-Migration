"""Tests for database_convert (EGO binary XML + .database)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import pytest

from _fixture import (
    build_binxml_bytes,
    build_bxml_bytes,
    build_database_bytes,
    build_schema_xml,
)
from database_convert import (
    BINXML,
    BXML_LITTLE,
    TEXT,
    DatabaseError,
    XmlDoc,
    XmlError,
    dump,
    get_xml_type,
    load,
    read_database,
    write_database,
)
from database_convert.database import Field, Table, xml_to_schema


# ---------------------------------------------------------------------------
# detection


def test_get_type_binxml():
    assert get_xml_type(build_binxml_bytes()) == BINXML


def test_get_type_bxml():
    assert get_xml_type(build_bxml_bytes(little=True)) == BXML_LITTLE


def test_get_type_text():
    raw = b'<?xml version="1.0"?><root/>'
    assert get_xml_type(raw) == TEXT


# ---------------------------------------------------------------------------
# BinXml


def test_binxml_roundtrip():
    doc = XmlDoc("garage", attrs=[("id", "42")])
    child = XmlDoc("car", attrs=[("name", "focus_rally")], text="notes")
    doc.children.append(child)

    raw = dump(doc, BINXML)
    back = load(raw)
    assert back.name == "garage"
    assert back.attrs == [("id", "42")]
    assert back.children[0].name == "car"
    assert back.children[0].attrs == [("name", "focus_rally")]
    assert back.children[0].text == "notes"
    assert dump(back, BINXML) == raw


def test_binxml_text_roundtrip():
    doc = load(build_binxml_bytes())
    text = dump(doc, TEXT)
    assert b"garage" in text
    assert text.strip().startswith(b"<?xml")
    back = load(text)
    assert back.name == "garage"
    assert back.children[0].name == "car"


def test_binxml_fixture():
    raw = build_binxml_bytes()
    doc = load(raw)
    assert doc.name == "garage"


# ---------------------------------------------------------------------------
# BXML


def test_bxml_little_roundtrip():
    raw = build_bxml_bytes(little=True)
    doc = load(raw)
    assert doc.name == "Menu"
    assert doc.children[0].attrs == [("label", "Career")]
    assert dump(doc, BXML_LITTLE) == raw


# ---------------------------------------------------------------------------
# database


def schema_model():
    return xml_to_schema(build_schema_xml())


def test_database_roundtrip():
    raw = build_database_bytes()
    db = read_database(raw, schema_model())
    assert len(db.tables) == 2
    cars, tyres = db.tables
    assert [r[0] for r in cars.rows] == [1, 2]
    assert [r[1] for r in cars.rows] == ["focus_rally", "polo_rally"]
    assert [r[2] for r in cars.rows] == [1200.5, 1175.0]
    assert [r[2] for r in tyres.rows] == [True, False]
    assert write_database(db) == raw


def test_database_roundtrip_repeated_strings():
    db = schema_model()
    db.tables[0].rows.clear()
    db.tables[0].add_row([1, "shared_model", 1.0])
    db.tables[0].add_row([2, "shared_model", 2.0])
    db.tables[1].rows.clear()
    raw = write_database(db)
    back = read_database(raw, db)
    assert back.tables[0].rows[0][1] == "shared_model"
    assert back.tables[0].rows[1][1] == "shared_model"


def test_database_has_prts():
    assert b"PRTS" in build_database_bytes()


def test_xml_to_schema():
    schema = schema_model()
    assert schema.schema_version == 539233987
    assert len(schema.tables) == 2
    assert [f.name for f in schema.tables[0].fields] == ["ID", "Model", "Mass"]
    assert schema.tables[1].fields[0].type == "string"
    assert schema.tables[1].fields[0].size == 16


# ---------------------------------------------------------------------------
# errors


def test_bad_binxml_rejected():
    with pytest.raises(XmlError):
        load(b"garbage binary data, not xml at all")
