"""Plugin tests using the `bpy` pip module (skipped without it).

Interface-only pieces (the eyedropper's click handling, the right-click menu
entry and panel drawing) need a real Blender window and aren't covered here.
"""

import filecmp
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
CLI_SRC = os.path.join(PLUGIN_ROOT, '..', 'blender-to-json-cli', 'src')
CLI_TESTS = os.path.join(PLUGIN_ROOT, '..', 'blender-to-json-cli', 'tests')


def test_core_copy_matches_cli():
    ours = os.path.join(PLUGIN_ROOT, 'blender_to_json_plugin', 'core')
    theirs = os.path.join(CLI_SRC, 'blender_to_json', 'core')
    names = sorted(f for f in os.listdir(theirs) if f.endswith('.py'))
    assert names == sorted(f for f in os.listdir(ours) if f.endswith('.py'))
    _, mismatch, errors = filecmp.cmpfiles(ours, theirs, names, shallow=False)
    assert not mismatch and not errors, f'run python sync_core.py ({mismatch or errors})'


bpy = pytest.importorskip('bpy')
sys.path.insert(0, PLUGIN_ROOT)
import blender_to_json_plugin as plugin  # noqa: E402
from blender_to_json_plugin import export_ops, params_ops, preview  # noqa: E402
from blender_to_json_plugin.core import plan as planner  # noqa: E402


@pytest.fixture
def registered():
    plugin.register()
    yield
    plugin.unregister()


@pytest.fixture
def scene(registered):
    bpy.ops.wm.read_factory_settings(use_empty=False)  # Cube, Camera, Light
    return bpy.context.scene


def mirror():
    return json.loads(bpy.context.scene['blender_to_json'])


def test_tracking_parameters(scene, tmp_path):
    width, created = params_ops.track_full_path(scene, 'bpy.data.scenes["Scene"].render.resolution_x')
    assert created and width.name == 'resolutionX' and width.value() == 1920
    again, created = params_ops.track_full_path(scene, 'bpy.data.scenes["Scene"].render.resolution_x')
    assert not created and again == width

    power, _ = params_ops.track(scene, 'lights', 'Light', 'energy')
    cam, _ = params_ops.track(scene, 'scenes', 'Scene', 'camera')
    loc_z, _ = params_ops.track_full_path(scene, 'bpy.data.objects["Cube"].location[2]')
    assert (power.name, cam.name, loc_z.name) == ('energy', 'camera', 'locationZ')
    assert cam.value() == 'Camera'
    assert power.label() == 'Light › Power'

    # Embedded datablocks (a material's node tree) are addressed through their owner.
    mat = bpy.data.materials.new('Paint')
    mat.use_nodes = True
    node = mat.node_tree.nodes['Principled BSDF']
    path = node.inputs['Roughness'].path_from_id('default_value')
    from blender_to_json_plugin.core import datapath
    located = datapath.locate(mat.node_tree, path)
    assert located[:2] == ('materials', 'Paint') and located[2].startswith('node_tree.nodes[')
    rough, _ = params_ops.track(scene, *located)
    assert rough.value() == pytest.approx(node.inputs['Roughness'].default_value)

    width.name = 'width'
    scene.render.resolution_x = 640          # live value changes are picked up on save
    bpy.data.objects['Cube'].name = 'Box'    # renames are followed through the ID reference
    bpy.data.lights['Light'].name = 'Key'
    path = str(tmp_path / 'params.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)

    params = mirror()['parameters']
    assert params['width'] == {'id_type': 'scenes', 'id_name': 'Scene', 'path': 'render.resolution_x',
                               'value': 640}
    assert params['locationZ']['id_name'] == 'Box'
    assert params['energy']['id_name'] == 'Key'
    assert loc_z.problem(scene.blender_to_json_settings) is None

    settings = scene.blender_to_json_settings
    settings.parameters.add().name = '2 bad'
    assert 'letters' in settings.parameters[-1].problem(settings)


def test_settings_mirror_only_changed_values(scene):
    settings = scene.blender_to_json_settings.export
    settings.tile_width = 64
    settings.base_tile = bpy.data.objects['Cube']
    settings.holdout_collection = bpy.data.collections['Collection']
    settings.ignore_layers.add().name = 'S | junk'
    settings.output_dir = '//assets'
    assert mirror()['settings'] == {
        'output_dir': '//assets', 'holdoutCollection': 'Collection', 'baseTile': 'Cube', 'tileWidth': 64,
        'ignoreLayers': ['S | junk']}


def test_constants_written_by_scripts_survive(scene):
    scene['blender_to_json'] = json.dumps({'version': 2, 'parameters': {
        'level': {'value': 3},
        'width': {'id_type': 'scenes', 'id_name': 'Scene', 'path': 'render.resolution_x'}}})
    from blender_to_json_plugin import sync
    sync.on_load_post()
    assert [p.name for p in scene.blender_to_json_settings.parameters] == ['width']
    sync.write_scene(scene)
    assert mirror()['parameters']['level'] == {'value': 3}


def _build_named_scene():
    root = bpy.context.scene.collection
    house = bpy.data.collections.new('S | house')
    root.children.link(house)
    cube = bpy.data.objects['Cube']
    for col in cube.users_collection:
        col.objects.unlink(cube)
    house.objects.link(cube)  # unnamed: part of the house render
    marker = bpy.data.objects.new('P | door', None)
    house.objects.link(marker)
    return house, cube


def test_preview_and_selection(scene):
    house, cube = _build_named_scene()
    nodes = preview.build(scene)
    by = {n.blender_name: n for n in planner.iter_nodes(nodes)}
    assert by['S | house'].renders and by['Cube'].status == planner.CONTENT
    assert by['P | door'].status == planner.EXPORT

    bpy.ops.blender_to_json.preview_exclude(name='S | house')
    nodes = preview.build(scene)
    assert {n.blender_name: n for n in nodes}['S | house'].status == planner.IGNORED
    bpy.ops.blender_to_json.preview_exclude(name='S | house')
    assert not scene.blender_to_json_settings.export.ignore_layers

    bpy.ops.object.select_all(action='DESELECT')
    cube.select_set(True)
    assert export_ops._selected_layer_names(bpy.context) == ['S | house']


def test_create_camera(scene):
    scene.blender_to_json_settings.export.camera_preset = 'ISOMETRIC'
    assert bpy.ops.blender_to_json.create_camera() == {'FINISHED'}
    cam = scene.camera
    assert cam.name == 'IsometricCamera' and cam.data.type == 'ORTHO'
    assert round(cam.rotation_euler.x, 4) == round(0.95532, 4)


def test_export_command_runs(scene, tmp_path):
    pytest.importorskip('PIL')
    _build_named_scene()
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 1
    scene.render.resolution_x, scene.render.resolution_y = 160, 90
    scene.blender_to_json_settings.export.output_dir = str(tmp_path / 'out')
    params_ops.track(scene, 'scenes', 'Scene', 'render.resolution_x')[0].name = 'width'

    fake = tmp_path / 'blender'
    fake.write_text(f"#!/bin/sh\nexec {sys.executable} {os.path.join(CLI_TESTS, 'blender', 'fake_blender.py')} \"$@\"\n")
    fake.chmod(0o755)
    cli = [sys.executable, '-m', 'blender_to_json']

    cmd, cwd, folder, temp_dir = export_ops.prepare_export(bpy.context, 'ALL', cli=cli)
    assert temp_dir is not None  # unsaved changes -> temporary copy
    cmd[cmd.index('--blender') + 1] = str(fake)
    cmd += ['--param', 'width=320', '--set', 'optimizePngs=false']
    env = dict(os.environ, PYTHONPATH=CLI_SRC)
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.load(open(os.path.join(folder, 'data.json')))
    assert data['name'] == 'untitled' and data['width'] == 320
    house = data['layers'][0]
    assert house['name'] == 'house' and os.path.isfile(os.path.join(folder, house['filePath']))
    assert house['children'][0]['name'] == 'door'

    with pytest.raises(export_ops.ExportSetupError):
        scene.blender_to_json_settings.export.output_dir = ''
        export_ops.prepare_export(bpy.context, 'ALL', cli=cli)


class FakeLayout:
    """Stands in for bpy.types.UILayout and checks what the panels ask for."""

    def __init__(self, log):
        self.log = log

    def __getattr__(self, name):  # use_property_split, alert, active, scale_y, ...
        if name in ('row', 'column', 'box', 'split', 'grid_flow', 'column_flow'):
            return lambda *a, **k: FakeLayout(self.log)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def label(self, text='', icon='NONE', **_):
        self.log.append(('label', text))

    def separator(self, **_):
        pass

    def prop(self, data, prop, **kwargs):
        if not prop.startswith('['):
            assert prop in data.bl_rna.properties, f'{type(data).__name__} has no property {prop!r}'
        else:
            assert prop[2:-2] in data.keys()
        self.log.append(('prop', prop))

    def operator(self, idname, **_):
        module, name = idname.split('.')
        assert hasattr(getattr(bpy.ops, module), name), idname
        self.log.append(('operator', idname))
        return type('OpProps', (), {})()

    def template_list(self, *args, **kwargs):
        self.log.append(('list', args[0]))


def _draw(panel_cls, context):
    log = []
    holder = type('Holder', (), {})()
    holder.layout = FakeLayout(log)
    panel_cls.draw(holder, context)
    return log


def test_panels_draw(scene):
    from blender_to_json_plugin import ui
    _build_named_scene()
    params_ops.track(scene, 'scenes', 'Scene', 'render.resolution_x')
    obj = bpy.data.objects['Camera']
    obj['speed'] = 2.0
    params_ops.track(scene, 'objects', 'Camera', '["speed"]')
    params_ops.track(scene, 'objects', 'Camera', 'location[1]')
    scene.blender_to_json_settings.export.ignore_layers.add().name = 'S | old'

    for panel in (ui.B2J_PT_main, ui.B2J_PT_setup, ui.B2J_PT_settings, ui.B2J_PT_parameters, ui.B2J_PT_preview):
        log = _draw(panel, bpy.context)
        assert log, panel.__name__

    log = _draw(ui.B2J_PT_preview, bpy.context)
    labels = [entry for entry in log if entry[0] in ('operator', 'label')]
    assert ('operator', 'blender_to_json.preview_select') in labels
    assert any(entry == ('label', 'in render') for entry in log)

    # The list rows draw the tracked property's own widget.
    ul_log = []
    for param in scene.blender_to_json_settings.parameters:
        ui.B2J_UL_parameters.draw_item(None, bpy.context, FakeLayout(ul_log), scene.blender_to_json_settings,
                                       param, 0, None, '', 0)
    assert ('prop', 'resolution_x') in ul_log and ('prop', '["speed"]') in ul_log
    assert ('prop', 'location') in ul_log
