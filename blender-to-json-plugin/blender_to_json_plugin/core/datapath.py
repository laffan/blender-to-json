"""Address any Blender property by datablock + data path, and read/write it.

A tracked parameter stores where a property lives, e.g.

    {"id_type": "scenes", "id_name": "Scene", "path": "render.resolution_x"}

which is what Blender's "Copy Full Data Path" produces as
`bpy.data.scenes["Scene"].render.resolution_x`.

Parsing is pure Python; reading and writing need bpy (imported lazily).
"""

import re

_FULL_PATH = re.compile(
    r'''^bpy\.data\.(?P<type>\w+)\[(?P<q>["'])(?P<name>(?:\\.|(?!(?P=q)).)*)(?P=q)'''
    r'''(?:\s*,\s*(?P<q2>["'])(?P<lib>(?:\\.|(?!(?P=q2)).)*)(?P=q2))?\](?P<rest>.*)$''')

_TOKEN = re.compile(
    r'''\.?(?P<attr>[A-Za-z_]\w*)|\[(?P<index>-?\d+)\]|\[(?P<q>["'])(?P<key>(?:\\.|(?!(?P=q)).)*)(?P=q)\]''')

ID_COLLECTIONS = {
    'Object': 'objects', 'Collection': 'collections', 'Material': 'materials', 'World': 'worlds',
    'Camera': 'cameras', 'Light': 'lights', 'Image': 'images', 'NodeTree': 'node_groups',
    'Mesh': 'meshes', 'Scene': 'scenes', 'Texture': 'textures', 'Action': 'actions',
    'Text': 'texts', 'Curve': 'curves',
}

_AXES = 'XYZW'


class DataPathError(Exception):
    pass


def _unescape(text):
    return re.sub(r'\\(.)', r'\1', text)


def parse_full_path(text):
    """Split `bpy.data.objects["Cube"].location[0]` into
    ("objects", "Cube", "location[0]"). Raises DataPathError."""
    match = _FULL_PATH.match(text.strip())
    if not match or not match.group('rest'):
        raise DataPathError(f"not a property path: {text!r}")
    rest = match.group('rest')
    if rest.startswith('.'):
        rest = rest[1:]
    tokenize(rest)  # validate
    return match.group('type'), _unescape(match.group('name')), rest


def tokenize(path):
    """Split a data path into ('attr', name) / ('index', int) / ('key', str) tokens."""
    tokens = []
    pos = 0
    while pos < len(path):
        match = _TOKEN.match(path, pos)
        if not match or match.end() == pos or (match.group('attr') and pos > 0 and path[pos] != '.'):
            raise DataPathError(f"can't parse data path {path!r} at {path[pos:]!r}")
        if match.group('attr'):
            tokens.append(('attr', match.group('attr')))
        elif match.group('index') is not None:
            tokens.append(('index', int(match.group('index'))))
        else:
            tokens.append(('key', _unescape(match.group('key'))))
        pos = match.end()
    if not tokens:
        raise DataPathError('empty data path')
    return tokens


def join(tokens):
    out = ''
    for kind, value in tokens:
        if kind == 'attr':
            out += ('.' if out else '') + value
        elif kind == 'index':
            out += f'[{value}]'
        else:
            out += '["' + value.replace('\\', '\\\\').replace('"', '\\"') + '"]'
    return out


def suggest_name(path):
    """A parameter name for a data path: render.resolution_x -> resolutionX."""
    tokens = tokenize(path)
    kind, value = tokens[-1]
    suffix = ''
    if kind == 'index':
        suffix = _AXES[value] if 0 <= value < 4 else str(value)
        kind, value = tokens[-2] if len(tokens) > 1 else ('attr', 'value')
    if kind == 'key':
        value = re.sub(r'\W+', '_', value)
    parts = [p for p in str(value).split('_') if p]
    name = (parts[0] + ''.join(p[:1].upper() + p[1:] for p in parts[1:])) if parts else 'param'
    if not re.match(r'[A-Za-z_]', name):
        name = 'p' + name
    return name + suffix


# ---------------------------------------------------------------------- bpy side

def find_id(id_type, id_name):
    import bpy
    collection = getattr(bpy.data, id_type, None)
    if collection is None:
        return None
    return collection.get(id_name)


def full_path(id_type, id_name, path):
    name = id_name.replace('\\', '\\\\').replace('"', '\\"')
    sep = '' if path.startswith('[') else '.'
    return f'bpy.data.{id_type}["{name}"]{sep}{path}'


def _resolve_tokens(owner, tokens):
    for kind, value in tokens:
        if kind == 'attr':
            owner = getattr(owner, value)
        else:
            owner = owner[value]
    return owner


def ui_target(id_block, path):
    """Return (owner, property, index) for drawing the property with
    `layout.prop(owner, property, index=index)`."""
    tokens = tokenize(path)
    index = -1
    if tokens[-1][0] == 'index' and len(tokens) > 1 and tokens[-2][0] == 'attr':
        index = tokens[-1][1]
        tokens = tokens[:-1]
    kind, value = tokens[-1]
    owner = _resolve_tokens(id_block, tokens[:-1])
    prop = value if kind == 'attr' else '["' + value.replace('"', '\\"') + '"]'
    return owner, prop, index


def describe(id_block, path):
    """Human-readable label, e.g. 'Scene › Resolution X'."""
    tokens = tokenize(path)
    label = None
    try:
        index = None
        if tokens[-1][0] == 'index' and len(tokens) > 1:
            index = tokens[-1][1]
            tokens = tokens[:-1]
        kind, value = tokens[-1]
        if kind == 'attr':
            owner = _resolve_tokens(id_block, tokens[:-1])
            rna = owner.bl_rna.properties.get(value)
            label = rna.name if rna is not None and rna.name else value
        else:
            label = value
        if index is not None:
            label += f' {_AXES[index]}' if 0 <= index < 4 else f' [{index}]'
    except (AttributeError, KeyError, IndexError, TypeError):
        label = path
    return f'{id_block.name} › {label}'


def to_json(value):
    """Convert a property value to something json.dumps accepts."""
    import bpy
    if isinstance(value, bpy.types.ID):
        return value.name
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, 'to_dict'):
        return value.to_dict()
    if hasattr(value, 'to_list'):
        return value.to_list()
    try:
        items = list(value)
    except TypeError:
        return str(value)
    return [to_json(v) for v in items]


def get_value(id_block, path):
    try:
        return to_json(id_block.path_resolve(path))
    except ValueError as e:
        raise DataPathError(f"{id_block.name}: can't read {path!r} ({e})")


def set_value(id_block, path, value):
    """Set the property at `path` from a JSON value.

    ID pointers take a datablock name; enum flags take a list; arrays take a
    list (or a single number when the path ends in an index).
    """
    tokens = tokenize(path)
    kind, last = tokens[-1]
    try:
        owner = _resolve_tokens(id_block, tokens[:-1])
        if kind == 'attr':
            rna = owner.bl_rna.properties.get(last) if hasattr(owner, 'bl_rna') else None
            if rna is not None and rna.type == 'POINTER':
                value = _lookup_id(rna, value)
            elif rna is not None and rna.type == 'ENUM' and rna.is_enum_flag:
                value = set(value if isinstance(value, (list, tuple, set)) else [value])
            elif rna is not None and rna.type == 'FLOAT' and isinstance(value, int) and not rna.is_array:
                value = float(value)
            setattr(owner, last, value)
        else:
            owner[last] = value
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as e:
        raise DataPathError(f"{id_block.name}: can't set {path!r} to {value!r} ({e})")


def _lookup_id(rna, value):
    import bpy
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise TypeError('expected a datablock name')
    type_name = rna.fixed_type.identifier
    collection = ID_COLLECTIONS.get(type_name)
    if collection is None:
        raise TypeError(f"don't know where to find {type_name} datablocks")
    found = getattr(bpy.data, collection).get(value)
    if found is None:
        raise ValueError(f"no {type_name} named {value!r}")
    return found


def locate(id_block, path):
    """Return (id_type, id_name, path) for a property found on `id_block`.

    Embedded datablocks (a material's node tree, a scene's compositor) aren't
    in bpy.data, so they're addressed through their owner instead.
    """
    import bpy
    for attr in ID_COLLECTIONS.values():
        collection = getattr(bpy.data, attr, None)
        if collection is not None and collection.get(id_block.name) == id_block:
            return attr, id_block.name, path
    for attr in ('materials', 'worlds', 'lights', 'scenes', 'textures', 'linestyles'):
        for owner in getattr(bpy.data, attr, ()):
            if getattr(owner, 'node_tree', None) == id_block:
                return attr, owner.name, 'node_tree' + ('' if path.startswith('[') else '.') + path
    for attr in dir(bpy.data):
        collection = getattr(bpy.data, attr, None)
        if isinstance(collection, bpy.types.bpy_prop_collection):
            try:
                if collection.get(id_block.name) == id_block:
                    return attr, id_block.name, path
            except (TypeError, AttributeError):
                continue
    raise DataPathError(f"can't find where {id_block.name!r} lives in bpy.data")
