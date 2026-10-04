"""Mirror the parameter list into a plain JSON scene property.

The blender-to-json CLI reads `scene["blender_to_json"]` headlessly, without
this plugin installed, so the mirror has to be ordinary custom-property data
rather than add-on PropertyGroup storage (which Blender 5.0+ no longer exposes
through `scene[...]`).

Format:
    {"version": 1,
     "parameters": {"mainCam": {"type": "CAMERA", "value": "Camera", "description": ""}}}
"""

import json

import bpy
from bpy.app.handlers import persistent

SCENE_PROPERTY = 'blender_to_json'
FORMAT_VERSION = 1


def serialize(scene):
    settings = scene.blender_to_json_settings
    params = {}
    for param in settings.parameters:
        if not param.name or param.name in params:
            continue
        entry = {'type': param.param_type, 'value': param.get_value()}
        if param.description:
            entry['description'] = param.description
        params[param.name] = entry
    return {'version': FORMAT_VERSION, 'parameters': params}


def write_scene(scene):
    if not isinstance(scene, bpy.types.Scene):
        return
    text = json.dumps(serialize(scene), indent=1)
    if scene.get(SCENE_PROPERTY) != text:
        scene[SCENE_PROPERTY] = text


def read_scene(scene):
    """Load parameters from the JSON mirror into the UI list.

    Used when a file's mirror was written by a script or by another copy of
    the plugin and the UI list is empty.
    """
    raw = scene.get(SCENE_PROPERTY)
    if not raw:
        return 0
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return 0
    settings = scene.blender_to_json_settings
    count = 0
    for name, entry in data.get('parameters', {}).items():
        if not isinstance(entry, dict):
            entry = {'value': entry}
        param = settings.parameters.add()
        param.name = name
        param_type = str(entry.get('type', 'STRING')).upper()
        param.param_type = param_type if param_type in {'STRING', 'INT', 'FLOAT', 'BOOL', 'CAMERA', 'OBJECT',
                                                         'COLLECTION'} else 'STRING'
        param.description = entry.get('description', '')
        param.set_value(entry.get('value'))
        count += 1
    return count


@persistent
def on_save_pre(*_args):
    # ID pointers can be renamed without triggering our update callbacks, so
    # refresh every scene's mirror right before the file is written.
    for scene in bpy.data.scenes:
        write_scene(scene)


@persistent
def on_load_post(*_args):
    for scene in bpy.data.scenes:
        if not scene.blender_to_json_settings.parameters and scene.get(SCENE_PROPERTY):
            read_scene(scene)


def register():
    bpy.app.handlers.save_pre.append(on_save_pre)
    bpy.app.handlers.load_post.append(on_load_post)


def unregister():
    for handlers, func in ((bpy.app.handlers.save_pre, on_save_pre),
                           (bpy.app.handlers.load_post, on_load_post)):
        if func in handlers:
            handlers.remove(func)
