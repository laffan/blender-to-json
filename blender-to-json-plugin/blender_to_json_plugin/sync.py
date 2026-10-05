"""Mirror parameters and export settings into a plain JSON scene property.

The blender-to-json CLI reads `scene["blender_to_json"]` headlessly, without
this plugin installed, so the mirror has to be ordinary custom-property data
rather than add-on PropertyGroup storage (which Blender 5.0+ no longer exposes
through `scene[...]`). The format is documented in core/parameters.py.
"""

import json

import bpy
from bpy.app.handlers import persistent

from .core.parameters import FORMAT_VERSION, SCENE_PROPERTY

# (PropertyGroup attribute, CLI config key, kind)
SETTINGS = [
    ('output_dir', 'output_dir', 'value'),
    ('camera', 'camera', 'id'),
    ('render_bounds', 'renderBounds', 'value'),
    ('render_padding', 'renderPadding', 'value'),
    ('cast_shadows', 'castShadowsFromHidden', 'value'),
    ('holdout_collection', 'holdoutCollection', 'id'),
    ('base_tile', 'baseTile', 'id'),
    ('tile_width', 'tileWidth', 'value'),
    ('snap_to_grid', 'snapToTileGrid', 'value'),
    ('tile_slice_size', 'tile_slice_size', 'value'),
    ('psd', 'psd', 'value'),
    ('pass_through', 'passThroughUnnamedCollections', 'value'),
    ('ignore_layers', 'ignoreLayers', 'names'),
]


def serialize_settings(settings):
    """Settings changed from their defaults, as CLI config keys."""
    out = {}
    rna = settings.bl_rna.properties
    for attr, key, kind in SETTINGS:
        value = getattr(settings, attr)
        if kind == 'id':
            if value is not None:
                out[key] = value.name
        elif kind == 'names':
            names = [item.name for item in value if item.name]
            if names:
                out[key] = names
        elif value != rna[attr].default:
            out[key] = value
    return out


def _existing_constants(scene):
    try:
        data = json.loads(scene.get(SCENE_PROPERTY) or '{}')
    except (TypeError, ValueError):
        return {}
    return {name: entry for name, entry in (data.get('parameters') or {}).items()
            if not (isinstance(entry, dict) and entry.get('path'))}


def serialize(scene):
    root = scene.blender_to_json_settings
    # Constants written by scripts aren't shown in the panel; keep them.
    params = _existing_constants(scene)
    for param in root.parameters:
        if not param.name:
            continue
        entry = {'id_type': param.id_type, 'id_name': param.id_name, 'path': param.path,
                 'value': param.value()}
        if param.description:
            entry['description'] = param.description
        params[param.name] = entry
    return {'version': FORMAT_VERSION, 'parameters': params, 'settings': serialize_settings(root.export)}


def write_scene(scene):
    if not isinstance(scene, bpy.types.Scene) or not hasattr(scene, 'blender_to_json_settings'):
        return
    for param in scene.blender_to_json_settings.parameters:
        param.refresh_name()
    text = json.dumps(serialize(scene), indent=1)
    if scene.get(SCENE_PROPERTY) != text:
        scene[SCENE_PROPERTY] = text


def read_scene(scene):
    """Load tracked parameters from the JSON mirror into the UI list.

    Used when the mirror was written by a script or another copy of the
    plugin and the list is empty. Constants (entries without a path) can't be
    shown in the list and stay in the mirror only.
    """
    raw = scene.get(SCENE_PROPERTY)
    if not raw:
        return 0
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return 0
    root = scene.blender_to_json_settings
    count = 0
    for name, entry in (data.get('parameters') or {}).items():
        if not isinstance(entry, dict) or not entry.get('path'):
            continue
        param = root.parameters.add()
        param.name = name
        param.id_type = entry.get('id_type', '')
        param.id_name = entry.get('id_name', '')
        param.path = entry['path']
        param.id_ref = param.target()
        param.description = entry.get('description', '')
        count += 1
    return count


@persistent
def on_save_pre(*_args):
    # Tracked values, renamed datablocks and so on change without our update
    # callbacks firing, so refresh every scene's mirror before writing the file.
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
