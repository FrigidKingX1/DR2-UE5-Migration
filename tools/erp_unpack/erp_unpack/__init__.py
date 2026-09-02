"""erp_unpack — EGO Resource Package (.erp) extractor.

Reference port of EgoEngineLibrary/Archive/Erp/ (MIT).
"""

from __future__ import annotations

from .archive import (
    ErpFile,
    ErpFormatError,
    ErpFragment,
    ErpResource,
    extract_erp,
    extract_resource,
    read_erp,
)

__all__ = [
    "ErpFile",
    "ErpFragment",
    "ErpResource",
    "ErpFormatError",
    "read_erp",
    "extract_resource",
    "extract_erp",
]

__version__ = "0.1.0"
