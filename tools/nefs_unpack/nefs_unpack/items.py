"""Item model: files/directories in a NeFS archive and their data blocks.

Ports the role of VictorBush.Ego.NefsLib (NefsItem, NefsItemSize,
NefsDataChunk) for reconstructing the directory tree and locating/decompressing
item data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .constants import (
    NO_BLOCKS_INDEX,
    DataTransformType,
    EntryFlags,
    EntryFlags200,
    NefsVersion,
)
from .header import NeFSHeader, VolumeInfo


@dataclass
class DataChunk:
    size: int             # transformed bytes in this chunk
    cumulative_size: int  # running total of transformed bytes
    transform_type: int   # DataTransformType
    offset: int           # offset of this chunk's raw bytes in the data volume
    checksum: int = 0


@dataclass
class NefsItem:
    id: int
    file_name: str
    directory_id: int
    is_directory: bool
    is_duplicate: bool
    first_duplicate_id: int
    extracted_size: int
    data_offset: int                   # offset in data volume (only for files)
    volume_index: int
    chunks: List[DataChunk] = field(default_factory=list)
    is_transformed: bool = False
    flags: int = 0
    # v2.0.0 item-level transform (from writable-entry flags).
    is_zlib: bool = False
    is_aes: bool = False
    version: int = 0

    @property
    def transformed_size(self) -> int:
        if not self.chunks:
            return self.extracted_size
        return self.chunks[-1].cumulative_size


class NeFSItemList:
    """Holds all items plus the volume (data file) sources."""

    def __init__(self, header: NeFSHeader, volume_paths: List[str]):
        self.header = header
        self.volume_paths = volume_paths
        self.items: List[NefsItem] = []
        # id -> item for quick lookup
        self._by_id: dict = {}

    def add(self, item: NefsItem) -> None:
        self.items.append(item)
        self._by_id[item.id] = item

    def get(self, item_id: int) -> Optional[NefsItem]:
        return self._by_id.get(item_id)

    def volume_path(self, index: int) -> str:
        return self.volume_paths[index]

    def build_tree(self) -> "NefsDirectoryNode":
        """Reconstruct a directory tree from the flat item list."""
        root = NefsDirectoryNode(".", None)
        # Directory items are referenced by parent() == own id.
        for item in self.items:
            if item.is_directory:
                node = NefsDirectoryNode(item.file_name, item)
                root.children[item.id] = node
        # Attach files and subdirectories to their parent directory.
        for item in self.items:
            if item.is_directory:
                continue
            parent = self.get(item.directory_id)
            if parent is None or parent.id == item.id:
                root.files.append(item)
            else:
                parent_dir = root.children.get(parent.id)
                if parent_dir is not None:
                    parent_dir.files.append(item)
        # Now place directories under their parents (non-root).
        for item in self.items:
            if not item.is_directory or item.id == item.directory_id:
                continue
            parent_id = item.directory_id
            # Parent might be a non-directory entry whose shared parent is root.
            parent_item = self.get(parent_id)
            parent_dir_id = parent_item.directory_id if parent_item else item.id
            parent_node = root.children.get(parent_dir_id)
            if parent_node is not None:
                parent_node.dirs.append(item)
        return root


@dataclass
class NefsDirectoryNode:
    name: str
    item: Optional[NefsItem]
    dirs: List[NefsItem] = field(default_factory=list)
    files: List[NefsItem] = field(default_factory=list)
    children: dict = field(default_factory=dict)


def build_item_list(header: NeFSHeader, data_file_paths: List[str]) -> NeFSItemList:
    """Build the item list from the parsed header.  Mirrors
    NefsItemListBuilder160/200.BuildItem."""
    item_list = NeFSItemList(header, data_file_paths)
    block_size = header.toc.block_size or header.toc.hash_block_size or 0x10000
    if block_size == 0:
        block_size = 0x10000
    version = header.intro.version

    for idx in range(header.intro.num_entries):
        try:
            item_list.add(_build_item(header, idx, block_size, version))
        except Exception:
            # Mirror NefsLib: skip items that fail to build.
            continue

    # Associate volumes with names from volume info table.
    _assign_volume_paths(header, item_list, data_file_paths)
    return item_list


def _assign_volume_paths(header, item_list, data_file_paths) -> None:
    paths: List[str] = []
    for i, vol in enumerate(header.volumes):
        if i == 0:
            paths.append(data_file_paths[i] if i < len(data_file_paths) else "")
        else:
            name = vol.name or f"volume_{i}"
            import os
            base_dir = os.path.dirname(data_file_paths[0])
            paths.append(os.path.join(base_dir, name))
    item_list.volume_paths = paths


def _build_item(header: NeFSHeader, idx: int, block_size: int, version: int) -> NefsItem:
    if version == NefsVersion.VERSION_200:
        return _build_item_v200(header, idx, block_size, version)

    entry = header.entries[idx]
    shared = header.shared_entries[entry.shared_info]
    writable = header.writable_entries[idx]

    flags = writable.flags
    is_directory = bool(flags & EntryFlags.DIRECTORY)
    is_transformed = bool(flags & EntryFlags.TRANSFORMED)
    is_duplicated = bool(flags & EntryFlags.DUPLICATED)

    file_name = header.get_file_name(shared.name_offset)
    data_offset = entry.start
    extracted_size = shared.size

    chunks: List[DataChunk] = []
    if not is_directory:
        num_blocks = (extracted_size + block_size - 1) // block_size
        blocks = _build_blocks(header, entry.first_block, num_blocks, block_size,
                               data_offset, is_transformed)
        chunks = blocks

    return NefsItem(
        id=idx,
        file_name=file_name,
        directory_id=shared.parent,
        is_directory=is_directory,
        is_duplicate=is_duplicated,
        first_duplicate_id=shared.first_duplicate,
        extracted_size=extracted_size,
        data_offset=data_offset,
        volume_index=writable.volume,
        chunks=chunks,
        is_transformed=is_transformed,
        flags=flags,
        version=version,
    )


def _build_item_v200(header: NeFSHeader, idx: int, block_size: int, version: int) -> NefsItem:
    """Version 2.0.0 item builder (ports NefsItemListBuilder200.BuildItem)."""
    entry = header.entries[idx]
    shared = header.shared_entries[entry.shared_info]
    writable = header.writable_entries[idx]

    flags = writable.flags
    is_directory = bool(flags & EntryFlags200.IS_DIRECTORY)
    is_zlib = bool(flags & EntryFlags200.IS_ZLIB)
    is_aes = bool(flags & EntryFlags200.IS_AES)
    is_duplicated = bool(flags & EntryFlags200.IS_DUPLICATED)

    file_name = header.get_file_name(shared.name_offset)
    data_offset = entry.start
    extracted_size = shared.size

    chunks: List[DataChunk] = []
    is_transformed = False
    if not is_directory and entry.first_block != NO_BLOCKS_INDEX:
        # Item is transformed: block table only stores cumulative End sizes;
        # the transform kind is item-level (zlib / aes from flags).
        is_transformed = True
        num_blocks = (extracted_size + block_size - 1) // block_size
        chunks = _build_blocks_v200(header, entry.first_block, num_blocks,
                                    data_offset)

    return NefsItem(
        id=idx,
        file_name=file_name,
        directory_id=shared.parent,
        is_directory=is_directory,
        is_duplicate=is_duplicated,
        first_duplicate_id=shared.first_duplicate,
        extracted_size=extracted_size,
        data_offset=data_offset,
        volume_index=writable.volume,
        chunks=chunks,
        is_transformed=is_transformed,
        flags=flags,
        is_zlib=is_zlib,
        is_aes=is_aes,
        version=version,
    )


def _build_blocks_v200(header, first_block, num_blocks, data_offset):
    """Build DataChunks for a v2.0.0 item.  Block table entries only carry the
    cumulative transformed size (`End`); per-chunk transform is item-level."""
    chunks = []
    prev_end = 0
    for i in range(first_block, first_block + num_blocks):
        block = header.blocks[i]
        transformed_size = block.end
        size = transformed_size - prev_end
        chunks.append(DataChunk(
            size=size,
            cumulative_size=transformed_size,
            transform_type=DataTransformType.NONE,  # unused; item-level transform
            offset=data_offset + prev_end,
            checksum=0,
        ))
        prev_end = transformed_size
    return chunks


def _build_blocks(header, first_block, num_blocks, block_size, data_offset, is_transformed):
    """Build the DataChunk list from the block table.  Ports
    NefsItemListBuilder.BuildBlockList + NefsItemListBuilder160 logic.

    Mirrors NefsLib: if the entry is NOT flagged transformed, all blocks are
    treated as untransformed (raw copy), regardless of the per-block
    transformation values.  If it IS flagged transformed, each block uses its
    own transformation value.
    """
    chunks = []
    prev_end = 0
    for i in range(first_block, first_block + num_blocks):
        block = header.blocks[i]
        transformed_size = block.end
        size = transformed_size - prev_end
        if is_transformed:
            transform_type = block.transformation
        else:
            transform_type = DataTransformType.NONE
        chunks.append(DataChunk(
            size=size,
            cumulative_size=transformed_size,
            transform_type=transform_type,
            offset=data_offset + prev_end,
            checksum=block.checksum,
        ))
        prev_end = transformed_size
    return chunks
