# Roadmap — DR2 → UE5 Migration Tooling

Goal: build a clean-room-ish, Python-based toolchain to reverse-engineer
DiRT Rally 2.0 (EGO Engine) archives for **personal, non-commercial** research
and migration to Unreal Engine 5.  No game assets or extracted copies are ever
redistributed.

## Status

`116→` tooling is in active development.  The first deliverables — a working
`nefs_unpack` (Python port of NefsLib) plus `erp_unpack` (EGO Resource Package),
`jpk_unpack` (JPAK), and `pssg_unpack` (binary scene graph) — are functional
and covered by synthetic round-trip tests.

> **DR2 archive version note.** DiRT Rally 2.0's real archives are NeFS
> **v2.0.0**, not v1.6.0.  The TOC layout (B200), writable-entry flag enum, and
> split-header validation all differ from v1.6.0; the toolchain is now
> version-aware.  See `docs/FORMATS.md` §2.1, §4.

## Milestones

### M1 — Archive extraction (MOSTLY COMPLETE, validated on real DR2 data)
- [x] Python `nefs_unpack` library:
  - [x] Header parser (intro, TOC, parts 1–8) — v1.6.0 and **v2.0.0** (DR2)
  - [x] Standard `.nefs` and split-header `.dat` reading
  - [x] Exe header/writable-data finder (`scan`) — version-aware, numpy fast path
  - [x] Item tree reconstruction (dirs, files, shared entries)
  - [x] Detransform: AES-256-ECB, zlib, LZSS
  - [x] `unpack` / `list` / `scan` CLI
  - [x] Synthetic round-trip tests (all pass)
- [x] `docs/FORMATS.md`, `docs/ENCRYPTION.md`
- [x] ERP archive support — `tools/erp_unpack` (KPAR v4, zlib/zstd fragments)
- [x] JPK archive support — `tools/jpk_unpack` (JPAK, 32-byte entries)
- [x] PSSG scene-graph reader/writer — `tools/pssg_unpack`
- [x] Real-data validation (user-supplied install at
      `D:\Steam\steamapps\common\DiRT Rally 2.0`):
  - XOR/RSA-obfuscated headers decoded; all game/cars/locations archives parse
    with 0 failures; `music.nfs` nested archive.
  - `scan` auto-finds all four split `.dat` volumes with correct primary +
    secondary offsets; part-6 flags/volumes confirmed sane
    (all `Volume==0`, flags within `0x1F`).
  - Spot-extraction from `game.dat` gives byte-exact size matches.
  - **Full `game.dat` unpack validated** (DR2 `unpack`): 406 entries → 390 files
    across 16 directories, **0/390 size mismatches**, 0 missing.  The `.xml`
    contents split cleanly by magic: 3 plain XML (all well-formed), 18 BinXml
    (`1A 22 52 72`), 7 BXML (`\x01BXML`) — both binary forms decode to readable
    text via `database_convert`.  `.pssg` magic/size correct; `.tmep`/`.tpk`
    blobs non-trivial and structurally consistent.
  - Fix found during validation: `extract_archive` used its own tree builder and
    flattened everything onto the first self-parented dir, dropping 387/390
    DR2 files.  Rewritten to walk `NefsArchive.tree` (same tree as `list`),
    consistent for v1.6.0 + v2.0.0.
  - **Full `game_2_1.dat` (9.3 GB, 948 entries) unpack validated** — the largest
    volume.  Two fixes: (1) `extract_archive` now **streams** each item from disk
    via `extract_item_from_file` instead of loading the whole volume into RAM
    (would need ~9.3 GB + overhead; now flat memory); (2) `detransform_chunk_v200`
    falls back to the AES-decrypted bytes when a window is not an independent
    raw-deflate stream (DR2 audio `.bnk` are hybrid raw/deflate Wwise banks).
    Result: **246/246 `.bnk` are structurally valid Wwise `BKHD` banks** (section
    chain + byte-exact sizes), 43/45 plain XML well-formed (the 2 exceptions have
    a bare-`\r` line ending in the *source data*), plus 55 BinXml and 39 PSSG.
    Duplicate content-pack entries share on-disk paths (last-writer-wins), so 629
    tree files collapse to 416 unique files on extraction.
  - Every DR2 archive is NeFS v2.0.0; there are **no** `.erp` `.database`
    files in DR2 (older-EGO formats — N/A here).

### M2 — Asset pipeline
- [x] DIC audio dictionary unpack — `tools/dic_unpack`
- [x] CTF physics blob converter — `tools/ctf_convert`
- [x] PSSG mesh/texture conversion (on top of `pssg_unpack`) — `tools/pssg_convert`
- [x] DB/XML schema conversion — `tools/database_convert`
- [ ] schema files under `schemas/`

### M2 notes (current state)
- `pssg_convert` decodes vertex/index buffers (`RenderDataSourceReader`), traverses
  car scene node libraries (interior `RENDERNODE`/`VISIBLERENDERNODE` + exterior
  `MATRIXPALETTEJOINTNODE` with index subranges), resolves shader→texture bindings,
  and writes OBJ/MTL + DDS + a `pssg_manifest.json`.  14 tests, CLI verified.
- `database_convert` ports `XmlFile` (BinXml/BXML/text) and `DatabaseFile`
  (modern `PRTS` string-table + legacy `LBT`/`ITM`), schema-driven typed rows,
  CLI `info`/`xml`/`db-decode`/`db-info`.  12 tests, **validated on real
  DR2 data**: `int_131.xml` (text XML) → BinXml → text round-trip passes, and a
  real `131.nd2` (BinXml magic) decodes to readable vehicle-damage physics XML.
- `ctf_convert` ctf ↔ csv/json works on synthetic fixtures; the binary CTF path
  (`db-decode`/`info` on `.ctf`) and `.database` decoding require schema XMLs
  that DR2 does not ship — blocked until a community schema is supplied.
- All tool test suites pass: nefs_unpack (9), database_convert (12),
  pssg_convert (14), pssg_unpack (6), jpk_unpack (3), erp_unpack (3),
  dic_unpack (4), ctf_convert (13).

### M3 — Unreal Engine 5 migration (Phase 0 + A complete)
- [x] **Phase 0 — target selection & audit** (car `131.nefs`, the FIAT Abarth
      131 Mirafiori '77): extracted 69 files / 274 MB to `assets/validation/`
      (gitignored).  Found and fixed three parser bugs that only real car
      archives trigger:
  - `pssg_unpack/reader`: attribute values are now read with the *declared
    size* as authoritative (typed interpretation only when size matches the
    encoding), mirroring EgoEngineLibrary's Unknown → `ReadBytes(size)`.
    Real files carry e.g. `source` attributes with size 14 holding
    length-prefixed strings; the old name-guessed Int read desynced the stream.
  - `pssg_convert/extract`: the node walk now descends `ROOTNODE` (real car
    NODE libraries wrap everything in it; without this 0 meshes were found).
  - `pssg_convert/extract`: `_split_st` built the split UV-set type name as
    `half4` + `2` = `half42`; also fixed `_unpack_rgba` byte order for
    big-endian `uchar4` colors.
- [x] **Phase A — glTF 2.0 exporter** (`pssg_convert gltf`, 9 new tests):
  - `.gltf` + `.bin` + external PNG textures; POSITION (min/max), NORMAL,
    `TEXCOORD_0..n` (half2/half4/float2/float4), COLOR_0, ushort/uint indices.
  - Textures decoded BC1/BC2/BC3/BC7 → PNG via optional `imagecodecs`
    (graceful skip when absent); **DXT5nmap swizzle** (X in alpha, Y in green)
    reconstructed to RGB normal maps; sRGB variants share block encodings.
  - Material binding, two paths: explicit `SHADERINPUT` refs (TextureResolver)
    with base-name→suffix fallback (`131_glass.tga` → `131_glass_d.tga`), then
    the car naming convention (`bodywork` → `<car>_main_d.tga` etc.) for
    exterior shaders that carry no texture inputs (real DR2 cars).
  - Validated on the real car: exterior **178 meshes / 18 materials / 24
    textures**, global bbox **1.74 × 2.10 × 4.63 m** (meters, Y-up); interior
    **45 meshes / 10 materials**.  Livery + normal maps visually verified.
  - Coordinate pass-through by default; `--neg-z` applies the D3D
    left-handed → glTF right-handed conversion (negate Z, reverse winding).
- [x] **Phase B — neural PBR synthesis** (`tools/pbr_synth`, 16 tests):
  - Headless **ComfyUI service runner** (`comfy.py`): launches ComfyUI as a
    subprocess (venv-aware, `--highvram`), submits API-format graphs to
    `POST /prompt`, polls `GET /history/{id}`, fetches outputs via `/view`,
    releases VRAM via `POST /free`, daemon log pump + context-manager
    lifecycle.  Protocol covered by tests against a fake in-process server.
  - **Ubisoft CHORD** integration (`chord_workflow.py`):
    `LoadImage → ChordLoadModel → ChordMaterialEstimation (basecolor/normal/
    roughness/metalness) → ChordNormalToHeight (Poisson)`.  Weights
    `chord_v1.safetensors` (2.76 GB, sha256-verified) — canonical source is
    the gated HF repo `Ubisoft/ubisoft-laforge-chord` (accept terms for
    long-term use); **Ubisoft Machine Learning License**, never redistributed.
    ComfyUI lives outside the repo at `E:\ClaudeATHome\Tools\ComfyUI`.
  - **Legacy reconciliation** (`reconcile.py`): gloss from ``_s`` alpha (or
    luminance fallback) → roughness `sqrt(1-gloss)`; blended
    `0.7*CHORD + 0.3*legacy`; OpenGL→DirectX normal G-invert; **ORM packing**
    (R=AO from ``_o``, G=blended roughness, B=CHORD metalness); 16-bit height.
  - **Packaging**: `T_<Car>_<Part>_<D|N|ORM|H>.png` (e.g. `T_Fiat131_Body_D.png`)
    ready for UE `TC_Masks` / `TC_Normalmap` / `TC_Grayscale` imports.
  - Validated on the real car: **6/6 parts synthesized** (Body, Cabin, Glass,
    Lights, Caliper, Disc → 24 files).  CHORD de-lit the livery correctly
    (baked dirt removed, decals preserved); ORM material classes track the
    atlas (smooth clear-coat vs rough mechanical parts).  Known limitation:
    CHORD reads rusty/dirty albedo as dielectric, so brake discs come out
    non-metallic — override metallic per-material in the UE Master Material.
- [x] **Phase C — UE 5.5 headless ingest** (`tools/ue_ingest`, validated
      against a real `G:\UE5\UE_5.5` install):
  - `prepare` merges the Phase A glTF manifest + Phase B PBR pack into an
    ingest manifest (shader→part→`T_<Car>_<Part>_*` texture mapping); `import`
    drives `UnrealEditor-Cmd.exe -run=pythonscript -unattended` on a generated
    blank project (`E:\ClaudeATHome\Projects\UE\CarImport`, outside the repo).
  - UE-side `ue_script.py`: Interchange glTF import via `AssetImportTask`,
    texture imports with per-kind settings (sRGB basecolor, `TC_NORMALMAP`,
    `TC_MASKS` ORM, `TC_GRAYSCALE` height), Master Material `M_CarPBR`
    (BaseColor/Normal/ORM params → BaseColor, Normal, R→AO, G→Roughness,
    B→Metallic) built with `MaterialEditingLibrary`, per-part
    `MaterialInstanceConstant`s, slot assignment by glTF material name,
    Nanite verification.
  - UE 5.5 Python API notes baked in: `MaterialEditingLibrary.create_material_asset`
    is gone (use `MaterialFactoryNew`), Python enums are ALL-CAPS
    (`TEXTUREGROUP_WORLD`), `NaniteSettings` has no Python-writable fields
    (Nanite is project-default-on; verified `bEnabled=True` on import).
  - **Validated result: 178 StaticMeshes + 24 textures + M_CarPBR + 8
    shader→MI bindings (78 material slots assigned) + Nanite 178/178,
    0 errors** (`import_result.json` written next to the manifest).
- [x] **Phase D — level assembly** (`assemble_level.py`, staged by `prepare`,
      run via `ue_ingest assemble`):
  - Creates/saves level `L_CarShowroom`; spawns a grid ground plane; spawns
    every primary imported StaticMesh at the origin — the glTF exporter
    flattened vertices without node transforms, so origin placement
    reassembles the car (hash-suffixed Interchange duplicates skipped).
  - Lumen rig: movable DirectionalLight (atmosphere sun), SkyAtmosphere,
    VolumetricCloud, real-time-capture SkyLight, ExponentialHeightFog,
    unbounded PostProcessVolume; Lumen GI + reflections + VSM enabled in
    `DefaultEngine.ini`.
  - UE commandlet finding: `EditorActorSubsystem.spawn_actor_from_object`
    access-violates inside `-run=pythonscript` (5.5.4); the safe pattern is
    `spawn_actor_from_class(StaticMeshActor)` + `set_static_mesh` on the
    component.  `set_actor_rotation` requires the `teleport_physics` arg.
  - **Validated: 105 car actors + ground + 6-piece lighting rig, level saved,
    0 errors** (`assemble_result.json`).
- [x] **Phase E — human-led gaps closed autonomously**:
  - **Audio pipeline**: vgmstream-cli (external, `E:\ClaudeATHome\Tools\vgmstream`)
    transcodes the 100 extracted WEMs to WAV -> imported as **100
    SoundWaves** (`ue_ingest audio`) -> **MS_Engine131** MetaSoundSource
    asset created via MetaSoundSourceFactory.  Graph authoring deferred:
    `find_or_begin_building` returns an unusable Python wrapper in 5.5.4
    commandlets, and `get_editor_subsystem(MetaSoundBuilderSubsystem)` is
    rejected ('must be a Class' despite static_class).
  - **Vehicle data in-engine**: 8 `PM_<surface>` PhysicalMaterials +
    **`BP_Vehicle131`** Chaos vehicle Blueprint (WheeledVehiclePawn parent,
    created + compiled via BlueprintFactory/BlueprintEditorLibrary; note the
    engine plugin is `ChaosVehiclesPlugin` under Experimental).  CurveFloat
    assets are impossible headlessly on 5.5.4 (unreflected FRichCurve;
    CurveImportFactory AND ReimportCurveFactory CSV import both
    access-violate the commandlet) — braking curves stay in
    `vehicle_config.json`/`vehicle_curves.csv` inside the project.
  - **Terrain in-engine**: `heightfield_extract --gltf` exports the 300x287
    grid as a glTF terrain mesh (m, normals, UVs) -> imported via Interchange
    and spawned into `L_CarShowroom` as a Nanite-enabled StaticMesh
    (`Terrain_AustraliaRally01`).  Staging must preserve the original
    glTF/bin basenames (buffer URI).
  - Commandlet landmine confirmed twice: `spawn_actor_from_object`
    access-violates under `-run=pythonscript`; always
    `spawn_actor_from_class(StaticMeshActor)` + `set_static_mesh`.
  - **Final state of the UE project** (`E:\ClaudeATHome\Projects\UE\CarImport`):
    L_CarShowroom contains the fully materialized Fiat 131 Abarth '77
    (105 actors, polished PBR materials incl. glass/lights/metallic
    overrides) standing on real imported Australian rally terrain with the
    Lumen lighting rig; /Game/Import also holds 100 SoundWaves,
    MS_Engine131, 8 surface PhysicalMaterials and BP_Vehicle131.
- [x] Phase F - autonomous finalization (MetaSound, Chaos tuning, audio
      curation, integration):
  - **F1 MetaSound authoring (COMPLETE)**: `MS_Engine131` is a fully
    authored MetaSoundSource - one looping Wave Player (UE/Wave Player/
    Stereo) bound to the longest engine-candidate SoundWave, wired
    `UE.Source.OnPlay -> Play` and stereo `Out Left/Right -> Output`.
    Key headless landmines solved: `find_or_begin_building` returns a
    `(builder, result)` tuple; `build_to_asset` opens a Slate overwrite
    dialog (-> crash) if the target name exists; `rename_asset`/
    `delete_asset` on built MetaSounds access-violate in UnrealEd.  Fix:
    seed the builder from a throwaway `MS_Seed` skeleton and
    `build_to_asset` directly into the free `MS_Engine131` name (no
    rename/delete of built assets).
  - **F2 Audio analysis (COMPLETE)**: new `tools/audio_analyze` - numpy
    STFT feature extraction (duration/RMS/spectral centroid/flatness/
    envelope CV), engine-vs-effect classification (12 engine loops found
    in the s_mech bank), PIL spectrogram contact sheet, and a curated
    `Listen_Here` folder with the top 6 engine candidates for by-ear
    confirmation (the one thing that cannot be automated).
  - **F3 Chaos movement tuning (COMPLETE, scalar API)**: the earlier
    "not Python-settable" assessment was too pessimistic - all
    `FVehicleEngineConfig`/`FVehicleTransmissionConfig`/
    `FVehicleDifferentialConfig`/`FVehicleSteeringConfig`/
    `FChaosWheelSetup` fields are reflected and settable on the
    movement component CDO.  `BP_Vehicle131` is now tuned end-to-end:
    mass 1000 kg, 7000 RPM / 190 Nm engine, 5-speed auto RWD
    transmission, 4 wheel setups bound to the new **`BP_Wheel131`**
    (0.31 m radius, tuned suspension/friction), round-trip verified.
    **Curve keys ARE authorable and persistent headlessly** after all:
    `FRuntimeFloatCurve.import_text` needs no FRichCurve reflection, but
    an in-memory curve-wrapper edit is lost on save - the persistent
    route is `modify()` + **whole-struct** `import_text` on
    `engine_setup`/`steering_setup` (routes through
    `FStructProperty::ImportText` + PostEditChangeProperty tagging).
    The torque curve (10 keys, peak 1.0 @ 4500 RPM) and steering curve
    (6 keys, 35 deg at standstill down to 6 deg @ 120 MPH) are authored
    on the vehicle and verified by fresh-process reload of the saved BP.
    Landmine: enum members are ALL-CAPS with underscores
    (`ANGLE_RATIO`), so substring matching on the C++ casing fails.  Provenance: the encrypted CTF cannot be
    decoded and ai_vehicle_statistics has no engine/gear/mass data, so
    values are real-world Fiat 131 Abarth Group 4 specs (documented
    approximation).
  - **F4 Integration (COMPLETE)**: `assemble_level.py` spawns the tuned
    `BP_Vehicle131` into `L_CarShowroom` alongside the 105 mesh actors
    (raised Z so wheels rest on the ground plane).
- [ ] Residual (needs interactive editor, documented):
      standalone CurveFloat assets (`UCurveFloat.FloatCurve` is not
      Python-exposed on 5.5 - only getter UFUNCTIONs - and the CSV import
      factories crash the commandlet; per-surface brake data stays in
      `vehicle_config.json`/PM friction).
- [x] By-ear engine pick (the human-in-the-loop step): the user chose
      `49239638.wav` from the `Listen_Here` set; `ue_ingest audio
      --engine-wave 49239638` rebuilds `MS_Engine131` bound to that
      SoundWave (exact asset-name match incl. the `SM131_` prefix).
- [x] Phase G - drivable showroom (`ue_ingest drivable`): Blueprint graph
      authoring is impossible headlessly, so the pass reuses the engine
      Vehicle Advanced template's pre-wired input assets (copied into
      Content by the CLI: `VehicleTemplate/` Blueprints + Input,
      `OffroadCar/` skeletal mesh + physics asset + materials):
      duplicates `OffroadCar_Pawn` as **`BP_Vehicle131_Drivable`**, creates
      **`GM_Vehicle131`** (DefaultPawn = the drivable pawn, PlayerController
      = `VehiclePlayerController` with its IMC/input-action bindings),
      spawns a PlayerStart in `L_CarShowroom`, sets the WorldSettings
      GameMode override (+ `GlobalDefaultGameMode` in DefaultGame.ini as a
      guaranteed fallback), and adds a positional `EngineLoop131`
      AmbientSound playing MS_Engine131.  Drive with the template bindings
      (WASD + gamepad).
  - **PIE fix chain (root causes found via `-game` log replay)**: the
    "nothing works on Play" failure was three stacked bugs, all proven by
    running the project in game mode headlessly (`-game -RenderOffScreen`
    + log grep - reproduces GameMode spawn/possession without an editor):
    (1) the stale `BP_Vehicle131` shell from the F4 assemble pass sat at
    the origin WITH collision and physically blocked the GameMode pawn
    spawn ("SpawnActor failed because of collision") -> no pawn -> no
    possession -> the template controller's per-tick "Accessed None:
    Vehicle Movement Component" spam; (2) the terrain heightfield is a
    VERTICAL WALL filling the +X/-Y quadrant (bounds X 0..299m, Y
    -286..0m, Z up to 560m) - any spawn with Y<=~75cm overlaps its edge
    face, so the PlayerStart now rests at (600, 300, 150), outside the
    terrain footprint and the display meshes; (3) the offroad materials
    parent into SportsCar assets, so the SportsCar pack must be copied
    too (and it MUST be the 5.5-layout pack - 5.8 renamed those assets).
    Final headless `-game` run: zero errors, world up for play.
- [x] Live-editor QA pass (September 2026, via the MCP toolset): the
      drivable pawn was still running TEMPLATE tuning - the Fiat 131
      values (mass 1000, 7000 RPM / 190 Nm, 5-speed RWD, torque and
      steering curves) are now applied to **`BP_Vehicle131_Drivable`**
      and verified live in PIE (idle RPM exactly 1100).  Drive test
      telemetry: 0-79 km/h in 10s full throttle, stop in ~2s under
      brakes, clean steering hold - all with stable ride height.
      Additional fixes: ground plane enlarged 60m -> 3km (the car
      drove off the old edge into the void), stale `BP_Vehicle131` +
      `BP_Wheel131` assets deleted (source of the "wheel 0 bone name"
      warnings; the wheel-bone warning is fully gone), ambient engine
      loop confirmed bound to MS_Engine131, and the PIE session logs
      zero Accessed-None / LogVehicle / LogSpawn errors.
  - QA findings recorded for future work: `GetForwardSpeed` returns
    cm/s; `SetThrottleInput` decays per-tick (harmless for keyboard
    input - Enhanced Input re-fires per tick - but automation must
    re-fire or use rapid-fire calls); gear -1 at standstill is the
    template's by-design auto-reverse; the terrain heightfield is a
    static backdrop WALL (its bounds span X 0..299m / Y -286..0m /
    Z up to 560m, and the car drives beneath its high surface) - a
    proper drivable terrain would need re-orientation as a floor;
    5.8 removed `unreal.ComponentUtils` and renamed several enums
    (`ECC_VISIBILITY`, `DrawDebugTrace`, 2-tuple `get_actor_bounds`).
- [x] Live-editor regression sweep (September 2026, second MCP session):
      three real bugs found and fixed, all verified by live PIE drive
      tests via the new **`tools/ue_mcp/qa_drive.py`** regression script:
  - **Stacked duplicate layers in `L_CarShowroom`**: the level held 420
    display-mesh actors for only 105 unique (mesh, position) keys - every
    part was quadrupled at the origin (z-fighting + 4x draw calls).  Root
    cause: `assemble_level.py` dedup only skipped hash-suffixed Interchange
    duplicates (a 5.5-era convention 5.8 no longer produces) AND re-runs
    spawned a whole new layer on top of the loaded level.  Fix: the pass
    now deletes its own previously-spawned actors (display meshes under
    the mesh dir + ground + lighting rig) before rebuilding, and dedups by
    unique mesh path - re-runs are idempotent (verified: re-run yields
    exactly 105 actors, 0 duplicates).
  - **`assemble_level.py` re-spawned the obsolete `BP_Vehicle131` shell**
    at the origin - re-introducing the exact collision-blocker that once
    broke GameMode pawn spawn ("nothing works on Play").  Fix: the
    showroom no longer spawns any vehicle (the drivable car comes from
    the GameMode/PlayerStart setup in `ue_ingest drivable`); the stale
    asset was deleted (confirmed absent) and PIE now spawns exactly one
    possessed `BP_Vehicle131_Drivable_C`.
  - **Ground size regression**: the assemble pass reset the ground to
    60x60 m, so a driven car fell off the edge mid-test (found it at
    Z = -5.2 km doing 320 km/h).  The ground is now 3 km x 3 km in the
    assemble pass itself.
  - **Automation finding - input APIs**: while a controller possesses the
    pawn (`RequiresControllerForInputs=True` on the movement component),
    ALL direct `SetThrottleInput`/`SetBrakeInput`/`SetSteeringInput`
    values are reset to 0 every tick - automation must either disable
    `requires_controller_for_inputs` on the live PIE instance (per-
    instance only; human WASD input is unaffected) or use the
    Increase/Decrease accumulator API the template controller uses.
    `qa_drive.py` does the former and validates: 0-44 km/h in 10 s
    (RPM climbing to 2478), stop in ~4 s under brake (idle 1102),
    clean steering hold - ride height stable on the 3 km floor.
- [x] Engine 5.8 migration (September 2026): project switched to UE 5.8.2
      (`G:\UE5\UE_5.8\UE_5.8`); assets auto-upgraded on first load, all
      scripted passes re-ran clean. 5.8 notes: `TraceTypeQuery` members
      renamed (`ECC_VISIBILITY`), `DrawDebugType` -> `DrawDebugTrace`,
      `get_actor_bounds` returns a 2-tuple, `collision_enabled` UPROPERTY
      gone (use `get_collision_enabled()`), ToolsetRegistry init script
      errors on `unreal.PythonTestRunner` (engine-side, harmless).  The
      official **Model Context Protocol** plugin + ToolsetRegistry are
      enabled in the project for editor-integrated agent workflows.
  - **Mount-path fix**: the vehicle FeaturePack must live at
    `/Game/Vehicles/...` (`SharedContentPacks MountName="Vehicles"` in the
    template's TemplateDefs.ini; every internal ref points there).  The
    first copy to `/Game/OffroadCar` broke skeleton/physics-asset/mesh
    imports, and - worse - the pawn duplicate was saved while imports were
    broken, **baking a null mesh reference into the asset** (in PIE the
    car was an invisible, physics-less hull).  Fix: content moved to
    `Content/Vehicles/`, stale duplicate deleted, pass re-run, mesh
    resolves (`SKM_Offroad`) and the AnimBP skeleton error is gone.
  - Headless landmines found: `compile_blueprint` AFTER CDO property
    writes RESETS the CDO from the stored template (writes lost - save
    without compiling); a duplicate referenced by a GameMode must be
    `save_loaded_asset`-ed BEFORE the referencing asset is saved (else the
    class ref silently resolves None on fresh load); in-memory-only
    property writes read back fine in-process, so every persistence claim
    needs a fresh-process verification.
- [ ] Residual (needs interactive editor or new pipeline work, documented):
      the Fiat 131 body is still the template OffroadCar placeholder -
      swapping in the real 131 mesh needs a SkeletalMesh + PhysicsAsset
      (the imported 131 meshes are StaticMeshes); engine sound on the pawn
      itself (needs an AudioComponent/RPM wiring); PIE smoke test.

## Non-goals
- Redistribution of proprietary assets
- Paid tools or paid plugin distribution
- Online/multiplayer reverse engineering

## Tools
- Language: Python 3.12 (matches `rxinfinite` / `RBR-RE` projects)
- Dependencies: `cryptography` (AES), stdlib `zlib`
- Tests: `pytest` (synthetic fixtures; real-file validation when available)

## Reference
- `VictorBush.Ego.NefsLib` (C#) — used as format reference under its MIT
  license; this repo is a clean Python reimplementation of the *format*,
  not a copy of the code.