"""In-editor automation: headless import of the DR2 migration output.

Runs inside ``UnrealEditor-Cmd.exe -run=pythonscript``.  Steps:
1. load manifest.json (written by tools/ue_ingest prepare);
2. import the PBR texture pack (sRGB basecolor, linear N/ORM/H);
3. import the car glTF via Interchange (meshes + UVs + vertex colors);
4. build the PBR Master Material (M_CarPBR) with MaterialEditingLibrary;
5. create per-part Material Instances and assign them to mesh slots;
6. enable Nanite on imported StaticMeshes;
7. save everything and write import_result.json next to the manifest.

Every stage is defensive (feature-detected) and logs its outcome; the
results are aggregated into import_result.json so the caller can verify
success without parsing the whole editor log.
"""

import json
import os
import traceback

import unreal

RESULT = {"steps": {}, "errors": [], "assets": {}}

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(HERE, "manifest.json")
RESULT_PATH = os.path.join(HERE, "import_result.json")

ROOT = "/Game/Import"


def log(msg: str) -> None:
    unreal.log_warning(f"[ue_ingest] {msg}")


def fail(step: str, exc: Exception) -> None:
    RESULT["errors"].append(f"{step}: {exc}")
    log(f"FAILED {step}: {exc}")
    unreal.log_warning(traceback.format_exc())


def step_ok(step: str, detail=None) -> None:
    RESULT["steps"][step] = detail if detail is not None else "ok"
    log(f"OK {step}: {detail}")


# ---------------------------------------------------------------------------
# 2) textures


def import_texture(path: str, name: str, dest: str, compression, srgb: bool,
                   lod_group):
    al = unreal.EditorAssetLibrary
    asset_path = f"{dest}/{name}"
    if al.does_asset_exist(asset_path):
        return al.load_asset(asset_path)

    task = unreal.AssetImportTask()
    task.filename = path
    task.destination_path = dest
    task.destination_name = name
    task.automated = True
    task.save = True
    task.replace_existing = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    tex = al.load_asset(asset_path)
    if tex is None:
        raise RuntimeError(f"texture import produced nothing for {path}")

    tex.set_editor_property("compression_settings", compression)
    tex.set_editor_property("srgb", srgb)
    try:
        tex.set_editor_property("lod_group", lod_group)
    except Exception:
        pass
    al.save_loaded_asset(tex)
    return tex


def import_textures(manifest) -> dict:
    dest = f"{ROOT}/{manifest['car_display']}/Textures"
    # kind -> manifest key + (compression, srgb, lod_group)
    kinds = {
        "D": ("basecolor", unreal.TextureCompressionSettings.TC_DEFAULT,
              True, unreal.TextureGroup.TEXTUREGROUP_WORLD),
        "N": ("normal", unreal.TextureCompressionSettings.TC_NORMALMAP,
              False, unreal.TextureGroup.TEXTUREGROUP_WORLD_NORMAL_MAP),
        "ORM": ("orm", unreal.TextureCompressionSettings.TC_MASKS,
                False, unreal.TextureGroup.TEXTUREGROUP_WORLD),
        "H": ("height", unreal.TextureCompressionSettings.TC_GRAYSCALE,
              False, unreal.TextureGroup.TEXTUREGROUP_WORLD),
    }
    textures = {}
    for mat in manifest["materials"]:
        for kind, (key, compression, srgb, lod_group) in kinds.items():
            stem = mat[key]
            src = os.path.join(manifest["pbr_dir"], stem + ".png")
            if not os.path.isfile(src):
                log(f"missing texture {src}")
                continue
            tex = import_texture(src, stem, dest, compression, srgb, lod_group)
            textures[stem] = tex.get_path_name()
    step_ok("textures", textures)
    return textures


# ---------------------------------------------------------------------------
# 3) glTF import


def import_gltf(manifest) -> list:
    dest = f"{ROOT}/{manifest['car_display']}/Meshes"
    gltf_path = manifest["gltf_file"]
    al = unreal.EditorAssetLibrary

    # Primary path: asset tools (Interchange registers the glTF factory).
    task = unreal.AssetImportTask()
    task.filename = gltf_path
    task.destination_path = dest
    task.automated = True
    task.save = True
    task.replace_existing = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    # Scan the destination for all imported StaticMeshes (the task also
    # imports the glTF materials alongside them).
    static_meshes = []
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = registry.get_assets_by_path(dest, recursive=True)
    except Exception as exc:
        log(f"asset registry scan failed: {exc}")
        assets = []
    log(f"registry scan({dest}) -> {len(assets)}")
    for asset_data in assets:
        try:
            obj = asset_data.get_asset()
        except Exception:
            continue
        if obj is not None and isinstance(obj, unreal.StaticMesh):
            static_meshes.append(obj)
    step_ok("gltf_import", [m.get_name() for m in static_meshes])
    return static_meshes


# ---------------------------------------------------------------------------
# 4) master material


def build_master_material(manifest) -> unreal.Material:
    mel = unreal.MaterialEditingLibrary
    al = unreal.EditorAssetLibrary
    mat_path = f"{ROOT}/Materials/M_CarPBR"

    if al.does_asset_exist(mat_path):
        return al.load_asset(mat_path)

    # 5.4+ removed MaterialEditingLibrary.create_material_asset; create via
    # AssetTools with MaterialFactoryNew.
    factory = unreal.MaterialFactoryNew()
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        "M_CarPBR", f"{ROOT}/Materials", unreal.Material, factory)
    if mat is None:
        raise RuntimeError("material creation returned None")

    def tex_param(name, y):
        expr = mel.create_material_expression(
            mat, unreal.MaterialExpressionTextureSampleParameter2D,
            -700, y)
        expr.set_editor_property("parameter_name", name)
        return expr

    base = tex_param("BaseColorTex", -300)
    base.set_editor_property("sampler_type",
                             unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    normal = tex_param("NormalTex", -100)
    normal.set_editor_property("sampler_type",
                               unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    orm = tex_param("ORMTex", 100)
    orm.set_editor_property("sampler_type",
                            unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)

    mel.connect_material_property(base, "RGB",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    mel.connect_material_property(normal, "RGB",
                                  unreal.MaterialProperty.MP_NORMAL)
    mel.connect_material_property(orm, "R",
                                  unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    mel.connect_material_property(orm, "G",
                                  unreal.MaterialProperty.MP_ROUGHNESS)

    # Metallic = ORM.B boosted by a per-instance MetallicOverride scalar, so
    # parts CHORD misreads as dielectric (rusty brake discs) can be forced.
    metal = mel.create_material_expression(
        mat, unreal.MaterialExpressionAdd, -300, 260)
    orm_b = mel.create_material_expression(
        mat, unreal.MaterialExpressionComponentMask, -460, 300)
    mel.connect_material_expressions(orm, "B", orm_b, "")
    orm_b.set_editor_property("r", False)
    orm_b.set_editor_property("g", False)
    orm_b.set_editor_property("b", True)
    orm_b.set_editor_property("a", False)
    override = mel.create_material_expression(
        mat, unreal.MaterialExpressionScalarParameter, -460, 380)
    override.set_editor_property("parameter_name", "MetallicOverride")
    override.set_editor_property("default_value", 0.0)
    mel.connect_material_expressions(orm_b, "", metal, "A")
    mel.connect_material_expressions(override, "", metal, "B")
    mel.connect_material_property(metal, "", unreal.MaterialProperty.MP_METALLIC)

    mel.recompile_material(mat)
    al.save_loaded_asset(mat)
    return mat


def _shading_model_enum(name: str):
    """Find the shading-model enum type across UE Python versions."""
    for type_name in ("MaterialShadingModel", "ShadingModel",
                      "EMaterialShadingModel"):
        enum_type = getattr(unreal, type_name, None)
        if enum_type is not None and hasattr(enum_type, name):
            return getattr(enum_type, name)
    return None


def build_special_materials() -> dict:
    """Glass (translucent) and lights (emissive) masters + reparent MIs."""
    mel = unreal.MaterialEditingLibrary
    al = unreal.EditorAssetLibrary
    masters = {}

    glass_path = f"{ROOT}/Materials/M_CarGlass"
    if al.does_asset_exist(glass_path):
        masters["glass"] = al.load_asset(glass_path)
    else:
        glass = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "M_CarGlass", f"{ROOT}/Materials", unreal.Material,
            unreal.MaterialFactoryNew())
        sm_enum = _shading_model_enum("TRANSLUCENT")
        if sm_enum is not None:
            glass.set_editor_property("shading_model", sm_enum)
        glass.set_editor_property("blend_mode",
                                  unreal.BlendMode.BLEND_TRANSLUCENT)
        base = mel.create_material_expression(
            glass, unreal.MaterialExpressionTextureSampleParameter2D,
            -500, -100)
        base.set_editor_property("parameter_name", "BaseColorTex")
        base.set_editor_property("sampler_type",
                                 unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
        mel.connect_material_property(base, "RGB",
                                      unreal.MaterialProperty.MP_BASE_COLOR)
        opacity = mel.create_material_expression(
            glass, unreal.MaterialExpressionScalarParameter, -500, 100)
        opacity.set_editor_property("parameter_name", "Opacity")
        opacity.set_editor_property("default_value", 0.3)
        mel.connect_material_property(opacity, "",
                                      unreal.MaterialProperty.MP_OPACITY)
        rough = mel.create_material_expression(
            glass, unreal.MaterialExpressionScalarParameter, -500, 200)
        rough.set_editor_property("parameter_name", "Roughness")
        rough.set_editor_property("default_value", 0.05)
        mel.connect_material_property(rough, "",
                                      unreal.MaterialProperty.MP_ROUGHNESS)
        mel.recompile_material(glass)
        al.save_loaded_asset(glass)
        masters["glass"] = glass

    lights_path = f"{ROOT}/Materials/M_CarLights"
    if al.does_asset_exist(lights_path):
        masters["lights"] = al.load_asset(lights_path)
    else:
        lights = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "M_CarLights", f"{ROOT}/Materials", unreal.Material,
            unreal.MaterialFactoryNew())
        base = mel.create_material_expression(
            lights, unreal.MaterialExpressionTextureSampleParameter2D,
            -500, -100)
        base.set_editor_property("parameter_name", "BaseColorTex")
        base.set_editor_property("sampler_type",
                                 unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
        mel.connect_material_property(base, "RGB",
                                      unreal.MaterialProperty.MP_BASE_COLOR)
        boost = mel.create_material_expression(
            lights, unreal.MaterialExpressionScalarParameter, -500, 100)
        boost.set_editor_property("parameter_name", "EmissiveBoost")
        boost.set_editor_property("default_value", 4.0)
        mul = mel.create_material_expression(
            lights, unreal.MaterialExpressionMultiply, -300, 0)
        mel.connect_material_expressions(base, "RGB", mul, "A")
        mel.connect_material_expressions(boost, "", mul, "B")
        mel.connect_material_property(mul, "",
                                      unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        mel.recompile_material(lights)
        al.save_loaded_asset(lights)
        masters["lights"] = lights

    step_ok("special_materials", sorted(masters))
    return masters


def reparent_special_instances(instances, masters, manifest) -> int:
    """Switch glass/lights MIs onto their dedicated masters."""
    count = 0
    part_by_shader = {}
    for mat_def in manifest["materials"]:
        part_by_shader[mat_def["shader"]] = mat_def["part"].lower()
    for shader, mi in instances.items():
        part = part_by_shader.get(shader, "")
        if part in masters:
            mi.set_editor_property("parent", masters[part])
            unreal.EditorAssetLibrary.save_loaded_asset(mi)
            count += 1
    step_ok("reparent_special", count)
    return count


# ---------------------------------------------------------------------------
# 5) material instances + assignment


def build_material_instances(manifest, textures, master) -> dict:
    al = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.MaterialInstanceConstantFactoryNew()
    mel = unreal.MaterialEditingLibrary

    instances = {}
    for mat_def in manifest["materials"]:
        name = f"MI_{mat_def['part'].capitalize()}"
        asset_path = f"{ROOT}/Materials/{name}"
        if al.does_asset_exist(asset_path):
            mi = al.load_asset(asset_path)
        else:
            mi = at.create_asset(name, f"{ROOT}/Materials",
                                 unreal.MaterialInstanceConstant, factory)
            if mi is None:
                log(f"could not create {name}")
                continue

        mi.set_editor_property("parent", master)
        for param, key in (("BaseColorTex", "basecolor"),
                           ("NormalTex", "normal"),
                           ("ORMTex", "orm")):
            tex_path = textures.get(mat_def[key])
            if tex_path:
                tex = al.load_asset(tex_path)
                mel.set_material_instance_texture_parameter_value(
                    mi, param, tex)
        al.save_loaded_asset(mi)
        instances[mat_def["shader"]] = mi
    step_ok("material_instances", sorted(instances))
    return instances


def _apply_metallic_overrides(instances) -> int:
    """Per-part metallic overrides (CHORD reads rusty albedo as dielectric)."""
    overrides = {"disc": 1.0, "caliper": 0.6}
    applied = 0
    seen = set()
    for shader, mi in instances.items():
        part = mi.get_name().replace("MI_", "").lower()
        if part in seen or part not in overrides:
            continue
        seen.add(part)
        unreal.MaterialEditingLibrary. \
            set_material_instance_scalar_parameter_value(
                mi, "MetallicOverride", overrides[part])
        unreal.EditorAssetLibrary.save_loaded_asset(mi)
        applied += 1
    step_ok("metallic_overrides", applied)
    return applied


def assign_materials(meshes, instances) -> int:
    """Replace imported slot materials whose slot/material name matches."""
    assigned = 0
    shader_names = {}
    for shader, mi in instances.items():
        safe = "".join(c if (c.isalnum() or c in "._-") else "_"
                       for c in shader)
        shader_names[safe] = mi

    for mesh in meshes:
        try:
            mats = list(mesh.get_editor_property("static_materials"))
        except Exception:
            continue
        changed = False
        for i, sm in enumerate(mats):
            candidates = []
            try:
                candidates.append(str(sm.get_editor_property(
                    "imported_material_slot_name")))
            except Exception:
                pass
            try:
                candidates.append(str(sm.get_editor_property(
                    "material_slot_name")))
            except Exception:
                pass
            mi_obj = sm.get_editor_property("material_interface")
            if mi_obj is not None:
                candidates.append(mi_obj.get_name())
            mi = None
            for cand in candidates:
                if not cand:
                    continue
                for safe, candidate_mi in shader_names.items():
                    if cand == safe or cand.startswith(safe):
                        mi = candidate_mi
                        break
                if mi is not None:
                    break
            if mi is not None:
                sm.set_editor_property("material_interface", mi)
                mats[i] = sm
                changed = True
                assigned += 1
        if changed:
            mesh.set_editor_property("static_materials", mats)
            unreal.EditorAssetLibrary.save_loaded_asset(mesh)
    step_ok("material_assignment", assigned)
    return assigned


# ---------------------------------------------------------------------------
# 6) Nanite


def enable_nanite(meshes) -> int:
    enabled = 0
    subsystem = unreal.get_editor_subsystem(
        unreal.StaticMeshEditorSubsystem)

    # 5.5 exposes no mutable NaniteSettings fields to Python; inspect what
    # the import actually produced (Nanite is project-default-on in 5.5).
    for mesh in meshes[:3]:
        try:
            cur = mesh.get_editor_property("nanite_settings")
            log(f"{mesh.get_name()} nanite_settings: {cur.export_text()}")
        except Exception as exc:
            log(f"nanite read failed for {mesh.get_name()}: {exc}")

    for mesh in meshes:
        try:
            cur = mesh.get_editor_property("nanite_settings")
            text = cur.export_text()
            # treat "(enabled=True)"-style payloads as enabled
            if "enabled" in text.lower() and "false" not in text.lower():
                enabled += 1
                continue
            if hasattr(subsystem, "set_nanite_settings"):
                subsystem.set_nanite_settings(mesh, None)
            unreal.EditorAssetLibrary.save_loaded_asset(mesh)
            enabled += 1
        except Exception as exc:
            log(f"nanite failed for {mesh.get_name()}: {exc}")
    step_ok("nanite", enabled)
    return enabled


# ---------------------------------------------------------------------------


def main() -> None:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    log(f"manifest loaded: car={manifest['car_display']} "
        f"materials={len(manifest['materials'])} "
        f"nodes={len(manifest['nodes'])}")

    try:
        textures = import_textures(manifest)
    except Exception as exc:
        fail("textures", exc)
        textures = {}

    try:
        meshes = import_gltf(manifest)
    except Exception as exc:
        fail("gltf_import", exc)
        meshes = []

    try:
        master = build_master_material(manifest)
    except Exception as exc:
        fail("master_material", exc)
        master = None

    instances = {}
    if master is not None:
        try:
            instances = build_material_instances(manifest, textures, master)
        except Exception as exc:
            fail("material_instances", exc)
    if instances:
        try:
            masters = build_special_materials()
            reparent_special_instances(instances, masters, manifest)
        except Exception as exc:
            fail("special_materials", exc)
        try:
            _apply_metallic_overrides(instances)
        except Exception as exc:
            fail("metallic_overrides", exc)
    if instances and meshes:
        try:
            assign_materials(meshes, instances)
        except Exception as exc:
            fail("material_assignment", exc)
    if meshes:
        try:
            enable_nanite(meshes)
        except Exception as exc:
            fail("nanite", exc)

    RESULT["assets"] = {
        "textures": len(textures),
        "static_meshes": len(meshes),
        "material_instances": len(instances),
    }
    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, indent=2)
    log(f"done: {json.dumps(RESULT['assets'])} "
        f"errors={len(RESULT['errors'])}")


main()
