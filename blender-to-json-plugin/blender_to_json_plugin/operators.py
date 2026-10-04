import json
import os

import bpy
from bpy.props import EnumProperty

from . import sync


def _settings(context):
    return context.scene.blender_to_json_settings


def _active(context):
    settings = _settings(context)
    if 0 <= settings.active_index < len(settings.parameters):
        return settings.parameters[settings.active_index]
    return None


def _unique_name(settings, base):
    names = {p.name for p in settings.parameters}
    if base not in names:
        return base
    i = 2
    while f'{base}{i}' in names:
        i += 1
    return f'{base}{i}'


class B2J_OT_parameter_add(bpy.types.Operator):
    bl_idname = 'blender_to_json.parameter_add'
    bl_label = 'Add Parameter'
    bl_description = 'Add a named parameter that the blender-to-json CLI can refer to as @name'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = _settings(context)
        param = settings.parameters.add()
        param.name = _unique_name(settings, 'param')
        settings.active_index = len(settings.parameters) - 1
        sync.write_scene(context.scene)
        return {'FINISHED'}


class B2J_OT_parameter_add_camera(bpy.types.Operator):
    bl_idname = 'blender_to_json.parameter_add_camera'
    bl_label = 'Add Camera Parameter'
    bl_description = 'Add a camera parameter set to the active camera object (or the scene camera)'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = _settings(context)
        obj = context.active_object
        camera = obj if obj is not None and obj.type == 'CAMERA' else context.scene.camera
        param = settings.parameters.add()
        param.name = _unique_name(settings, 'camera')
        param.param_type = 'CAMERA'
        if camera is not None:
            param.value_camera = camera
        settings.active_index = len(settings.parameters) - 1
        sync.write_scene(context.scene)
        return {'FINISHED'}


class B2J_OT_parameter_remove(bpy.types.Operator):
    bl_idname = 'blender_to_json.parameter_remove'
    bl_label = 'Remove Parameter'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active(context) is not None

    def execute(self, context):
        settings = _settings(context)
        settings.parameters.remove(settings.active_index)
        settings.active_index = min(settings.active_index, len(settings.parameters) - 1)
        sync.write_scene(context.scene)
        return {'FINISHED'}


class B2J_OT_parameter_move(bpy.types.Operator):
    bl_idname = 'blender_to_json.parameter_move'
    bl_label = 'Move Parameter'
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=[('UP', 'Up', ''), ('DOWN', 'Down', '')])

    @classmethod
    def poll(cls, context):
        return _active(context) is not None

    def execute(self, context):
        settings = _settings(context)
        index = settings.active_index
        target = index - 1 if self.direction == 'UP' else index + 1
        if 0 <= target < len(settings.parameters):
            settings.parameters.move(index, target)
            settings.active_index = target
            sync.write_scene(context.scene)
        return {'FINISHED'}


class B2J_OT_copy_reference(bpy.types.Operator):
    bl_idname = 'blender_to_json.copy_reference'
    bl_label = 'Copy Reference'
    bl_description = 'Copy the parameter reference to the clipboard'

    kind: EnumProperty(items=[
        ('REF', '@name', 'The reference to paste into a config value, e.g. "camera": "@name"'),
        ('PARAM', '--param', 'A command-line override, e.g. --param name=value'),
    ])

    @classmethod
    def poll(cls, context):
        return _active(context) is not None

    def execute(self, context):
        param = _active(context)
        if self.kind == 'REF':
            text = f'@{param.name}'
        else:
            text = f"--param {param.name}={json.dumps(param.get_value())}"
        context.window_manager.clipboard = text
        self.report({'INFO'}, f'Copied: {text}')
        return {'FINISHED'}


class B2J_OT_copy_command(bpy.types.Operator):
    bl_idname = 'blender_to_json.copy_command'
    bl_label = 'Copy CLI Command'
    bl_description = 'Copy a blender-to-json command for this file to the clipboard'

    def execute(self, context):
        path = bpy.data.filepath
        if not path:
            self.report({'WARNING'}, 'Save the file first')
            return {'CANCELLED'}
        text = f'blender-to-json "{path}"'
        settings = _settings(context)
        if len(bpy.data.scenes) > 1:
            text += f' --set scene={json.dumps(context.scene.name)}'
        cam = next((p for p in settings.parameters if p.param_type == 'CAMERA'), None)
        if cam is not None:
            text += f' --set camera=@{cam.name}'
        context.window_manager.clipboard = text
        self.report({'INFO'}, f'Copied: {text}')
        return {'FINISHED'}


class B2J_OT_sync(bpy.types.Operator):
    bl_idname = 'blender_to_json.sync'
    bl_label = 'Refresh Stored Parameters'
    bl_description = ('Rewrite the JSON copy of the parameters the CLI reads. This also happens '
                      'automatically on every save')

    def execute(self, context):
        sync.write_scene(context.scene)
        self.report({'INFO'}, f'Stored {len(_settings(context).parameters)} parameter(s) '
                              f'in "{os.path.basename(bpy.data.filepath) or "unsaved file"}"')
        return {'FINISHED'}


classes = (
    B2J_OT_parameter_add,
    B2J_OT_parameter_add_camera,
    B2J_OT_parameter_remove,
    B2J_OT_parameter_move,
    B2J_OT_copy_reference,
    B2J_OT_copy_command,
    B2J_OT_sync,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
