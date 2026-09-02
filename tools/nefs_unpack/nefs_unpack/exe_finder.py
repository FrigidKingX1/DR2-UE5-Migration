"""Locate split-header (headless) NeFS metadata inside a game executable.

Ports VictorBush.Ego.NefsLib.IO.NefsExeHeaderFinder: scans for the 'NeFS'
FourCC, reads the header intro to determine the version, and then locates the
writable-entry data (parts 6-7) by validating candidate offsets.

The output is a :class:`HeadlessSource` describing where the primary and
secondary header blocks live in the exe, plus the name of the `.dat` data file
it corresponds to.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .binary_reader import BinaryReader
from .constants import FOUR_CC, INTRO_SIZE, NefsVersion

# Union of every valid entry flag bit (NefsTocEntryFlags150).  A writable entry
# is only "known-good" if none of these bits are set outside this mask.
_ENTRY_FLAG_MASK160 = 0x3F  # v1.4/1.5/1.6: includes the 0x20 "patched" bit
# v2.0.0 dropped the 0x20 "patched" flag: IsZlib|IsAes|IsDirectory|IsDuplicated|LastSibling
_ENTRY_FLAG_MASK200 = 0x1F


@dataclass
class HeadlessSource:
    data_file_path: str
    exe_path: str
    primary_offset: int
    secondary_offset: int

    def __repr__(self) -> str:
        return (
            f"HeadlessSource(data={self.data_file_path!r}, "
            f"primary={self.primary_offset:#x}, secondary={self.secondary_offset:#x})"
        )


def _find_fourcc_offsets(exe_bytes: bytes) -> List[int]:
    """Return every byte offset in the exe where the FourCC appears (either
    endianness)."""
    target_le = struct.pack("<I", FOUR_CC)
    target_be = struct.pack(">I", FOUR_CC)
    offsets: List[int] = []
    idx = 0
    while True:
        pos_le = exe_bytes.find(target_le, idx)
        pos_be = exe_bytes.find(target_be, idx)
        candidates = [p for p in (pos_le, pos_be) if p != -1]
        if not candidates:
            break
        next_pos = min(candidates)
        offsets.append(next_pos)
        idx = next_pos + 1
    return offsets


def _parse_intro(blob: bytes, offset: int, is_le: bool
                 ) -> Tuple[int, int, int]:
    """Read (version, toc_size, num_entries) from the header intro at offset.

    Intro layout (NefsTocHeaderA160):
        u32 magic, 0x20 hash, 0x40 aes_hex, u32 toc_size, u32 version,
        u32 num_entries, u32 user_value, ...
    We just need toc_size@100, version@104, num_entries@108.
    """
    br = BinaryReader(blob, little_endian=is_le)
    br.seek(offset + 100)
    toc_size = br.read_u32()
    version = br.read_u32()
    num_entries = br.read_u32()
    return version, toc_size, num_entries


def _parse_toc_b(blob: bytes, offset: int, is_le: bool, version: int) -> Tuple[int, int, int, int, int, int, int]:
    """Read the B TOC fields based on header version.

    v1.6.0 layout (after the 128-byte intro):
        u16 num_volumes, u16 hash size lo, u16 block size lo, u16 split size lo,
        u32 entry, u32 wentry, u32 shared, u32 wshared, u32 name, u32 block,
        u32 vol, u32 hashdigest.

    v2.0.0 drops the block/split size u16s (NefsTocHeaderB200):
        u16 num_volumes, u16 hash size lo, u32 entry, u32 wentry, u32 shared,
        u32 wshared, u32 name, u32 block, u32 vol, u32 hashdigest, 23 x u32 pad.

    Returns (num_volumes, entry_start, shared_start, name_start, vol_start,
             wentry_start, wshared_start)."""
    br = BinaryReader(blob, little_endian=is_le)
    br.seek(offset + INTRO_SIZE)
    num_volumes = br.read_u16()
    br.read_u16()  # hash block size lo
    if version == NefsVersion.VERSION_200:
        pass
    else:
        br.read_u16()  # block size lo
        br.read_u16()  # split size lo
    entry_start = br.read_u32()
    wentry_start = br.read_u32()
    shared_start = br.read_u32()
    wshared_start = br.read_u32()
    name_start = br.read_u32()
    br.read_u32()  # block table start
    vol_start = br.read_u32()
    br.read_u32()  # hash digest table start
    return (num_volumes, entry_start, shared_start, name_start, vol_start,
            wentry_start, wshared_start)


def _read_null_ascii(blob: bytes, offset: int, limit: int = 256) -> str:
    end = blob.find(b"\x00", offset, offset + limit)
    if end == -1:
        end = offset + limit
    return blob[offset:end].decode("ascii", errors="replace")


def _read_file_name(blob: bytes, fourcc: int, is_le: bool, name_start: int,
                    vol_start: int) -> str:
    """Read the volume 0 name (the data file name) from the exe header."""
    br = BinaryReader(blob, little_endian=is_le)
    br.seek(fourcc + vol_start)
    # Volume info: u64 size, u32 name_offset, u32 data_offset
    br.read_u64()
    name_offset = br.read_u32()
    br.read_u32()
    return _read_null_ascii(blob, fourcc + name_start + name_offset)


def find_headers(exe_path: str, data_file_dir: str, search_entire_exe: bool = False
                 ) -> List[HeadlessSource]:
    """Scan an executable and return the headless (split-header) sources it
    contains.

    Ports NefsExeHeaderFinder.FindHeadersAsync.
    """
    with open(exe_path, "rb") as f:
        exe_bytes = f.read()

    if search_entire_exe:
        data_start, data_end = 0, len(exe_bytes)
    else:
        data_start, data_end = _get_data_section_range(exe_bytes)

    sources: List[HeadlessSource] = []
    last_secondary_range: Optional[Tuple[int, int]] = None

    # Collect candidate strategies first (fourcc + valid version).
    candidates: List[Tuple[int, bool, int, int, int]] = []  # fourcc, is_le, toc_size, version, num_entries
    for fourcc_offset in _find_fourcc_offsets(exe_bytes):
        is_le = struct.unpack("<I", exe_bytes[fourcc_offset:fourcc_offset + 4])[0] == FOUR_CC
        try:
            version, toc_size, num_entries = _parse_intro(exe_bytes, fourcc_offset, is_le)
        except Exception:
            continue
        if version not in (NefsVersion.VERSION_140, NefsVersion.VERSION_150,
                           NefsVersion.VERSION_160, NefsVersion.VERSION_200):
            continue
        candidates.append((fourcc_offset, is_le, toc_size, version, num_entries))

    # Order by descending toc_size (largest volume first).
    for fourcc, is_le, toc_size, version, num_entries in sorted(
            candidates, key=lambda c: -c[2]):
        try:
            (num_volumes, entry_start, shared_start, name_start, vol_start,
             wentry_start, wshared_start) = _parse_toc_b(
                exe_bytes, fourcc, is_le, version)
            name = _read_file_name(exe_bytes, fourcc, is_le, name_start, vol_start)
            if not name:
                continue
            num_shared = (name_start - shared_start) // 20
            if num_shared < 0:
                # Invalid geometry: shared table can't extend past the name
                # table (name_start < shared_start).  Not a real header.
                continue
            secondary = _scan_writable_offset(
                exe_bytes, fourcc, is_le,
                data_start, data_end,
                num_volumes, num_entries, num_shared,
                wentry_start, wshared_start, entry_start, shared_start,
                skip_range=last_secondary_range,
                version=version,
            )
            if secondary == -1:
                continue
            from os.path import join
            data_file_path = join(data_file_dir, name)
            sources.append(HeadlessSource(data_file_path, exe_path, fourcc, secondary))
            # Remember the writable range we just claimed (parts 6+7) so a later
            # fourcc cannot re-validate the *same* secondary block.  NefsLib
            # skips the preceding found range to keep consecutive headers from
            # aliasing one another's writable data.
            last_secondary_range = (secondary, secondary + num_entries * 4 + num_shared * 8)
        except Exception:
            continue
    return sources


def _get_data_section_range(exe_bytes: bytes) -> Tuple[int, int]:
    """Best-effort: return the bounds of the PE/headers (0..len) or '.data'.
    For DR2 we simply use the whole file to be safe."""
    return 0, len(exe_bytes)


def _scan_writable_offset(
    blob: bytes,
    fourcc: int,
    is_le: bool,
    data_start: int,
    data_end: int,
    num_volumes: int,
    num_entries: int,
    num_shared: int,
    wentry_start: int,
    wshared_start: int,
    entry_start: int,
    shared_start: int,
    skip_range: Optional[Tuple[int, int]] = None,
    version: int = NefsVersion.VERSION_160,
) -> int:
    """Find the writable-entry block by validating candidate offsets.

    Ports NefsExeHeaderFinderStrategy.FindWriteableDataOffsetAsync +
    ValidateWriteableDataAsync for the given version.  ``skip_range`` drops any
    candidate whose block starts inside a previously claimed writable range
    (NefsLib anti-aliasing between consecutive headless headers).
    """
    writable_size = num_entries * 4 + num_shared * 8
    br = BinaryReader(blob, little_endian=is_le)

    def skip_hit(p: int) -> bool:
        if skip_range is None:
            return False
        # Drop any candidate whose block *starts* inside the previously claimed
        # range [s, e) so a later fourcc cannot re-validate the same secondary
        # block.  Candidates at/after e are distinct and pass through.
        s, e = skip_range
        return s <= p < e

    # Fast path: build a boolean "plausible writable entry" mask over the scan
    # range (each candidate entry is vol u16 + flags u16), then only fully
    # validate window starts that lie within runs of >= num_entries plausible
    # entries.  NefsLib validates every byte; we preselect aligned windows to
    # keep this tractable in Python.
    candidate_starts = _plausible_window_starts(
        blob, data_start, data_end, num_entries, _flag_mask(version))

    for pos in candidate_starts:
        if skip_hit(pos):
            continue
        if pos + writable_size > min(data_end, len(blob)):
            continue
        valid = _validate_writable(br, pos, num_volumes, num_entries, num_shared,
                                   fourcc, is_le, entry_start, shared_start, version)
        if valid:
            return pos
    return -1


def _flag_mask(version: int) -> int:
    return _ENTRY_FLAG_MASK200 if version == NefsVersion.VERSION_200 else _ENTRY_FLAG_MASK160


def _plausible_window_starts(
    blob: bytes,
    data_start: int,
    data_end: int,
    num_entries: int,
    flag_mask: int,
) -> List[int]:
    """Return candidate writable-block start offsets in ``[data_start, data_end)``
    where ``num_entries`` consecutive u32 words each look like a writable entry
    (low u16 volume == 0, high u16 flags within ``flag_mask``) and the window
    contains at least one non-zero flag byte (to discard pure zero-padding runs).

    The numpy fast path probes every window start inside an admissible run,
    across all 4 byte alignments, so a table sitting after zero padding (or at
    an unaligned offset) is still found.  ``_validate_writable`` is the
    authoritative check; this only preselects candidates to keep that cheap.
    """
    if num_entries <= 0:
        return []
    start = max(0, data_start)
    end = min(data_end, len(blob))
    if end - start < num_entries * 4:
        return []
    try:
        import numpy as np
        win_len = num_entries
        results = []
        eglob = len(blob)
        # uint32 cumulative sums can overflow on very large exes; use int64.
        flag_dtype = np.int64
        for r in range(4):
            n_r = eglob - r
            if n_r <= 0:
                continue
            pad4 = (4 - n_r % 4) % 4
            seg = blob[r:] + b"\x00" * pad4
            arr = np.frombuffer(seg, dtype="<u4")
            lo = max(0, (start - r) // 4)
            hi = max(0, min(len(arr), (end - r + 3) // 4))
            if hi - lo < win_len:
                continue
            words = arr[lo:hi]
            # low u16 (volume) must be 0; high u16 (flags) must be within mask
            vol_ok = (words & 0xFFFF) == 0
            flag_ok = ((words >> 16) & np.uint32(0xFFFF ^ flag_mask)) == 0
            ok = (vol_ok & flag_ok).astype(np.int8)
            n = len(ok)
            cum = np.zeros(n + 1, dtype=np.int64)
            np.cumsum(ok, out=cum[1:])
            # windows of length win_len that are all plausible
            window_ok = np.zeros(n, dtype=bool)
            window_ok[:n - win_len + 1] = (
                (cum[win_len:] - cum[:n - win_len + 1]) == win_len)
            win_idx = np.flatnonzero(window_ok)
            if len(win_idx) == 0:
                continue
            # Zero-padded regions produce huge numbers of "plausible"
            # (all-zero) windows; a real writable block has non-zero flag
            # bytes somewhere. Sum the flag halves across each window.
            flags = (words >> 16).astype(flag_dtype)
            fcum = np.zeros(n + 1, dtype=flag_dtype)
            np.cumsum(flags, out=fcum[1:])
            sel = (fcum[win_idx + win_len] - fcum[win_idx]) > 0
            win_idx = win_idx[sel]
            base = r + lo * 4
            results.extend(int(i) * 4 + base for i in win_idx)
        # Confine to [start, end); the (start - r)//4 rounding can otherwise
        # yield a candidate whose first word begins just before `start`.
        results = [p for p in results if start <= p and p + win_len * 4 <= end]
        results.sort()
        return results
    except ImportError:
        # Pure-python fallback: prefilter first word only, byte-granular.
        out = []
        pos = start
        while pos + num_entries * 4 <= end:
            val = struct.unpack_from("<I", blob, pos)[0]
            if (val & 0xFFFF) == 0 and ((val >> 16) & (0xFFFF ^ flag_mask)) == 0:
                out.append(pos)
            pos += 1
        return out


def _validate_writable(br: BinaryReader, pos: int, num_volumes: int,
                       num_entries: int, num_shared: int, fourcc: int,
                       is_le: bool, entry_start: int, shared_start: int,
                       version: int) -> bool:
    blob = br._data
    flag_mask = _ENTRY_FLAG_MASK200 if version == NefsVersion.VERSION_200 else _ENTRY_FLAG_MASK160
    try:
        br.seek(pos)
        write_vols = []
        write_flags = []
        for _ in range(num_entries):
            write_vols.append(br.read_u16())
            write_flags.append(br.read_u16())
        # Validate volume/flags for each writable entry
        for i in range(num_entries):
            if write_vols[i] < num_volumes and (write_flags[i] & ~flag_mask) == 0:
                continue
            return False
        # Read the shared writable entries and entries/shared-infos to validate.
        sh_pos = pos + num_entries * 4
        br.seek(sh_pos)
        for _ in range(num_shared):
            br.read_u32()
            br.read_u32()
        # Basic sanity: parse entries and shared infos from primary tables.
        br2 = BinaryReader(blob, little_endian=is_le)
        br2.seek(fourcc + entry_start)
        first_entries_start = [
            (br2.read_u32(), br2.read_u32(), br2.read_u32(), br2.read_u32(),
             br2.read_u32()) for _ in range(num_entries)
        ]
        br2.seek(fourcc + shared_start)
        shared_infos = [
            (br2.read_u32(), br2.read_u32(), br2.read_u32(), br2.read_u32(),
             br2.read_u32()) for _ in range(num_shared)
        ]
        br.seek(sh_pos)
        sh_entries = [
            (br.read_u32(), br.read_u32()) for _ in range(num_shared)
        ]
        for i in range(num_entries):
            entry = first_entries_start[i]
            start_off = ((entry[1] & 0xFFFFFFFF) << 32) | (entry[0] & 0xFFFFFFFF)
            shared_idx = entry[2]
            if shared_idx >= num_shared:
                return False
            info = shared_infos[shared_idx]
            first_dup = info[4]
            flags = write_flags[i]
            if version == NefsVersion.VERSION_200:
                # NefsTocEntryFlags200: IsZlib=1, IsAes=2, IsDirectory=4,
                # IsDuplicated=8, LastSibling=0x10.  The patched bit (0x20)
                # is gone; the writeable shared info must match by itself.
                f_dir = bool(flags & 4)
                patched = sh_entries[shared_idx][1] == first_dup
                duplicated = bool(flags & 8) or first_dup == i
            else:
                # NefsTocEntryFlags150: Transformed=1, Directory=2,
                # Duplicated=4, Cacheable=8, LastSibling=0x10, Patched=0x20.
                f_dir = bool(flags & 2)
                patched = bool(flags & 32) or sh_entries[shared_idx][1] == first_dup
                duplicated = bool(flags & 4) or first_dup == i
            if ((f_dir and start_off == 0) or (not f_dir and info[1] == first_dup)) \
                    and patched and duplicated:
                continue
            return False
        return True
    except Exception:
        return False
