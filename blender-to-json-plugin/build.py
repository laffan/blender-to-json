"""Zip the add-on for "Install from Disk" in Blender.

    python build.py            -> dist/blender_to_json_plugin-<version>.zip
"""

import os
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = 'blender_to_json_plugin'


def main():
    with open(os.path.join(HERE, PACKAGE, 'blender_manifest.toml')) as f:
        version = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M).group(1)
    os.makedirs(os.path.join(HERE, 'dist'), exist_ok=True)
    out = os.path.join(HERE, 'dist', f'{PACKAGE}-{version}.zip')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(os.path.join(HERE, PACKAGE)):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for name in files:
                if name.endswith('.pyc'):
                    continue
                path = os.path.join(root, name)
                zf.write(path, os.path.relpath(path, HERE))
    print(out)


if __name__ == '__main__':
    main()
