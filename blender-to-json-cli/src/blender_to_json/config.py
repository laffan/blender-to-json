"""Configuration loading and command-line overrides."""

import copy
import json
import os

CONFIG_FILENAME = 'blender-to-json.config'

DEFAULTS = {
    # Files
    'output_dir': 'output',
    'name': None,
    'blend_files': [],
    'blender_path': None,
    'factoryStartup': True,
    'enableAutoexec': False,

    # Scene / camera / render
    'scene': None,
    'camera': None,
    'resolution': None,
    'resolutionPercentage': None,
    'renderEngine': None,
    'samples': None,
    'renderBounds': 'object',
    'renderPadding': 2,
    'maxRenderSize': 16384,
    'castShadowsFromHidden': False,

    # Tile tools (ported from blender-2d-tile-tools)
    'baseTile': None,
    'tileWidth': None,
    'snapToTileGrid': False,
    'holdoutCollection': None,
    'psd': False,

    # Traversal
    'only': [],
    'ignoreLayers': [],
    'passThroughUnnamedCollections': False,
    'customPropertiesAsAttributes': True,

    # Output (same names as psd-to-json where they overlap)
    'trimTransparent': True,
    'tile_slice_size': 512,
    'tile_scaled_versions': [],
    'jpgQuality': 85,
    'pngQualityRange': {'low': 45, 'high': 65},
    'optimizePngs': True,
    'atlasPadding': 2,

    # Behaviour
    'generateOnSave': False,
    'metadataOnly': False,

    # Overrides for parameters stored in the blend file (see the plugin)
    'parameters': {},
}


class ConfigError(Exception):
    pass


def parse_cli_value(text):
    """Interpret a --set/--param value: JSON if it parses, else a string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def parse_assignment(text, flag):
    if '=' not in text:
        raise ConfigError(f"{flag} expects key=value, got '{text}'")
    key, value = text.split('=', 1)
    key = key.strip()
    if not key:
        raise ConfigError(f"{flag} expects key=value, got '{text}'")
    return key, parse_cli_value(value)


def set_dotted(config, dotted_key, value):
    """Set `a.b.c` style keys, creating nested objects as needed."""
    keys = dotted_key.split('.')
    target = config
    for key in keys[:-1]:
        if not isinstance(target.get(key), dict):
            target[key] = {}
        target = target[key]
    target[keys[-1]] = value


def find_config(explicit_path=None, cwd=None):
    if explicit_path:
        if not os.path.isfile(explicit_path):
            raise ConfigError(f"config file not found: {explicit_path}")
        return os.path.abspath(explicit_path)
    candidate = os.path.join(cwd or os.getcwd(), CONFIG_FILENAME)
    return candidate if os.path.isfile(candidate) else None


def load_config(path=None, sets=(), params=()):
    """Build the effective config.

    Precedence (lowest to highest): defaults, config file, --set flags.
    `--param` flags are merged into config['parameters'].
    Returns (config, base_dir, explicit) where base_dir is the directory that
    relative paths in the config are resolved against and explicit is the set
    of top-level keys set by the config file or --set (these take precedence
    over settings stored in the .blend by the plugin).
    """
    config = copy.deepcopy(DEFAULTS)
    base_dir = os.getcwd()
    explicit = set()
    if path:
        try:
            with open(path) as f:
                user = json.load(f)
        except ValueError as e:
            raise ConfigError(f"invalid JSON in {path}: {e}")
        if not isinstance(user, dict):
            raise ConfigError(f"{path} must contain a JSON object")
        # psd-to-json habit: accept "files" as an alias.
        if 'files' in user and 'blend_files' not in user:
            user['blend_files'] = user.pop('files')
        config.update(user)
        explicit.update(user)
        base_dir = os.path.dirname(os.path.abspath(path))

    for text in sets:
        key, value = parse_assignment(text, '--set')
        set_dotted(config, key, value)
        explicit.add(key.split('.')[0])

    config['parameters'] = dict(config.get('parameters') or {})
    for text in params:
        key, value = parse_assignment(text, '--param')
        config['parameters'][key] = value

    if config.get('renderBounds') not in ('object', 'frame'):
        raise ConfigError("renderBounds must be 'object' or 'frame'")
    return config, base_dir, explicit


def resolve_path(path, base_dir):
    return os.path.normpath(os.path.join(base_dir, os.path.expanduser(path)))
