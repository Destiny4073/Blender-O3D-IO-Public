# ==============================================================================
#  Copyright (c) 2023-2026 Thomas Mathieson.
# ==============================================================================
import os
import time

import bpy
from mathutils import Matrix

from bpy_extras import node_shader_utils


def log(*args):
    print("[X_Export]", *args)


# OMSI mesh files use Direct3D's frame (X right, Y up, Z forward); Blender is
# Z-up, so the exporter swaps Y and Z — the inverse of what the engine (and the
# o3d exporter in this plugin) does.
AXIS_SWAP = Matrix((
    (1, 0, 0, 0),
    (0, 0, 1, 0),
    (0, 1, 0, 0),
    (0, 0, 0, 1)
))

def _f(v):
    return "{0:.6f}".format(v)


def _safe_name(name):
    """Strips characters which would break the .x text format."""
    return "".join(c for c in name if c.isalnum() or c in "_-. ").strip() or "mesh"


def _write_number_list(writer, indent, items, components):
    """
    Writes a DirectX number list: each item is a `;`-separated group of
    floats, items separated by `,`, terminated by `;;`.
    """
    for i, item in enumerate(items):
        terminator = ";" if i == len(items) - 1 else ","
        writer.write("{0}{1};{2}\n".format(indent, ";".join(_f(x) for x in item), terminator))


def _write_index_list(writer, indent, faces):
    """
    Writes a DirectX face list: each face is `n;i0,i1,...;`, faces separated by
    `,`, terminated by `;;`.
    """
    for i, face in enumerate(faces):
        terminator = ";" if i == len(faces) - 1 else ","
        writer.write("{0}{1};{2};{3}\n".format(indent, len(face), ",".join(str(x) for x in face), terminator))


def _export_material(writer, mat, name, indent=""):
    """
    Writes a DirectX Material block from a Blender material.
    """
    if mat is None:
        # The DirectX default material
        writer.write("{0}Material {{\n".format(indent))
        writer.write("{0} 1.000000;1.000000;1.000000;1.000000;;\n".format(indent))
        writer.write("{0} 1.000000;\n".format(indent))
        writer.write("{0} 0.000000;0.000000;0.000000;;\n".format(indent))
        writer.write("{0} 0.000000;0.000000;0.000000;;\n".format(indent))
        writer.write("{0}}}\n".format(indent))
        return

    wrapper = node_shader_utils.PrincipledBSDFWrapper(mat, is_readonly=True)
    diffuse = wrapper.base_color
    alpha = wrapper.alpha
    power = max(1.0 - wrapper.roughness, 0.0)
    specular = (wrapper.specular, wrapper.specular, wrapper.specular)
    emission = wrapper.emission_color[:3]
    texture = ""
    if wrapper.base_color_texture is not None and wrapper.base_color_texture.image is not None:
        texture = os.path.basename(wrapper.base_color_texture.image.filepath)

    writer.write("{0}Material {1} {{\n".format(indent, name))
    writer.write("{0} {1};{2};{3};{4};;\n".format(indent, _f(diffuse[0]), _f(diffuse[1]), _f(diffuse[2]),
                                                  _f(alpha)))
    writer.write("{0} {1};\n".format(indent, _f(power)))
    writer.write("{0} {1};{2};{3};;\n".format(indent, _f(specular[0]), _f(specular[1]), _f(specular[2])))
    writer.write("{0} {1};{2};{3};;\n".format(indent, _f(emission[0]), _f(emission[1]), _f(emission[2])))
    if texture:
        writer.write("{0} TextureFilename {{ \"{1}\"; }}\n".format(indent, texture))
    writer.write("{0}}}\n".format(indent))


def _export_mesh_object(writer, ob, deps_graph, global_matrix):
    ob_eval = ob.evaluated_get(deps_graph)
    try:
        me = ob_eval.to_mesh()
    except RuntimeError:
        return False

    try:
        mesh_matrix = AXIS_SWAP @ ob.matrix_world
        if global_matrix is not None:
            mesh_matrix = global_matrix @ mesh_matrix
        normal_mat = mesh_matrix.to_3x3().normalized()
        invert_winding = mesh_matrix.is_negative

        has_uvs = len(me.uv_layers) > 0
        uv_layer = me.uv_layers.active.data if has_uvs else None

        # Build a deduplicated vertex list, exactly like the o3d exporter: the
        # .x format stores one texture coordinate per vertex, so vertices which
        # differ in their normal or UV must be split.
        verts = []
        vert_map = {}
        faces = []
        face_mats = []
        for poly in me.polygons:
            face = []
            for vert_idx, loop_idx in zip(poly.vertices, poly.loop_indices):
                vert = me.vertices[vert_idx]
                co = tuple(mesh_matrix @ vert.co)
                try:
                    normal = tuple(normal_mat @ me.corner_normals[loop_idx].vector)
                except (AttributeError, IndexError):
                    normal = tuple(normal_mat @ vert.normal)
                uv = tuple(uv_layer[loop_idx].uv[:2]) if uv_layer is not None else (0.0, 0.0)

                key = (co, normal, uv)
                idx = vert_map.get(key)
                if idx is None:
                    idx = len(verts)
                    vert_map[key] = idx
                    verts.append((co, normal, uv))
                face.append(idx)
            if len(face) < 3:
                continue
            # Direct3D's winding is mirrored relative to Blender's (the axis
            # swap flips the handedness), so the face order is reversed — the
            # same rule the o3d exporter applies.
            if invert_winding:
                face.reverse()
            faces.append(face)
            face_mats.append(poly.material_index)

        if len(verts) == 0 or len(faces) == 0:
            return False

        name = _safe_name(ob.name)

        # Collect the materials used by this mesh
        materials = []
        mat_remapped = {}
        for slot_idx, slot in enumerate(ob_eval.material_slots):
            if slot.material is None:
                continue
            mat_remapped[slot_idx] = len(materials)
            materials.append(slot.material)

        writer.write("Frame {0} {{\n".format(name))
        writer.write(" FrameTransformMatrix {\n")
        writer.write("  1.000000;0.000000;0.000000;0.000000,\n")
        writer.write("  0.000000;1.000000;0.000000;0.000000,\n")
        writer.write("  0.000000;0.000000;1.000000;0.000000,\n")
        writer.write("  0.000000;0.000000;0.000000;1.000000;;\n")
        writer.write(" }\n")
        writer.write(" Mesh {0} {{\n".format(name))

        # Vertices
        writer.write("  {0};\n".format(len(verts)))
        _write_number_list(writer, "  ", [(co, normal, uv)[0] for co, normal, uv in verts], 3)
        # Faces
        writer.write("  {0};\n".format(len(faces)))
        _write_index_list(writer, "  ", faces)

        # Normals (one per vertex, indexed per face corner)
        writer.write("  MeshNormals {\n")
        writer.write("   {0};\n".format(len(verts)))
        _write_number_list(writer, "   ", [(co, normal, uv)[1] for co, normal, uv in verts], 3)
        writer.write("   {0};\n".format(len(faces)))
        _write_index_list(writer, "   ", faces)
        writer.write("  }\n")

        # Texture coordinates (one per vertex)
        writer.write("  MeshTextureCoords {\n")
        writer.write("   {0};\n".format(len(verts)))
        _write_number_list(writer, "   ", [(co, normal, uv)[2] for co, normal, uv in verts], 2)
        writer.write("  }\n")

        # Materials
        writer.write("  MeshMaterialList {\n")
        writer.write("   {0};\n".format(max(len(materials), 1)))
        writer.write("   {0};\n".format(len(faces)))
        if len(materials) == 0:
            writer.write("   {0};;\n".format(",".join("0" for _ in faces)))
            _export_material(writer, None, "", indent="   ")
        else:
            writer.write("   {0};;\n".format(
                ",".join(str(mat_remapped.get(m, 0)) for m in face_mats)))
            for slot_idx, mat in enumerate(materials):
                _export_material(writer, mat, "{0}_mat{1}".format(name, slot_idx), indent="   ")
        writer.write("  }\n")

        writer.write(" }\n")
        writer.write("}\n")
        return True
    finally:
        ob_eval.to_mesh_clear()


def do_export_x(filepath, context, global_matrix, use_selection):
    """
    Exports the selected objects to a DirectX .x mesh file (text format), the
    same format OMSI reads.

    :param filepath: the path to the .x file to write
    :param context: blender context
    :param global_matrix: transformation matrix to apply before export
    :param use_selection: export only the selected objects
    :return: the number of exported meshes
    """
    start_time = time.time()

    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode='OBJECT')

    if use_selection:
        obs = context.selected_objects
    else:
        obs = context.scene.objects

    deps_graph = context.evaluated_depsgraph_get()

    bpy.context.window_manager.progress_begin(0, len(obs))

    n_exported = 0
    with open(filepath, "w", encoding="cp1252", errors="replace", newline="\n") as f:
        f.write("xof 0303txt 0032\n")
        for index, ob in enumerate(obs):
            if ob.type != 'MESH':
                continue
            log("Exporting " + ob.name + "...")
            bpy.context.window_manager.progress_update(index)
            if _export_mesh_object(f, ob, deps_graph, global_matrix):
                n_exported += 1

    bpy.context.window_manager.progress_end()
    log("Exported {0} models to {1} in {2} seconds!".format(n_exported, filepath, time.time() - start_time))
    return n_exported
