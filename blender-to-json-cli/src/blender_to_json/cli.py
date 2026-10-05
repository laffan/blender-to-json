"""Command-line entry point."""

import argparse
import os
import shutil
import sys
import tempfile
import time

from . import __version__, report
from .blender_runner import BlenderError, find_blender, run_job
from .config import CONFIG_FILENAME, ConfigError, find_config, load_config, resolve_path

EPILOG = f"""
Configuration is read from ./{CONFIG_FILENAME} (or --config). Any config key
can be overridden with --set key=value (dotted keys reach into objects, values
are parsed as JSON when possible). String values written as "@name" refer to
parameters defined in the blend file with the Blender-to-JSON plugin; override
those with --param name=value.

examples:
  blender-to-json level1.blend level2.blend
  blender-to-json --config game.config --set camera=@topDown
  blender-to-json level1.blend --param width=1024 --set tile_slice_size=@tileSize
  blender-to-json level1.blend --dryrun
  blender-to-json level1.blend --only house,trees
  blender-to-json level1.blend --list-params
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog='blender-to-json',
        description='Render Blender collections/objects as game assets with a JSON manifest.',
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('files', nargs='*', help='.blend files (default: blend_files from the config)')
    parser.add_argument('-c', '--config', help=f'path to a config file (default: ./{CONFIG_FILENAME})')
    parser.add_argument('-s', '--set', action='append', default=[], metavar='KEY=VALUE',
                        help='override a config value (repeatable)')
    parser.add_argument('-p', '--param', action='append', default=[], metavar='NAME=VALUE',
                        help='set a parameter tracked in the blend file (or define a constant); repeatable')
    parser.add_argument('-o', '--output-dir', help='output directory (relative to the current directory)')
    parser.add_argument('--blender', help='path to the Blender executable')
    parser.add_argument('--only', action='append', default=[], metavar='NAMES',
                        help='export only these collections/objects (comma-separated, repeatable; layer '
                             'name or full Blender name). Results are merged into an existing data.json')
    parser.add_argument('--dryrun', '--dry-run', action='store_true',
                        help='show how each file is parsed and what would be rendered, without rendering '
                             'or writing anything')
    parser.add_argument('--metadata-only', action='store_true',
                        help='skip rendering and image processing; only write data.json')
    parser.add_argument('--watch', action='store_true', help='re-export when a .blend file changes')
    parser.add_argument('--list-params', action='store_true',
                        help='print the parameters stored in each blend file and exit')
    parser.add_argument('--keep-temp', action='store_true', help='keep the intermediate work directory')
    parser.add_argument('-v', '--verbose', action='store_true', help='show all Blender output')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    return parser


def collect_files(args, config, base_dir):
    if args.files:
        files = [os.path.abspath(f) for f in args.files]
    else:
        files = [resolve_path(f, base_dir) for f in config.get('blend_files', [])]
    if not files:
        raise ConfigError(f"no .blend files given. Pass them as arguments or list them under "
                          f"\"blend_files\" in {CONFIG_FILENAME}.")
    missing = [f for f in files if not os.path.isfile(f)]
    if missing:
        raise ConfigError('file(s) not found: ' + ', '.join(missing))
    return files


def blend_name(path):
    return os.path.splitext(os.path.basename(path))[0]


def make_job(mode, blend_file, config, work_dir, explicit=()):
    blender_config = {k: v for k, v in config.items() if k not in ('blend_files', 'parameters')}
    return {
        'mode': mode,
        'name': blend_name(blend_file),
        'work_dir': work_dir,
        'config': blender_config,
        'explicit': sorted(explicit),
        'parameters': config.get('parameters', {}),
    }


def list_params(blender, files, config, explicit, verbose):
    for blend_file in files:
        work_dir = tempfile.mkdtemp(prefix='b2j-')
        try:
            result = run_job(blender, blend_file,
                             make_job('list-params', blend_file, config, work_dir, explicit),
                             work_dir, config, verbose)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        print(report.format_params(blend_file, result))


def export_file(blender, blend_file, config, base_dir, explicit, args):
    if args.dryrun:
        mode = 'dryrun'
    else:
        mode = 'export'
        print(f"[blender-to-json] exporting {blend_file}")
    work_dir = tempfile.mkdtemp(prefix='b2j-')
    try:
        raw = run_job(blender, blend_file, make_job(mode, blend_file, config, work_dir, explicit),
                      work_dir, config, args.verbose)
        output_root = resolve_path(str(raw['config'].get('output_dir', 'output')), base_dir)
        if args.dryrun:
            print(report.format_dryrun(blend_file, raw, output_root))
            return
        from .post.process import post_process  # needs Pillow; keep other modes usable without it
        path = post_process(raw, work_dir, output_root)
        print(f"[blender-to-json] wrote {path}")
    finally:
        if args.keep_temp:
            print(f"[blender-to-json] work directory kept at {work_dir}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)


def export_all(blender, files, config, base_dir, explicit, args):
    failures = 0
    for blend_file in files:
        try:
            export_file(blender, blend_file, config, base_dir, explicit, args)
        except BlenderError as e:
            failures += 1
            print(f"[blender-to-json] ERROR exporting {blend_file}: {e}", file=sys.stderr)
    return failures


def watch(blender, files, config, base_dir, explicit, args):
    print('[blender-to-json] watching for changes (Ctrl+C to stop)...')
    mtimes = {f: os.path.getmtime(f) for f in files}
    try:
        while True:
            time.sleep(2)
            for blend_file in files:
                try:
                    mtime = os.path.getmtime(blend_file)
                except FileNotFoundError:
                    continue  # Blender briefly removes the file while saving
                if mtime > mtimes[blend_file]:
                    mtimes[blend_file] = mtime
                    print(f"[blender-to-json] change detected in {blend_file}")
                    export_all(blender, [blend_file], config, base_dir, explicit, args)
    except KeyboardInterrupt:
        print('\n[blender-to-json] stopped watching')


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config, base_dir, explicit = load_config(find_config(args.config), args.set, args.param)
        if args.output_dir:
            # A path given on the command line is relative to the cwd, not the config.
            config['output_dir'] = os.path.abspath(args.output_dir)
            explicit.add('output_dir')
        if args.metadata_only:
            config['metadataOnly'] = True
            explicit.add('metadataOnly')
        if args.only:
            config['only'] = [name.strip() for text in args.only for name in text.split(',') if name.strip()]
            explicit.add('only')
        files = collect_files(args, config, base_dir)
        blender = find_blender(args.blender or config.get('blender_path'))
    except (ConfigError, BlenderError) as e:
        print(f"blender-to-json: error: {e}", file=sys.stderr)
        return 2

    if args.list_params:
        try:
            list_params(blender, files, config, explicit, args.verbose)
        except BlenderError as e:
            print(f"blender-to-json: error: {e}", file=sys.stderr)
            return 1
        return 0

    failures = export_all(blender, files, config, base_dir, explicit, args)
    if not args.dryrun and (args.watch or config.get('generateOnSave')):
        watch(blender, files, config, base_dir, explicit, args)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
