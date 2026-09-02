"""PSSG data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union

# Attribute value payloads
AttrValue = Union[int, str, float, tuple, bytes]


@dataclass
class PssgAttribute:
    name: str
    pssg_type: int
    size: int          # as recorded by the file (bytes the value spans)
    value: AttrValue


@dataclass
class PssgElement:
    name: str
    attributes: List[PssgAttribute] = field(default_factory=list)
    is_data: bool = False
    value: bytes = b""
    children: List["PssgElement"] = field(default_factory=list)
    size: int = 0
    attribute_size: int = 0

    def iter_all(self) -> List["PssgElement"]:
        """Depth-first flatten of this element and descendants."""
        out: List[PssgElement] = [self]
        for child in self.children:
            out.extend(child.iter_all())
        return out


@dataclass
class PssgFile:
    file_size: int = 0                                  # "file length - 8" int from header
    element_table: List[str] = field(default_factory=list)     # name by (id-1)
    attribute_table: List[tuple] = field(default_factory=list) # (name, pssg_type) by (id-1)
    root: Optional[PssgElement] = None