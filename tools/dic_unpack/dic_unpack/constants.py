"""Neon Sound Dictionary (.dic) format constants.

Magic reflects the target platform (DIC1 = PC little-endian, etc.).

Big-endian platforms: PS3 (DIC3), X360 (DIC5), WII (DIC7).
Little-endian platforms: PC (DIC1), PS2 (DIC2), XBOX (DIC4), PSP (DIC6).

Reference: src/010 Templates/dic.bt (Ego-Engine-Modding, MIT).
"""

from __future__ import annotations

SKU_PC = 0x31434944   # "DIC1"
SKU_PS2 = 0x32434944  # "DIC2"
SKU_PS3 = 0x44494333  # "DIC3"
SKU_XBOX = 0x34434944 # "DIC4"
SKU_X360 = 0x44494335 # "DIC5"
SKU_PSP = 0x36434944  # "DIC6"
SKU_WII = 0x44494337  # "DIC7"

BIG_ENDIAN_SKUS = frozenset({SKU_PS3, SKU_X360, SKU_WII})

NAME_SIZE = 16
HEADER_SIZE = 16
BANK_HEADER_SIZE = 24
SAMPLE_SIZE = 24
BANK_TRAILER_SIZE = 8


class AudioFormat:
    PCM16_BIG = 0
    PCM16_LITTLE = 1
    FLOAT32 = 2
    ADPCM = 3
    ATRAC_LOW = 4
    ATRAC_MEDIUM = 5
    ATRAC_HIGH = 6


FORMAT_NAMES = {
    AudioFormat.PCM16_BIG: "pcm16_big",
    AudioFormat.PCM16_LITTLE: "pcm16_little",
    AudioFormat.FLOAT32: "float32",
    AudioFormat.ADPCM: "adpcm",
    AudioFormat.ATRAC_LOW: "atrac_low",
    AudioFormat.ATRAC_MEDIUM: "atrac_medium",
    AudioFormat.ATRAC_HIGH: "atrac_high",
}