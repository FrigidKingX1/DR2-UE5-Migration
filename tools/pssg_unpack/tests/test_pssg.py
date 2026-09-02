"""Round-trip tests for pssg_unpack."""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from pssg_unpack import PssgAttribute, PssgElement, PssgFile, PssgFormatError, read_pssg, write_pssg
from pssg_unpack.constants import (
    ATTR_FLOAT,
    ATTR_FLOAT3,
    ATTR_INT,
    ATTR_STRING,
    ATTR_UNKNOWN,
)


def build_model() -> PssgFile:
    root = PssgElement(name="PSSGDATABASE")
    root.attributes.append(PssgAttribute("id", ATTR_STRING, 4 + 7, "dr2test"))
    root.attributes.append(PssgAttribute("count", ATTR_INT, 4, 10600))

    lib = PssgElement(name="LIBRARY")
    lib.attributes.append(PssgAttribute("name", ATTR_STRING, 4 + 5, "main"))
    node = PssgElement(name="NODE")
    node.attributes.append(PssgAttribute("scale", ATTR_FLOAT3, 12, (1.0, 2.0, 3.0)))
    lib.children.append(node)
    root.children.append(lib)

    blk = PssgElement(name="DATABLOCK")
    blk.attributes.append(PssgAttribute("id", ATTR_STRING, 4 + 2, "db"))
    blk.attributes.append(PssgAttribute("size", ATTR_INT, 4, 12))
    data = PssgElement(name="DATABLOCKDATA", is_data=True, value=b"0123456789ab")
    blk.children.append(data)
    root.children.append(blk)

    tex = PssgElement(name="TEXTUREIMAGE", is_data=True, value=b"\x89PNG\r\n")
    tex.attributes.append(PssgAttribute("format", ATTR_STRING, 4 + 5, "DDS"))
    root.children.append(tex)

    user = PssgElement(name="USERDATA", is_data=True, value=b"\xff\xff\xff\xff" + b"blob")
    root.children.append(user)

    misc = PssgElement(name="MODIFIERNETWORKINSTANCEUNIQUEMODIFIERINPUT",
                       is_data=True, value=struct.pack(">2I", 1, 2))
    root.children.append(misc)

    return PssgFile(file_size=0, root=root)


def test_roundtrip_lossless():
    model = build_model()
    blob = write_pssg(model)
    assert blob[:4] == b"PSSG"

    parsed = read_pssg(blob)
    assert parsed.root.name == "PSSGDATABASE"
    assert len(parsed.root.children) == 5

    # re-serialising the parsed model must be byte-identical
    blob2 = write_pssg(parsed)
    assert blob2 == blob
    # and re-parsing once more is stable
    parsed2 = read_pssg(blob2)
    assert write_pssg(parsed2) == blob2


def test_structure_and_values():
    blob = write_pssg(build_model())
    parsed = read_pssg(blob)

    root = parsed.root
    attrs = {a.name: a for a in root.attributes}
    assert attrs["id"].value == "dr2test"
    assert attrs["id"].size == 4 + 7
    assert attrs["count"].value == 10600
    assert attrs["count"].size == 4

    children = {c.name: c for c in root.children}
    lib = children["LIBRARY"]
    assert lib.children[0].name == "NODE"
    scale = lib.children[0].attributes[0]
    assert scale.name == "scale"
    assert scale.value == (1.0, 2.0, 3.0)

    db = children["DATABLOCK"]
    assert db.children[0].is_data
    assert db.children[0].value == b"0123456789ab"

    tex = children["TEXTUREIMAGE"]
    assert tex.is_data
    assert tex.value == b"\x89PNG\r\n"
    assert {a.name for a in tex.attributes} == {"format"}

    user = children["USERDATA"]
    assert user.is_data
    assert user.value == b"\xff\xff\xff\xffblob"


def test_unknown_type_data_detection():
    # USERDATA (Unknown schema type) whose payload begins with a bogus
    # element-id must be classified as a data element (byte-scan check).
    blob = write_pssg(build_model())
    parsed = read_pssg(blob)
    user = {c.name: c for c in parsed.root.children}["USERDATA"]
    assert user.is_data and user.value == b"\xff\xff\xff\xffblob"


def test_unknown_type_container_detection():
    # An Unknown-typed element holding valid child elements is a container.
    root = PssgElement(name="PSSGDATABASE")
    user = PssgElement(name="USERDATA")   # Unknown type in schema registry
    child = PssgElement(name="DATA", is_data=True, value=b"xyz")
    user.children.append(child)
    root.children.append(user)
    blob = write_pssg(PssgFile(root=root))
    parsed = read_pssg(blob)
    u = parsed.root.children[0]
    assert not u.is_data
    assert u.children[0].name == "DATA"
    assert u.children[0].value == b"xyz"


def test_schema_tables():
    blob = write_pssg(build_model())
    parsed = read_pssg(blob)
    # element schema should contain every element name used exactly once
    names = parsed.root.iter_all()
    used = {e.name for e in names}
    for name in used:
        assert parsed.element_table.count(name) == 1
    # all attributes used should be registered
    used_attrs = {a.name for e in names for a in e.attributes}
    for name in used_attrs:
        assert any(tname == name for tname, _ in parsed.attribute_table)


def test_bad_magic():
    with pytest.raises(PssgFormatError):
        read_pssg(b"JUNK" * 16)