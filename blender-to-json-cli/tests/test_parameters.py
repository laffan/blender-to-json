import json

import pytest

from blender_to_json.core.parameters import (
    SCENE_PROPERTY, ParameterError, apply_parameters, is_tracked, read_scene_parameters, read_scene_settings,
    resolve_references)


class FakeScene(dict):
    pass


def test_read_constants_and_settings():
    scene = FakeScene({SCENE_PROPERTY: json.dumps({'version': 2, 'parameters': {
        'level': {'value': 2}, 'legacy': 5,
        'width': {'id_type': 'scenes', 'id_name': 'Scene', 'path': 'render.resolution_x', 'value': 100}},
        'settings': {'output_dir': '//assets'}})})
    params = read_scene_parameters(scene)
    assert params['legacy'] == {'value': 5}
    assert is_tracked(params['width']) and not is_tracked(params['level'])
    assert read_scene_settings(scene) == {'output_dir': '//assets'}
    assert read_scene_parameters(FakeScene()) == {}


def test_apply_constants_without_bpy():
    values, problems = apply_parameters({'level': {'value': 2}}, {'level': 4, 'extra': True})
    assert values == {'level': 4, 'extra': True}
    assert problems == []


def test_resolve_references():
    params = {'cam': 'Top', 'size': 256}
    config = {'camera': '@cam', 'tile_slice_size': '@size', 'note': '@@literal',
              'list': ['@size', 1], 'nested': {'x': '@cam'}, 'plain': 'cam'}
    assert resolve_references(config, params) == {
        'camera': 'Top', 'tile_slice_size': 256, 'note': '@literal',
        'list': [256, 1], 'nested': {'x': 'Top'}, 'plain': 'cam'}


def test_unknown_reference():
    with pytest.raises(ParameterError, match='@missing'):
        resolve_references({'camera': '@missing'}, {'cam': 1})
