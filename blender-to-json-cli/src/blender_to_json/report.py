"""Human-readable output for --dryrun and --list-params."""

import json
import math
import os

CATEGORY_LETTERS = {'group': 'G', 'sprite': 'S', 'tileset': 'T', 'point': 'P', 'zone': 'Z'}


def _fmt(value):
    return json.dumps(value, ensure_ascii=False)


def _num(value):
    if value is None:
        return '?'
    return str(int(value)) if float(value).is_integer() else f'{value:g}'


def _attrs(attributes):
    if not attributes:
        return ''
    return '  {' + ', '.join(f'{k}: {_fmt(v)}' for k, v in attributes.items()) + '}'


def _render_text(render, config, category):
    if not render:
        return 'no render'
    text = f"render {render['width']}x{render['height']}"
    if render.get('objects'):
        text += f" ({render['objects']} object{'s' if render['objects'] != 1 else ''})"
    if category == 'tileset':
        size = int(config.get('tile_slice_size', 512))
        cols = math.ceil(render['width'] / size)
        rows = math.ceil(render['height'] / size)
        text += f" -> up to {cols}x{rows} tiles of {size}px"
    return text


def _describe(node, config):
    status = node.get('status', 'export')
    blender_name = node.get('blenderName') or (node.get('source') or {}).get('name', '')

    if status == 'ignored':
        text = f"x {blender_name}  -- ignored: {node.get('reason', '')}"
        if node.get('hiddenCount'):
            text += f" ({node['hiddenCount']} item{'s' if node['hiddenCount'] != 1 else ''} inside)"
        return text
    if status == 'content':
        return f". {blender_name}  ({node.get('reason', '')})"
    if status == 'hoist':
        return f"~ {blender_name}  -- {node.get('reason', 'contents exported')}"

    letter = CATEGORY_LETTERS.get(node.get('category'), '?')
    head = f"{letter} {node['name']}"
    if node.get('type'):
        head += f" ({node['type']})"
    details = []
    category = node.get('category')
    origin = node.get('origin')
    if category == 'point' and origin:
        details.append(f"at ({_num(origin['x'])}, {_num(origin['y'])}) depth {_num(origin['depth'])}")
    elif category == 'zone':
        points = node.get('points') or []
        details.append(f"{len(points)}-point hull")
        if node.get('depthRange'):
            details.append(f"depth {_num(node['depthRange']['near'])}-{_num(node['depthRange']['far'])}")
    elif category in ('sprite', 'tileset') and node.get('type') in ('atlas', 'spritesheet'):
        frames = node.get('frames') or []
        listed = ', '.join(f"{f['name']} {f['render']['width']}x{f['render']['height']}"
                           if f.get('render') else f"{f['name']} (no render)" for f in frames)
        details.append(f"{len(frames)} frame{'s' if len(frames) != 1 else ''}: {listed}")
    elif category in ('sprite', 'tileset') and node.get('type') != 'animation':
        details.append(_render_text(node.get('render'), config, category))
    if category not in ('point', 'zone') and origin:
        details.append(f"depth {_num(origin['depth'])}")
    if node.get('holdout'):
        details.append('holdout')
    if node.get('onlyRoot'):
        details.append('--only')

    text = f"{head}  [{blender_name}]"
    if details:
        text += '  ' + ', '.join(details)
    return text + _attrs(node.get('attributes'))


def _tree(nodes, config, prefix=''):
    lines = []
    for i, node in enumerate(nodes):
        last = i == len(nodes) - 1
        lines.append(prefix + ('`- ' if last else '|- ') + _describe(node, config))
        children = node.get('children') or []
        if children:
            lines.extend(_tree(children, config, prefix + ('   ' if last else '|  ')))
    return lines


def format_dryrun(blend_file, raw, output_root):
    config = raw.get('config', {})
    camera = raw.get('camera', {})
    lines = [
        f"{blend_file}",
        f"  scene '{raw.get('scene')}', camera '{camera.get('name')}' ({camera.get('type')}), "
        f"{raw.get('width')}x{raw.get('height')}px"
        + (f", scale {camera['scale']:g}" if camera.get('scale') else ''),
        f"  would write to {os.path.join(output_root, raw.get('name', ''))}{os.sep}",
    ]
    if raw.get('baseTile'):
        bt = raw['baseTile']
        lines.append(f"  base tile '{bt['name']}': {_num(bt['width'])}x{_num(bt['height'])}px"
                     + ('  (snapping sprites to the tile grid)' if config.get('snapToTileGrid') else ''))
    if raw.get('only'):
        lines.append(f"  only: {', '.join(raw['only'])}")
    if raw.get('parameters'):
        lines.append('  parameters: ' + ', '.join(f'@{k}={_fmt(v)}' for k, v in raw['parameters'].items()))
    lines.append('')
    layers = raw.get('layers') or []
    lines.extend(_tree(layers, config) if layers else ['(nothing to export)'])
    summary = raw.get('summary')
    if summary:
        lines.append('')
        lines.append(f"{summary['layers']} layer(s), {summary['renders']} render(s), "
                     f"{summary['ignored']} ignored, {len(raw.get('warnings') or [])} warning(s)")
    for warning in raw.get('warnings') or []:
        lines.append(f"  warning: {warning}")
    lines.append('Dry run: nothing was rendered or written.')
    return '\n'.join(lines)


def format_params(blend_file, result):
    lines = [f"\n{blend_file}  (scene: {result['scene']})"]
    params = result.get('parameters') or {}
    if not params:
        lines.append('  no parameters defined')
    for name, entry in params.items():
        if entry.get('path'):
            target = f"{entry['id_type']}[{entry['id_name']!r}].{entry['path']}".replace('.[', '[')
        else:
            target = 'constant'
        lines.append(f"  @{name:<18} {_fmt(entry.get('value')):<24} {target}")
    settings = result.get('settings') or {}
    if settings:
        lines.append('  settings stored in the file:')
        for key, value in settings.items():
            lines.append(f"    {key} = {_fmt(value)}")
    for warning in result.get('warnings') or []:
        lines.append(f"  warning: {warning}")
    return '\n'.join(lines)
