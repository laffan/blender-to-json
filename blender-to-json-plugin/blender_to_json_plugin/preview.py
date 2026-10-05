"""Live preview of how blender-to-json will parse the scene.

The tree is rebuilt from the shared plan module (the same one the CLI uses)
every time the panel redraws, so it follows renames and new collections as
you work.
"""

import bpy
from bpy.props import StringProperty

from . import sync
from .core import plan as planner

MAX_ROWS = 400

CATEGORY_ICONS = {
    'group': 'OUTLINER_COLLECTION',
    'sprite': 'IMAGE_DATA',
    'tileset': 'MESH_GRID',
    'point': 'EMPTY_AXIS',
    'zone': 'MOD_MASK',
}
LETTERS = {'group': 'G', 'sprite': 'S', 'tileset': 'T', 'point': 'P', 'zone': 'Z'}

# Collapsed rows, by Blender name. Not saved with the file.
_collapsed = set()


def plan_options(scene):
    settings = scene.blender_to_json_settings.export
    return planner.PlanOptions(
        ignore=[item.name for item in settings.ignore_layers],
        pass_through=settings.pass_through,
        holdout=settings.holdout_collection,
    )


def build(scene):
    return planner.build_plan(scene.collection, plan_options(scene))


def _key(node):
    return f'{node.kind}:{node.blender_name}'


def _ignored_by_user(scene, node):
    names = {item.name for item in scene.blender_to_json_settings.export.ignore_layers}
    return node.blender_name in names or (node.parsed is not None and node.name in names)


def _label(node):
    if node.status == planner.CONTENT:
        return node.blender_name, 'in render'
    if node.status == planner.HOIST:
        return node.blender_name, 'contents only'
    if node.status == planner.IGNORED:
        extra = f' ({node.hidden_count} inside)' if node.hidden_count else ''
        return node.blender_name, (node.reason or 'ignored') + extra
    text = f'{LETTERS[node.category]} {node.name}'
    if node.type:
        text += f' · {node.type}'
    notes = []
    if node.renders:
        notes.append('render')
    if node.frames:
        notes.append(f'{len(node.frames)} frames')
    if node.holdout:
        notes.append('ground')
    if node.attributes:
        notes.append(', '.join(f'{k}:{v}' for k, v in list(node.attributes.items())[:3]))
    return text, '  '.join(notes)


def _icon(node):
    if node.warning:
        return 'ERROR'
    if node.status == planner.EXPORT:
        return CATEGORY_ICONS.get(node.category, 'DOT')
    if node.status == planner.CONTENT:
        return 'DOT'
    if node.kind == 'collection':
        return 'OUTLINER_COLLECTION'
    return 'OBJECT_DATA'


def draw_tree(layout, scene, nodes, depth=0, budget=None):
    budget = budget if budget is not None else [MAX_ROWS]
    for node in nodes:
        if budget[0] <= 0:
            layout.label(text=f'… more items not shown (limit {MAX_ROWS})', icon='INFO')
            return
        budget[0] -= 1
        children = list(node.frames) + list(node.children)
        row = layout.row(align=True)
        for _ in range(depth):
            row.separator(factor=1.5)
        if children:
            collapsed = _key(node) in _collapsed
            op = row.operator('blender_to_json.preview_toggle', text='', emboss=False,
                              icon='TRIA_RIGHT' if collapsed else 'TRIA_DOWN')
            op.key = _key(node)
        else:
            row.label(text='', icon='BLANK1')

        text, note = _label(node)
        sub = row.row(align=True)
        sub.active = node.status in (planner.EXPORT, planner.CONTENT) or bool(children)
        sub.alert = bool(node.warning)
        op = sub.operator('blender_to_json.preview_select', text=text, icon=_icon(node), emboss=False)
        op.kind, op.name = node.kind, node.blender_name
        if node.warning:
            note = node.warning
        if note:
            sub.label(text=note)

        if node.status != planner.CONTENT and node.parsed is not None:
            excluded = _ignored_by_user(scene, node)
            op = row.operator('blender_to_json.preview_exclude', text='', emboss=False,
                              icon='CHECKBOX_DEHLT' if excluded else 'CHECKBOX_HLT')
            op.name = node.blender_name

        if children and _key(node) not in _collapsed:
            draw_tree(layout, scene, children, depth + 1, budget)


class B2J_OT_preview_toggle(bpy.types.Operator):
    bl_idname = 'blender_to_json.preview_toggle'
    bl_label = 'Expand/Collapse'
    bl_description = 'Show or hide what is inside'
    bl_options = {'INTERNAL'}

    key: StringProperty()

    def execute(self, context):
        _collapsed.symmetric_difference_update({self.key})
        context.area.tag_redraw()
        return {'FINISHED'}


class B2J_OT_preview_select(bpy.types.Operator):
    bl_idname = 'blender_to_json.preview_select'
    bl_label = 'Select'
    bl_description = 'Select this object, or make this collection active'
    bl_options = {'INTERNAL', 'UNDO'}

    kind: StringProperty()
    name: StringProperty()

    def execute(self, context):
        if self.kind == 'object':
            obj = context.scene.objects.get(self.name)
            if obj is None:
                return {'CANCELLED'}
            for other in context.selected_objects:
                other.select_set(False)
            if obj.visible_get():
                obj.select_set(True)
            context.view_layer.objects.active = obj
        else:
            layer_collection = _find_layer_collection(context.view_layer.layer_collection, self.name)
            if layer_collection is None:
                return {'CANCELLED'}
            context.view_layer.active_layer_collection = layer_collection
        return {'FINISHED'}


def _find_layer_collection(layer_collection, name):
    if layer_collection.collection.name == name:
        return layer_collection
    for child in layer_collection.children:
        found = _find_layer_collection(child, name)
        if found is not None:
            return found
    return None


class B2J_OT_preview_exclude(bpy.types.Operator):
    bl_idname = 'blender_to_json.preview_exclude'
    bl_label = 'Include/Exclude'
    bl_description = 'Include or exclude this item from the export (stored in ignoreLayers)'
    bl_options = {'INTERNAL', 'UNDO'}

    name: StringProperty()

    def execute(self, context):
        items = context.scene.blender_to_json_settings.export.ignore_layers
        for index, item in enumerate(items):
            if item.name == self.name:
                items.remove(index)
                break
        else:
            items.add().name = self.name
        sync.write_scene(context.scene)
        return {'FINISHED'}


classes = (B2J_OT_preview_toggle, B2J_OT_preview_select, B2J_OT_preview_exclude)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
