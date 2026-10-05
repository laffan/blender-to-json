"""The plugin's copy of the shared core must match the CLI's (no Blender needed)."""

import filecmp
import os

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_CORE = os.path.join(PLUGIN_ROOT, '..', 'blender-to-json-cli', 'src', 'blender_to_json', 'core')
PLUGIN_CORE = os.path.join(PLUGIN_ROOT, 'blender_to_json_plugin', 'core')


def test_core_copy_matches_cli():
    names = sorted(f for f in os.listdir(CLI_CORE) if f.endswith('.py'))
    assert names == sorted(f for f in os.listdir(PLUGIN_CORE) if f.endswith('.py'))
    _, mismatch, errors = filecmp.cmpfiles(PLUGIN_CORE, CLI_CORE, names, shallow=False)
    assert not mismatch and not errors, f'run python sync_core.py ({mismatch or errors})'
