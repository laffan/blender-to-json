import bpy

from . import export_ops, preview
from .core import datapath
from .core import plan as planner

CATEGORY = 'Blender to JSON'


class _SidebarPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY


class B2J_PT_main(_SidebarPanel, bpy.types.Panel):
    bl_idname = 'B2J_PT_main'
    bl_label = 'Blender to JSON'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        row = col.row(align=True)
        row.scale_y = 1.4
        row.operator('blender_to_json.export', text='Export', icon='RENDER_STILL').mode = 'ALL'
        row = col.row(align=True)
        row.operator('blender_to_json.export', text='Export Selected', icon='RESTRICT_SELECT_OFF').mode = 'SELECTED'
        row.operator('blender_to_json.export', text='Dry Run', icon='VIEWZOOM').mode = 'DRYRUN'
        row = col.row(align=True)
        row.operator('blender_to_json.open_folder', icon='FILE_FOLDER')
        row.operator('blender_to_json.copy_command', text='Copy Command', icon='CONSOLE')

        if export_ops.is_running():
            box = layout.box()
            row = box.row()
            row.label(text=export_ops.status_text() or 'Working…', icon='SORTTIME')
            row.operator('blender_to_json.cancel', text='', icon='X')
        elif export_ops.status_text():
            layout.label(text=export_ops.status_text(), icon='INFO')


class B2J_PT_setup(_SidebarPanel, bpy.types.Panel):
    bl_idname = 'B2J_PT_setup'
    bl_label = 'Setup'
    bl_parent_id = 'B2J_PT_main'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blender_to_json_settings.export
        row = layout.row(align=True)
        row.prop(settings, 'camera_preset', text='')
        row.operator('blender_to_json.create_camera', icon='CAMERA_DATA')
        layout.operator('blender_to_json.transparent_film', icon='TEXTURE')


class B2J_PT_settings(_SidebarPanel, bpy.types.Panel):
    bl_idname = 'B2J_PT_settings'
    bl_label = 'Export Settings'
    bl_parent_id = 'B2J_PT_main'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.blender_to_json_settings.export

        col = layout.column()
        col.prop(settings, 'output_dir')
        col.prop(settings, 'config_path')
        col.prop(settings, 'open_folder')

        col = layout.column(heading='Render')
        col.prop(settings, 'camera')
        col.prop(settings, 'render_bounds')
        col.prop(settings, 'render_padding')
        col.prop(settings, 'cast_shadows')
        col.prop(settings, 'holdout_collection', text='Crop with Ground')

        col = layout.column(heading='Tiles')
        col.prop(settings, 'base_tile')
        sub = col.column()
        sub.active = settings.base_tile is not None
        sub.prop(settings, 'tile_width')
        sub.prop(settings, 'snap_to_grid')
        col.prop(settings, 'tile_slice_size')

        col = layout.column(heading='Output')
        col.prop(settings, 'psd')
        col.prop(settings, 'pass_through')

        if settings.ignore_layers:
            box = layout.box()
            box.label(text='Excluded (toggle in Export Preview):')
            for item in settings.ignore_layers:
                row = box.row()
                row.label(text=item.name, icon='CHECKBOX_DEHLT')
                op = row.operator('blender_to_json.preview_exclude', text='', icon='X', emboss=False)
                op.name = item.name

        layout.label(text='A config file or --set flags override these.', icon='INFO')


class B2J_UL_parameters(bpy.types.UIList):
    bl_idname = 'B2J_UL_parameters'

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        problem = item.problem(data)
        split = row.split(factor=0.4, align=True)
        split.label(text=f'@{item.name}', icon='ERROR' if problem else 'RNA')
        _draw_value(split, item, text='')


def _draw_value(layout, param, text=None):
    """Draw the tracked property's own widget, so its live value is visible and editable."""
    id_block = param.target()
    if id_block is None:
        layout.alert = True
        layout.label(text='missing')
        return
    try:
        owner, prop, index = datapath.ui_target(id_block, param.path)
        kwargs = {} if text is None else {'text': text}
        layout.prop(owner, prop, index=index, **kwargs)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, datapath.DataPathError):
        layout.alert = True
        layout.label(text='unreadable')


class B2J_PT_parameters(_SidebarPanel, bpy.types.Panel):
    bl_idname = 'B2J_PT_parameters'
    bl_label = 'Parameters'
    bl_parent_id = 'B2J_PT_main'

    def draw(self, context):
        layout = self.layout
        root = context.scene.blender_to_json_settings

        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator('blender_to_json.parameter_pick', text='Pick Property', icon='EYEDROPPER')
        row.operator('blender_to_json.parameter_add_path', text='', icon='PASTEDOWN')

        row = layout.row()
        row.template_list('B2J_UL_parameters', '', root, 'parameters', root, 'active_index', rows=3)
        col = row.column(align=True)
        col.operator('blender_to_json.parameter_remove', icon='REMOVE', text='')
        col.separator()
        col.operator('blender_to_json.parameter_move', icon='TRIA_UP', text='').direction = 'UP'
        col.operator('blender_to_json.parameter_move', icon='TRIA_DOWN', text='').direction = 'DOWN'

        if not (0 <= root.active_index < len(root.parameters)):
            col = layout.column(align=True)
            col.label(text='Click Pick Property, then click any', icon='INFO')
            col.label(text='property in Blender to track it. Or')
            col.label(text='right-click a property › Track as')
            col.label(text='Blender to JSON Parameter.')
            return

        param = root.parameters[root.active_index]
        box = layout.box()
        box.prop(param, 'name')
        col = box.column(align=True)
        col.label(text=param.label(), icon='RNA')
        _draw_value(col, param)
        sub = box.column()
        sub.scale_y = 0.7
        sub.label(text=param.full_path())
        box.prop(param, 'description')

        problem = param.problem(root)
        if problem:
            box.alert = True
            box.label(text=problem, icon='ERROR')

        row = box.row(align=True)
        row.label(text=f'"@{param.name}"')
        row.operator('blender_to_json.copy_reference', text='', icon='COPYDOWN').kind = 'REF'
        row = box.row(align=True)
        row.label(text=f'--param {param.name}=…')
        row.operator('blender_to_json.copy_reference', text='', icon='COPYDOWN').kind = 'PARAM'


class B2J_PT_preview(_SidebarPanel, bpy.types.Panel):
    bl_idname = 'B2J_PT_preview'
    bl_label = 'Export Preview'
    bl_parent_id = 'B2J_PT_main'
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        nodes = preview.build(context.scene)
        counts = planner.summarize(nodes)
        self.layout.label(text=f"{counts['layers']} layers · {counts['renders']} renders")

    def draw(self, context):
        layout = self.layout
        nodes = preview.build(context.scene)
        counts = planner.summarize(nodes)
        if counts['warnings']:
            layout.label(text=f"{counts['warnings']} problem(s) shown in red", icon='ERROR')
        if not nodes:
            layout.label(text='The scene is empty.')
            return
        col = layout.column(align=True)
        preview.draw_tree(col, context.scene, nodes)
        hint = layout.column(align=True)
        hint.scale_y = 0.7
        hint.label(text='Names: G group, S sprite, T tiles, P point, Z zone.')
        hint.label(text='Checkbox: include/exclude. Click a name to select it.')


classes = (B2J_PT_main, B2J_PT_setup, B2J_PT_settings, B2J_UL_parameters, B2J_PT_parameters, B2J_PT_preview)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
