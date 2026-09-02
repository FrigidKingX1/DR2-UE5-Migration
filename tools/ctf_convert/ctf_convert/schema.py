import xml.etree.ElementTree as ET

from .model import FloatList


class SchemaError(ValueError):
    pass


def _parse_int_flag(raw):
    return int(raw)


class CtfEntryInfo:
    __slots__ = (
        "id",
        "name",
        "type",
        "min_operator",
        "min_flag",
        "max_operator",
        "max_flag",
        "ref_id",
        "link_id",
        "read_only",
        "description",
        "restricted_values",
    )

    def __init__(self, entry_id, elm):
        self.id = entry_id
        self.name = elm.get("name")
        if self.name is None:
            raise SchemaError(f"ctf entry #{entry_id} missing 'name'")
        self.type = elm.get("type")
        if self.type is None:
            raise SchemaError(f"ctf entry {self.name!r} missing 'type'")
        if self.type not in ("int", "float", "double", "bool", "string", "float-list"):
            raise SchemaError(f"ctf entry {self.name!r} has unsupported type {self.type!r}")

        self.min_operator = elm.get("minOperator")
        self.min_flag = _parse_int_flag(elm.get("minFlag")) if "minFlag" in elm.attrib else -1
        self.max_operator = elm.get("maxOperator")
        self.max_flag = _parse_int_flag(elm.get("maxFlag")) if "maxFlag" in elm.attrib else -1
        self.ref_id = int(elm.get("refID")) if "refID" in elm.attrib else -1
        self.link_id = int(elm.get("linkID")) if "linkID" in elm.attrib else -1
        self.read_only = "readOnly" in elm.attrib

        self.description = ""
        self.restricted_values = []
        for param in elm:
            if not isinstance(param.tag, str):
                continue
            if param.get("name") == "description":
                self.description = param.text or ""
            elif param.get("name") == "restrictedValue":
                self.restricted_values.append(param.text or "")

    def default_value(self):
        if self.type == "int":
            return 0
        if self.type == "float":
            return 0.0
        if self.type == "double":
            return 0.0
        if self.type == "bool":
            return False
        if self.type == "string":
            return ""
        if self.type == "float-list":
            return FloatList(0, 0.0, [])
        raise SchemaError(f"cannot default ctf entry type {self.type!r}")

    def is_used(self, flag):
        if self.min_flag != -1:
            if not self.pass_operation(flag, self.min_operator, self.min_flag):
                return False
        if self.max_flag != -1:
            if not self.pass_operation(flag, self.max_operator, self.max_flag):
                return False
        return True

    @staticmethod
    def pass_operation(flag, op, target):
        return {
            "e": flag == target,
            "lt": flag < target,
            "lte": flag <= target,
            "gt": flag > target,
            "gte": flag >= target,
        }.get(op, False)


class CtfSchema:
    def __init__(self, entries, extension="ctf", line=0, name="schema"):
        self.entries = entries
        self.ext = extension
        self.line = line
        self.name = name

    @property
    def by_name(self):
        return {e.name: e for e in self.entries}

    def find_ref(self, ref_id):
        for e in self.entries:
            if e.ref_id == ref_id:
                return e
        raise SchemaError(f"no entry has refID == {ref_id}")

    def last_required(self):
        for e in reversed(self.entries):
            if e.min_flag == 0:
                return e
        return None

    @classmethod
    def from_bytes(cls, data, name="schema"):
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise SchemaError(f"invalid ctf schema xml: {exc}") from None
        entries = []
        for i, elm in enumerate(root):
            if not isinstance(elm.tag, str):
                continue
            entries.append(CtfEntryInfo(i, elm))
        if not entries:
            raise SchemaError("schema has no entries")
        ext = root.get("extension", "ctf")
        try:
            line = int(root.get("line", 0))
        except ValueError:
            line = 0
        schema = cls(entries, extension=ext, line=line, name=name)
        if schema.last_required() is None:
            raise SchemaError('schema has no entry with minFlag="0"')
        return schema

    @classmethod
    def from_file(cls, path):
        with open(path, "rb") as fh:
            return cls.from_bytes(fh.read(), name=path)