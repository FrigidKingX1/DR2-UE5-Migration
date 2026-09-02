"""Test the exe header finder against a synthetic executable blob containing a
split-header (headless) v1.6.0 archive header."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from nefs_unpack.exe_finder import find_headers, _find_fourcc_offsets
from nefs_unpack.constants import FOUR_CC, NefsVersion, INTRO_SIZE

import struct


def _synthetic_exe() -> bytes:
    """Build a fake exe: padding, primary header (intro+toc+parts1-5), padding,
    then the writable block (parts 6-7)."""
    # -- Intro --
    intro = bytearray(INTRO_SIZE)
    struct.pack_into("<I", intro, 0, FOUR_CC)
    struct.pack_into("<I", intro, 104, NefsVersion.VERSION_160)
    struct.pack_into("<I", intro, 108, 3)  # num_entries

    # -- TOC B --
    toc = bytearray(128)
    struct.pack_into("<H", toc, 0, 1)      # num_volumes
    struct.pack_into("<H", toc, 2, 1)      # hash block size lo
    struct.pack_into("<H", toc, 4, 1)      # block size lo
    struct.pack_into("<H", toc, 6, 0)      # split size lo

    # Will patch start offsets after computing layout.
    # Layout (all absolute, fourcc = primary offset):
    # intro[128], toc[128], part1 (3*20), part2 (3*20), part3 names,
    # part4 (1 block*8), part5 (1 vol*16), part8 (1*32), then a gap,
    # then writable part6 (3*4) + part7 (3*8).

    def under(exe_offset):
        # pack values relative to the primary header start
        return exe_offset

    base = 0x1000  # primary offset
    p = base + INTRO_SIZE + INTRO_SIZE
    p1 = p
    p += 3 * 20
    p2 = p
    p += 3 * 20
    # name table
    names = bytearray()
    name_off = {}
    for nm in ("vol0.dat", "a.txt", "sub"):
        name_off[nm] = len(names)
        names += nm.encode() + b"\x00"
    p3 = p
    p += len(names)
    p4 = p
    p += 1 * 8
    p5 = p
    p += 1 * 16
    p8 = p
    p += 1 * 32
    # writable entries after a gap
    writable_start = p + 0x100
    w6 = writable_start
    w7 = w6 + 3 * 4
    wend = w7 + 3 * 8

    struct.pack_into("<I", toc, 8, p1 - base)     # entry table start
    struct.pack_into("<I", toc, 12, w6 - base)    # writable entry start
    struct.pack_into("<I", toc, 16, p2 - base)    # shared entry start
    struct.pack_into("<I", toc, 20, w7 - base)    # writable shared start
    struct.pack_into("<I", toc, 24, p3 - base)    # name table start
    struct.pack_into("<I", toc, 28, p4 - base)    # block table start
    struct.pack_into("<I", toc, 32, p5 - base)    # volume info start
    struct.pack_into("<I", toc, 36, p8 - base)    # hash digest start

    # part1 entries: start, sharedInfo, firstBlock, nextDup
    entries = struct.pack("<" + "I" * (5 * 3),
                          0, 0, 0, 0, 0,        # id0 dir
                          0x0, 0, 1, 0, 0,      # id1 a.txt start=0x0
                          0x0, 0, 2, 0, 0)      # id2 sub dir
    # part2 shared: parent, firstChild, nameOffset, size, firstDup
    shared = struct.pack("<" + "I" * (5 * 3),
                         0, 1, 0, 0, 0,          # root: parent 0, child 1
                         0, 1, name_off["a.txt"], 1, 1,  # a.txt: firstChild==firstDup==1
                         0, 3, name_off["sub"], 0, 2)    # sub: parent 0, child 3
    # part3: names
    # names is above
    # part4 blocks (end, trans, checksum)
    blocks = struct.pack("<IHH", 1, 0, 0)
    # part5 volume info (size, nameOff, dataOff)
    vol = struct.pack("<QII", 0, name_off["vol0.dat"], 0)
    # part8 hash digest
    hash8 = b"\x00" * 32

    # Build primary block
    primary = bytes(intro) + bytes(toc) + entries + shared + bytes(names) + \
        blocks + vol + hash8
    assert len(primary) == (p8 - base + 32)

    # writable entries: (volume u16, flags u16). flags: dir=2, transformed=1
    writable = struct.pack("<" + "HHHHHH",
                           0, 2,   # root dir
                           0, 0,   # a.txt none
                           0, 2)   # sub dir
    # writable shared: (nextSibling, patchedEntry) x3; patchedEntry == firstDup
    writable_shared = struct.pack("<" + "II" * 3,
                                  0, 0, 0, 1, 0, 2)

    exe = bytearray(0x3000)
    exe[base:base + len(primary)] = primary
    exe[w6:w6 + len(writable)] = writable
    exe[w7:w7 + len(writable_shared)] = writable_shared
    return bytes(exe)


def test_find_fourcc_offsets():
    exe = _synthetic_exe()
    offsets = _find_fourcc_offsets(exe)
    assert 0x1000 in offsets


def test_find_headers(tmp_path):
    exe = _synthetic_exe()
    exe_path = os.path.join(tmp_path, "game.exe")
    with open(exe_path, "wb") as f:
        f.write(exe)

    sources = find_headers(exe_path, str(tmp_path))
    assert len(sources) == 1
    s = sources[0]
    assert s.primary_offset == 0x1000
    assert s.secondary_offset != -1