"""EGO JPK archive constants.

JPK archives are identified by the 'JPAK' magic (0x4A50414B).
Reference: EgoEngineLibrary/Archive/Jpk (Ego-Engine-Modding, MIT).
"""

from __future__ import annotations

JPK_MAGIC = 1262571594  # 0x4A50414B -> "JPAK"
HEADER_SIZE = 32
ENTRY_SIZE = 32
