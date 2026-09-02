# DiRT Rally 2.0 — Encryption / Encoding

Personal, non-commercial study of the NeFS data-at-rest protection used by EGO
game data.

## 1. AES-256-ECB data encryption

**Applications:** all DR2 `.dat`/`.nefs` item data that is flagged `Transformed`
with block transformation `AES (4)`.

- Algorithm: AES-256.
- Mode: **ECB** (no IV).
- Key: the 32 bytes decoded from the ASCII hex string in the header intro at
  offset `0x24` (`intro.aes_key_hex`).
- Padding: `Zeros` (NefsTransformer uses `PaddingMode.Zeros`).  When decrypting
  whole ciphertext chunks that are AES-block multiples, this is lossless.

Transform order on **write** (game): `zlib compress` → `AES-ECB encrypt`.
On **read** (unpacker): `AES-ECB decrypt` → `zlib inflate`.

For v1.6.0 blocks the `Transformation` field distinguishes pure AES-ECB (value
`4`) from pure zlib (value `7`) — they are **not** combined on a single block.
See [FORMATS.md](FORMATS.md) §2 Part 4.

### ECB note

ECB encrypts each 16-byte block independently; identical plaintext blocks
produce identical ciphertext.  This has no bearing on extraction beyond
permitting chunk-level decryption with a bare block cipher (no chaining).

### Random padding after deflate

The deflate stream is followed by **random padding** so the stored chunk length
lands on an AES block boundary.  Python `zlib.decompressobj()` stops cleanly at
the logical end of the deflate stream, discarding the trailing garbage — this
is the key behavior (vs `DeflateStream` in .NET earlier) that allows a
straightforward Python port.  Decrypt whole chunk (multiple of 16 bytes) then
decompress, truncating output to `extracted_size`.

## 2. Header intro encryption (RSA)

**Application:** older EGO titles and some DLC/console headers where the intro
starts with non-'NeFS' bytes.

The 128-byte header intro is "encrypted" by raising the plaintext to the
**public** exponent mod the modulus of an RSA-1024 key embedded in the game
executable:

    plaintext = ciphertext ^ 0x10001  (mod N)

- No PKCS#1 padding; the exponent is hardcoded to `0x10001`.
- The modulus (`N`) for DiRT Rally 2 is the bytes in
  `NefsRsaKeys.DefaultPublicKey` (see `header_decode.py`).
- Multiple title keys are known (DR2, DR2-public, DR2-Alt, Dirt 2, F1 2010–14,
  Grid 2, Grid Autosport, DiRT Showdown, DiRT, OF:DR/Red River, F1 Race Stars,
  Toybox Turbos).  The unpacker tries each until the recovered intro decodes to
  `0x5346544E` ("NeFS").
- Console builds may require a byte-swap of each 16-bit unit before the modular
  exponentiation.

This is usable for DR2 DLC whose `.nefs` uses an encrypted intro; standard DR2
`.dat` splits keep the plaintext intro inside the exe.

## 3. v1.5.1 XOR obfuscation

**Application:** rare older builds (v1.5.1) where the intro is XOR-obfuscated.

The 128-byte intro is treated as an array of `uint32`.  The following XOR
passes undo the obfuscation (port of `NefsReader.DecodeXorIntroAsync`):

    vals[14] ^= vals[5]; vals[5] ^= vals[2]; vals[2] ^= vals[4];
    vals[4] ^= vals[7];  vals[7] ^= vals[3];  vals[3] ^= vals[9];
    vals[9] ^= vals[10]; vals[10] ^= vals[1]; vals[1] ^= vals[13];
    vals[13] ^= vals[11]; vals[11] ^= vals[0]; vals[0] ^= vals[12];
    vals[12] ^= vals[6];  vals[6] ^= vals[8];  vals[8] ^= vals[14];
    mod = vals[14];
    for i in 15..31: vals[i] ^= mod

## 4. Checksums

- Block table stores a CRC-16 per block (`Checksum` field).  Computed over the
  **pre-transform** (raw chunk) bytes when `SupportsBlockChecksum`.
- The header intro stores a SHA-256 of the header.  Part 8 stores one SHA-256
  digest per hash-block of the compressed data volume.

These are optional integrity checks for the unpacker; extraction does not
depend on them. (`tools/nefs_unpack` currently trusts the tables; a
`--verify` mode could validate hashes/CRCs later.)

## 5. Key handling policy

- AES key is read from the archive header; no secrets are hard-coded.
- RSA public keys for header decryption are embedded in `header_decode.py`
  (public data used only to decrypt the game's own header).
- Nothing extracted or derived from archives is ever redistributed.

## 6. Python implementation notes

- AES: `cryptography` package (`Cipher(algorithms.AES(key), modes.ECB())`).
- zlib: `zlib.decompressobj()` on raw deflate chunks (handles trailing random
  padding; see §1).
- RSA: modular exponentiation via Python big-int `pow(m, 0x10001, n)`, then
  pad to 128 bytes.
- LZSS: ring-buffer port from `LzssDecompress.cs` (see `transformer.py`).