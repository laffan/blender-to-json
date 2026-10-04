import json

import pytest

from blender_to_json.blender_stage.parameters import (
    SCENE_PROPERTY, ParameterError, merge_parameters, read_scene_parameters, resolve_references)


class FakeScene(dict):
    pass


def test_read_and_merge():
    scene = FakeScene({SCENE_PROPERTY: json.dumps({'version': 1, 'parameters': {
        'cam': {'type': 'CAMERA', 'value': 'Camera.001'},
        'size': {'type': 'INT', 'value': 512}}})})
    params = merge_parameters(read_scene_parameters(scene), {'size': 256, 'extra': True})
    assert params == {'cam': 'Camera.001', 'size': 256, 'extra': True}
    assert read_scene_parameters(FakeScene()) == {}


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
