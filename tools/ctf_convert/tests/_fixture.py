import struct

LE_I32 = struct.Struct("<i")
LE_F32 = struct.Struct("<f")
LE_F64 = struct.Struct("<d")


SCHEMA_XML = """<root extension="ctf" line="2">
  <entry name="magic" type="int" readOnly="1"/>
  <entry name="flag" type="int" readOnly="1"/>
  <entry name="always_float" type="float" minFlag="0" minOperator="gte"/>
  <entry name="auto_clutch" type="bool"/>
  <entry name="geometry_string" type="string" minFlag="1" minOperator="gte"/>
  <entry name="drivetrain" type="int" minFlag="2" minOperator="gte"/>
  <entry name="sc_enabled" type="bool" refID="7"/>
  <entry name="sc_curve" type="float-list" linkID="7"/>
  <entry name="weight" type="double"/>
  <entry name="overflow_only" type="float" minFlag="4" minOperator="gte">
    <param name="description">only present at flag >= 4</param>
  </entry>
</root>
"""

CSV_LINES = [
    "Car,Setup,Engine,N/A",
    "DBG-01",
    "",  # data row (line 2 in schema)
]


def build_fixture(link_enabled=True):
    buf = bytearray()
    buf += LE_I32.pack(999)             # magic
    buf += LE_I32.pack(2)               # flag
    buf += LE_F32.pack(1.5)             # always_float
    buf += LE_I32.pack(1)               # auto_clutch (bool)
    buf += b"AWD-1\x00"                 # geometry_string
    buf += LE_I32.pack(4)               # drivetrain
    buf += LE_I32.pack(1 if link_enabled else 0)  # sc_enabled (bool)
    if link_enabled:                    # sc_curve (float-list, linkID)
        buf += LE_I32.pack(2)
        buf += LE_F32.pack(0.25)
        buf += LE_F32.pack(0.0)
        buf += LE_F32.pack(1.0)
    buf += LE_F64.pack(1240.5)          # weight
    return bytes(buf)