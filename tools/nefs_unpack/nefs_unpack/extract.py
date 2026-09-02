"""Extract items from a parsed archive to disk, preserving the tree."""

from __future__ import annotations

import os

from .archive import NefsArchive
from .transformer import extract_item


def _read_volume(archive: NefsArchive, volume_index: int) -> bytes:
    """Read the raw bytes of a volume (data file) into memory."""
    path = archive.items.volume_path(volume_index)
    with open(path, "rb") as f:
        return f.read()


def _safe(name: str) -> str:
    # Reject path separators and empty names to avoid traversal.
    import re
    cleaned = re.sub(r'[\\/:*?"<>|\x00]', "_", name)
    if not cleaned or cleaned in (".", ".."):
        return "_"
    return cleaned


def extract_archive(archive: NefsArchive, out_dir: str) -> None:
    """Recursively extract ``archive`` to ``out_dir``.

    Volumes are read once and cached by index.  AES key is taken from the
    archive header.
    """
    os.makedirs(out_dir, exist_ok=True)

    # Pre-load every volume's raw bytes.
    volumes: dict = {}
    for index in range(len(archive.items.header.volumes)):
        try:
            volumes[index] = _read_volume(archive, index)
        except OSError as e:
            print(f"warning: could not read volume {index}: {e}")

    aes_key = archive.aes_key

    # Reconstruct a tree where each directory node maps name->node.
    node_by_id: dict = {}
    for item in archive.items.items:
        if item.is_directory:
            node_by_id[item.id] = {"item": item, "files": [], "dirs": {}}

    # Attach every file/subdir to its parent directory's node.
    for parent_item in archive.items.items:
        if parent_item.is_directory and parent_item.id in node_by_id:
            node = node_by_id[parent_item.id]
            for sub_item in archive.items.items:
                if sub_item.id == parent_item.id:
                    continue
                if sub_item.is_directory and sub_item.directory_id == parent_item.id \
                        and sub_item.id in node_by_id:
                    node["dirs"][sub_item.id] = node_by_id[sub_item.id]
                elif not sub_item.is_directory and sub_item.directory_id == parent_item.id:
                    node["files"].append(sub_item)

    # Determine the top-level node.
    # The archive root is the self-parented directory (parent == own id), or a
    # directory with an empty name.  Everything else attaches under it.
    root_item = None
    for item in archive.items.items:
        if item.is_directory and (
            item.directory_id == item.id or not item.file_name
        ):
            root_item = item
            break
    if root_item is not None and root_item.id in node_by_id:
        top = node_by_id[root_item.id]
    else:
        # No explicit root directory: build a synthetic one.
        top = {"files": [], "dirs": {}}
        for item in archive.items.items:
            if item.is_directory:
                parent = archive.items.get(item.directory_id)
                if parent is None or not parent.is_directory:
                    top["dirs"][item.id] = node_by_id[item.id]
            else:
                parent = archive.items.get(item.directory_id)
                if parent is None or not parent.is_directory:
                    top["files"].append(item)

    _walk(archive, top, out_dir, volumes, aes_key)


def _walk(archive, node, out_dir, volumes, aes_key):
    for item in node["files"]:
        path = os.path.join(out_dir, _safe(item.file_name))
        data = extract_item(volumes.get(item.volume_index, b""), item, aes_key)
        if item.volume_index not in volumes:
            print(f"warning: volume {item.volume_index} not available, empty output for {item.file_name}")
        with open(path, "wb") as f:
            f.write(data)
    for node_id, sub in node["dirs"].items():
        item = sub["item"]
        sub_dir = os.path.join(out_dir, _safe(item.file_name))
        os.makedirs(sub_dir, exist_ok=True)
        _walk(archive, sub, sub_dir, volumes, aes_key)
