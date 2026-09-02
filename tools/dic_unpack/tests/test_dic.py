"""Round-trip tests for dic_unpack."""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from dic_unpack import DicFormatError, extract_dic, read_dic, sample_data

from _fixture import EXPECTED, build_dic


def _write(tmp_path, name="test.dic"):
    path = os.path.join(tmp_path, name)
    with open(path, "wb") as f:
        f.write(build_dic())
    return path


def test_roundtrip(tmp_path):
    path = _write(tmp_path)
    dic, raw = read_dic(path)
    assert dic.sku == 0x31434944
    assert dic.unique_id == 0xDEADBEEF
    assert dic.version == "DIC2"
    assert not dic.big_endian
    assert len(dic.banks) == 2

    b_physics, b_ui = dic.banks
    assert b_physics.name == "physics"
    assert b_physics.num_samples == 2
    assert b_physics.extension == "raw"
    assert b_physics.samples[0].sample_rate == 44100
    assert b_physics.samples[0].num_channels == 2
    assert b_physics.samples[0].audio_format == 1  # PCM16_LITTLE
    assert b_physics.samples[0].loop is False
    assert b_physics.samples[1].loop is True
    assert b_physics.samples[1].music is True

    assert sample_data(b_physics.samples[0], raw) == b"\x01\x00\x02\x00" * 8
    assert sample_data(b_physics.samples[1], raw) == b"\x44\x33\x22\x11" * 6
    assert sample_data(b_ui.samples[0], raw) == b"\x00\x80" * 10


def test_extract(tmp_path):
    path = _write(tmp_path)
    out = os.path.join(tmp_path, "out")
    written = extract_dic(path, out)
    for rel, content in EXPECTED.items():
        with open(os.path.join(out, rel), "rb") as f:
            assert f.read() == content
    assert {w.replace(os.sep, "/") for w in written} == set(EXPECTED.keys())


def test_wav_wrap(tmp_path):
    path = _write(tmp_path)
    out = os.path.join(tmp_path, "out")
    extract_dic(path, out, wav=True)
    wav_path = os.path.join(out, "physics", "engine_loop.wav")
    with open(wav_path, "rb") as f:
        wav = f.read()
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    # PCM 16-bit, 2 ch, 44100 Hz  (fmt_tag @20, channels @22, rate @24)
    fmt_tag, channels, rate = struct.unpack_from("<HHI", wav, 20)
    assert (fmt_tag, channels, rate) == (1, 2, 44100)
    assert wav[44:] == b"\x01\x00\x02\x00" * 8


def test_bad_magic(tmp_path):
    p = os.path.join(tmp_path, "bad.dic")
    with open(p, "wb") as f:
        f.write(b"JUNK" * 8)
    with pytest.raises(DicFormatError):
        read_dic(p)