import bpy

from .properties import TYPE_ICONS


class B2J_UL_parameters(bpy.types.UIList):
    bl_idname = 'B2J_UL_parameters'

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        problem = item.problem(data)
        row.label(text=f'@{item.name}', icon='ERROR' if problem else TYPE_ICONS[item.param_type])
        value = row.row()
        value.alert = bool(problem)
        value.prop(item, item.value_attr, text='')


class B2J_PT_main(bpy.types.Panel):
    bl_idname = 'B2J_PT_main'
    bl_label = 'Blender to JSON'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Blender to JSON'

    def draw(self, context):
        layout = self.layout
        layout.operator('blender_to_json.copy_command', icon='CONSOLE')


class B2J_PT_parameters(bpy.types.Panel):
    bl_idname = 'B2J_PT_parameters'
    bl_label = 'Parameters'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Blender to JSON'
    bl_parent_id = 'B2J_PT_main'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blender_to_json_settings

        row = layout.row()
        row.template_list('B2J_UL_parameters', '', settings, 'parameters', settings, 'active_index', rows=4)
        col = row.column(align=True)
        col.operator('blender_to_json.parameter_add', icon='ADD', text='')
        col.operator('blender_to_json.parameter_remove', icon='REMOVE', text='')
        col.separator()
        col.operator('blender_to_json.parameter_add_camera', icon='CAMERA_DATA', text='')
        col.separator()
        col.operator('blender_to_json.parameter_move', icon='TRIA_UP', text='').direction = 'UP'
        col.operator('blender_to_json.parameter_move', icon='TRIA_DOWN', text='').direction = 'DOWN'

        if not (0 <= settings.active_index < len(settings.parameters)):
            layout.label(text='Add a parameter to refer to it from the CLI.', icon='INFO')
            return

        param = settings.parameters[settings.active_index]
        box = layout.box()
        box.prop(param, 'name')
        box.prop(param, 'param_type')
        box.prop(param, param.value_attr)
        box.prop(param, 'description')

        problem = param.problem(settings)
        if problem:
            box.label(text=problem, icon='ERROR')

        row = box.row(align=True)
        row.label(text=f'Config: "@{param.name}"')
        row.operator('blender_to_json.copy_reference', text='', icon='COPYDOWN').kind = 'REF'
        row = box.row(align=True)
        row.label(text=f'CLI: --param {param.name}=…')
        row.operator('blender_to_json.copy_reference', text='', icon='COPYDOWN').kind = 'PARAM'

        layout.operator('blender_to_json.sync', icon='FILE_REFRESH')


classes = (B2J_UL_parameters, B2J_PT_main, B2J_PT_parameters)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
