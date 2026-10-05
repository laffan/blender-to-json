"""Copy the shared core package from the CLI into the add-on.

The add-on has to be self-contained (it's installed as a zip), so it carries a
copy of blender-to-json-cli/src/blender_to_json/core. Edit the CLI's copy,
then run:

    python sync_core.py

tests/test_plugin.py fails if the two copies drift apart.
"""

import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, '..', 'blender-to-json-cli', 'src', 'blender_to_json', 'core')
TARGET = os.path.join(HERE, 'blender_to_json_plugin', 'core')


def core_files(directory):
    return sorted(f for f in os.listdir(directory) if f.endswith('.py'))


def main():
    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    os.makedirs(TARGET)
    for name in core_files(SOURCE):
        shutil.copy2(os.path.join(SOURCE, name), os.path.join(TARGET, name))
        print(f'copied core/{name}')


if __name__ == '__main__':
    main()
