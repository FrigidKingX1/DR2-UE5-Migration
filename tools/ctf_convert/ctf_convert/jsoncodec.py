import json

from .ctf import CtfFormatError
from .model import FloatList
from .schema import CtfSchema


def entries_to_json(entries, schema: CtfSchema, flag=None):
    """Serialize parsed entries as a friendly json document.

    ``flag`` is the value of the schema's ``flag`` entry (its numeric id is
    recorded too, for round-tripping schemas where a different entry carries
    the flag).
    """
    flag_id = None
    if flag is None:
        for i, e in enumerate(schema.entries):
            if e.name == "flag":
                flag = entries.get(i)
                break
    for i, e in enumerate(schema.entries):
        if e.name == "flag":
            flag_id = i
            break
    payload = {}
    for id in sorted(entries):
        info = schema.entries[id]
        payload[info.name] = _encode(info.type, entries[id])
    return {
        "schema": _basename(schema.name),
        "flag": flag,
        "flagEntryId": flag_id,
        "entries": payload,
        "order": [e.name for e in schema.entries],
    }


def json_to_entries(data, schema: CtfSchema):
    """Build ``{schema_id: value}`` for :func:`write_ctf` from json output."""
    if not isinstance(data, dict) or "entries" not in data:
        raise CtfFormatError("json document must be an object with an 'entries' mapping")
    payload = data["entries"]
    flag = data.get("flag")
    flag_entry = schema.by_name.get("flag")
    if flag is None and flag_entry is not None:
        flag = 0

    entries = {}
    for info in schema.entries:
        if info.name in ("magic", "flag"):
            if info.name == "magic":
                entries[info.id] = _decode(info.type, payload.get(info.name, 0))
            elif flag is not None:
                entries[info.id] = flag
            continue
        if info.name in payload:
            entries[info.id] = _decode(info.type, payload[info.name])
    return entries


def _basename(path):
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _encode(type, value):
    if type == "float-list":
        return (value if isinstance(value, FloatList) else FloatList(0, 0.0, list(value))).to_dict()
    return value


def _decode(type, value):
    if type == "float-list":
        if isinstance(value, FloatList):
            return value
        return FloatList.from_dict(value)
    return value