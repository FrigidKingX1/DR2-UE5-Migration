"""Synthetic DIC (PC / DIC1, little-endian) fixture builder."""

from __future__ import annotations

import struct

NAME_SIZE = 16


def _name(raw: str, size: int = NAME_SIZE) -> bytes:
    b = raw.encode("latin-1")
    assert len(b) <= size
    return b.ljust(size, b"\x00")


def _flags(sample_rate: int, loop: bool, num_channels: int, fmt: int,
           music: bool) -> int:
    return (int(music) << 31) | (fmt << 28) | (0 << 24) \
        | ((num_channels - 1) << 21) | (int(loop) << 20) | sample_rate


def build_dic() -> bytes:
    """A little-endian PC ('DIC1') sound dictionary with 2 banks."""
    engine = b"\x01\x00\x02\x00" * 8     # 32 bytes
    music = b"\x44\x33\x22\x11" * 6      # 24 bytes
    beep = b"\x00\x80" * 10              # 20 bytes

    samples1 = [
        (0, _flags(44100, False, 2, 1, False), "engine_loop", engine),
        (0, _flags(22050, True, 1, 1, True), "music_intro", music),
    ]
    samples2 = [
        (0, _flags(11025, False, 1, 0, False), "beep", beep),
    ]

    main_header = struct.pack("<II", 0x31434944, 0xDEADBEEF)  # "DIC1", uniqueId
    main_header += b"DIC2"
    main_header += struct.pack("<I", 2)

    # Layout: main(16) + b1 hdr(24) + b1 samples(48) + b1 trailer(8)
    #              + b2 hdr(24) + b2 samples(24) + b2 trailer(8) = 152
    b1_samples_start = len(main_header) + 24                            # 40
    b1_trailer_start = b1_samples_start + 2 * 24                        # 88
    b2_samples_start = b1_trailer_start + 8 + 24                        # 120
    b2_trailer_start = b2_samples_start + 1 * 24                        # 144
    header_len = b2_trailer_start + 8                                   # 152

    # fill audio offsets (absolute into the file) after header_len
    off0 = header_len
    samples1[0] = (off0, samples1[0][1], "engine_loop", engine)
    samples1[1] = (off0 + len(engine), samples1[1][1], "music_intro", music)
    samples2[0] = (samples1[1][0] + len(music), samples2[0][1], "beep", beep)

    def bank_header(offset: int, num_samples: int, name: str) -> bytes:
        return struct.pack("<II", offset, num_samples) + _name(name)

    def samples_block(samples) -> bytes:
        block = b""
        for soff, flags, sname, _ in samples:
            block += struct.pack("<II", soff, flags) + _name(sname)
        return block

    trailer1 = samples1[-1][0] + len(samples1[-1][3])
    trailer2 = samples2[-1][0] + len(samples2[-1][3])

    bank1 = (bank_header(b1_samples_start, 2, "physics")
             + samples_block(samples1)
             + struct.pack("<I", trailer1) + _name("raw", 4))
    bank2 = (bank_header(b2_samples_start, 1, "ui")
             + samples_block(samples2)
             + struct.pack("<I", trailer2) + _name("raw", 4))

    blob = bytearray(header_len + (trailer2 - off0))
    blob[:header_len] = main_header + bank1 + bank2
    for off, _, _, data in samples1 + samples2:
        blob[off:off + len(data)] = data

    assert blob[off0:off0 + len(engine)] == engine
    return bytes(blob)


EXPECTED = {
    "physics/engine_loop.raw": b"\x01\x00\x02\x00" * 8,
    "physics/music_intro.raw": b"\x44\x33\x22\x11" * 6,
    "ui/beep.raw": b"\x00\x80" * 10,
}