import json

import pytest

from blender_to_json.config import ConfigError, load_config


def test_precedence(tmp_path):
    path = tmp_path / 'blender-to-json.config'
    path.write_text(json.dumps({
        'output_dir': 'assets', 'tile_slice_size': 256, 'parameters': {'a': 1},
        'pngQualityRange': {'low': 80, 'high': 90}}))
    config, base_dir, explicit = load_config(str(path), sets=['tile_slice_size=128', 'camera=@top',
                                                    'pngQualityRange.low=70'],
                                   params=['a=2', 'b="x"'])
    assert base_dir == str(tmp_path)
    assert explicit == {'output_dir', 'tile_slice_size', 'parameters', 'pngQualityRange', 'camera'}
    assert config['output_dir'] == 'assets'
    assert config['tile_slice_size'] == 128
    assert config['camera'] == '@top'
    assert config['pngQualityRange'] == {'low': 70, 'high': 90}
    assert config['parameters'] == {'a': 2, 'b': 'x'}
    assert config['renderBounds'] == 'object'  # default


def test_errors(tmp_path):
    with pytest.raises(ConfigError):
        load_config(None, sets=['nonsense'])
    bad = tmp_path / 'bad.config'
    bad.write_text('{nope')
    with pytest.raises(ConfigError):
        load_config(str(bad))
