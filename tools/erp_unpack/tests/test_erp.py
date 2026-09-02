"""Round-trip tests for erp_unpack."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from erp_unpack import extract_erp, read_erp

from _fixture import EXPECTED, build_erp


def test_roundtrip(tmp_path):
    path = os.path.join(tmp_path, "test.erp")
    with open(path, "wb") as f:
        f.write(build_erp())

    erp, raw = read_erp(path)
    assert erp.version == 4
    assert len(erp.resources) == 2

    by_id = {r.identifier: r for r in erp.resources}
    from erp_unpack import extract_resource
    assert extract_resource(by_id["textures/foo.dds"], raw) == EXPECTED["textures/foo.dds"]
    assert extract_resource(by_id["data/config.xml"], raw) == EXPECTED["data/config.xml"]


def test_extract_tree(tmp_path):
    path = os.path.join(tmp_path, "test.erp")
    with open(path, "wb") as f:
        f.write(build_erp())
    out = os.path.join(tmp_path, "out")
    written = extract_erp(path, out)

    for rel, content in EXPECTED.items():
        with open(os.path.join(out, rel), "rb") as f:
            assert f.read() == content
    normalized = {w.replace(os.sep, "/") for w in written}
    assert normalized == set(EXPECTED.keys())


def test_not_erp(tmp_path, capsys):
    from erp_unpack import ErpFormatError
    p = os.path.join(tmp_path, "bad.erp")
    with open(p, "wb") as f:
        f.write(b"JUNK" * 32)
    import pytest
    with pytest.raises(ErpFormatError):
        read_erp(p)
