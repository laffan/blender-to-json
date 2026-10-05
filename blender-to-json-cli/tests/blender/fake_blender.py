"""Stand-in for the Blender executable, backed by the `bpy` pip module.

Understands the subset of Blender's command line that the CLI uses:
    fake_blender.py -b [file.blend] [flags...] --python script.py -- args...
"""

import runpy
import sys

import bpy


def main():
    args = sys.argv[1:]
    blend = args[args.index('-b') + 1]
    script = args[args.index('--python') + 1]
    if blend.endswith('.blend'):
        bpy.ops.wm.open_mainfile(filepath=blend)
    sys.argv = ['blender'] + args
    runpy.run_path(script, run_name='__main__')


if __name__ == '__main__':
    main()
