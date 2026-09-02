"""Synthetic fixtures for database_convert tests.

Builds in-memory EGO schema XML, BinXml files, BXML files and a ``.database``
binary via the public writer API, so tests round-trip byte-exact output.
"""

from __future__ import annotations

from database_convert.database import (
    Database,
    Field,
    Table,
    write_database,
    xml_to_schema,
)
from database_convert.xmlcodec import XmlDoc, dump


def build_schema_xml():
    """An EGO schema XmlDoc describing two tables."""
    root = XmlDoc("schema")
    sv = XmlDoc("schemaVersion", attrs=[("version", "539233987")])
    root.children.append(sv)
    t1 = XmlDoc("cars", attrs=[("name", "cars")])
    for nm, ty, size, key in [
        ("ID", "int", None, "primary"),
        ("Model", "string", "64", None),
        ("Mass", "float", None, None),
    ]:
        attrs = [("name", nm), ("type", ty)]
        if size:
            attrs.append(("size", size))
        if key:
            attrs.append(("key", key))
        t1.children.append(XmlDoc("field", attrs=attrs))
    root.children.append(t1)

    t2 = XmlDoc("tyres", attrs=[("name", "tyres")])
    for nm, ty, size, key in [
        ("Name", "string", "16", None),
        ("Grip", "float", None, None),
        ("Flag", "bool", None, None),
    ]:
        attrs = [("name", nm), ("type", ty)]
        if size:
            attrs.append(("size", size))
        if key:
            attrs.append(("key", key))
        t2.children.append(XmlDoc("field", attrs=attrs))
    root.children.append(t2)
    return root


def build_schema_model():
    """A Database model derived from build_schema_xml()."""
    return xml_to_schema(build_schema_xml())


def build_database_bytes():
    """A modern string-table ``.database`` with two populated tables."""
    db = Database(schema_version=539233987)
    cars = Table([
        Field("ID", "int", key="primary"),
        Field("Model", "string", size=64),
        Field("Mass", "float"),
    ], name="cars")
    cars.add_row([1, "focus_rally", 1200.5])
    cars.add_row([2, "polo_rally", 1175.0])
    db.tables.append(cars)

    tyres = Table([
        Field("Name", "string", size=16),
        Field("Grip", "float"),
        Field("Flag", "bool"),
    ], name="tyres")
    tyres.add_row(["soft", 1.05, True])
    tyres.add_row(["hard", 0.92, False])
    db.tables.append(tyres)
    return write_database(db)


def build_binxml_bytes(doc=None):
    if doc is None:
        node = XmlDoc("garage", attrs=[("id", "42")])
        child = XmlDoc("car", attrs=[("name", "focus_rally")], text="notes")
        node.children.append(child)
        doc = node
    return dump(doc, "BinXml")


def build_bxml_bytes(doc=None, little=True):
    if doc is None:
        doc = XmlDoc("Menu")
        it = XmlDoc("item", attrs=[("label", "Career")], text="Go")
        doc.children.append(it)
    return dump(doc, "BxmlLittle" if little else "BxmlBig")
