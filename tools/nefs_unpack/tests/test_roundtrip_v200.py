"""Round-trip test for v2.0.0: build a synthetic archive, parse it, and verify
extraction reproduces the exact original bytes for every item (including the
raw-deflate and AES-transformed files).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pytest

from nefs_unpack import read_standard_archive
from nefs_unpack.transformer import detransform_chunk_v200, extract_item

from _fixture_v200 import AES_KEY, build_nefs_v200


def _load(tmp_path):
    blob = build_nefs_v200()
    path = os.path.join(tmp_path, "archive_v200.nefs")
    with open(path, "wb") as f:
        f.write(blob)
    archive = read_standard_archive(path)
    # Volume path points back at the same file (contains header + data).
    archive.items.volume_paths = [path]
    return archive, blob


EXPECTED = {
    "a.txt": b"hello, world",
    "b.bin": b"compressible " * 40,
    "c.bin": bytes(range(256)) * 2,
    "nested.txt": b"nested file contents here",
}


def test_roundtrip_v200_all_items(tmp_path):
    archive, blob = _load(tmp_path)
    assert archive.version == 0x20000
    assert archive.aes_key == AES_KEY

    found = {}
    with open(archive.items.volume_path(0), "rb") as f:
        volume = f.read()
    for item in archive.items.items:
        if item.is_directory:
            continue
        data = extract_item(volume, item, archive.aes_key)
        found[item.file_name] = data

    assert found == EXPECTED


def test_roundtrip_v200_paths_and_directories(tmp_path):
    archive, blob = _load(tmp_path)
    names = {i.file_name: i for i in archive.items.items}
    assert "sub" in names and names["sub"].is_directory
    assert "nested.txt" in names
    assert names["nested.txt"].directory_id == names["sub"].id


def test_roundtrip_v200_flags(tmp_path):
    archive, blob = _load(tmp_path)
    names = {i.file_name: i for i in archive.items.items}
    # a.txt: raw, no transform flags
    assert not names["a.txt"].is_zlib
    assert not names["a.txt"].is_aes
    assert not names["a.txt"].is_transformed
    # b.bin: raw-deflate
    assert names["b.bin"].is_zlib
    assert not names["b.bin"].is_aes
    assert names["b.bin"].is_transformed
    # c.bin: AES-ECB
    assert not names["c.bin"].is_zlib
    assert names["c.bin"].is_aes
    assert names["c.bin"].is_transformed
    # nested.txt: raw
    assert not names["nested.txt"].is_zlib
    assert not names["nested.txt"].is_aes
    assert not names["nested.txt"].is_transformed


def test_hybrid_chunk_fallback_keeps_decrypted_bytes():
    """DR2 audio ``.bnk`` items mix raw and deflate windows under one item-level
    ``IsZlib`` flag.  When a chunk is not an independent raw-deflate stream,
    ``detransform_chunk_v200`` must return the AES-decrypted bytes (matching the
    reference NefsLib behavior of failing gracefully) instead of raising."""
    key = b"K" * 32
    # 80 bytes (5 AES blocks) of clearly-not-deflate content so the zlib
    # fallback path keeps the (decrypted) bytes unchanged.
    payload = os.urandom(80)  # 80 bytes = 5 AES blocks
    assert len(payload) % 16 == 0

    # No AES: non-deflate bytes fall through unchanged (is_zlib ignored on error).
    out = detransform_chunk_v200(payload, is_zlib=True, is_aes=False,
                                 aes_key=None, extracted_size=10000)
    assert out == payload

    # AES + non-deflate: AES-256-ECB round trip preserves the payload.
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    cipher = enc.update(payload) + enc.finalize()
    out2 = detransform_chunk_v200(cipher, is_zlib=True, is_aes=True,
                                  aes_key=key, extracted_size=10000)
    assert out2 == payload
