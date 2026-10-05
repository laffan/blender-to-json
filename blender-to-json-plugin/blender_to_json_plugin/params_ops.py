"""Operators for tracked parameters: eyedropper, right-click menu, list editing."""

import json

import bpy
from bpy.props import EnumProperty, StringProperty

from . import sync
from .core import datapath


def _root(context):
    return context.scene.blender_to_json_settings


def _active(context):
    root = _root(context)
    if 0 <= root.active_index < len(root.parameters):
        return root.parameters[root.active_index]
    return None


def _unique_name(root, base):
    names = {p.name for p in root.parameters}
    if base not in names:
        return base
    i = 2
    while f'{base}{i}' in names:
        i += 1
    return f'{base}{i}'


def track(scene, id_type, id_name, path):
    """Add (or re-select) a parameter tracking `bpy.data.<id_type>[id_name].<path>`."""
    id_block = datapath.find_id(id_type, id_name)
    if id_block is None:
        raise datapath.DataPathError(f'no {id_type} named {id_name!r}')
    id_block.path_resolve(path)  # raises ValueError if the path is wrong
    root = scene.blender_to_json_settings
    for index, existing in enumerate(root.parameters):
        if existing.target() == id_block and existing.path == path:
            root.active_index = index
            return existing, False
    param = root.parameters.add()
    param.name = _unique_name(root, datapath.suggest_name(path))
    param.id_type, param.id_name, param.path = id_type, id_name, path
    param.id_ref = id_block
    root.active_index = len(root.parameters) - 1
    sync.write_scene(scene)
    return param, True


def track_full_path(scene, text):
    id_type, id_name, path = datapath.parse_full_path(text)
    return track(scene, id_type, id_name, path)


def _report_tracked(op, param, created):
    verb = 'Tracking' if created else 'Already tracking'
    op.report({'INFO'}, f'{verb} @{param.name} = {json.dumps(param.value())}  ({param.label()})')


# ---------------------------------------------------------------------- eyedropper

def _area_under_mouse(window, x, y):
    for area in window.screen.areas:
        if area.x <= x < area.x + area.width and area.y <= y < area.y + area.height:
            for region in area.regions:
                if region.x <= x < region.x + region.width and region.y <= y < region.y + region.height:
                    return area, region
            return area, None
    return None, None


class B2J_OT_parameter_pick(bpy.types.Operator):
    """Click any property in Blender's interface to track it as a parameter"""
    bl_idname = 'blender_to_json.parameter_pick'
    bl_label = 'Pick Property'
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        self._clipboard = context.window_manager.clipboard
        context.window.cursor_modal_set('EYEDROPPER')
        context.workspace.status_text_set('Click a property to track it as a parameter  ·  Esc / right-click: cancel')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        context.window_manager.clipboard = self._clipboard

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE' or event.value != 'PRESS':
            # Let the interface see mouse moves so the hovered button becomes active.
            return {'PASS_THROUGH'}

        wm = context.window_manager
        area, region = _area_under_mouse(context.window, event.mouse_x, event.mouse_y)
        text = ''
        if area is not None and region is not None:
            wm.clipboard = ''
            try:
                with context.temp_override(window=context.window, area=area, region=region):
                    bpy.ops.ui.copy_data_path_button(full_path=True)
            except (RuntimeError, TypeError):
                pass
            text = wm.clipboard
        self._finish(context)

        if not text:
            self.report({'WARNING'}, 'No property under the cursor. Hover a property field and click, or '
                                     'right-click the property › Track as Blender to JSON Parameter')
            return {'CANCELLED'}
        try:
            param, created = track_full_path(context.scene, text)
        except (datapath.DataPathError, ValueError) as e:
            self.report({'WARNING'}, f"Can't track {text}: {e}")
            return {'CANCELLED'}
        _report_tracked(self, param, created)
        for a in context.screen.areas:
            a.tag_redraw()
        return {'FINISHED'}


# ---------------------------------------------------------------------- right-click menu

class B2J_OT_parameter_track_button(bpy.types.Operator):
    """Track this property as a Blender to JSON parameter"""
    bl_idname = 'blender_to_json.parameter_track_button'
    bl_label = 'Track as Blender to JSON Parameter'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return getattr(context, 'button_pointer', None) is not None and \
            getattr(context, 'button_prop', None) is not None

    def execute(self, context):
        pointer = context.button_pointer
        prop = context.button_prop
        id_block = getattr(pointer, 'id_data', None)
        if id_block is None:
            self.report({'WARNING'}, "This property doesn't belong to any datablock, so it can't be tracked")
            return {'CANCELLED'}
        try:
            path = pointer.path_from_id(prop.identifier)
            id_type, id_name, path = datapath.locate(id_block, path)
            param, created = track(context.scene, id_type, id_name, path)
        except (ValueError, datapath.DataPathError) as e:
            self.report({'WARNING'}, f"Can't track {prop.identifier}: {e}")
            return {'CANCELLED'}
        _report_tracked(self, param, created)
        return {'FINISHED'}


def button_context_menu(self, context):
    if B2J_OT_parameter_track_button.poll(context):
        self.layout.separator()
        self.layout.operator(B2J_OT_parameter_track_button.bl_idname, icon='EYEDROPPER')


# ---------------------------------------------------------------------- list editing

class B2J_OT_parameter_add_path(bpy.types.Operator):
    """Track a property by its full data path (Ctrl+Shift+Alt+C over any property copies it)"""
    bl_idname = 'blender_to_json.parameter_add_path'
    bl_label = 'Track Data Path'
    bl_options = {'REGISTER', 'UNDO'}

    full_path: StringProperty(name='Full Data Path',
                              description='e.g. bpy.data.scenes["Scene"].render.resolution_x')

    def invoke(self, context, event):
        clip = context.window_manager.clipboard.strip()
        if clip.startswith('bpy.data.'):
            self.full_path = clip
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        try:
            param, created = track_full_path(context.scene, self.full_path)
        except (datapath.DataPathError, ValueError) as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        _report_tracked(self, param, created)
        return {'FINISHED'}


class B2J_OT_parameter_remove(bpy.types.Operator):
    bl_idname = 'blender_to_json.parameter_remove'
    bl_label = 'Remove Parameter'
    bl_description = 'Stop tracking this property'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active(context) is not None

    def execute(self, context):
        root = _root(context)
        root.parameters.remove(root.active_index)
        root.active_index = min(root.active_index, len(root.parameters) - 1)
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
        root = _root(context)
        index = root.active_index
        target = index - 1 if self.direction == 'UP' else index + 1
        if 0 <= target < len(root.parameters):
            root.parameters.move(index, target)
            root.active_index = target
            sync.write_scene(context.scene)
        return {'FINISHED'}


class B2J_OT_copy_reference(bpy.types.Operator):
    bl_idname = 'blender_to_json.copy_reference'
    bl_label = 'Copy Reference'
    bl_description = 'Copy the parameter reference to the clipboard'

    kind: EnumProperty(items=[
        ('REF', '@name', 'The reference to paste into a config value, e.g. "camera": "@name"'),
        ('PARAM', '--param', 'A command-line flag that sets the property, e.g. --param name=value'),
    ])

    @classmethod
    def poll(cls, context):
        return _active(context) is not None

    def execute(self, context):
        param = _active(context)
        if self.kind == 'REF':
            text = f'@{param.name}'
        else:
            text = f"--param {param.name}={json.dumps(param.value())}"
        context.window_manager.clipboard = text
        self.report({'INFO'}, f'Copied: {text}')
        return {'FINISHED'}


classes = (
    B2J_OT_parameter_pick,
    B2J_OT_parameter_track_button,
    B2J_OT_parameter_add_path,
    B2J_OT_parameter_remove,
    B2J_OT_parameter_move,
    B2J_OT_copy_reference,
)


def _context_menu_type():
    # UI_MT_button_context_menu is the supported hook (Blender 3.3+); the
    # add-on-defined WM_MT_button_context it replaced is deprecated.
    return getattr(bpy.types, 'UI_MT_button_context_menu', None)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    menu = _context_menu_type()
    if menu is not None:
        menu.append(button_context_menu)


def unregister():
    menu = _context_menu_type()
    if menu is not None:
        menu.remove(button_context_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
