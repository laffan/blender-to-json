"""Plugin round-trip test using the `bpy` pip module (skipped without it)."""

import json
import os
import sys

import pytest

bpy = pytest.importorskip('bpy')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import blender_to_json_plugin as plugin  # noqa: E402


@pytest.fixture
def registered():
    plugin.register()
    yield
    plugin.unregister()


def test_parameters_are_mirrored_for_the_cli(registered, tmp_path):
    bpy.ops.wm.read_factory_settings(use_empty=False)
    scene = bpy.context.scene
    top = bpy.data.objects.new('TopDown', bpy.data.cameras.new('TopDown'))
    scene.collection.objects.link(top)
    bpy.context.view_layer.objects.active = top

    bpy.ops.blender_to_json.parameter_add_camera()
    bpy.ops.blender_to_json.parameter_add()
    settings = scene.blender_to_json_settings
    size = settings.parameters[1]
    size.name = 'tileSize'
    size.param_type = 'INT'
    size.value_int = 256

    bpy.ops.blender_to_json.parameter_add()
    assert settings.parameters[2].problem(settings) is None
    settings.parameters[2].name = '2 bad'
    assert settings.parameters[2].problem(settings)
    bpy.ops.blender_to_json.parameter_remove()

    top.name = 'TopDownCam'  # renames don't fire update callbacks; save_pre must catch it
    path = str(tmp_path / 'params.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)

    plugin.unregister()
    try:
        bpy.ops.wm.open_mainfile(filepath=path)
        mirror = json.loads(bpy.context.scene['blender_to_json'])
    finally:
        plugin.register()

    assert mirror == {'version': 1, 'parameters': {
        'camera': {'type': 'CAMERA', 'value': 'TopDownCam'},
        'tileSize': {'type': 'INT', 'value': 256},
    }}

    # Re-opening with the plugin loaded keeps the list.
    bpy.ops.wm.open_mainfile(filepath=path)
    names = [p.name for p in bpy.context.scene.blender_to_json_settings.parameters]
    assert names == ['camera', 'tileSize']


def test_mirror_is_imported_when_list_is_empty(registered):
    bpy.ops.wm.read_factory_settings(use_empty=False)
    scene = bpy.context.scene
    scene['blender_to_json'] = json.dumps({'version': 1, 'parameters': {
        'cam': {'type': 'CAMERA', 'value': 'Camera'}, 'speed': {'type': 'FLOAT', 'value': 1.5}}})
    from blender_to_json_plugin import sync
    sync.on_load_post()
    params = {p.name: p.get_value() for p in scene.blender_to_json_settings.parameters}
    assert params == {'cam': 'Camera', 'speed': 1.5}
