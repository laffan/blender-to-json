"""Entry point executed by Blender:

    blender -b scene.blend --python-exit-code 1 --python entry.py -- job.json

The job file names a mode ("export" or "list-params"), the config, parameter
overrides and the path where the result JSON should be written.
"""

import json
import os
import sys
import traceback

# Make the `blender_to_json` package importable from Blender's Python.
_SRC = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def main(argv):
    args = argv[argv.index('--') + 1:] if '--' in argv else []
    if len(args) != 1:
        print("usage: blender -b file.blend --python entry.py -- job.json", file=sys.stderr)
        return 2

    with open(args[0]) as f:
        job = json.load(f)

    from blender_to_json.blender_stage import exporter

    try:
        if job.get('mode') == 'list-params':
            result = exporter.list_parameters(job)
        else:
            result = exporter.export(job)
    except (exporter.ExportError, exporter.ParameterError) as e:
        result = {'error': str(e), 'expected': True}
    except Exception as e:  # noqa: BLE001 - report anything to the CLI
        traceback.print_exc()
        result = {'error': f"{type(e).__name__}: {e}"}

    with open(job['result_path'], 'w') as f:
        json.dump(result, f, indent=2)
    return 1 if 'error' in result else 0


if __name__ == '__main__':
    code = main(sys.argv)
    if code:
        sys.exit(code)
