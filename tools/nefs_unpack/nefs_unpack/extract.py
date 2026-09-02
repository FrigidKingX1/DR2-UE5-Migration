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

    Uses :meth:`NefsArchive.tree` (the same tree the ``list`` command renders)
    so directory nesting is consistent with how the archive is displayed.
    Volumes are read once and cached by index; the AES key comes from the
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
    _walk(archive.tree, out_dir, volumes, aes_key)


def _walk(node, out_dir: str, volumes: dict, aes_key: bytes) -> None:
    for item in node.files:
        path = os.path.join(out_dir, _safe(item.file_name))
        if item.volume_index in volumes:
            data = extract_item(volumes[item.volume_index], item, aes_key)
        else:
            data = b""
            print(f"warning: volume {item.volume_index} not available, empty output for {item.file_name}")
        with open(path, "wb") as f:
            f.write(data)
    for node_id, sub in node.children.items():
        sub_dir = os.path.join(out_dir, _safe(sub.name))
        os.makedirs(sub_dir, exist_ok=True)
        _walk(sub, sub_dir, volumes, aes_key)
