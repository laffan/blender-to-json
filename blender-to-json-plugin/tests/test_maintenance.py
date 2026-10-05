"""Reset Scripts and Uninstall against a linked install, in a throwaway Blender home.

Runs in a subprocess so Blender's real user config is never touched.
"""

import os
import shutil
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip('bpy')

PLUGIN_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'blender_to_json_plugin')

SCRIPT = textwrap.dedent('''
    import os, sys
    import bpy
    import addon_utils

    copy = sys.argv[1]
    repo = bpy.utils.user_resource('EXTENSIONS', path='user_default', create=True)
    link = os.path.join(repo, 'blender_to_json')
    os.symlink(copy, link)
    bpy.ops.extensions.repo_refresh_all()
    module = 'bl_ext.user_default.blender_to_json'
    assert addon_utils.enable(module, default_set=True) is not None

    maintenance = sys.modules[module + '.maintenance']
    assert maintenance.install_info() == ('linked', os.path.realpath(copy)), maintenance.install_info()
    assert bpy.types.B2J_PT_main.bl_category == 'Blender to JSON'

    # Simulate a git pull: change a panel and a shared core module.
    ui = os.path.join(copy, 'ui.py')
    source = open(ui).read()
    assert "CATEGORY = 'Blender to JSON'" in source
    open(ui, 'w').write(source.replace("CATEGORY = 'Blender to JSON'", "CATEGORY = 'Pulled'"))
    with open(os.path.join(copy, 'core', 'plan.py'), 'a') as f:
        f.write('\\nRELOAD_MARKER = 1\\n')

    maintenance.reset_scripts()
    assert bpy.types.B2J_PT_main.bl_category == 'Pulled', bpy.types.B2J_PT_main.bl_category
    assert sys.modules[module + '.core.plan'].RELOAD_MARKER == 1
    assert module in bpy.context.preferences.addons

    sys.modules[module + '.maintenance'].uninstall()
    assert not os.path.lexists(link)
    assert module not in bpy.context.preferences.addons
    assert not hasattr(bpy.types, 'B2J_PT_main')
    print('MAINTENANCE OK')
''')


def test_reset_scripts_and_uninstall(tmp_path):
    copy = tmp_path / 'plugin_copy'
    shutil.copytree(PLUGIN_SRC, copy, ignore=shutil.ignore_patterns('__pycache__'))
    script = tmp_path / 'check.py'
    script.write_text(SCRIPT)
    env = dict(os.environ, HOME=str(tmp_path / 'home'), APPDATA=str(tmp_path / 'home'))
    result = subprocess.run([sys.executable, str(script), str(copy)], env=env, capture_output=True, text=True)
    assert 'MAINTENANCE OK' in result.stdout, result.stdout[-2000:] + result.stderr[-2000:]
    # The linked source folder survives the uninstall.
    assert (copy / '__init__.py').is_file() and (copy / 'core' / 'plan.py').is_file()
