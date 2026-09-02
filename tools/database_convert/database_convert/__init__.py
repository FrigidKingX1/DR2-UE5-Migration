"""database_convert �?" convert EGO binary XML and ``.database`` files.

Provides:
  * XML flavour detection and conversion (Text <-> BinXml <-> BXML)
  * ``.database`` binary DataSet decode to readable XML (schema-driven)
"""

from __future__ import annotations

from .binio import EndianBinaryReader, EndianBinaryWriter  # noqa: F401
from .database import (  # noqa: F401
    Database,
    DatabaseError,
    Field,
    Table,
    read_database,
    write_database,
    xml_to_schema,
)
from .xmlcodec import (  # noqa: F401
    BINXML,
    BXML_BIG,
    BXML_LITTLE,
    TEXT,
    XmlDoc,
    XmlError,
    dump,
    get_xml_type,
    load,
)

__all__ = [
    "BINXML", "BXML_BIG", "BXML_LITTLE", "TEXT",
    "Database", "DatabaseError", "EndianBinaryReader", "EndianBinaryWriter",
    "Field", "Table", "XmlDoc", "XmlError",
    "dump", "get_xml_type", "load", "read_database", "write_database",
    "xml_to_schema",
]

__version__ = "0.1.0"
