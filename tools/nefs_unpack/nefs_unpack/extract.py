"""Extract items from a parsed archive to disk, preserving the tree.

Extraction is streaming: every item is read from its volume via
:func:`extract_item_from_file`, which seeks to only the byte ranges the item
needs.  Volumes (which can be multi-gigabyte split `.dat` files) are never
loaded into memory in full, keeping full-archive unpack safe on small-RAM
machines.
"""

from __future__ import annotations

import os

from .archive import NefsArchive
from .transformer import extract_item_from_file


def _safe(name: str) -> str:
    # Reject path separators and empty names to avoid traversal.
    import re
    cleaned = re.sub(r'[\\/:*?"<>|\x00]', "_", name)
    if not cleaned or cleaned in (".", ".."):
        return "_"
    return cleaned


def _volume_path(archive: NefsArchive, volume_index: int) -> str | None:
    try:
        return archive.items.volume_path(volume_index)
    except (OSError, IndexError):
        return None


def extract_archive(archive: NefsArchive, out_dir: str) -> None:
    """Recursively extract ``archive`` to ``out_dir``.

    Uses :meth:`NefsArchive.tree` (the same tree the ``list`` command renders)
    so directory nesting is consistent with how the archive is displayed.
    Items are streamed from disk via ``extract_item_from_file``, so volumes are
    never loaded into memory whole; the AES key comes from the archive header.
    """
    os.makedirs(out_dir, exist_ok=True)

    _walk(archive.tree, out_dir, archive)


def _walk(node, out_dir: str, archive: NefsArchive) -> None:
    aes_key = archive.aes_key
    for item in node.files:
        path = os.path.join(out_dir, _safe(item.file_name))
        volume_path = _volume_path(archive, item.volume_index)
        if volume_path is None:
            data = b""
            print(f"warning: volume {item.volume_index} not available, empty output for {item.file_name}")
        else:
            try:
                data = extract_item_from_file(volume_path, item, aes_key)
            except OSError as e:
                data = b""
                print(f"warning: could not read volume {item.volume_index}: {e}")
        with open(path, "wb") as f:
            f.write(data)
    for node_id, sub in node.children.items():
        sub_dir = os.path.join(out_dir, _safe(sub.name))
        os.makedirs(sub_dir, exist_ok=True)
        _walk(sub, sub_dir, archive)
