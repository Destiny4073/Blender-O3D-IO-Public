# ==============================================================================
#  Copyright (c) 2023-2026 Thomas Mathieson / openOMSI contributors.
# ==============================================================================
import os

import bpy
from mathutils import Matrix, Vector

from . import xfile
from .blender_texture_io import load_image
from .o3d_node_shader_utils import PrincipledBSDFWrapper, set_material_blend_mode


def log(*args):
    print("[X_Import]", *args)


# OMSI mesh files use Direct3D's frame (X right, Y up, Z forward); Blender is
# Z-up, so the importer swaps Y and Z — exactly like the engine (and the o3d
# importer in this plugin) does.
AXIS_SWAP = Matrix((
    (1, 0, 0, 0),
    (0, 0, 1, 0),
    (0, 1, 0, 0),
    (0, 0, 0, 1)
))


def _create_material(xmaterial, filepath, counter):
    """
    Generates a Blender material for a .x material definition.

    :param xmaterial: (diffuse rgba, specular rgb, emissive rgb, power, texture)
    :param filepath: the path to the .x file (textures are looked up beside it)
    :param counter: the global material counter
    :return: the new Blender material
    """
    diffuse, specular, emissive, power, texture = xmaterial
    base_name = os.path.basename(texture) if texture else "xmat"
    mat_blender = bpy.data.materials.new("{0}-{1}".format(base_name, counter))
    mat_blender.use_nodes = True
    mat = PrincipledBSDFWrapper(mat_blender, is_readonly=False)
    mat.base_color = diffuse[0:3]
    mat.specular = 0
    # The specular power maps to roughness the same way the o3d importer maps
    # the o3d specular hardness.
    mat.roughness = min(max(1.0 - power / 100.0, 0.0), 1.0)
    if any(abs(e) > 1e-6 for e in emissive):
        mat.emission_color = emissive
        mat.emission_strength = 1.0

    mat_blender.use_backface_culling = True
    if diffuse[3] < 1.0:
        set_material_blend_mode(mat_blender, "HASHED")

    if texture:
        img = load_image(filepath, texture)
        if img is not None:
            # In some versions of Blender the colourspace isn't correctly
            # detected, force it to sRGB for the diffuse texture
            img.colorspace_settings.name = 'sRGB'
            img.alpha_mode = "NONE"
            mat.base_color_texture.image = img
            if diffuse[3] < 1.0:
                # The material is transparent, so use the texture's alpha
                mat.alpha_texture.image = img
                mat.alpha = 0

    return mat_blender


def import_x_file(filepath, context, parent_collection=None, split_normals=True, obj_root=None):
    """
    Imports a DirectX .x mesh file and creates a Blender object for every Mesh
    data object in it.

    :param filepath: the path to the .x file to import
    :param context: blender context
    :param parent_collection: the collection to parent the objects to
                              (defaults to the scene collection)
    :param split_normals: whether to import the mesh normals as custom split
                          normals
    :param obj_root: the root directory the file's export path is stored
                     relative to (defaults to the file's directory)
    :return: a list of the imported Blender objects
    """
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except IOError:
        log("WARNING: Couldn't open {0}!".format(filepath))
        return []

    try:
        xmeshes = xfile.parse_x(data)
    except xfile.XFileError as e:
        log("WARNING: Couldn't parse {0}: {1}".format(filepath, e))
        return []

    if obj_root is None:
        obj_root = os.path.dirname(filepath)
    if parent_collection is None:
        parent_collection = bpy.context.scene.collection

    blender_objs = []
    mat_counter = 0
    for xmesh in xmeshes:
        verts = xmesh["vertices"]
        name = xmesh["name"]
        if len(verts) == 0 or len(xmesh["faces"]) == 0:
            log("WARNING: Mesh {0} of {1} has no geometry, skipping...".format(name, filepath))
            continue

        # Convert to Blender's coordinate system (swap Y and Z)
        vertex_pos = [AXIS_SWAP @ Vector(v[0]) for v in verts]
        normals = [(AXIS_SWAP.to_3x3() @ Vector(v[1])).normalized() for v in verts]
        uvs = [tuple(v[2]) for v in verts]
        # Drop degenerate faces (repeated vertex indices) — they crash Blender's
        # custom split normals code
        faces = []
        face_mats = []
        for face, mat in zip(xmesh["faces"], xmesh["face_materials"]):
            if len(set(face)) == len(face):
                faces.append(face)
                face_mats.append(mat)

        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(vertex_pos, [], [list(f) for f in faces])
        mesh.uv_layers.new(name="UV Map")

        # Build the edges and validate the mesh *before* setting custom split
        # normals: Blender's normals code walks edge fans and crashes on
        # degenerate or unvalidated geometry.
        mesh.update(calc_edges=True)
        mesh.validate(verbose=False, clean_customdata=True)

        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
        if split_normals and bpy.app.version >= (4, 1, 0):
            # create_normals_split() and use_auto_smooth were removed in
            # Blender 4.1; custom split normals are used automatically once set
            mesh.normals_split_custom_set_from_vertices(normals)
        elif split_normals:
            mesh.create_normals_split()
            mesh.normals_split_custom_set_from_vertices(normals)
            mesh.use_auto_smooth = True

        mesh.update()
        mesh.calc_loop_triangles()
        if bpy.app.version < (4, 1, 0):
            mesh.calc_normals_split()

        for face in mesh.polygons:
            for vert_idx, loop_idx in zip(face.vertices, face.loop_indices):
                mesh.uv_layers[0].data[loop_idx].uv = uvs[vert_idx]

        # Generate materials
        for i, xmaterial in enumerate(xmesh["materials"]):
            mesh.materials.append(_create_material(xmaterial, filepath, mat_counter))
            mat_counter += 1

        for fi, face in enumerate(mesh.polygons):
            if fi < len(face_mats):
                face.material_index = face_mats[fi]

        blender_obj = bpy.data.objects.new(name, mesh)
        blender_obj["export_path"] = filepath[len(obj_root):]
        parent_collection.objects.link(blender_obj)
        blender_objs.append(blender_obj)

    return blender_objs
