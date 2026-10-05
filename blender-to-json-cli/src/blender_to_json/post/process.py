"""Turn the Blender stage's raw.json + renders into final assets and data.json.

Runs in the system Python (needs Pillow, not bpy).
"""

import json
import math
import os

from PIL import Image

from . import packer
from .images import load_render, save_png
from .tiles import slice_tiles


class PostProcessor:
    def __init__(self, raw, work_dir, layer_dir):
        self.raw = raw
        self.work_dir = work_dir
        self.layer_dir = layer_dir
        self.config = raw['config']
        self.metadata_only = bool(self.config.get('metadataOnly'))
        self.trim = self.config.get('trimTransparent', True)
        self.warnings = list(raw.get('warnings', []))
        self.base_tile = raw.get('baseTile')
        self.snap = bool(self.config.get('snapToTileGrid')) and self.base_tile is not None
        self.images = {}  # id(layer) -> PIL image, for PSD output

    def warn(self, message):
        print(f"[blender-to-json] WARNING: {message}")
        self.warnings.append(message)

    # ------------------------------------------------------------------ entry

    def run(self):
        layers = [self._layer(node) for node in self.raw['layers']]
        layers = [layer for layer in layers if layer is not None]
        assign_initial_depth(layers)

        data = {
            'name': self.raw['name'],
            'source': self.raw.get('source'),
            'scene': self.raw.get('scene'),
            'width': self.raw['width'],
            'height': self.raw['height'],
            'camera': self.raw['camera'],
            'tile_slice_size': int(self.config.get('tile_slice_size', 512)),
            **({'baseTile': self.base_tile} if self.base_tile else {}),
            'tile_scaled_versions': self.config.get('tile_scaled_versions', []) or [],
            'parameters': self.raw.get('parameters', {}),
            'layers': layers,
        }
        if self.warnings:
            data['warnings'] = self.warnings
        return data

    # ------------------------------------------------------------------ layers

    def _layer(self, node):
        if node.get('status', 'export') != 'export':
            return None
        category = node['category']
        layer = {'name': node['name'], 'category': category}
        for flag in ('onlyRoot', 'holdout'):
            if node.get(flag):
                layer[flag] = True
        if node.get('type'):
            layer['type'] = node['type']

        origin = node.get('origin')
        layer['depth'] = origin['depth'] if origin else None
        if node.get('depthRange'):
            layer['depthRange'] = node['depthRange']

        handler = {
            'group': self._group,
            'point': self._point,
            'zone': self._zone,
            'sprite': self._sprite,
            'tileset': self._tileset,
        }[category]
        result = handler(node, layer)
        if result is None:
            return None

        result['attributes'] = node.get('attributes', {})
        result['source'] = node.get('source')

        children = [self._layer(child) for child in node.get('children', [])]
        children = [c for c in children if c is not None]
        if children:
            result['children'] = children
        return result

    @staticmethod
    def _rect_from_bounds(layer, bounds):
        if bounds:
            layer['x'] = math.floor(bounds['left'])
            layer['y'] = math.floor(bounds['top'])
            layer['width'] = math.ceil(bounds['right']) - layer['x']
            layer['height'] = math.ceil(bounds['bottom']) - layer['y']

    def _group(self, node, layer):
        self._rect_from_bounds(layer, node.get('bounds'))
        return layer

    def _point(self, node, layer):
        layer['x'] = node['origin']['x']
        layer['y'] = node['origin']['y']
        return layer

    def _zone(self, node, layer):
        points = node['points']
        xs = [p['x'] for p in points]
        ys = [p['y'] for p in points]
        left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        layer.update({
            'x': left,
            'y': top,
            'width': round(right - left, 2),
            'height': round(bottom - top, 2),
            'points': points,
            # psd-to-json/psd-to-phaser compatible forms
            'subpaths': [[[p['x'], p['y']] for p in points]],
            'bbox': {'left': left, 'top': top, 'right': right, 'bottom': bottom},
        })
        if node.get('origin'):
            layer['origin'] = node['origin']
        return layer

    def _sprite(self, node, layer):
        sprite_type = node.get('type', 'basic')
        if sprite_type == 'atlas':
            return self._atlas(node, layer)
        if sprite_type == 'spritesheet':
            return self._spritesheet(node, layer)
        if sprite_type == 'animation':
            self._rect_from_bounds(layer, node.get('bounds'))
            layer['note'] = "Sprite type 'animation' not yet processed"
            return layer
        return self._basic(node, layer)

    def _placed_image(self, node, label):
        """Return (image, x, y) for a rendered node; image is None in
        metadata-only mode, x/y fall back to the render region."""
        render = node.get('render')
        if render is None:
            return None, None, None
        if self.metadata_only or 'file' not in render:
            return None, render['left'], render['top']
        image, x, y = load_render(self.work_dir, render, self.trim)
        if image is None:
            self.warn(f"'{label}' rendered fully transparent")
        return image, x, y

    def _apply_rect(self, layer, node, image, x, y):
        if image is not None:
            layer.update({'x': x, 'y': y, 'width': image.width, 'height': image.height})
        else:
            self._rect_from_bounds(layer, node.get('bounds'))

    def _snap(self, image, x, y, width, height, origin):
        """Grow a sprite's rectangle outward to the base-tile grid anchored
        at its origin (blender-2d-tile-tools' tile alignment)."""
        if not self.snap or origin is None or x is None:
            return image, x, y
        cell_w = max(1, round(self.base_tile['width']))
        cell_h = max(1, round(self.base_tile['height']))
        gx = round(origin['x'] - self.base_tile['originX'])
        gy = round(origin['y'] - self.base_tile['originY'])
        left = gx + math.floor((x - gx) / cell_w) * cell_w
        top = gy + math.floor((y - gy) / cell_h) * cell_h
        right = gx + math.ceil((x + width - gx) / cell_w) * cell_w
        bottom = gy + math.ceil((y + height - gy) / cell_h) * cell_h
        if image is not None:
            canvas = Image.new('RGBA', (right - left, bottom - top), (0, 0, 0, 0))
            canvas.paste(image, (x - left, y - top))
            image = canvas
        else:
            self._snapped_size = (right - left, bottom - top)
        return image, left, top

    def _basic(self, node, layer):
        image, x, y = self._placed_image(node, node['source']['name'])
        if self.snap and image is not None:
            image, x, y = self._snap(image, x, y, image.width, image.height, node.get('origin'))
        self._apply_rect(layer, node, image, x, y)
        if self.snap and image is None and 'x' in layer:
            _, layer['x'], layer['y'] = self._snap(None, layer['x'], layer['y'], layer['width'],
                                                  layer['height'], node.get('origin'))
            layer['width'], layer['height'] = self._snapped_size
        if node.get('origin'):
            layer['origin'] = node['origin']
        if image is not None:
            rel = f"sprites/{node['name']}.png"
            save_png(image, os.path.join(self.layer_dir, rel), self.config)
            layer['filePath'] = rel
            self.images[id(layer)] = image
        return layer

    def _tileset(self, node, layer):
        image, x, y = self._placed_image(node, node['source']['name'])
        self._apply_rect(layer, node, image, x, y)
        use_jpg = str(node.get('type', '')).lower() == 'jpg'
        if image is None and self.metadata_only and 'width' in layer:
            # Estimate the grid from the projected bounds.
            image = Image.new('RGBA', (max(1, layer['width']), max(1, layer['height'])))
        if image is None:
            return layer
        layer.update(slice_tiles(image, node['name'], self.layer_dir, self.config, use_jpg))
        if not self.metadata_only:
            self.images[id(layer)] = image
        return layer

    def _collect_frames(self, node):
        """Return (unique_frames, instances) for atlas/spritesheet nodes."""
        unique = {}
        instances = []
        for frame in node.get('frames', []):
            image, x, y = self._placed_image(frame, frame['source']['name'])
            if x is None:
                continue
            if image is None:
                bounds = frame.get('bounds') or {}
                width = math.ceil(bounds.get('right', 0)) - math.floor(bounds.get('left', 0))
                height = math.ceil(bounds.get('bottom', 0)) - math.floor(bounds.get('top', 0))
                if not self.metadata_only:
                    continue
                x, y = math.floor(bounds.get('left', 0)), math.floor(bounds.get('top', 0))
            else:
                if self.snap:
                    image, x, y = self._snap(image, x, y, image.width, image.height, frame.get('origin'))
                width, height = image.width, image.height
            if frame['name'] not in unique:
                unique[frame['name']] = {'name': frame['name'], 'image': image,
                                         'width': width, 'height': height}
            instance = {'name': frame['name'], 'x': x, 'y': y}
            if image is not None:
                self.images[id(instance)] = image
            if frame.get('origin'):
                instance['depth'] = frame['origin']['depth']
                instance['origin'] = frame['origin']
            if frame.get('attributes'):
                instance['attributes'] = frame['attributes']
            instances.append(instance)
        return list(unique.values()), instances

    def _instances_rect(self, layer, frames, instances):
        sizes = {f['name']: (f['width'], f['height']) for f in frames}
        if not instances:
            return
        left = min(i['x'] for i in instances)
        top = min(i['y'] for i in instances)
        right = max(i['x'] + sizes[i['name']][0] for i in instances)
        bottom = max(i['y'] + sizes[i['name']][1] for i in instances)
        layer.update({'x': left, 'y': top, 'width': right - left, 'height': bottom - top})

    def _atlas(self, node, layer):
        frames, instances = self._collect_frames(node)
        if not frames:
            self.warn(f"atlas '{node['name']}' has no frames; skipped")
            return None
        self._instances_rect(layer, frames, instances)
        layer['instances'] = instances

        if self.metadata_only:
            layer['frames'] = {f['name']: {'width': f['width'], 'height': f['height']} for f in frames}
            return layer

        padding = int(self.config.get('atlasPadding', 2))
        positions, width, height = packer.pack([(f['width'], f['height']) for f in frames], padding)
        atlas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        layer['frames'] = {}
        for frame, (x, y) in zip(frames, positions):
            atlas.paste(frame['image'], (x, y))
            layer['frames'][frame['name']] = {'x': x, 'y': y, 'width': frame['width'], 'height': frame['height']}

        rel = f"sprites/{node['name']}.png"
        save_png(atlas, os.path.join(self.layer_dir, rel), self.config)
        layer['filePath'] = rel
        return layer

    def _spritesheet(self, node, layer):
        frames, instances = self._collect_frames(node)
        if not frames:
            self.warn(f"spritesheet '{node['name']}' has no frames; skipped")
            return None
        self._instances_rect(layer, frames, instances)

        frame_width = max(f['width'] for f in frames)
        frame_height = max(f['height'] for f in frames)
        columns = math.ceil(math.sqrt(len(frames)))
        rows = math.ceil(len(frames) / columns)
        layer.update({
            'frame_width': frame_width,
            'frame_height': frame_height,
            'frame_count': len(frames),
            'columns': columns,
            'rows': rows,
            'instances': instances,
        })

        if self.metadata_only:
            layer['frames'] = {f['name']: {'width': f['width'], 'height': f['height']} for f in frames}
            return layer

        sheet = Image.new('RGBA', (columns * frame_width, rows * frame_height), (0, 0, 0, 0))
        layer['frames'] = {}
        for index, frame in enumerate(frames):
            x = (index % columns) * frame_width
            y = (index // columns) * frame_height
            offset_x = (frame_width - frame['width']) // 2
            offset_y = (frame_height - frame['height']) // 2
            sheet.paste(frame['image'], (x + offset_x, y + offset_y))
            layer['frames'][frame['name']] = {'x': x, 'y': y, 'width': frame['width'], 'height': frame['height']}

        rel = f"sprites/{node['name']}.png"
        save_png(sheet, os.path.join(self.layer_dir, rel), self.config)
        layer['filePath'] = rel
        return layer


def assign_initial_depth(layers):
    """Order every layer (groups included) by camera depth.

    The farthest layer gets initialDepth 0; nearer layers get higher values,
    matching psd-to-json where higher = drawn on top. Layers in the holdout
    collection come first; layers without a depth are drawn last.
    """
    flat = []

    def collect(items):
        for item in items:
            flat.append(item)
            collect(item.get('children', []))

    collect(layers)
    # Holdout ("ground") layers always go underneath everything else.
    ordered = sorted(
        enumerate(flat),
        key=lambda pair: (not pair[1].get('holdout'), pair[1].get('depth') is None,
                          -(pair[1].get('depth') or 0), pair[0]))
    for rank, (_, layer) in enumerate(ordered):
        layer['initialDepth'] = rank


def _key(layer):
    source = layer.get('source') or {}
    return source.get('kind'), source.get('name')


def _find(layers, key):
    for i, layer in enumerate(layers):
        if _key(layer) == key:
            return layers, i
        found = _find(layer.get('children', []), key)
        if found:
            return found
    return None


def merge_layers(existing, new):
    """Merge a --only export into an existing layer tree.

    Layers marked onlyRoot replace the existing layer that came from the same
    Blender collection/object (wherever it is), or are added if new. Group
    containers that were only exported to hold them are matched up with their
    existing counterparts so the rest of the tree is left untouched.
    """
    def place(nodes, siblings):
        for node in nodes:
            found = _find(existing, _key(node))
            if node.get('onlyRoot'):
                if found:
                    found[0][found[1]] = node
                else:
                    siblings.append(node)
            elif found:
                target = found[0][found[1]]
                place(node.get('children', []), target.setdefault('children', []))
            else:
                siblings.append(node)

    place(new, existing)
    return existing


def _strip_flags(layers):
    for layer in layers:
        layer.pop('onlyRoot', None)
        _strip_flags(layer.get('children', []))


def post_process(raw, work_dir, output_root):
    """Write assets and data.json for one blend file; return the output path.

    With --only, the new layers are merged into an existing data.json.
    """
    layer_dir = os.path.join(output_root, raw['name'])
    os.makedirs(layer_dir, exist_ok=True)
    processor = PostProcessor(raw, work_dir, layer_dir)
    data = processor.run()
    path = os.path.join(layer_dir, 'data.json')

    if raw.get('only') and os.path.isfile(path):
        with open(path) as f:
            previous = json.load(f)
        data['layers'] = merge_layers(previous.get('layers', []), data['layers'])
        assign_initial_depth(data['layers'])
        print(f"[blender-to-json] merged {', '.join(raw['only'])} into the existing {path}")
    _strip_flags(data['layers'])

    if processor.config.get('psd') and not processor.metadata_only:
        from .psd import write_psd
        if raw.get('only'):
            processor.warn('PSD output skipped: --only exports are partial')
        else:
            psd_path = write_psd(data, processor.images, os.path.join(layer_dir, f"{raw['name']}.psd"))
            data['psdPath'] = os.path.relpath(psd_path, layer_dir)
            print(f"[blender-to-json] wrote {psd_path}")
    if processor.warnings:
        data['warnings'] = processor.warnings

    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    return path
