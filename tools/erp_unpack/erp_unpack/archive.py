"""EGO ERP archive reader and extractor.

Implements the ERP ("KPAR") package format used by EGO Engine titles.
DiRT Rally 2.0 uses ERP version 4.  Extension: `.erp`.

Reference port of EgoEngineLibrary/Archive/Erp/ (MIT).
"""

from __future__ import annotations

import io
import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import List, Optional

from .constants import ERP_MAGIC, HEADER_SIZE, SUPPORTED_VERSION, Compression


class ErpFormatError(Exception):
    pass


@dataclass
class ErpFragment:
    name: str
    offset: int
    size: int          # uncompressed size
    flags: int
    compression: int
    packed_size: int
    data_offset: int   # absolute offset in file where raw payload starts

    @property
    def is_compressed(self) -> bool:
        return Compression.is_compressed(self.compression)

    def decompress(self, blob: bytes) -> bytes:
        if Compression.is_compressed(self.compression):
            if self.compression in Compression.ZLIB_VALUES:
                return zlib.decompress(blob)
            elif self.compression in Compression.ZSTD_VALUES:
                try:
                    import zstandard as zstd
                    return zstd.ZstdDecompressor().decompress(blob, max_output_size=self.size)
                except ImportError:
                    raise ErpFormatError(
                        "Fragment uses Zstandard compression; install 'zstandard' "
                        "to decompress.")
            else:
                raise ErpFormatError(f"Unknown compression type {self.compression:#x}")
        else:
            return blob


@dataclass
class ErpResource:
    identifier: str
    resource_type: str
    unknown: int = 0
    unknown2: int = 0
    hash: bytes = b""
    fragments: List[ErpFragment] = field(default_factory=list)

    def _clean_identifier(self) -> str:
        # Strip an "eaid://" scheme prefix to get the on-disk path.
        id_ = self.identifier
        if id_.lower().startswith("eaid"):
            # strip up to and including "://"
            if "://" in id_:
                return id_.split("://", 1)[1]
            return id_[4:]
        return id_

    @property
    def file_name(self) -> str:
        return os.path.basename(self._clean_identifier())

    @property
    def folder(self) -> str:
        path = self._clean_identifier()
        if path.startswith("/"):
            path = path.lstrip("/")
        d = os.path.dirname(path)
        return "" if d in ("", "/", ".", "\\") else d

    @property
    def size(self) -> int:
        return sum(f.size for f in self.fragments)


@dataclass
class ErpFile:
    version: int
    resource_offset: int
    resources: List[ErpResource] = field(default_factory=list)


def _read_string(raw: bytes, offset: int, length: int) -> str:
    chunk = raw[offset:offset + length]
    end = chunk.find(b"\x00")
    if end != -1:
        chunk = chunk[:end]
    return chunk.decode("utf-8", errors="replace")


def read_erp(file_path: str) -> tuple[ErpFile, bytes]:
    """Parse an ERP archive.  Returns (ErpFile, whole-file bytes)."""
    with open(file_path, "rb") as f:
        raw = f.read()

    if len(raw) < HEADER_SIZE:
        raise ErpFormatError("File too small to be an ERP archive.")
    magic, version = struct.unpack_from("<II", raw, 0)
    if magic != ERP_MAGIC:
        raise ErpFormatError("Not an ERP file (bad magic).")
    if version < 0 or version > SUPPORTED_VERSION:
        raise ErpFormatError(f"Unsupported ERP version {version}.")

    # Skip: 8 padding, 8 info offset, 8 info size
    resource_offset = struct.unpack_from("<Q", raw, 0x20)[0]
    num_files, num_temp_files = struct.unpack_from("<II", raw, 0x30)

    pos = 0x38
    resources: List[ErpResource] = []
    for _ in range(num_files):
        pos = _read_resource(raw, pos, version, resource_offset, resources)

    return ErpFile(version, resource_offset, resources), raw


def _read_resource(raw: bytes, pos: int, version: int, resource_offset: int,
                   resources: List[ErpResource]) -> int:
    if pos + 4 > len(raw):
        raise ErpFormatError("Truncated ERP resource info block.")
    entry_len = struct.unpack_from("<I", raw, pos)[0]
    pos += 4

    id_len = struct.unpack_from("<h", raw, pos)[0]
    if id_len < 0:
        id_len = 0
    pos += 2
    identifier = _read_string(raw, pos, id_len)
    pos += id_len

    resource_type = _read_string(raw, pos, 16)
    pos += 16

    unknown = struct.unpack_from("<I", raw, pos)[0]
    pos += 4

    unknown2 = 0
    if version >= 4:
        unknown2 = struct.unpack_from("<h", raw, pos)[0]
        pos += 2

    num_fragments = raw[pos]
    pos += 1

    res = ErpResource(identifier, resource_type, unknown, unknown2)
    for _ in range(num_fragments):
        pos = _read_fragment(raw, pos, version, resource_offset, res)

    if version > 2:
        res.hash = raw[pos:pos + 16]
        pos += 16

    resources.append(res)
    return pos


def _read_fragment(raw: bytes, pos: int, version: int, resource_offset: int,
                   res: ErpResource) -> int:
    name = _read_string(raw, pos, 4)
    pos += 4
    offset, size = struct.unpack_from("<QQ", raw, pos)
    pos += 16
    flags = struct.unpack_from("<i", raw, pos)[0]
    pos += 4
    compression = Compression.NONE
    packed_size = size
    if version > 2:
        compression = raw[pos]
        pos += 1
        packed_size = struct.unpack_from("<Q", raw, pos)[0]
        pos += 8

    data_offset = resource_offset + offset
    res.fragments.append(ErpFragment(
        name, offset, size, flags, compression, packed_size, data_offset))
    return pos


def extract_resource(res: ErpResource, raw: bytes) -> bytes:
    """Extract and concatenate a resource's fragments into one byte blob."""
    out = io.BytesIO()
    for frag in res.fragments:
        blob = raw[frag.data_offset:frag.data_offset + frag.packed_size]
        out.write(frag.decompress(blob))
    return out.getvalue()


def extract_erp(file_path: str, out_dir: str) -> List[str]:
    """Extract all resources in an ERP archive to ``out_dir``.

    Returns the list of paths written (relative to ``out_dir``)."""
    erp, raw = read_erp(file_path)
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []

    for res in erp.resources:
        data = extract_resource(res, raw)
        rel_dir = res.folder
        rel_path = os.path.join(rel_dir, res.file_name) if res.file_name else rel_dir
        target = os.path.join(out_dir, rel_path)
        os.makedirs(os.path.dirname(target) or out_dir, exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        written.append(rel_path)

    return written
