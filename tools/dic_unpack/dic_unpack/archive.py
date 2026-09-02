"""Neon Sound Dictionary (.dic) reader/extractor.

DIC archives hold loaded audio samples for EGO titles (DiRT Rally 2.0 uses
the PC/DIC1 little-endian variant).  Audio payload is raw; wrapped to WAV
for uncompressed PCM16-LE and float32 on request.

Reference: 010 template dic.bt (Ego-Engine-Modding, MIT).
"""

from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .constants import (
    BANK_HEADER_SIZE,
    BANK_TRAILER_SIZE,
    BIG_ENDIAN_SKUS,
    FORMAT_NAMES,
    HEADER_SIZE,
    NAME_SIZE,
    SAMPLE_SIZE,
    AudioFormat,
)


class DicFormatError(Exception):
    pass


def _read_string(raw: bytes, offset: int, size: int) -> str:
    chunk = raw[offset:offset + size]
    end = chunk.find(b"\x00")
    if end != -1:
        chunk = chunk[:end]
    return chunk.decode("latin-1")


@dataclass
class DicSample:
    offset: int
    sample_rate: int
    loop: bool
    num_channels: int
    audio_format: int
    music: bool
    name: str
    length: int = 0            # derived from the next sample/trailer


@dataclass
class DicBank:
    offset: int
    num_samples: int
    name: str
    extension: str
    length: int                # trailer length (end of last sample)
    samples: List[DicSample] = field(default_factory=list)


@dataclass
class DicFile:
    sku: int
    unique_id: int
    version: str
    big_endian: bool
    banks: List[DicBank] = field(default_factory=list)


def _decode_flags(flags: int) -> dict:
    # Same bit positions for both endiannesses (see dic.bt notes).
    return {
        "sample_rate": flags & 0xFFFFF,
        "loop": bool((flags >> 20) & 1),
        "num_channels": ((flags >> 21) & 0x7) + 1,
        "reserved": (flags >> 24) & 0xF,
        "audio_format": (flags >> 28) & 0x7,
        "music": bool((flags >> 31) & 1),
    }


def read_dic(file_path: str) -> tuple[DicFile, bytes]:
    """Parse a `.dic` sound dictionary.  Returns (DicFile, whole-file bytes)."""
    with open(file_path, "rb") as f:
        raw = f.read()

    if len(raw) < HEADER_SIZE:
        raise DicFormatError("File too small to be a DIC dictionary.")

    # platform detection: read u32 BE first (matches dic.bt)
    be_sku = struct.unpack_from(">I", raw, 0)[0]
    big_endian = be_sku in BIG_ENDIAN_SKUS
    sku = struct.unpack_from("<I", raw, 0 if not big_endian else 0)[0]
    if big_endian:
        sku = be_sku
    else:
        if sku not in (0x31434944, 0x32434944, 0x34434944, 0x36434944):
            raise DicFormatError("Not a DIC file (bad magic).")

    u32 = ">I" if big_endian else "<I"
    u32x2 = ">II" if big_endian else "<II"

    unique_id = struct.unpack_from(u32, raw, 4)[0]
    version = _read_string(raw, 8, 4)
    num_banks = struct.unpack_from(u32, raw, 12)[0]

    dic = DicFile(sku=sku, unique_id=unique_id, version=version, big_endian=big_endian)

    pos = HEADER_SIZE
    for _ in range(num_banks):
        if pos + BANK_HEADER_SIZE > len(raw):
            raise DicFormatError("Truncated DIC bank header.")
        bank_off, num_samples = struct.unpack_from(u32x2, raw, pos)
        pos += 8
        name = _read_string(raw, pos, NAME_SIZE)
        pos += NAME_SIZE

        info_pos = bank_off
        if info_pos + num_samples * SAMPLE_SIZE + BANK_TRAILER_SIZE > len(raw):
            raise DicFormatError(f"Bank {name!r} sample table out of range.")

        bank = DicBank(bank_off, num_samples, name, extension="", length=0)
        sample_offsets: List[int] = []
        for i in range(num_samples):
            so, flags = struct.unpack_from(u32x2, raw, info_pos)
            info_pos += 8
            sname = _read_string(raw, info_pos, NAME_SIZE)
            info_pos += NAME_SIZE
            fd = _decode_flags(flags)
            sample_offsets.append(so)
            bank.samples.append(DicSample(
                offset=so,
                sample_rate=fd["sample_rate"],
                loop=fd["loop"],
                num_channels=fd["num_channels"],
                audio_format=fd["audio_format"],
                music=fd["music"],
                name=sname,
            ))

        trailer_len, extension = (struct.unpack_from(u32, raw, info_pos)[0],
                                  _read_string(raw, info_pos + 4, 4))
        bank.length = trailer_len
        bank.extension = extension

        # derive per-sample length from the following offset / trailer end
        for i, s in enumerate(bank.samples):
            end = sample_offsets[i + 1] if i + 1 < num_samples else trailer_len
            if end <= s.offset:
                s.length = 0
            else:
                s.length = end - s.offset

        dic.banks.append(bank)
        pos = info_pos + BANK_TRAILER_SIZE

    return dic, raw


def sample_data(sample: DicSample, raw: bytes) -> bytes:
    end = min(len(raw), sample.offset + sample.length)
    start = min(max(sample.offset, 0), len(raw))
    return raw[start:end]


def _wav_wrap(data: bytes, channels: int, sample_rate: int, fmt_tag: int,
              bits: int) -> bytes:
    data_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    out = io.BytesIO()
    out.write(b"RIFF")
    out.write(struct.pack("<I", 36 + len(data)))
    out.write(b"WAVE")
    out.write(b"fmt ")
    out.write(struct.pack("<IHHIIHH", 16, fmt_tag, channels, sample_rate,
                          data_rate, block_align, bits))
    out.write(b"data")
    out.write(struct.pack("<I", len(data)))
    out.write(data)
    return out.getvalue()


def extract_dic(file_path: str, out_dir: str, wav: bool = False) -> List[str]:
    """Extract every sample's audio payload to ``out_dir``.

    Returns the list of relative paths written.  ``wav=True`` wraps
    uncompressed PCM16-LE / float32 audio in a RIFF-WAVE header."""
    dic, raw = read_dic(file_path)
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []
    counts: dict = {}

    for bank in dic.banks:
        ext = bank.extension or "raw"
        for sample in bank.samples:
            data = sample_data(sample, raw)
            name = sample.name or f"{bank.name}_sample"
            key = (bank.name, name)
            counts[key] = counts.get(key, 0) + 1
            stem = f"{name}_{counts[key]}" if counts[key] > 1 else name
            rel = os.path.join(bank.name, f"{stem}.{ext}")

            payload = data
            if wav:
                fmt_tag = bits = None
                if sample.audio_format == AudioFormat.PCM16_LITTLE:
                    fmt_tag, bits = 1, 16
                elif sample.audio_format == AudioFormat.FLOAT32:
                    fmt_tag, bits = 3, 32
                if fmt_tag is not None:
                    rel = rel[:-len(ext)] + "wav"
                    payload = _wav_wrap(data, sample.num_channels,
                                        sample.sample_rate, fmt_tag, bits)

            target = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(payload)
            written.append(rel)

    return written