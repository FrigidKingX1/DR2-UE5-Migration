from .ctf import CtfFormatError
from .model import FloatList
from .schema import CtfSchema


def _split_lines(text):
    return text.replace("\r\n", "\n").split("\n")


def _join_lines(lines):
    return "\r\n".join(lines)


def parse_csv_value(type, raw):
    if type == "int":
        if not raw:
            return ""
        return int(raw)
    if type == "float":
        if not raw:
            return ""
        return float(raw)
    if type == "double":
        if not raw:
            return ""
        return float(raw)
    if type == "bool":
        if not raw:
            return ""
        return bool(int(raw))
    if type == "string":
        return raw
    if type == "float-list":
        parts = raw.split(";")
        if len(parts) < 2:
            raise CtfFormatError(
                "float-list csv cells must look like 'count;step;v1;v2;...'"
            )
        count = int(parts[0])
        step = float(parts[1])
        items = [float(p) for p in parts[2:]]
        if len(items) < count:
            raise CtfFormatError(
                f"float-list cell declares {count} items but only {len(items)} present"
            )
        return FloatList(count, step, items)
    raise CtfFormatError(f"csv interchange does not support type {type!r}")


def format_csv_value(type, value):
    if type == "int":
        return str(int(value))
    if type in ("float", "double"):
        return f"{float(value):.6f}"
    if type == "bool":
        return "1" if value else "0"
    if type == "string":
        return str(value)
    if type == "float-list":
        cell = [str(int(value.count)), f"{float(value.step):.6f}"]
        cell += [f"{float(v):.6f}" for v in value.items[: value.count]]
        return ";".join(cell)
    raise CtfFormatError(f"csv interchange does not support type {type!r}")


def csv_to_entries(text, schema: CtfSchema):
    """Parse a EGO CTF csv file into ``{schema_id: value}``.

    Mirrors ``CsvFile``: every schema entry is read from the data row; gating
    is *not* applied (the row lists all columns regardless of flag).
    """
    lines = _split_lines(text)
    if schema.line >= len(lines):
        raise CtfFormatError(
            f"csv has {len(lines)} lines but schema 'line' is {schema.line}"
        )
    values = lines[schema.line].split(",")
    entries = {}
    for info in schema.entries:
        raw = values[info.id] if info.id < len(values) else ""
        entries[info.id] = parse_csv_value(info.type, raw)
    return entries


def entries_to_csv(entries, schema: CtfSchema, lines=None):
    """Render entries as a CSV document compatible with the EGO CTF Editor.

    ``lines`` (optional) preserves the other rows (header etc.) verbatim, as
    in ``CsvFile.Write``.  The data row is rebuilt from ``entries`` in schema
    order, each value followed by a comma.

    Bool entries use ``0``/``1``; float-list entries use a semicolon cell of
    the form ``count;step;v1;v2;...``.
    """
    if lines is None:
        lines = [""] * (schema.line + 1)
    else:
        lines = _split_lines(lines) if isinstance(lines, str) else list(lines)
        while len(lines) < schema.line:
            lines.append("")
    row = []
    for id in sorted(entries):
        row.append(format_csv_value(schema.entries[id].type, entries[id]))
    lines[schema.line] = ",".join(row) + ","
    return _join_lines(lines)