import json
import os

from PIL import Image

from blender_to_json.post.packer import pack
from blender_to_json.post.process import assign_initial_depth, merge_layers, post_process


def test_pack_no_overlap():
    sizes = [(10, 20), (30, 5), (8, 8), (15, 15), (40, 3)]
    positions, width, height = pack(sizes, padding=1)
    rects = [(x, y, x + w, y + h) for (x, y), (w, h) in zip(positions, sizes)]
    for i, a in enumerate(rects):
        assert a[2] <= width and a[3] <= height
        for b in rects[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_initial_depth_far_is_zero():
    layers = [{'name': 'near', 'depth': 1.0},
              {'name': 'group', 'depth': 5.0, 'children': [{'name': 'far', 'depth': 9.0}]},
              {'name': 'nodepth', 'depth': None}]
    assign_initial_depth(layers)
    order = {l['name']: l['initialDepth'] for l in [layers[0], layers[1], layers[1]['children'][0], layers[2]]}
    assert order == {'far': 0, 'group': 1, 'near': 2, 'nodepth': 3}


def _render(work_dir, name, size, box):
    image = Image.new('RGBA', size, (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), box)
    os.makedirs(os.path.join(work_dir, 'renders'), exist_ok=True)
    image.save(os.path.join(work_dir, 'renders', name))
    return os.path.join('renders', name)


def test_post_process(tmp_path):
    work = str(tmp_path / 'work')
    out = str(tmp_path / 'out')
    sprite_file = _render(work, '0001.png', (24, 24), (2, 3, 22, 21))
    tiles_file = _render(work, '0002.png', (70, 40), (0, 0, 70, 40))
    frame_a = _render(work, '0003.png', (14, 14), (2, 2, 12, 12))
    frame_b = _render(work, '0004.png', (10, 10), (2, 2, 8, 8))
    origin = {'x': 50.0, 'y': 50.0, 'depth': 20.0}
    raw = {
        'name': 'level', 'width': 200, 'height': 100, 'camera': {'name': 'Camera'},
        'config': {'tile_slice_size': 32, 'tile_scaled_versions': [16], 'optimizePngs': False},
        'parameters': {'difficulty': 3}, 'warnings': [],
        'layers': [
            {'name': 'crate', 'category': 'sprite', 'attributes': {'weight': 10},
             'source': {'kind': 'object', 'name': 'S | crate'}, 'origin': origin,
             'render': {'file': sprite_file, 'left': 38, 'top': 38, 'width': 24, 'height': 24}},
            {'name': 'ground', 'category': 'tileset', 'attributes': {}, 'type': 'jpg',
             'source': {'kind': 'collection', 'name': 'T | ground | jpg |'},
             'origin': {'x': 1, 'y': 1, 'depth': 30.0},
             'render': {'file': tiles_file, 'left': -5, 'top': 10, 'width': 70, 'height': 40}},
            {'name': 'spawn', 'category': 'point', 'attributes': {}, 'source': {},
             'origin': {'x': 12.5, 'y': 7.25, 'depth': 3.0}},
            {'name': 'lake', 'category': 'zone', 'attributes': {}, 'source': {},
             'points': [{'x': 0, 'y': 0, 'depth': 1}, {'x': 10, 'y': 0, 'depth': 2},
                        {'x': 5, 'y': 8, 'depth': 3}], 'origin': origin},
            {'name': 'props', 'category': 'sprite', 'type': 'atlas', 'attributes': {}, 'source': {},
             'origin': origin, 'frames': [
                 {'name': 'barrel', 'attributes': {}, 'source': {'name': 'barrel'}, 'origin': origin,
                  'render': {'file': frame_a, 'left': 100, 'top': 50, 'width': 14, 'height': 14}},
                 {'name': 'rock', 'attributes': {}, 'source': {'name': 'rock'}, 'origin': origin,
                  'render': {'file': frame_b, 'left': 130, 'top': 60, 'width': 10, 'height': 10}}]},
        ],
    }
    path = post_process(raw, work, out)
    data = json.load(open(path))
    layers = {l['name']: l for l in data['layers']}

    crate = layers['crate']
    assert (crate['x'], crate['y'], crate['width'], crate['height']) == (40, 41, 20, 18)
    assert crate['filePath'] == 'sprites/crate.png'
    assert Image.open(os.path.join(out, 'level', crate['filePath'])).size == (20, 18)

    ground = layers['ground']
    assert (ground['columns'], ground['rows'], ground['filetype']) == (3, 2, 'jpg')
    assert os.path.isfile(os.path.join(out, 'level', 'tiles', 'ground', '32', 'ground_tile_2_1.jpg'))
    edge = Image.open(os.path.join(out, 'level', 'tiles', 'ground', '16', 'ground_tile_2_1.jpg'))
    assert edge.size == (3, 4)  # 6x8 edge tile scaled by 16/32

    assert (layers['spawn']['x'], layers['spawn']['y'], layers['spawn']['depth']) == (12.5, 7.25, 3.0)
    lake = layers['lake']
    assert lake['subpaths'] == [[[0, 0], [10, 0], [5, 8]]]
    assert lake['bbox'] == {'left': 0, 'top': 0, 'right': 10, 'bottom': 8}

    props = layers['props']
    assert set(props['frames']) == {'barrel', 'rock'}
    assert props['instances'][0] == {'name': 'barrel', 'x': 102, 'y': 52, 'depth': 20.0, 'origin': origin}
    assert (props['x'], props['y'], props['width'], props['height']) == (102, 52, 36, 16)

    assert layers['ground']['initialDepth'] == 0  # farthest
    assert layers['spawn']['initialDepth'] == 4   # nearest
    assert data['parameters'] == {'difficulty': 3}


def test_holdout_layers_go_to_the_bottom():
    layers = [{'name': 'far', 'depth': 50.0}, {'name': 'ground', 'depth': 1.0, 'holdout': True}]
    assign_initial_depth(layers)
    assert [l['initialDepth'] for l in layers] == [1, 0]


def test_merge_layers_replaces_only_roots():
    existing = [
        {'name': 'world', 'source': {'kind': 'collection', 'name': 'G | world'}, 'children': [
            {'name': 'crate', 'source': {'kind': 'object', 'name': 'S | crate'}, 'filePath': 'old'},
            {'name': 'house', 'source': {'kind': 'collection', 'name': 'S | house'}},
        ]},
        {'name': 'ground', 'source': {'kind': 'collection', 'name': 'T | ground'}},
    ]
    new = [
        {'name': 'world', 'source': {'kind': 'collection', 'name': 'G | world'}, 'children': [
            {'name': 'crate', 'source': {'kind': 'object', 'name': 'S | crate'}, 'filePath': 'new',
             'onlyRoot': True},
            {'name': 'barrel', 'source': {'kind': 'object', 'name': 'S | barrel'}, 'onlyRoot': True},
        ]},
    ]
    merged = merge_layers(existing, new)
    world = merged[0]
    assert [c['name'] for c in world['children']] == ['crate', 'house', 'barrel']
    assert world['children'][0]['filePath'] == 'new'
    assert merged[1]['name'] == 'ground'


def test_psd_layer_names_round_trip():
    from blender_to_json.core.naming import parse_layer_name
    from blender_to_json.post.psd import layer_name

    for layer in [
        {'category': 'sprite', 'name': 'props', 'type': 'atlas', 'attributes': {}},
        {'category': 'point', 'name': 'spawn', 'attributes': {'team': 'red', 'level': 3, 'boss': True,
                                                             'targets': ['a', 'b']}},
        {'category': 'tileset', 'name': 'ground', 'type': 'jpg', 'attributes': {'lazyLoad': True}},
        {'category': 'group', 'name': 'world', 'attributes': {}},
    ]:
        parsed = parse_layer_name(layer_name(layer))
        assert parsed['name'] == layer['name']
        assert parsed['category'] == layer['category']
        assert parsed.get('type') == layer.get('type')
        assert parsed['attributes'] == layer['attributes']


def test_dryrun_report():
    from blender_to_json.report import format_dryrun

    raw = {'name': 'lvl', 'scene': 'Scene', 'width': 200, 'height': 100,
           'camera': {'name': 'Camera', 'type': 'orthographic'}, 'config': {'tile_slice_size': 64},
           'parameters': {'difficulty': 3}, 'warnings': ['careful'],
           'summary': {'layers': 2, 'renders': 1, 'ignored': 1, 'warnings': 0},
           'layers': [
               {'status': 'export', 'name': 'ground', 'category': 'tileset',
                'source': {'name': 'T | ground'}, 'render': {'width': 130, 'height': 64, 'objects': 1},
                'origin': {'x': 1, 'y': 2, 'depth': 21.0}, 'children': [
                    {'status': 'content', 'blenderName': 'plane', 'reason': "part of the 'T | ground' render"}]},
               {'status': 'ignored', 'blenderName': 'helper', 'reason': 'no category'},
           ]}
    text = format_dryrun('lvl.blend', raw, '/out')
    assert "T ground  [T | ground]  render 130x64 (1 object) -> up to 3x1 tiles of 64px, depth 21" in text
    assert "`- . plane  (part of the 'T | ground' render)" in text
    assert "`- x helper  -- ignored: no category" in text
    assert 'warning: careful' in text
