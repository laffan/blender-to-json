"""Read parameters stored by the companion plugin and resolve `@name` references.

The plugin mirrors its parameter list into a plain JSON string stored as a
scene custom property, so it can be read headlessly without the plugin
installed:

    scene["blender_to_json"] = '{"version": 1, "parameters": {
        "mainCam": {"type": "CAMERA", "value": "Camera.001"},
        "tileSize": {"type": "INT", "value": 512}
    }}'
"""

import json

SCENE_PROPERTY = 'blender_to_json'


class ParameterError(Exception):
    pass


def read_scene_parameters(scene):
    """Return {name: {"type": ..., "value": ...}} stored in `scene`."""
    raw = scene.get(SCENE_PROPERTY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise ParameterError(f"scene property '{SCENE_PROPERTY}' is not valid JSON: {e}")
    params = data.get('parameters', {})
    if not isinstance(params, dict):
        raise ParameterError(f"scene property '{SCENE_PROPERTY}' has no 'parameters' object")
    return params


def merge_parameters(scene_params, overrides):
    """Flatten scene parameters to {name: value}, then apply overrides.

    `overrides` is a plain {name: value} dict (from the config's
    `parameters` object and the CLI's --param flags).
    """
    values = {name: entry.get('value') if isinstance(entry, dict) else entry
              for name, entry in scene_params.items()}
    values.update(overrides or {})
    return values


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
