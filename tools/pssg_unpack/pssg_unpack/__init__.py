"""pssg_unpack — EGO PSSG (big-endian binary scene graph) reader/writer.

Reference port of EgoEngineLibrary/Graphics/Pssg (MIT).
"""

from __future__ import annotations

from . import constants
from .model import PssgAttribute, PssgElement, PssgFile
from .reader import PssgFormatError, read_pssg
from .writer import write_pssg

__all__ = [
    "PssgAttribute",
    "PssgElement",
    "PssgFile",
    "PssgFormatError",
    "read_pssg",
    "write_pssg",
    "constants",
]

__version__ = "0.1.0"