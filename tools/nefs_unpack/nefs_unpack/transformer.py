"""Detransformation of item data (AES-256-ECB, zlib, raw, LZSS).

Ports VictorBush.Ego.NefsLib.IO.NefsTransformer.DetransformChunkAsync and
LzssDecompress.

Important DR2 note: ciphertext chunks produced by the game are AES-256-ECB
encrypted and then the result is padded to a multiple of the AES block size
with random bytes.  zlib inflate is non-consuming on trailing garbage, so we
use `zlib.decompressobj()` which stops cleanly at the end of the compressed
stream and discards trailing padding — this is exactly what defeats the
"DeflateStream error" described in ego.nefsedit issue #3.
"""

from __future__ import annotations

import io
import zlib

from .constants import DataTransformType, NefsVersion


def _aes_aes_new(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        cipher = Cipher(algorithms.AES(key), modes.ECB())
        return cipher.decryptor()
    except Exception:
        return None


class AesDecryptor:
    """Thin AES-ECB no-padding decryptor wrapper (uses 'cryptography')."""

    def __init__(self, key: bytes):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        self._decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()

    def update(self, data: bytes) -> bytes:
        return self._decryptor.update(data)

    def finalize(self) -> bytes:
        return self._decryptor.finalize()


def _decompress_lzss(data: bytes, output_limit: int) -> bytes:
    """LZSS decompressor, ported byte-for-byte from LzssDecompress.cs."""
    ring_buffer = bytearray([32] * 4113)
    ring_head = 4078
    history = False
    history_lsb = 0
    history_length = 0
    history_offset = 0
    control_flags = 0

    out = bytearray()
    i = 0
    input_len = len(data)
    while True:
        while history_length > 0:
            if len(out) >= output_limit:
                break
            v = ring_buffer[history_offset]
            history_length -= 1
            history_offset = (history_offset + 1) & 0xFFF
            out.append(v)
            ring_buffer[ring_head] = v
            ring_head = (ring_head + 1) & 0xFFF
        if i >= input_len or len(out) >= output_limit:
            break
        b_ = data[i]
        i += 1
        if control_flags > 255:
            if (control_flags & 1) != 0:
                out.append(b_)
                control_flags >>= 1
                ring_buffer[ring_head] = b_
                ring_head = (ring_head + 1) & 0xFFF
            elif history:
                control_flags >>= 1
                history = False
                history_offset = history_lsb | (16 * (b_ & 0xF0))
                history_length = (b_ & 0xF) + 3
            else:
                history_lsb = b_
                history = True
        else:
            control_flags = b_ | 0xFF00
    return bytes(out)


_DECOMPRESS_LZSS = _decompress_lzss


def detransform_chunk(raw: bytes, transform_type: int, aes_key: bytes, extracted_size: int) -> bytes:
    """Apply AES decrypt then decompress to a single data chunk's plaintext."""
    data = raw
    if transform_type == DataTransformType.AES and aes_key:
        dec = AesDecryptor(aes_key)
        data = dec.update(data) + dec.finalize()
    elif transform_type == DataTransformType.AES:
        raise ValueError("Chunk marked AES but no AES key available for this archive.")

    if transform_type == DataTransformType.ZLIB:
        dobj = zlib.decompressobj()
        data = dobj.decompress(data)
        data += dobj.flush()
    elif transform_type == DataTransformType.LZSS:
        data = _DECOMPRESS_LZSS(data, extracted_size)

    if len(data) > extracted_size:
        data = data[:extracted_size]
    return data


def _raw_deflate_decompress(data: bytes) -> bytes:
    """Raw DEFLATE (RFC 1951, no zlib header) decompression.

    .NET ``DeflateStream`` used by NefsLib reads/writes raw deflate.  A
    ``decompressobj(-15)`` stops cleanly at the end of the deflate stream and
    ignores any trailing AES zero-padding.
    """
    dobj = zlib.decompressobj(-15)
    out = dobj.decompress(data)
    try:
        out += dobj.flush()
    except zlib.error:
        pass
    return out


def detransform_chunk_v200(raw: bytes, is_zlib: bool, is_aes: bool,
                           aes_key: bytes, extracted_size: int) -> bytes:
    """Detransform a v2.0.0 chunk: AES-256-ECB decrypt, then raw-deflate inflate.

    Mirrors NefsTransformer.DetransformChunkAsync for the v2.0.0 transform
    (``NefsDataTransform(blockSize, isZlib, aesKey)``).
    """
    data = raw
    if is_aes:
        if not aes_key:
            raise ValueError("Chunk marked AES but no AES key available.")
        dec = AesDecryptor(aes_key)
        data = dec.update(data) + dec.finalize()
    if is_zlib:
        data = _raw_deflate_decompress(data)
    if len(data) > extracted_size:
        data = data[:extracted_size]
    return data


def extract_item(data_volume: bytes, item: NefsItem, aes_key: bytes) -> bytes:
    """Extract a NefsItem's plaintext bytes from the raw data volume."""
    if item.is_directory:
        return b""
    if not item.chunks:
        # Untransformed single block: read directly.
        start = item.data_offset
        end = start + item.extracted_size
        return data_volume[start:end]

    is_v200 = item.version == NefsVersion.VERSION_200
    out = io.BytesIO()
    for chunk in item.chunks:
        start = chunk.offset
        end = start + chunk.size
        raw = data_volume[start:end]
        if is_v200:
            plain = detransform_chunk_v200(raw, item.is_zlib, item.is_aes,
                                           aes_key, item.extracted_size)
        else:
            plain = detransform_chunk(raw, chunk.transform_type, aes_key,
                                      item.extracted_size)
        out.write(plain)
    result = out.getvalue()
    if len(result) > item.extracted_size:
        result = result[:item.extracted_size]
    return result


def extract_item_from_file(volume_path: str, item: NefsItem, aes_key: bytes) -> bytes:
    """Extract an item reading only the byte ranges it needs from the volume.

    Avoids loading a whole (multi-GB) volume into memory when only a handful
    of items are wanted.  ``entry.Start`` is an absolute offset into the
    volume file (NefsLib's data source offsets the volume by DataOffset; here
    on-disk chunks already point at absolute positions inside the file).
    """
    if item.is_directory:
        return b""
    is_v200 = item.version == NefsVersion.VERSION_200
    out = io.BytesIO()
    with open(volume_path, "rb") as f:
        if not item.chunks:
            # Untransformed single block: read directly.
            f.seek(item.data_offset)
            out.write(f.read(item.extracted_size))
            return out.getvalue()
        for chunk in item.chunks:
            f.seek(chunk.offset)
            raw = f.read(chunk.size)
            if is_v200:
                plain = detransform_chunk_v200(raw, item.is_zlib, item.is_aes,
                                               aes_key, item.extracted_size)
            else:
                plain = detransform_chunk(raw, chunk.transform_type, aes_key,
                                          item.extracted_size)
            out.write(plain)
    result = out.getvalue()
    if len(result) > item.extracted_size:
        result = result[:item.extracted_size]
    return result
