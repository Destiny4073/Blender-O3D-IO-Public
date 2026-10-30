# ==============================================================================
#  Copyright (c) 2022-2023 Thomas Mathieson.
# ==============================================================================

# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####
# <pep8 compliant>

# NOTE: Since Blender 5.0 legacy `bl_info` based add-ons are no longer
# supported; this add-on is packaged as an extension and its metadata lives in
# `blender_manifest.toml`.
VERSION = (2, 2, 0)

from .o3d_io import io_o3d_import, io_o3d_export, io_omsi_tile, io_omsi_map_panel, io_x_import, io_x_export
from .o3d_io.translations import translations_dict
import bpy
from mathutils import Matrix

from bpy_extras.io_utils import (
    ImportHelper,
    ExportHelper,
    axis_conversion,
)

from bpy.props import (BoolProperty,
                       FloatProperty,
                       StringProperty,
                       CollectionProperty,
                       IntProperty
                       )


def log(*args):
    print("[O3D_IO]", *args)


def adjust_scene_render_settings(context):
    """
    Sets the scene's view transform to Filmic so the viewport matches how the
    materials looked in Blender 3.x.

    Blender 4.0 changed the default view transform from Filmic to AgX, which
    renders the very same view noticeably darker (both in the solid viewport
    and in renders). Filmic is still available, so use it to keep the old look,
    falling back to Standard if it is ever removed.
    """
    scene = context.scene
    for view in ('Filmic', 'Standard'):
        try:
            scene.view_settings.view_transform = view
            scene.view_settings.look = 'None'
            log("Set the view transform to '{0}' so the OMSI materials look like they did in Blender 3.x.".format(view))
            return
        except TypeError:
            continue
    log("WARNING: Couldn't set the view transform.")


class ImportModelCFG(bpy.types.Operator, ImportHelper):
    """Imports an OMSI model file from a CFG, SCO, or O3D file"""
    bl_idname = "import_scene.omsi_model_cfg"
    bl_label = "Import OMSI Model.cfg"
    bl_options = {'PRESET', 'UNDO'}

    # ImportHelper mixin class uses this
    filename_ext = ".o3d"

    import_custom_normals: BoolProperty(
        name="Import custom normals",
        description="Import the mesh normals as Blender custom split normals. This allows the original normal data to "
                    "be preserved correctly but can be harder to edit later.",
        default=True
    )

    filter_glob: StringProperty(
        default="*.cfg;*.sco;*.o3d;*.rdy",
        options={'HIDDEN'},
    )

    import_x: BoolProperty(
        name="Import .x files",
        description="Attempt to import .x files referenced by the model, using the plugin's built-in .x importer.",
        default=True,
    )

    override_text_encoding: StringProperty(
        name="Override text encoding (leave blank for default)",
        description="If you are having issues with some letters/accents in object names not importing correctly, try "
                    "adjusting this. Sometimes model cfg files are encoded with an unusual encoding scheme. This "
                    "usually depends on the region/language of the computer used to make the cfg file. For western "
                    "Europe try: 'cp-1252', for Eastern Europe (Cyrillic languages) try: 'cp-1251', for a full list of "
                    "supported encodings check this website: "
                    "https://docs.python.org/3/library/codecs.html#standard-encodings",
        default="",
    )

    hide_lods: BoolProperty(
        name="Hide additional LODs",
        description="Hides any meshes in LODs other than the highest quality one.",
        default=True,
    )

    parent_collection: StringProperty(
        name="Parent collection (leave blank for default)",
        description="When set, this will place all the imported objects in the specified collection. If a collection "
                    "with the specified name does not exist, it will be created.",
        default=""
    )

    adjust_render_settings: BoolProperty(
        name="Set up scene for OMSI",
        description="Sets the view transform to Filmic so the materials look like they did in Blender 3.x. Blender "
                    "4.0+ defaults to the AgX view transform, which renders the same model noticeably darker.",
        default=True,
    )

    # Selected files
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    def execute(self, context):
        """
        Imports the selected CFG/SCO/O3D file
        :param context: blender context
        :return: success message
        """
        context.window.cursor_set('WAIT')

        # Find or create the parent collection
        parent_collection = None
        if self.parent_collection != "":
            if self.parent_collection not in bpy.data.collections:
                parent_collection = bpy.data.collections.new(self.parent_collection)
                bpy.context.scene.collection.children.link(parent_collection)
            else:
                parent_collection = bpy.data.collections[self.parent_collection]

        io_o3d_import.do_import(self.filepath, context, self.import_x, self.override_text_encoding, self.hide_lods,
                                import_lods=True, parent_collection=parent_collection,
                                split_normals=self.import_custom_normals)
        if self.adjust_render_settings:
            adjust_scene_render_settings(context)
        context.window.cursor_set('DEFAULT')

        return {'FINISHED'}


class ExportModelCFG(bpy.types.Operator, ExportHelper):
    """Exports an OMSI model file to a CFG, SCO, or O3D file"""
    bl_idname = "export_scene.omsi_model_cfg"
    bl_label = "Export OMSI Model.cfg"

    filename_ext = ".o3d"
    check_extension = None

    filter_glob: StringProperty(
        default="*.cfg;*.sco;*.o3d",
        options={'HIDDEN'},
    )
    export_custom_normals: BoolProperty(
        name="Export custom normals",
        description="Export Blender custom split normals as the mesh normals. This allows for higher fidelity normals "
                    "to be exported.",
        default=True
    )
    use_selection: BoolProperty(
        name="Selection Only",
        description="Export selected objects only",
        default=True,
    )
    global_scale: FloatProperty(
        name="Scale",
        min=0.01,
        max=1000.0,
        default=1.0,
    )
    o3d_version: IntProperty(
        name="O3D Version",
        min=1,
        max=7,
        default=7,
    )
    encrypt: BoolProperty(
        name="Encrypt vertex data",
        description="Scrambles the vertex data like OMSI's own 'protected' models do. Only enable this if you know "
                    "you need it, the file can't be read without the correct key otherwise.",
        default=False,
    )

    def execute(self, context):
        context.window.cursor_set('WAIT')

        global_matrix = Matrix.Scale(self.global_scale, 4)
        io_o3d_export.do_export(self.filepath, context, global_matrix, self.use_selection, self.o3d_version,
                                self.export_custom_normals, self.encrypt)

        context.window.cursor_set('DEFAULT')

        return {'FINISHED'}


class ImportOMSITile(bpy.types.Operator, ImportHelper):
    """Imports an OMSI map file from a .map/.cfg file"""
    bl_idname = "import_scene.omsi_tile"
    bl_label = "Import OMSI tile.map/global.cfg"
    bl_options = {'PRESET', 'UNDO'}

    # ImportHelper mixin class uses this
    filename_ext = ".map"

    filter_glob: StringProperty(
        default="*.map;*.cfg",
        options={'HIDDEN'},
    )

    import_scos: BoolProperty(
        name="Import SCOs",
        description="Import the SCO files",
        default=False
    )

    import_splines: BoolProperty(
        name="Import Splines",
        description="Import the map's splines",
        default=False
    )

    spline_tess_dist: FloatProperty(
        name="Spline Tesselation Precision",
        description="The minimum distance between spline segments",
        min=0.1,
        max=1000.0,
        default=6.0,
    )

    spline_curve_sag: FloatProperty(
        name="Spline Tesselation Curve Precision",
        description="The minimum sag distance between the curve and the tessellated segment. Note that this is used in "
                    "combination with the above setting, whichever is lower is used by the tessellator.",
        min=0.0005,
        max=1.0,
        default=0.005,
    )

    import_x: BoolProperty(
        name="Import .x Files",
        description="Attempt to import .x files referenced by the model, using the plugin's built-in .x importer.",
        default=True,
    )

    centre_x: IntProperty(
        name="Centre Tile X",
        description="When loading a global.cfg file, the x coordinate of the first tile to load.",
        default=0
    )
    centre_y: IntProperty(
        name="Centre Tile Y",
        description="When loading a global.cfg file, the y coordinate of the first tile to load.",
        default=0
    )
    load_radius: IntProperty(
        name="Load Radius",
        description="When loading a global.cfg file, how many tiles around the centre tile to load. Set to 0 to only "
                    "load the centre tile, 1 loads the centre tile and it's 4 neighbours, 2 loads the centre tile and "
                    "it's 8 neighbours...",
        default=999999,
        min=0
    )

    adjust_render_settings: BoolProperty(
        name="Set up scene for OMSI",
        description="Sets the view transform to Filmic so the materials look like they did in Blender 3.x. "
                    "Blender 4.0+ defaults to the AgX view transform, which renders the same model noticeably "
                    "darker.",
        default=True,
    )

    # Selected files
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    def execute(self, context):
        """
        Imports the selected map file
        :param context: blender context
        :return: success message
        """
        context.window.cursor_set('WAIT')
        io_omsi_tile.do_import(context, self.filepath, self.import_scos, self.import_splines, self.spline_tess_dist,
                               self.spline_curve_sag, self.import_x, self.centre_x, self.centre_y, self.load_radius)
        if self.adjust_render_settings:
            adjust_scene_render_settings(context)
        context.window.cursor_set('DEFAULT')

        return {'FINISHED'}


class ImportXFile(bpy.types.Operator, ImportHelper):
    """Imports a DirectX .x mesh file (as used by OMSI helper meshes and scenery objects)"""
    bl_idname = "import_scene.omsi_x"
    bl_label = "Import DirectX .x"
    bl_options = {'PRESET', 'UNDO'}

    # ImportHelper mixin class uses this
    filename_ext = ".x"

    filter_glob: StringProperty(
        default="*.x;*.X",
        options={'HIDDEN'},
    )

    import_custom_normals: BoolProperty(
        name="Import custom normals",
        description="Import the mesh normals as Blender custom split normals. This allows the original normal data to "
                    "be preserved correctly but can be harder to edit later.",
        default=True
    )

    parent_collection: StringProperty(
        name="Parent collection (leave blank for default)",
        description="When set, this will place all the imported objects in the specified collection. If a collection "
                    "with the specified name does not exist, it will be created.",
        default=""
    )

    adjust_render_settings: BoolProperty(
        name="Set up scene for OMSI",
        description="Sets the view transform to Filmic so the materials look like they did in Blender 3.x. "
                    "Blender 4.0+ defaults to the AgX view transform, which renders the same model noticeably "
                    "darker.",
        default=True,
    )

    def execute(self, context):
        context.window.cursor_set('WAIT')

        parent_collection = None
        if self.parent_collection != "":
            if self.parent_collection not in bpy.data.collections:
                parent_collection = bpy.data.collections.new(self.parent_collection)
                bpy.context.scene.collection.children.link(parent_collection)
            else:
                parent_collection = bpy.data.collections[self.parent_collection]

        io_x_import.import_x_file(self.filepath, context, parent_collection=parent_collection,
                                  split_normals=self.import_custom_normals)
        if self.adjust_render_settings:
            adjust_scene_render_settings(context)
        context.window.cursor_set('DEFAULT')

        return {'FINISHED'}


class ExportXFile(bpy.types.Operator, ExportHelper):
    """Exports the selected objects to a DirectX .x mesh file"""
    bl_idname = "export_scene.omsi_x"
    bl_label = "Export DirectX .x"

    # ExportHelper mixin class uses this
    filename_ext = ".x"

    filter_glob: StringProperty(
        default="*.x;*.X",
        options={'HIDDEN'},
    )

    use_selection: BoolProperty(
        name="Selection Only",
        description="Export selected objects only",
        default=True,
    )
    global_scale: FloatProperty(
        name="Scale",
        min=0.01,
        max=1000.0,
        default=1.0,
    )

    def execute(self, context):
        context.window.cursor_set('WAIT')

        global_matrix = Matrix.Scale(self.global_scale, 4)
        io_x_export.do_export_x(self.filepath, context, global_matrix, self.use_selection)

        context.window.cursor_set('DEFAULT')

        return {'FINISHED'}


def menu_func_import(self, context):
    self.layout.operator(ImportModelCFG.bl_idname, text="OMSI Model Config (*.cfg, *.sco, *.o3d)")


def menu_func_export(self, context):
    self.layout.operator(ExportModelCFG.bl_idname, text="OMSI Model Config (*.cfg, *.sco, *.o3d)")


def menu_func_import_tile(self, context):
    self.layout.operator(ImportOMSITile.bl_idname, text="OMSI Map Tile (*.map)")


def menu_func_import_x(self, context):
    self.layout.operator(ImportXFile.bl_idname, text="DirectX .x Mesh (*.x)")


def menu_func_export_x(self, context):
    self.layout.operator(ExportXFile.bl_idname, text="DirectX .x Mesh (*.x)")


classes = [
    ImportModelCFG,
    ExportModelCFG,
    ImportOMSITile,
    ImportXFile,
    ExportXFile
]


def register():
    all_classes = classes[:]
    all_classes.extend(io_omsi_map_panel.get_classes())
    log("Registering Blender-O3D-IO version {0}.{1}.{2}...".format(*VERSION))
    for cls in all_classes:
        bpy.utils.register_class(cls)

    io_omsi_map_panel.register()

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_tile)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_x)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_x)

    # Register the UI translations (the source strings are English; see
    # o3d_io/translations.py)
    bpy.app.translations.register(__name__, translations_dict)


def unregister():
    all_classes = classes[:]
    all_classes.extend(io_omsi_map_panel.get_classes())

    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_tile)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_x)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_x)

    io_omsi_map_panel.unregister()

    for cls in all_classes[::-1]:
        bpy.utils.unregister_class(cls)

    try:
        bpy.app.translations.unregister(__name__)
    except Exception as e:
        log("WARNING: Couldn't unregister the UI translations:", e)


if __name__ == "__main__":
    register()
