# Roadmap — DR2 → UE5 Migration Tooling

Goal: build a clean-room-ish, Python-based toolchain to reverse-engineer
DiRT Rally 2.0 (EGO Engine) archives for **personal, non-commercial** research
and migration to Unreal Engine 5.  No game assets or extracted copies are ever
redistributed.

## Status

`116→` tooling is in active development.  The first deliverables — a working
`nefs_unpack` (Python port of NefsLib) plus `erp_unpack` (EGO Resource Package),
`jpk_unpack` (JPAK), and `pssg_unpack` (binary scene graph) — are functional
and covered by synthetic round-trip tests.

> **DR2 archive version note.** DiRT Rally 2.0's real archives are NeFS
> **v2.0.0**, not v1.6.0.  The TOC layout (B200), writable-entry flag enum, and
> split-header validation all differ from v1.6.0; the toolchain is now
> version-aware.  See `docs/FORMATS.md` §2.1, §4.

## Milestones

### M1 — Archive extraction (MOSTLY COMPLETE, validated on real DR2 data)
- [x] Python `nefs_unpack` library:
  - [x] Header parser (intro, TOC, parts 1–8) — v1.6.0 and **v2.0.0** (DR2)
  - [x] Standard `.nefs` and split-header `.dat` reading
  - [x] Exe header/writable-data finder (`scan`) — version-aware, numpy fast path
  - [x] Item tree reconstruction (dirs, files, shared entries)
  - [x] Detransform: AES-256-ECB, zlib, LZSS
  - [x] `unpack` / `list` / `scan` CLI
  - [x] Synthetic round-trip tests (all pass)
- [x] `docs/FORMATS.md`, `docs/ENCRYPTION.md`
- [x] ERP archive support — `tools/erp_unpack` (KPAR v4, zlib/zstd fragments)
- [x] JPK archive support — `tools/jpk_unpack` (JPAK, 32-byte entries)
- [x] PSSG scene-graph reader/writer — `tools/pssg_unpack`
- [x] Real-data validation (user-supplied install at
      `D:\Steam\steamapps\common\DiRT Rally 2.0`):
  - XOR/RSA-obfuscated headers decoded; all game/cars/locations archives parse
    with 0 failures; `music.nfs` nested archive.
  - `scan` auto-finds all four split `.dat` volumes with correct primary +
    secondary offsets; part-6 flags/volumes confirmed sane
    (all `Volume==0`, flags within `0x1F`).
  - Spot-extraction from `game.dat` gives byte-exact size matches.
  - Every DR2 archive is NeFS v2.0.0; there are **no** `.erp` `.database`
    files in DR2 (older-EGO formats — N/A here).

### M2 — Asset pipeline
- [x] DIC audio dictionary unpack — `tools/dic_unpack`
- [x] CTF physics blob converter — `tools/ctf_convert`
- [x] PSSG mesh/texture conversion (on top of `pssg_unpack`) — `tools/pssg_convert`
- [x] DB/XML schema conversion — `tools/database_convert`
- [ ] schema files under `schemas/`

### M2 notes (current state)
- `pssg_convert` decodes vertex/index buffers (`RenderDataSourceReader`), traverses
  car scene node libraries (interior `RENDERNODE`/`VISIBLERENDERNODE` + exterior
  `MATRIXPALETTEJOINTNODE` with index subranges), resolves shader→texture bindings,
  and writes OBJ/MTL + DDS + a `pssg_manifest.json`.  14 tests, CLI verified.
- `database_convert` ports `XmlFile` (BinXml/BXML/text) and `DatabaseFile`
  (modern `PRTS` string-table + legacy `LBT`/`ITM`), schema-driven typed rows,
  CLI `info`/`xml`/`db-decode`/`db-info`.  12 tests, **validated on real
  DR2 data**: `int_131.xml` (text XML) → BinXml → text round-trip passes, and a
  real `131.nd2` (BinXml magic) decodes to readable vehicle-damage physics XML.
- `ctf_convert` ctf ↔ csv/json works on synthetic fixtures; the binary CTF path
  (`db-decode`/`info` on `.ctf`) and `.database` decoding require schema XMLs
  that DR2 does not ship — blocked until a community schema is supplied.
- All tool test suites pass: nefs_unpack (9), database_convert (12),
  pssg_convert (14), pssg_unpack (6), jpk_unpack (3), erp_unpack (3),
  dic_unpack (4), ctf_convert (13).

### M3 — Unreal Engine 5 migration (deferred)
- [ ] Decide physics approach: **Chaos Vehicle** vs **custom C++ solver**
- [ ] Asset import plugin for UE5
- [ ] FSH/track/vehicle assembly in-engine

## Non-goals
- Redistribution of proprietary assets
- Paid tools or paid plugin distribution
- Online/multiplayer reverse engineering

## Tools
- Language: Python 3.12 (matches `rxinfinite` / `RBR-RE` projects)
- Dependencies: `cryptography` (AES), stdlib `zlib`
- Tests: `pytest` (synthetic fixtures; real-file validation when available)

## Reference
- `VictorBush.Ego.NefsLib` (C#) — used as format reference under its MIT
  license; this repo is a clean Python reimplementation of the *format*,
  not a copy of the code.