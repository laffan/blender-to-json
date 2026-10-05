"""Parameters and export settings stored in a .blend by the companion plugin.

The plugin mirrors its data into a plain JSON string stored as a scene custom
property, so the CLI can read it headlessly without the plugin installed:

    scene["blender_to_json"] = '{
      "version": 2,
      "parameters": {
        "width":  {"id_type": "scenes", "id_name": "Scene",
                   "path": "render.resolution_x", "value": 1920},
        "sunPower": {"id_type": "lights", "id_name": "Sun", "path": "energy", "value": 3.0},
        "level": {"value": 2}
      },
      "settings": {"output_dir": "//assets", "baseTile": "Tile"}
    }'

A parameter with `id_type`/`id_name`/`path` *tracks* a Blender property:
`--param width=1024` writes the property before exporting and `@width` reads
its current value. A parameter with only `value` is a constant.
"""

import json

SCENE_PROPERTY = 'blender_to_json'
FORMAT_VERSION = 2


class ParameterError(Exception):
    pass


def read_scene_data(scene):
    raw = scene.get(SCENE_PROPERTY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise ParameterError(f"scene property '{SCENE_PROPERTY}' is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise ParameterError(f"scene property '{SCENE_PROPERTY}' must be a JSON object")
    return data


def read_scene_parameters(scene):
    """Return {name: entry} stored in `scene`."""
    params = read_scene_data(scene).get('parameters', {})
    if not isinstance(params, dict):
        raise ParameterError(f"scene property '{SCENE_PROPERTY}' has an invalid 'parameters' value")
    return {name: entry if isinstance(entry, dict) else {'value': entry} for name, entry in params.items()}


def read_scene_settings(scene):
    settings = read_scene_data(scene).get('settings', {})
    return settings if isinstance(settings, dict) else {}


def is_tracked(entry):
    return isinstance(entry, dict) and bool(entry.get('path')) and bool(entry.get('id_type'))


def apply_parameters(entries, overrides):
    """Write overrides into tracked properties, then read every parameter.

    Returns (values, problems): values is {name: value}; problems lists
    tracked parameters whose datablock no longer exists.
    Raises ParameterError if an override can't be applied.
    """
    from . import datapath

    overrides = overrides or {}
    for name, value in overrides.items():
        entry = entries.get(name)
        if not is_tracked(entry):
            continue
        id_block = datapath.find_id(entry['id_type'], entry['id_name'])
        if id_block is None:
            raise ParameterError(f"@{name} tracks {entry['id_type']}[{entry['id_name']!r}], which doesn't exist")
        try:
            datapath.set_value(id_block, entry['path'], value)
        except datapath.DataPathError as e:
            raise ParameterError(f"can't set @{name}: {e}")

    values = {}
    problems = []
    for name, entry in entries.items():
        if is_tracked(entry):
            id_block = datapath.find_id(entry['id_type'], entry['id_name'])
            if id_block is None:
                problems.append(f"@{name} tracks {entry['id_type']}[{entry['id_name']!r}], which doesn't "
                                "exist; using the last saved value")
                values[name] = entry.get('value')
                continue
            try:
                values[name] = datapath.get_value(id_block, entry['path'])
            except datapath.DataPathError as e:
                problems.append(f"@{name}: {e}; using the last saved value")
                values[name] = entry.get('value')
        else:
            values[name] = entry.get('value')
    for name, value in overrides.items():
        if not is_tracked(entries.get(name)):
            values[name] = value  # a constant, or a new name defined on the command line
    return values, problems


def resolve_references(value, params, where='config'):
    """Replace `"@name"` strings (recursively) with parameter values.

    `"@@text"` escapes to the literal string `"@text"`.
    """
    if isinstance(value, str):
        if value.startswith('@@'):
            return value[1:]
        if value.startswith('@') and len(value) > 1:
            name = value[1:]
            if name not in params:
                known = ', '.join(sorted(params)) or 'none defined'
                raise ParameterError(f"{where}: unknown parameter '@{name}' (available: {known})")
            return params[name]
        return value
    if isinstance(value, list):
        return [resolve_references(v, params, f'{where}[{i}]') for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: resolve_references(v, params, f'{where}.{k}') for k, v in value.items()}
    return value
