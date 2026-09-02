# DR2-UE5-Migration

Personal, non-commercial reverse-engineering and migration tooling for
DiRT Rally 2.0 (EGO Engine) assets to Unreal Engine 5.

**Never redistribute** original game assets or extracted reproductions.  This
project is for private research only.

## Layout

```
docs/                     FORMATS.md, ENCRYPTION.md, ROADMAP.md
tools/nefs_unpack/        Python NeFS archive unpacker (the working first deliverable)
assets/                   extraction target (gitignored)
schemas/                  (planned) asset schemas
unreal/                   (deferred) UE5 plugin
```

## nefs_unpack

Python port of the EGO NeFS archive format (DR2 uses v1.6.0).  Handles
standard `.nefs`/`.nfs` and split-header `.dat` archives, directory trees,
and AES-256-ECB + zlib/LZSS detransform.

```bash
cd tools/nefs_unpack

# Locate split headers inside the game exe
python -m nefs_unpack scan "path/to/DR2/dirtgame.exe" [data_dir]

# List a standalone archive
python -m nefs_unpack list archive.nefs

# Extract a standalone archive
python -m nefs_unpack unpack archive.nefs --out extracted/

# Extract a split .dat using offsets found by `scan`
python -m nefs_unpack unpack archive.dat \
    --exe "path/to/DR2/dirtgame.exe" \
    --primary 0x<hex> --secondary 0x<hex> \
    --out extracted/
```

Tests (synthetic fixtures prove format correctness without real files):

```bash
cd tools/nefs_unpack && python -m pytest -q
```

## Docs

- [FORMATS.md](docs/FORMATS.md) — NeFS header/table/item layout
- [ENCRYPTION.md](docs/ENCRYPTION.md) — AES-ECB/RSA-intro/XOR encoding
- [ROADMAP.md](docs/ROADMAP.md) — project plan

## Reference
- Format reference: [VictorBush.Ego.NefsLib](https://github.com/EgoEngineModding/ego.nefsedit)
  (read under its license; this project is a Python reimplementation of the format).