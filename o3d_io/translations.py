# ==============================================================================
#  Copyright (c) 2023-2026 Thomas Mathieson.
# ==============================================================================
"""
UI translations for Blender-O3D-IO.

The source strings are English (the message ids below); translations only
apply when the user's Blender interface language matches. Register with
``bpy.app.translations.register(__name__, translations_dict)`` and unregister
with ``bpy.app.translations.unregister(__name__)``.
"""

# Simplified Chinese UI strings.
_zh_CN = {
    # --- Operators ----------------------------------------------------------
    ("*", "Import OMSI Model.cfg"): "导入 OMSI 模型.cfg",
    ("*", "Export OMSI Model.cfg"): "导出 OMSI 模型.cfg",
    ("*", "Import OMSI tile.map/global.cfg"): "导入 OMSI 地图 tile.map/global.cfg",
    ("*", "Import DirectX .x"): "导入 DirectX .x",
    ("*", "Export DirectX .x"): "导出 DirectX .x",
    ("*", "Import OMSI global.cfg"): "导入 OMSI global.cfg",

    # --- Operator tooltips ---------------------------------------------------
    ("*", "Imports an OMSI model file from a CFG, SCO, or O3D file"):
        "从 CFG、SCO 或 O3D 文件导入 OMSI 模型",
    ("*", "Exports an OMSI model file to a CFG, SCO, or O3D file"):
        "将 OMSI 模型导出为 CFG、SCO 或 O3D 文件",
    ("*", "Imports an OMSI map file from a .map/.cfg file"):
        "从 .map/.cfg 文件导入 OMSI 地图",
    ("*", "Imports a DirectX .x mesh file (as used by OMSI helper meshes and scenery objects)"):
        "导入 DirectX .x 网格文件（OMSI 辅助网格和场景物件所用的格式）",
    ("*", "Exports the selected objects to a DirectX .x mesh file"):
        "将所选物体导出为 DirectX .x 网格文件",
    ("*", "Imports an OMSI global.cfg file and generates a preview of it"):
        "导入 OMSI global.cfg 文件并生成地图预览",

    # --- File menu entries ----------------------------------------------------
    ("*", "OMSI Model Config (*.cfg, *.sco, *.o3d)"): "OMSI 模型配置 (*.cfg, *.sco, *.o3d)",
    ("*", "OMSI Map Tile (*.map)"): "OMSI 地图地块 (*.map)",
    ("*", "DirectX .x Mesh (*.x)"): "DirectX .x 网格 (*.x)",

    # --- Import / export properties ------------------------------------------
    ("*", "Import custom normals"): "导入自定义法线",
    ("*", "Import the mesh normals as Blender custom split normals. This allows the original normal data to be "
          "preserved correctly but can be harder to edit later."):
        "将网格法线导入为 Blender 自定义分割法线。这样可以完整保留原始法线数据，但之后编辑起来会麻烦一些。",
    ("*", "Export custom normals"): "导出自定义法线",
    ("*", "Export Blender custom split normals as the mesh normals. This allows for higher fidelity normals to be "
          "exported."):
        "将 Blender 自定义分割法线导出为网格法线。这样可以导出更高精度的法线。",
    ("*", "Import .x files"): "导入 .x 文件",
    ("*", "Import .x Files"): "导入 .x 文件",
    ("*", "Attempt to import .x files referenced by the model, using the plugin's built-in .x importer."):
        "尝试导入模型引用的 .x 文件（使用本插件内置的 .x 导入器）。",
    ("*", "Override text encoding (leave blank for default)"): "覆盖文本编码（留空使用默认）",
    ("*", "If you are having issues with some letters/accents in object names not importing correctly, try "
          "adjusting this. Sometimes model cfg files are encoded with an unusual encoding scheme. This usually "
          "depends on the region/language of the computer used to make the cfg file. For western Europe try: "
          "'cp-1252', for Eastern Europe (Cyrillic languages) try: 'cp-1251', for a full list of supported "
          "encodings check this website: "
          "https://docs.python.org/3/library/codecs.html#standard-encodings"):
        "如果物体名称中的某些字母/重音符号导入不正确，请尝试调整此项。模型 cfg 文件有时使用不常见的编码保存，"
        "通常取决于制作该文件的电脑所在地区/语言。西欧请尝试 cp-1252，东欧（西里尔字母语言）请尝试 cp-1251。"
        "受支持编码的完整列表见：https://docs.python.org/3/library/codecs.html#standard-encodings",
    ("*", "Hide additional LODs"): "隐藏其余 LOD",
    ("*", "Hides any meshes in LODs other than the highest quality one."):
        "隐藏最高精度以外所有 LOD 层级中的网格。",
    ("*", "Parent collection (leave blank for default)"): "父级集合（留空使用默认）",
    ("*", "When set, this will place all the imported objects in the specified collection. If a collection with the "
          "specified name does not exist, it will be created."):
        "设置后，所有导入的物体都会放入指定的集合。若同名集合不存在，将自动创建。",
    ("*", "Selection Only"): "仅所选物体",
    ("*", "Export selected objects only"): "只导出选中的物体",
    ("*", "Scale"): "缩放",
    ("*", "O3D Version"): "O3D 版本",
    ("*", "Encrypt vertex data"): "加密顶点数据",
    ("*", "Scrambles the vertex data like OMSI's own 'protected' models do. Only enable this if you know you need "
          "it, the file can't be read without the correct key otherwise."):
        "像 OMSI 自带的“受保护”模型那样扰乱顶点数据。仅在确有需要时开启，否则没有正确密钥将无法读取该文件。",

    # --- Map / spline properties ----------------------------------------------
    ("*", "Import SCOs"): "导入 SCO",
    ("*", "Import the SCO files"): "导入 SCO 文件",
    ("*", "Import Splines"): "导入样条线",
    ("*", "Import the map's splines"): "导入地图的样条线",
    ("*", "Spline Tesselation Precision"): "样条线细分精度",
    ("*", "The minimum distance between spline segments"): "样条线线段之间的最小距离",
    ("*", "Spline Tesselation Curve Precision"): "样条线细分曲线精度",
    ("*", "The minimum sag distance between the curve and the tessellated segment. Note that this is used in "
          "combination with the above setting, whichever is lower is used by the tessellator."):
        "曲线与细分线段之间的最小矢高距离。注意此项与上一项配合使用，细分时取两者中较小的值。",
    ("*", "Centre Tile X"): "中心地块 X",
    ("*", "When loading a global.cfg file, the x coordinate of the first tile to load."):
        "加载 global.cfg 文件时，首个加载地块的 X 坐标。",
    ("*", "Centre Tile Y"): "中心地块 Y",
    ("*", "When loading a global.cfg file, the y coordinate of the first tile to load."):
        "加载 global.cfg 文件时，首个加载地块的 Y 坐标。",
    ("*", "Load Radius"): "加载半径",
    ("*", "When loading a global.cfg file, how many tiles around the centre tile to load. Set to 0 to only load "
          "the centre tile, 1 loads the centre tile and it's 4 neighbours, 2 loads the centre tile and it's 8 "
          "neighbours..."):
        "加载 global.cfg 文件时，围绕中心地块加载多大范围内的地块。0 表示只加载中心地块，1 表示加载中心地块及其"
        " 4 个相邻地块，2 表示加载中心地块及其 8 个相邻地块……",
    ("*", "Roadmap Mode"): "路网模式",
    ("*", "Imports trees, water and full quality splines for roadmap rendering"):
        "导入树木、水面和全精度样条线，用于渲染路网图",
    ("*", "Spline Preview Quality"): "样条线预览质量",
    ("*", "Clear Preview"): "清除预览",
    ("*", "File Path"): "文件路径",

    # --- Scene setup ------------------------------------------------------------
    ("*", "Set up scene for OMSI"): "为 OMSI 设置场景",
    ("*", "Sets the view transform to Filmic so the materials look like they did in Blender 3.x. Blender 4.0+ "
          "defaults to the AgX view transform, which renders the same model noticeably darker."):
        "将视图变换设为 Filmic，使材质呈现与 Blender 3.x 相同的效果。Blender 4.0+ 默认的 AgX 视图变换会让同一"
        "模型看起来明显更暗。",

    # --- Map preview panel --------------------------------------------------------
    ("*", "Import Omsi Map"): "导入 OMSI 地图",
    ("*", "Tile coords x: "): "地块坐标 x：",
    ("*", " y: "): " y：",
    ("*", "N/A"): "未知",
    ("*", "Map Path:"): "地图路径：",
    ("*", "Preview map"): "预览地图",
    ("*", "Clear map preview"): "清除地图预览",
    ("*", "Load for roadmap"): "加载为路网图",
    ("*", "Load tiles"): "加载地块",
}

translations_dict = {
    # Blender 4.x+ renamed the locale identifier from zh_CN to zh_HANS; register
    # both so the translations work on every supported version.
    "zh_HANS": _zh_CN,
    "zh_CN": _zh_CN,
}
