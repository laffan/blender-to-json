"""Core modules exercised against real Blender data (skipped without bpy)."""

import pytest

bpy = pytest.importorskip('bpy')

from blender_to_json.core import datapath, plan  # noqa: E402
from blender_to_json.core.parameters import ParameterError, apply_parameters  # noqa: E402


@pytest.fixture
def scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam'))
    other = bpy.data.objects.new('Other', bpy.data.cameras.new('Other'))
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    for obj in (cam, other, sun):
        sc.collection.objects.link(obj)
    sc.camera = cam
    return sc


def test_datapath_get_and_set(scene):
    obj = bpy.data.objects['Other']
    obj['speed'] = 1.5
    cases = [
        (scene, 'render.resolution_x', 640),
        (scene, 'camera', 'Other'),
        (bpy.data.lights['Sun'], 'energy', 7.5),
        (obj, 'location', [1.0, 2.0, 3.0]),
        (obj, 'location[2]', 9.0),
        (obj, '["speed"]', 4.25),
        (scene, 'render.film_transparent', True),
        (scene, 'render.engine', 'CYCLES'),
    ]
    for id_block, path, value in cases:
        datapath.set_value(id_block, path, value)
        assert datapath.get_value(id_block, path) == value, path
    assert obj.location.z == 9.0
    assert scene.camera.name == 'Other'
    assert datapath.describe(scene, 'render.resolution_x') == 'Scene › Resolution X'
    assert datapath.describe(obj, 'location[1]') == 'Other › Location Y'

    owner, prop, index = datapath.ui_target(obj, 'location[1]')
    assert owner == obj and prop == 'location' and index == 1
    owner, prop, index = datapath.ui_target(obj, '["speed"]')
    assert owner == obj and prop == '["speed"]' and index == -1

    with pytest.raises(datapath.DataPathError):
        datapath.set_value(scene, 'camera', 'Nope')
    with pytest.raises(datapath.DataPathError):
        datapath.set_value(scene, 'render.resolution_x', 'wide')


def test_apply_parameters_writes_tracked_properties(scene):
    entries = {
        'width': {'id_type': 'scenes', 'id_name': 'Scene', 'path': 'render.resolution_x', 'value': 1},
        'cam': {'id_type': 'scenes', 'id_name': 'Scene', 'path': 'camera'},
        'gone': {'id_type': 'objects', 'id_name': 'Missing', 'path': 'location', 'value': [0, 0, 0]},
        'level': {'value': 2},
    }
    values, problems = apply_parameters(entries, {'width': 800, 'cam': 'Other'})
    assert scene.render.resolution_x == 800
    assert values['width'] == 800 and values['cam'] == 'Other' and values['level'] == 2
    assert values['gone'] == [0, 0, 0] and len(problems) == 1
    with pytest.raises(ParameterError):
        apply_parameters(entries, {'gone': [1, 1, 1]})


def _collection(name, parent):
    col = bpy.data.collections.new(name)
    parent.children.link(col)
    return col


def _obj(name, collection):
    obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
    collection.objects.link(obj)
    return obj


def test_plan(scene):
    root = scene.collection
    world = _collection('G | world', root)
    house = _collection('S | house', world)
    _obj('wall', house)
    _obj('P | door', house)
    _obj('S | crate', world)
    misc = _collection('Misc', root)
    _obj('S | hidden', misc)
    _obj('G | notACollection', root)

    nodes = plan.build_plan(root, plan.PlanOptions())
    by = {n.blender_name: n for n in plan.iter_nodes(nodes)}
    assert by['G | world'].status == plan.EXPORT
    assert by['S | house'].renders
    assert by['wall'].status == plan.CONTENT
    assert by['P | door'].status == plan.EXPORT
    assert by['Misc'].status == plan.IGNORED and by['Misc'].hidden_count == 1
    assert 'S | hidden' not in by
    assert by['G | notACollection'].warning
    assert [o.name for o in plan.render_objects('collection', house)] == ['wall']

    # pass-through and --only
    nodes = plan.build_plan(root, plan.PlanOptions(pass_through=True))
    by = {n.blender_name: n for n in plan.iter_nodes(nodes)}
    assert by['Misc'].status == plan.HOIST and by['S | hidden'].status == plan.EXPORT

    options = plan.PlanOptions(only=['crate', 'S | hidden', 'nope'])
    nodes = plan.build_plan(root, options)
    by = {n.blender_name: n for n in plan.iter_nodes(nodes)}
    assert by['G | world'].status == plan.EXPORT  # container for crate
    assert by['S | crate'].only_root and by['S | hidden'].only_root
    assert by['S | house'].status == plan.IGNORED
    assert by['Misc'].status == plan.HOIST
    assert options.only - options.only_matched == {'nope'}

    nodes = plan.build_plan(root, plan.PlanOptions(ignore=['house', 'Misc']))
    by = {n.blender_name: n for n in plan.iter_nodes(nodes)}
    assert by['S | house'].reason == 'listed in ignoreLayers'
    assert by['Misc'].reason == 'listed in ignoreLayers'


def test_blend_settings_precedence():
    from blender_to_json.blender_stage.exporter import merge_blend_settings

    config = {'tile_slice_size': 512, 'camera': None, 'ignoreLayers': ['a'], 'output_dir': 'output'}
    settings = {'tile_slice_size': 64, 'camera': 'Top', 'ignoreLayers': ['b'], 'output_dir': '//assets'}
    merged = merge_blend_settings(config, settings, explicit={'camera'})
    assert merged['tile_slice_size'] == 64      # blend beats defaults
    assert merged['camera'] is None             # config file / --set beat blend
    assert merged['ignoreLayers'] == ['a', 'b']  # lists combine
    assert merged['output_dir'].endswith('assets') and not merged['output_dir'].startswith('//')
