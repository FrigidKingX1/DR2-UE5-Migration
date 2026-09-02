# DiRT Rally 2.0 — NeFS Archive Format

Reference: reverse-engineering effort for personal, non-commercial migration to
Unreal Engine 5.  Everything below is a Python-portable description of the
`VictorBush.Ego.NefsLib` C# library layout for DiRT Rally 2.0.

> **Version caveat.** DiRT Rally 2.0's actual archives are NeFS **v2.0.0**
> (`0x20000`), not v1.6.0 (`0x10600`).  The TOC block layout and writable-data
> validation differ between the two (see §2.1 and §4).  This document covers
> both, marking the v2.0.0 (B200) specific rules.

## 1. Overview

EGO titles store most game data in **NeFS** ("NeFS") archives.  Two physical
flavours exist:

| Type           | Files                | Header location             | Item data location         |
|----------------|----------------------|-----------------------------|----------------------------|
| Standard       | `*.nefs`, `*.nfs`    | Inline at file offset 0     | In the same file           |
| Split (headless) | `*.dat` + game exe | Primary+secondary header blocks inside the **executable** | In the `.dat` file |

DiRT Rally 2.0 uses version `0x10600` (v1.6.0).  v1.5.1+ introduced
[random-padded AES](ENCRYPTION.md) and the split header.

### Endianness

Most NeFS variants are **little-endian**.  Some console builds store the header
in big-endian; the FourCC is written byte-swapped.  Auto-detection: if the
32-bit value at the offset `< 4 bytes>` equals `0x5346544E` (little) → LE;
`0x4E465433` (big) → BE.

## 2. Header

A header is built from eight *parts*.  In a standard `.nefs` the parts sit
contiguously at file offset 0.  In a split `.dat`, parts 0–5 & 8 live in the
game executable's **primary header block** and parts 6–7 in a **secondary
header block** (both located via a `NeFS` magic scan + writable-data
validation).

### Part 0 — Header intro (`NefsTocHeaderA160`), 128 bytes

| Offset | Size | Field                          | Notes                            |
|--------|------|--------------------------------|----------------------------------|
| 0x00   | 4    | Magic (`0x5346544E`)           | "NeFS"                           |
| 0x04   | 32   | Hash (SHA-256)                 | Header integrity hash            |
| 0x24   | 64   | AES key (ASCII hex)            | 64 hex chars → 32-byte AES key   |
| 0x64   | 4    | TocSize                        | Total size of all header parts   |
| 0x68   | 4    | Version                        | `0x10600` for DR2                |
| 0x6C   | 4    | NumEntries                     | Entry count                      |
| 0x70   | 4    | UserValue                      |                                  |
| 0x74   | 12   | Padding (±)                    | Random bytes                     |

> **Encrypted/DLC headers**: in earlier EGO titles (incl. some DR2 DLC) the
> intro is RSA-"encrypted" with an embedded public key (raw RSA-1024, no
> padding, exponent 0x10001).  Before magic read, the intro bytes are raised to
> `pub_exp mod public_modulus`.  See [ENCRYPTION.md](ENCRYPTION.md).
>
> **v1.5.1**: some headers are XOR-obfuscated (see ENCRYPTION.md).

### Part T — Table of contents (`NefsTocHeaderB160`), 128 bytes

Relative to the header base (for standard `.nefs`: `offset 0`; for split:
the primary header block start):

| Offset | Size | Field                    | Notes                                |
|--------|------|--------------------------|--------------------------------------|
| 0x00   | u16  | NumVolumes               |                                      |
| 0x02   | u16  | HashBlockSize **lo**     | stored `<< 15`                       |
| 0x04   | u16  | BlockSize **lo**         | stored `<< 15`                       |
| 0x06   | u16  | SplitSize **lo**         | stored `<< 15`                       |
| 0x08   | u32  | EntryTableStart          | part 1                               |
| 0x0C   | u32  | WritableEntryTableStart  | part 6 (secondary)                   |
| 0x10   | u32  | SharedEntryInfoTableStart| part 2                               |
| 0x14   | u32  | WritableSharedEntryInfoTableStart | part 7 (secondary)            |
| 0x18   | u32  | NameTableStart           | part 3                               |
| 0x1C   | u32  | BlockTableStart          | part 4                               |
| 0x20   | u32  | VolumeInfoTableStart     | part 5                               |
| 0x24   | u32  | HashDigestTableStart     | part 8                               |

> **De-shift!** `BlockSize`, `HashBlockSize`, `SplitSize` are stored in the low
> bits (value `<< 15`).  Actual size = `lo << 15`.

### Part T200 — TOC (**v2.0.0** `NefsTocHeaderB200`), 128 bytes

DiRT Rally 2.0 archives use this layout.  It **drops** the two `block_size_lo`
/ `split_size_lo` u16 words that v1.6.0 has: only `num_volumes` and
`hash_block_size_lo` remain in the low 4 bytes, and everything after the first
32 bytes is padding.

| Offset | Size | Field                    | Notes                                |
|--------|------|--------------------------|--------------------------------------|
| 0x00   | u16  | NumVolumes               |                                      |
| 0x02   | u16  | HashBlockSize **lo**     | stored `<< 15`                       |
| 0x04   | u32  | EntryTableStart          | part 1                               |
| 0x08   | u32  | WritableEntryTableStart  | part 6 (secondary)                   |
| 0x0C   | u32  | SharedEntryInfoTableStart| part 2                               |
| 0x10   | u32  | WritableSharedEntryInfoTableStart | part 7 (secondary)            |
| 0x14   | u32  | NameTableStart           | part 3                               |
| 0x18   | u32  | BlockTableStart          | part 4                               |
| 0x1C   | u32  | VolumeInfoTableStart     | part 5                               |
| 0x20   | u32  | HashDigestTableStart     | part 8                               |
| 0x24   | 92   | Padding                  | zeros                                |

> This 128-byte TOC is the "B200" layout that the v2.0.0 split-header finder
> must parse.  Confusing it with the B160 layout (reading the extra two u16s)
> is what broke the DR2 exe finder.

### Part 1 — Entry table (20 bytes each)

| Offset | Size | Field            |
|--------|------|------------------|
| 0x00   | u32  | Data offset **A** (low) |
| 0x04   | u32  | Data offset **B** (high) |
| 0x08   | u32  | SharedEntryInfo  (index into part 2) |
| 0x0C   | u32  | FirstBlockIndex  (index into part 4) |
| 0x10   | u32  | NextDuplicate    (index of duplicate entry) |

64-bit data offset = `A | (B << 32)`.

### Part 2 — Shared entry info (20 bytes each)

| Offset | Size | Field            |
|--------|------|------------------|
| 0x00   | u32  | Parent           (parent entry index) |
| 0x04   | u32  | FirstChild       |
| 0x08   | u32  | NameOffset       (into part 3) |
| 0x0C   | u32  | Size             (extracted size) |
| 0x10   | u32  | FirstDuplicate   |

### Part 3 — Name table

NUL-terminated ASCII string table.  `NameOffset` from part 2 (file) / part 5
(volume) points here.  `size` in part 2 = length of the string.

### Part 4 — Block table (8 bytes each)

| Offset | Size | Field          |
|--------|------|----------------|
| 0x00   | u32  | **End** (cumulative transformed size of all blocks up to & including this one) |
| 0x04   | u16  | **Transformation** (enum, see below) |
| 0x06   | u16  | **Checksum** (CRC-16) |

Per-chunk size = `End[i] - End[i-1]` (with `End[-1] = 0`).

**Transformation values** (`NefsDataTransformType`):

| Value | Meaning |
|-------|---------|
| 0     | None (raw) |
| 1     | LZSS compressed |
| 4     | AES-256-ECB encrypted |
| 7     | zlib compressed |

If the entry's `WritableEntry.Flags` has `Transformed` set, each block uses its
own transformation from this table; otherwise all blocks are treated as if
`None`.

### Part 5 — Volume info table (16 bytes each)

| Offset | Size | Field       |
|--------|------|-------------|
| 0x00   | u64  | Size        |
| 0x08   | u32  | NameOffset  (into part 3) |
| 0x0C   | u32  | DataOffset  (offset into data file) |

Volume 0 is the primary data file (`.dat` / `.nefs`).  Additional volumes are
referenced as separate files whose name is `NameOffset`.

### Part 6 — Writable entry table (secondary block) (4 bytes each)

| Offset | Size | Field   |
|--------|------|---------|
| 0x00   | u16  | Volume  |
| 0x02   | u16  | Flags   |

Flags (`NefsTocEntryFlags150/160`):

| Bit | Name       | Value |
|-----|------------|-------|
| 0   | Transformed| 1 |
| 1   | Directory  | 2 |
| 2   | Duplicated | 4 |
| 3   | Cacheable  | 8 |
| 4   | LastSibling| 16 |
| 5   | Patched    | 32 |

> Valid-mask sanity: `Flags & ~0x3F == 0` (i.e. only bits 0–5 set).

### Part 6b — Writable entry flags (**v2.0.0** `NefsTocEntryFlags200`)

DiRT Rally 2.0's writable-entry flags are a **different enum** from v1.6.0 and
there is **no `Patched` bit**:

| Bit | Name         | Value |
|-----|--------------|-------|
| 0   | IsZlib       | 1 |
| 1   | IsAes        | 2 |
| 2   | IsDirectory  | 4 |
| 3   | IsDuplicated | 8 |
| 4   | LastSibling  | 16 |

> Valid-mask sanity: `Flags & ~0x1F == 0` (only bits 0–4 set).  A single file
> that is both zlib- and AES-compressed carries `flags = 0x3`; duplicated + zlib
> + AES = `0xB`, etc.

### Part 7 — Writable shared entry info (secondary block) (8 bytes each)

| Offset | Size | Field          |
|--------|------|----------------|
| 0x00   | u32  | NextSibling    |
| 0x04   | u32  | PatchedEntry   |

### Part 8 — Hash digest table

SHA-256 (32-byte) digests, one per "hash block".  Number of digests:

    num_hashes = ceil((volume.size - volume.data_offset) / hash_block_size)

The digests cover the (compressed) data in the primary volume.

## 3. Item data

For each file `i`:

- Data starts at `entry.Start` (absolute offset into the data volume).
- The file is split into `ceil(extracted_size / block_size)` blocks.
- Each block `j` occupies `End[j] - End[j-1]` bytes in the volume, starting at
  `entry.Start + (End[j-1])` (sequential).
- To obtain the plaintext, for each block read its `size` bytes, then apply the
  detransform chain:
  - if `Transformation == AES(4)`: AES-256-ECB decrypt (zero-padding).
  - if `Transformation == ZLIB(7)`: inflate.
  - if `Transformation == LZSS(1)`: LZSS decompress.
  - None: byte-for-byte copy.
- Concatenate chunks, truncate to `extracted_size`.

Directories carry no block data.

## 4. Split (.dat) layout

For a headless `.dat` archive:

1. Primary header block (parts 0–5, 8) lives in the executable at the `NeFS`
   magic offset.
2. Secondary header block (parts 6–7) is located by scanning the exe's writable
   `.data` region for a run of writable entries (parts 6/7) whose consistency
   validates against the primary block.  `nefs_unpack scan <exe> <game_dir>`
   automates both stages (see rules below).
3. The `.dat` file is found via volume 0's name (part 5) in the same directory
   as the exe.  `entry.Start` is an offset into this `.dat` file.

### Writable-block validation

NefsLib's `NefsExeHeaderFinderStrategy.ValidateWriteableDataAsync` accepts a
candidate start `p` when **all** of these hold for every writable entry `i`
(with `f_dir = flags & DirectoryBit`, `firstDup` the shared block's
`FirstDuplicate`, and `wshared.PatchedEntry` the writable-shared block's
`PatchedEntry`):

- `Volume < NumVolumes` and `Flags & ~mask == 0`, where `mask` is `0x3F` for
  v1.6.0, `0x1F` for v2.0.0.
- `((f_dir && entry.Start == 0) || (!f_dir && shared.FirstChild == firstDup))`
  (a directory's full 64-bit `Start` must be 0).
- `wshared.PatchedEntry == firstDup`.
- `(flags & DuplicatedBit) || firstDup == i`.

The `Start == 0` check uses the **full 64-bit** start (StartB<<32 | StartA) —
checking only StartA can reject valid directories.

### Scanning strategy (v2.0.0)

DR2's writable blocks are **not** at the start of a zero-padded window; each is
preceded by zero padding, so its real offset sits *mid-run*.  The finder must
probe **every window start inside** an admissible run, over **all 4 byte
alignments** (real DR2 blocks are 4-aligned, but the synthetic test uses an
unaligned offset).  A numpy gate pre-selects windows where every writable entry
looks plausible (`vol==0`, `flags` within mask) and that contain at least one
non-zero flag byte (to discard pure zero-padding runs), then full validation
runs on each surviving window.

### DR2 offsets (`dirtrally2.exe`, verified)

Each `.dat` volume is single-volume (`NumVolumes == 1`), so `Volume == 0` for
every item.  Primary blocks live in `.text`, secondaries in `.data`:

| `.dat`      | Primary    | Secondary | Entries |
|-------------|------------|-----------|---------|
| `game.dat`    | `0x10B3FE0` | `0x1570600` | 406  |
| `game_1.dat`  | `0x10BED68` | `0x1571980` | 2114 |
| `game_2.dat`  | `0x10DE1F0` | `0x1575800` | 242  |
| `game_2_1.dat`| `0x10F1678` | `0x1576380` | 948  |

> Passing `secondary = primary` (an old probe bug) reads garbage part-6
> flags/volumes even though names/sizes (from primary tables) look sane —
> e.g. `vol=61915`, `flags=0x4ccb`.  Real values after the fix: all `Volume==0`
> and `flags` within `0x1F`, max flag `0x14`/`0x1B` across the four volumes.

## 5. Notes

- `toc_size` (intro) can be used to compute the primary block length.
- Header scanning in the exe must look for `NeFS` in both endiannesses.
- When `SplitSize != 0` but `data_offset <= file_size`, the split-size hint may
  be bogus (observed on some console builds) — treat volume 0 as unsplit.
- Names are UTF-8-friendly ASCII; the C# code reads NUL-terminated ASCII.
- The AES key in the intro is a 64-char hex string (uppercase) → 32 bytes.

## 6. EGO Resource Package (`.erp`, "KPAR")

A flat, string-keyed blob container used for loose resources.  Magic
`0x4B504152` ("KPAR"); header is little-endian.

### Header (48 bytes)

| Offset | Size | Field            | Notes                          |
|--------|------|------------------|--------------------------------|
| 0x00   | u32  | Magic            | `0x4B504152`                   |
| 0x04   | i32  | Version          | DR2 uses 4                     |
| 0x08   | 8    | Padding          |                                |
| 0x10   | u64  | InfoOffset       | usually 48                     |
| 0x18   | u64  | InfoSize         | resource info block size       |
| 0x20   | u64  | ResourceOffset   | base for fragment data         |
| 0x28   | 8    | Padding          |                                |
| 0x30   | u32  | NumResources     |                                |
| 0x34   | u32  | NumTempFiles     | temp resources                 |

Resource info block follows the header (at ~0x38 for a default layout; readers
should walk the structure rather than trust InfoOffset).

### Resource info entry

| Field            | Size | Notes                  |
|------------------|------|------------------------|
| EntryInfoLength  | u32  | self-describing length |
| IdentifierLength | i16  | `bytes` length         |
| Identifier       | len  | UTF-8 (e.g. `eaid://...`) |
| ResourceType     | 16   | NUL-padded             |
| Unknown          | i32  |                        |
| Unknown2 (v4+)   | i16  |                        |
| NumFragments     | u8   |                        |
| Fragments        | 33 ea. | see below          |
| Hash (v3+)       | 16   | blob hash             |

### Fragment (33 bytes, v4)

| Field       | Size | Notes                     |
|-------------|------|---------------------------|
| Name        | 4    | NUL-padded ("DATA", "INFO") |
| Offset      | u64  | relative to ResourceOffset |
| Size        | u64  | uncompressed size          |
| Flags       | i32  | e.g. 16                    |
| Compression | u8   | enum below                |
| PackedSize  | u64  | bytes to read at ResourceOffset+Offset |

**Compression enum**:

| Value | Meaning                     |
|-------|-----------------------------|
| 0x00  | None                        |
| 0x01  | Zlib                        |
| 0x03  | ZStandard (Grid Legends)    |
| 0x10  | ZStandard                   |
| 0x11  | ZStandard (F1 23)           |
| 0x81, 0x90, 0x91 | None variants      |

Data begins at `ResourceOffset + Offset` and spans `PackedSize`, decompressed
to `Size` bytes.  Resource output = concatenation of its decompressed
fragments.  Implemented in `tools/erp_unpack`.

## 7. JPK (`.jpk`, "JPAK")

A minimal container of named blobs (no compression).  Magic
`0x4A50414B` ("JPAK"); little-endian; 32-byte header + 32-byte entries.

### Header (32 bytes)

| Offset | Size | Field             | Notes                     |
|--------|------|-------------------|---------------------------|
| 0x00   | u32  | Magic             | `0x4A50414B`              |
| 0x04   | 4    | Padding           | 0                         |
| 0x08   | i32  | NumEntries        |                           |
| 0x0C   | i32  | Alignment         | typically 16             |
| 0x10   | 4    | Padding           | 0                         |
| 0x14   | i32  | OffsetToFileNames | `32 + count*32`          |
| 0x18   | 8    | Padding           | 0                         |

### Entry table (32 bytes each, at `32 + i*32`)

| Field      | Size | Notes                   |
|------------|------|-------------------------|
| NameOffset | i32  | absolute file offset to NUL-terminated name |
| DataSize   | i32  |                         |
| FileOffset | i32  | absolute file offset to data |
| DataSize   | i32  | repeated                |
| Padding    | 16   |                         |

Names sit in a NUL-terminated table after the entry table; data blobs follow,
each padded to `Alignment`.  Entry data is read verbatim (no decompression).
Implemented in `tools/jpk_unpack`.

## 8. PSSG (`.pssg`, binary scene graph)

EGO's binary scene-graph/bundle container used for meshes, textures,
skeletons, shaders and scene assembly.  **Big-endian**, Latin-1 strings.
Mirrors `EgoEngineLibrary/Graphics/Pssg`.

### Top level

| Offset | Data                          |
|--------|-------------------------------|
| 0x00   | `"PSSG"` (4 ASCII)            |
| 0x04   | i32 BE `size` = `filelen - 8` |
| 0x08   | schema (below)                |
| ...    | root element tree             |

### Schema

| Field              | Size | Notes                     |
|--------------------|------|---------------------------|
| AttributeCount     | i32  |                           |
| ElementCount       | i32  |                           |
| per element:       |      |                           |
| — ElementId        | i32  | 1-based index             |
| — ElementName      | pssg str | int32 len + Latin-1 bytes |
| — SubAttrCount     | i32  |                           |
| — per attribute    |      |                           |
| — — AttributeId    | i32  | 1-based index             |
| — — AttributeName  | pssg str |                     |

→ `pssg str` = `i32 BE length` followed by that many Latin-1 bytes.

### Element

| Field          | Size | Notes                            |
|----------------|------|----------------------------------|
| ElementId      | i32  | 1-based into schema element table |
| Size           | i32  | bytes that follow the Size field |
| AttributeSize  | i32  | = sum below                   |
| attributes...  |      | each: `AttributeId(i32) + Size(i32) + value(Size bytes)` |
| value or children |  | if data element: raw bytes; else child elements |

**Attribute value encodings** (by schema attribute type):

| Schema type  | Value layout            |
|--------------|-------------------------|
| Int          | i32 BE                   |
| String       | pssg str (size field = 4 + len) |
| Float        | f32 BE                   |
| Float2/3/4   | 2/3/4 × f32 BE           |
| Unknown      | raw bytes                |

**Data-vs-container decision** (`PssgElement.ReadBinary`):

- Schema element type `None` or `Unknown` → candidate container.
- Special names always data: `DATABLOCKBUFFERED`, `NeAnimPacketData_B1`,
  `NeAnimPacketData_B4`, `RENDERINTERFACEBOUNDBUFFERED`.
- Unknown-typed elements are byte-scanned: reading `(tempID, tempSize)` pairs
  that stay in bounds → container, otherwise → data element.
- Otherwise (Byte/Float/UInt/… schemas) → data element whose bytes are the raw
  remainder of the element block.

`EgoEngineLibrary` ships a static schema (element type + attribute type by
name); the file only stores names, so the reader applies that map (names not
in the map become `Unknown` → raw bytes).  Implemented in `tools/pssg_unpack`.

## 9. Neon Sound Dictionary (`.dic`)

Codemasters' "Neon Sound Dictionary v2.00" — a container of loaded audio
samples.  Format captured by `src/010 Templates/dic.bt`.

| Sku |  Magic  | Platform |
|-----|---------|----------|
| DIC1| 0x31434944| PC (little-endian) |
| DIC2| 0x32434944| PS2 |
| DIC3| 0x44494333| PS3 (big-endian) |
| DIC4| 0x34434944| XBOX |
| DIC5| 0x44494335| X360 (big-endian) |
| DIC6| 0x36434944| PSP |
| DIC7| 0x44494337| WII (big-endian) |

### Header (16 bytes)

| Field     | Size | Notes                 |
|-----------|------|-----------------------|
| Sku       | u32  | platform magic        |
| UniqueId  | u32  | per-dictionary hash   |
| Version   | 4    | ASCII                 |
| NumBanks  | u32  |                       |

### Bank (per NumBanks)

Bank header is 24 bytes: `Offset(u32) NumSamples(u32) Name[16]`.  `Offset`
points at the bank's sample table (absolute in file), which holds:

| Field   | Size | Notes                    |
|---------|------|--------------------------|
| per sample (24 bytes): |  |                      |
| — Offset | u32 | absolute offset of audio payload |
| — Flags  | u32 | packed bitfield, see below     |
| — Name   | 16  | NUL-padded               |
| Trailer (8 bytes):     |  |                      |
| — Length | u32 | offset of end of last sample |
| — Ext    | 4   | file extension to use   |

### Sample flags (u32)

| Bits | Meaning                |
|------|------------------------|
| 0–19 | SampleRate (Hz)        |
| 20   | Loop                   |
| 21–23| NumChannels − 1        |
| 24–27| Reserved               |
| 28–30| Format (0 PCM16-BE, 1 PCM16-LE, 2 Float32, 3 ADPCM, 4–6 ATRAC) |
| 31   | Music                  |

Audio payload = `raw[nextOffset:trailerLength]` (or `[offset:Length]` for the
last sample).  Implemented in `tools/dic_unpack`.

## 10. CarTuningFile (`.ctf`)

Codemasters' XML-schema-driven car performance file (used by the whole EGO
family incl. DiRT Rally / DiRT Rally 2.0).  The binary holds **no field
names**; a sidecar schema XML (community-edited, ships with the Ego CTF
Editor) defines the entry order and types.  See `src/EgoEngineLibrary/Vehicle/`
in the Ego-Engine-Modding reference (`CtfFile.cs`, `CtfEntryInfo.cs`,
`CtfBinaryReader.cs`, `CsvFile.cs`).

### Schema XML

Root element carries `extension` (ctf/csv/all) and `line` (0-based index of
the data row when interchanging with csv).  Each child `<entry>`:

| Attribute | Meaning |
|-----------|---------|
| `name`    | required identifier |
| `type`    | `int` `float` `double` `bool` `string` `float-list` |
| `minFlag` `minOperator` | entry present only when `flag operator minFlag` (op `e lt lte gt gte`) |
| `maxFlag` `maxOperator` | same, upper bound |
| `refID`   | identifies this entry as a boolean gate referenced by `linkID` |
| `linkID`  | entry read only when the gate entry with `refID == linkID` is true |
| `readOnly` | ignored on read |
| `param name="description"` / `name="restrictedValue"` | metadata |

### Binary layout (little-endian, sequential)

Entries are read strictly in schema order, skipping flag-gated and link-gated
entries (auto-detect by name: first `magic` = i32, `flag` = i32).

| Type        | Encoding |
|-------------|----------|
| `int` `bool` | i32 (bool = 0/1) |
| `float`     | f32 |
| `double`    | f64 |
| `string`    | UTF-8, NUL-terminated |
| `float-list`| i32 count, f32 step, count×f32 |

Validation mirrors `CtfFile`: the last schema entry with `minFlag==0` must be
present, and the reader must land within one byte of EOF.  A `--lenient` read
mode tolerates files that carry extra gate-skipped entries (e.g. ctf rebuilt
from a csv, which lists every column regardless of gates), reconciling the
trailing bytes against the skipped entries in schema order.

### CSV interchange

Data row = one column per schema entry, in order, each value followed by a
comma; floats formatted `{:.6f}`.  `bool` → `0`/`1`; `float-list` → a single
semicolon cell `count;step;v1;v2;...`.  Implemented in `tools/ctf_convert`
(`info`, `to-csv`, `from-csv`, `to-json`, `from-json`).

## 11. Database (`.database`) + binary XML (`.xml`)

EGO stores most tuning and metadata in **schema-driven binary** files.
Two companion formats share the same XML DOM; both are little-endian unless
noted.

### 11.1 BinXml (`.xml` with magic `1A 22 52 72`)

| Section | Magic      | Content |
|---------|------------|---------|
| 1 | `1A 22 52 72` | magic + i32 total file size |
| 2 | `17 22 52 72` | magic + i32 size of sections 3+4 (+16) |
| 3 | `1D 22 52 72` | NUL-terminated UTF-8 string data (+ pad to 16) |
| 4 | `1E 22 52 72` | i32[ stringCount ] byte offsets of each string |
| 5 | `1B 22 52 72` | element defs: 6×i32 `{nameId,valueId,attrCount,attrStart,childCount,childStart}` |
| 6 | `1C 22 52 72` | attribute defs: 2×i32 `{nameId,valueId}` |

`childStart`/`childCount` address the element table contiguously: children are
reserved as a block (`AddRange(childCount)`) before any grandchildren are
appended, exactly as `XmlFile.BuildBinXml` does.  `valueId==0 && childCount==0`
means no text; otherwise `strings[valueId]` is the element's text.

### 11.2 BXML (`BXML`, `1B 58 4D 4C`)

Big- or little-endian node-length-prefixed tree.  Header `u8 1 + "BXML"`
(little) or `0 + "BXML"` (big), then per element:

    i16 nodeLength, u8 nodeType, u8 pad, i16 attrCount,
    name\0, attr (name\0 value\0)*, children…,
    i16 4, i16 5, i16 0   // element terminator

`nodeType` 0 = element, 1 = text node, 5 = terminator, 6 = EOF trailer
(`04 06 00` ×2).  `nodeLength` is unused on read.

### 11.3 `.database` (binary DataSet)

Little-endian, versioned by the first `u32 schemaVersion` (string-table
disabled for `1313096275` / `3934935529`).  Modern (string-table) layout
observed in DR2:

    [u32 schemaVersion][u32 0]
    per table: [u16 index][u16 0x2A2B][i32 rowCount]
    per row:   [u16 0x2A2D][u16 index][ field… ]
    trailer:   "PRTS"[u32 byteCount][ concatenated NUL-terminated strings ]

String fields are stored as a 4-byte byte-offset into the `PRTS` pool
(`dictionary[string] = poolByteOffset`; duplicates reuse the same offset).
Other types: `float` f32, `int` i32, `bool` u8 + 3 pad bytes.
Legacy (LBT) layout uses `u8 index + "LBT"` / `"ITM" + u8 index` markers and
fixed-width padded strings (`size + (4 - size%4)` or `+5` when `size%4==3`).

Decoding requires the companion **schema XML** (`schemaVersion` + per-table
`<field name= type= size= key=>` definitions).  Implemented in
`tools/database_convert` (`info`, `xml --to text|binxml|bxml`, `db-decode`
+ `db-info`).

## 12. Implemented ports (this repo)

- `constants.py` — all format constants.
- `binary_reader.py` — endian-aware byte reader.
- `header.py` — part parsers + `parse_header`.
- `header_decode.py` — RSA intro decrypt + v1.5.1 XOR decode.
- `items.py` — item/tree model + `build_item_list`.
- `transformer.py` — AES/zlib/LZSS detransform.
- `archive.py` — standard + split archive readers.
- `exe_finder.py` — exe header/writable-data locator (version-aware TOC B160/B200
  parse, v160/v200 writable-validation + flag-mask, numpy fast window scan).
- `extract.py` — recursive extraction.
- `tools/erp_unpack` — ERP (KPAR) reader/extractor + tests.
- `tools/jpk_unpack` — JPK (JPAK) reader/extractor + tests.
- `tools/pssg_unpack` — PSSG binary scene graph reader/writer + tests.
- `tools/dic_unpack` — DIC audio dictionary extractor + tests.
- `tools/ctf_convert` — CTF CarTuningFile read/write + CSV/JSON interchange + tests (port of `EgoEngineLibrary/Vehicle/CtfFile.cs`).
- `tools/pssg_convert` — PSSG mesh/texture extraction on top of `pssg_unpack`:
  - `RenderDataSourceReader` (port of `Formats/Pssg/RenderDataSourceReader.cs`) decodes
    positions/normals/tangents/colors and index buffers (big-endian `ushort`/`uint`,
    primitive `triangles`); vertex data types `float3`, `half4`, `hend3n` (11-11-10),
    colors `uint_color_argb`/`uchar4`; `ST` streams split on `float4`/`half4` into
    multiple UV sets (`half2` second-set offset of 4 bytes, `float2` of 8).
  - Scene traversal (mirror of `CarInteriorPssgGltfConverter`/`CarExteriorPssgGltfConverter`)
    finds the `NODE` (or `YYY`/F1) `LIBRARY` and recurses its node children; render nodes
    (`RENDERNODE`, `VISIBLERENDERNODE`, `MATRIXPALETTEJOINTNODE`) become meshes.  Stream
    instances (`RENDERSTREAMINSTANCE` + matrix-palette variants) resolve their `RENDERDATASOURCE`
    by `#id` and apply `indexOffset`/`indicesCountFromOffset` index subranges (SUV exterior path).
  - Texture→DDS (`dds.py`, port of `GraphicsExtensions.ToDdsFile` + `DdsFile`): DXT1–5,
    `*_srgb` → DX10 + DXGI codes, `bc6h_uf`, `bc7(_srgb)`, `ui8x4` (32bpp RGBA masks),
    `u8` (8bpp luminance); 2D (`TEXTUREIMAGE`+`TEXTUREMIPMAP`) and cube maps
    (`TEXTUREIMAGEBLOCK` → six faces concatenated +X..-Z).
  - Shader→texture bindings (`tbindings.py`): `SHADERINSTANCE`→`SHADERGROUP`→
    `SHADERINPUTDEFINITION` by `parameterID`, matched against `TDiffuseAlphaMap`,
    `TSpecularMap`, `TEmissiveMap`, `TOcclusionMap`, `TNormalMap` prefixes.
  - Wavefront OBJ/MTL writers (`obj.py`); CLI `info` + `extract --out` with a
    `pssg_manifest.json` mapping shaders to exported DDS textures.  14 tests.
- `tools/database_convert` — binary XML + `.database` codec (port of
  `EgoEngineLibrary/Xml/XmlFile.cs` + `Data/DatabaseFile.cs`):
  - BinXml/BXML detection (`GetXmlType`), text↔BinXml↔BXML round-trip,
    element/attribute string-table with contiguous child block reservation
    (mirrors `BuildBinXml`), pad-to-16 and section-size backpatch.
  - `.database` string-table (`PRTS`) + legacy `LBT`/`ITM` paths,
    schema-driven typed rows (`float`/`int`/`string`/`bool`), dedup string pool.
  - CLI `info`, `xml --to`, `db-decode`/`db-info`.  12 tests.