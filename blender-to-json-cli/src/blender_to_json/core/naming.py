"""Layer-name parsing, shared with psd-to-json.

A name has two to four pipe-separated parts:

    category | name                      -> 1 pipe
    category | name | attributes         -> 2 pipes
    category | name | type | attributes  -> 3 pipes

Names without a pipe (or with an unknown category) are ignored.

This module is pure Python so it can run both inside Blender and in the
system interpreter.
"""

import re

CATEGORY_MAP = {
    'G': 'group',
    'S': 'sprite',
    'T': 'tileset',
    'P': 'point',
    'Z': 'zone',
}

# Blender forces unique names by appending ".001", ".002", ... Stripping the
# suffix lets several objects share one exported name, the way identically
# named layers do in a PSD.
# Only the exact three-digit form is stripped, so a trailing float attribute
# such as `scale:1.5` survives (write `scale:1.500,` if you really need three
# decimals at the very end of a name).
_NUMERIC_SUFFIX = re.compile(r'\.\d{3}$')


def strip_numeric_suffix(name):
    return _NUMERIC_SUFFIX.sub('', name)


def _split_top_level(text, separator):
    """Split on `separator`, ignoring separators inside quotes or brackets."""
    parts = []
    current = ''
    quote_open = False
    depth = 0
    for char in text:
        if char == '"':
            quote_open = not quote_open
        elif not quote_open and char in '[{':
            depth += 1
        elif not quote_open and char in ']}':
            depth -= 1
        if char == separator and not quote_open and depth == 0:
            parts.append(current)
            current = ''
        else:
            current += char
    parts.append(current)
    return parts


def parse_value(value):
    value = value.strip()
    if not value:
        return None
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        return value[1:-1].replace('\\"', '"')
    if value.startswith('[') and value.endswith(']'):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_value(v) for v in _split_top_level(inner, ',')]
    if value.startswith('{') and value.endswith('}'):
        inner = value[1:-1].strip()
        obj = {}
        if inner:
            for item in _split_top_level(inner, ','):
                if ':' in item:
                    key, val = item.split(':', 1)
                    obj[key.strip().strip('"')] = parse_value(val)
        return obj
    lowered = value.lower()
    if lowered == 'true':
        return True
    if lowered == 'false':
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def parse_attribute_string(attr_string):
    """Parse `key:value, flag, other:[1, 2]` into a dict (or None if empty)."""
    attr_string = attr_string.strip()
    if not attr_string:
        return None

    attributes = {}
    for item in _split_top_level(attr_string, ','):
        item = item.strip()
        if not item:
            continue
        if ':' in item:
            key, value = item.split(':', 1)
            key = key.strip()
            parsed = parse_value(value)
            if key and parsed is not None:
                attributes[key] = parsed
        else:
            attributes[item] = True
    return attributes or None


def parse_layer_name(layer_name, strip_suffix=True):
    """Parse a Blender object/collection name.

    Returns a dict with `category`, `name`, optional `type` and
    `attributes`, or None if the name does not follow the scheme.
    """
    if strip_suffix:
        layer_name = strip_numeric_suffix(layer_name.strip())
    parts = [part.strip() for part in layer_name.split('|')]
    if len(parts) < 2 or len(parts) > 4:
        return None

    category = CATEGORY_MAP.get(parts[0].upper())
    if category is None:
        return None

    raw_name = parts[1]
    if not raw_name:
        return None

    result = {'category': category, 'name': raw_name, 'attributes': {}}

    tail = None
    if len(parts) == 3:
        tail = parts[2]
    elif len(parts) == 4:
        if parts[2]:
            result['type'] = parts[2]
        tail = parts[3]

    if tail is not None:
        attributes = parse_attribute_string(tail)
        if attributes:
            result['attributes'] = attributes

    return result
