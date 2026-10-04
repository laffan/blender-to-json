import re

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)

from . import sync

NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

PARAMETER_TYPES = [
    ('STRING', 'Text', 'A text value', 'SORTALPHA', 0),
    ('INT', 'Integer', 'A whole number', 'LINENUMBERS_ON', 1),
    ('FLOAT', 'Number', 'A decimal number', 'DRIVER_DISTANCE', 2),
    ('BOOL', 'Toggle', 'True or false', 'CHECKBOX_HLT', 3),
    ('CAMERA', 'Camera', 'A camera object (its name is passed to the CLI)', 'CAMERA_DATA', 4),
    ('OBJECT', 'Object', 'Any object (its name is passed to the CLI)', 'OBJECT_DATA', 5),
    ('COLLECTION', 'Collection', 'A collection (its name is passed to the CLI)', 'OUTLINER_COLLECTION', 6),
]

TYPE_ICONS = {item[0]: item[3] for item in PARAMETER_TYPES}


def _on_change(self, context):
    sync.write_scene(self.id_data)


def _is_camera(_self, obj):
    return obj.type == 'CAMERA'


class B2J_Parameter(bpy.types.PropertyGroup):
    # `name` is built into PropertyGroup; redefine it to get an update callback.
    name: StringProperty(
        name='Name',
        description='Refer to this parameter as @name in the config file or on the command line',
        default='param',
        update=_on_change)
    param_type: EnumProperty(name='Type', items=PARAMETER_TYPES, default='STRING', update=_on_change)
    description: StringProperty(name='Description', description='Optional note for yourself and collaborators',
                                update=_on_change)

    value_string: StringProperty(name='Value', update=_on_change)
    value_int: IntProperty(name='Value', update=_on_change)
    value_float: FloatProperty(name='Value', update=_on_change)
    value_bool: BoolProperty(name='Value', update=_on_change)
    value_camera: PointerProperty(name='Value', type=bpy.types.Object, poll=_is_camera, update=_on_change)
    value_object: PointerProperty(name='Value', type=bpy.types.Object, update=_on_change)
    value_collection: PointerProperty(name='Value', type=bpy.types.Collection, update=_on_change)

    @property
    def value_attr(self):
        return 'value_' + self.param_type.lower()

    def get_value(self):
        value = getattr(self, self.value_attr)
        if isinstance(value, bpy.types.ID):
            return value.name
        return value

    def set_value(self, value):
        """Set from a JSON value; ID types are looked up by name."""
        lookup = {
            'CAMERA': bpy.data.objects,
            'OBJECT': bpy.data.objects,
            'COLLECTION': bpy.data.collections,
        }.get(self.param_type)
        if lookup is not None:
            value = lookup.get(value) if value else None
        if value is not None:
            setattr(self, self.value_attr, value)

    def problem(self, scene_settings):
        """Return a short description of what is wrong with this parameter, or None."""
        if not NAME_PATTERN.match(self.name):
            return 'Use letters, digits and underscores only, not starting with a digit'
        if sum(1 for p in scene_settings.parameters if p.name == self.name) > 1:
            return 'Another parameter has the same name'
        if self.param_type in ('CAMERA', 'OBJECT', 'COLLECTION') and getattr(self, self.value_attr) is None:
            return 'No value selected'
        return None


class B2J_SceneSettings(bpy.types.PropertyGroup):
    parameters: CollectionProperty(type=B2J_Parameter)
    active_index: IntProperty(default=0)


classes = (B2J_Parameter, B2J_SceneSettings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blender_to_json_settings = PointerProperty(type=B2J_SceneSettings)


def unregister():
    del bpy.types.Scene.blender_to_json_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
