"""Full pipeline test: real scene, real renders, via the CLI.

Uses the `bpy` pip module as a stand-in for the Blender executable, so it is
skipped when bpy is not installed (pip install bpy; needs a matching Python).
"""

import json
import os
import stat
import subprocess
import sys

import pytest

pytest.importorskip('bpy')

from blender_to_json.cli import main  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(scope='module')
def fake_blender(tmp_path_factory):
    path = tmp_path_factory.mktemp('bin') / 'blender'
    path.write_text(f"#!/bin/sh\nexec {sys.executable} {os.path.join(HERE, 'blender', 'fake_blender.py')} \"$@\"\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture(scope='module', params=['ortho', 'persp'])
def blend_file(request, tmp_path_factory):
    path = tmp_path_factory.mktemp('scene') / f'level_{request.param}.blend'
    subprocess.run([sys.executable, os.path.join(HERE, 'blender', 'make_fixture.py'), str(path), request.param],
                   check=True, capture_output=True)
    return str(path)


def run(blend_file, fake_blender, out, *extra):
    code = main([blend_file, '--blender', fake_blender, '-o', str(out),
                 '--set', 'optimizePngs=false', '--set', 'camera=@mainCam',
                 '--set', 'tile_slice_size=@tileSize', *extra])
    assert code == 0
    name = os.path.splitext(os.path.basename(blend_file))[0]
    with open(out / name / 'data.json') as f:
        return json.load(f), out / name


def by_name(layers, found=None):
    found = {} if found is None else found
    for layer in layers:
        found.setdefault(layer['name'], layer)
        by_name(layer.get('children', []), found)
    return found


def test_export(blend_file, fake_blender, tmp_path):
    data, out = run(blend_file, fake_blender, tmp_path)
    layers = by_name(data['layers'])
    ortho = 'ortho' in blend_file

    assert data['width'] == 200 and data['height'] == 100
    assert data['tile_slice_size'] == 64
    assert data['camera']['type'] == ('orthographic' if ortho else 'perspective')
    assert set(layers) >= {'world', 'house', 'door', 'crate', 'edge', 'spawn', 'lake', 'ground', 'props', 'gems'}
    assert 'helper' not in layers

    spawn = layers['spawn']
    assert spawn['attributes'] == {'team': 'red', 'difficulty': 3}  # custom prop resolved via @difficulty
    assert spawn['depth'] == pytest.approx(19.0)
    if ortho:
        assert (spawn['x'], spawn['y']) == (120.0, 30.0)
        crate = layers['crate']  # 2x2 units at 10px/unit, centred at (50, 50)
        assert abs(crate['x'] - 40) <= 1 and abs(crate['width'] - 20) <= 1
        edge = layers['edge']  # half outside the 200px frame, exported whole
        assert edge['x'] + edge['width'] > 205

    for name in ('crate', 'house', 'edge', 'props', 'gems'):
        assert os.path.isfile(out / layers[name]['filePath']), name

    assert len(layers['lake']['points']) == 4
    assert all('depth' in p for p in layers['lake']['points'])
    assert layers['ground']['columns'] >= 1
    assert os.path.isfile(out / 'tiles' / 'ground' / '64' / 'ground_tile_0_0.png')
    assert set(layers['props']['frames']) == {'barrel', 'rock'}
    assert layers['gems']['frame_count'] == 2
    # the ground plane is farthest from the camera
    assert layers['ground']['initialDepth'] == 0
    assert 'warnings' not in data


def test_metadata_only(blend_file, fake_blender, tmp_path):
    data, out = run(blend_file, fake_blender, tmp_path, '--metadata-only')
    layers = by_name(data['layers'])
    assert 'filePath' not in layers['crate']
    assert not os.path.isdir(out / 'sprites')
    assert layers['ground']['columns'] >= 1


def test_list_params(blend_file, fake_blender, capsys):
    assert main([blend_file, '--blender', fake_blender, '--list-params']) == 0
    assert '@mainCam' in capsys.readouterr().out
