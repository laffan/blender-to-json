"""Layered PSD output (ported from blender-2d-tile-tools), needs psd-tools.

Layers are named with the psd-to-json scheme, so the PSD can be edited in
Photoshop and fed straight back into psd-to-json.
"""

import json

from PIL import Image, ImageDraw

LETTERS = {'group': 'G', 'sprite': 'S', 'tileset': 'T', 'point': 'P', 'zone': 'Z'}


def _format_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return '[' + ', '.join(_format_value(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{' + ', '.join(f'{k}: {_format_value(v)}' for k, v in value.items()) + '}'
    return json.dumps(str(value))


def layer_name(layer):
    """Rebuild a `C | name | type | attributes` layer name."""
    parts = [LETTERS[layer['category']], layer['name']]
    attributes = layer.get('attributes') or {}
    attr_text = ', '.join(k if v is True else f'{k}:{_format_value(v)}' for k, v in attributes.items())
    if layer.get('type'):
        # psd-to-json needs the trailing pipe to read the third part as a type.
        return ' | '.join(parts + [layer['type']]) + (f' | {attr_text}' if attr_text else ' |')
    if attr_text:
        parts.append(attr_text)
    return ' | '.join(parts)


def _marker(size=9):
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.line((0, 0, size - 1, size - 1), fill=(255, 0, 255, 255))
    draw.line((0, size - 1, size - 1, 0), fill=(255, 0, 255, 255))
    return image


def _zone_image(layer):
    points = layer.get('points') or []
    left, top = layer['x'], layer['y']
    width, height = max(1, round(layer['width'])), max(1, round(layer['height']))
    image = Image.new('RGBA', (width + 1, height + 1), (0, 0, 0, 0))
    if len(points) >= 3:
        ImageDraw.Draw(image).polygon([(p['x'] - left, p['y'] - top) for p in points],
                                      fill=(0, 160, 255, 80), outline=(0, 160, 255, 255))
    return image


def write_psd(data, images, path):
    try:
        from psd_tools import PSDImage
    except ImportError:
        raise RuntimeError("PSD output needs psd-tools: pip install 'blender-to-json[psd]'")

    psd = PSDImage.new(mode='RGBA', size=(data['width'], data['height']))

    def add(container, layers):
        # psd-tools appends upwards: the first layer added ends up at the bottom.
        for layer in sorted(layers, key=lambda l: l.get('initialDepth', 0)):
            category = layer['category']
            name = layer_name(layer)
            if category == 'group' or layer.get('type') in ('atlas', 'spritesheet'):
                group = container.create_group(name=name)
                if layer.get('type') in ('atlas', 'spritesheet'):
                    for instance in layer.get('instances', []):
                        image = images.get(id(instance))
                        if image is not None:
                            group.create_pixel_layer(image, name=instance['name'],
                                                     left=int(instance['x']), top=int(instance['y']))
                add(group, layer.get('children', []))
                continue
            if category == 'point':
                marker = _marker()
                container.create_pixel_layer(marker, name=name, left=round(layer['x']) - marker.width // 2,
                                             top=round(layer['y']) - marker.height // 2)
            elif category == 'zone':
                container.create_pixel_layer(_zone_image(layer), name=name,
                                             left=round(layer['x']), top=round(layer['y']))
            else:
                image = images.get(id(layer))
                if image is not None:
                    container.create_pixel_layer(image.convert('RGBA'), name=name,
                                                 left=int(layer['x']), top=int(layer['y']))
            if layer.get('children'):
                add(container, layer['children'])

    add(psd, data['layers'])
    psd.save(path)
    return path
