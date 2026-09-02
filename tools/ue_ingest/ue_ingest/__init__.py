"""UE5 ingest: headless import of the migration output into Unreal Engine.

Two halves:
* this package (plain Python) prepares an import manifest and invokes
  ``UnrealEditor-Cmd.exe -run=pythonscript`` headlessly;
* ``ue_script.py`` runs inside the editor commandlet: imports the glTF via
  Interchange, imports/packs textures, builds the PBR Master Material plus
  per-shader Material Instances, assigns them to the imported meshes and
  enables Nanite.

Inputs are the Phase A glTF export folder (with ``gltf_manifest.json``) and
the Phase B texture pack (``T_<Car>_<Part>_<D|N|ORM|H>.png``).
"""

from .prepare import build_manifest, prepare  # noqa: F401
from .runner import run_import  # noqa: F401

__all__ = ["build_manifest", "prepare", "run_import"]
