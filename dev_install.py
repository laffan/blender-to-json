#!/usr/bin/env python3
"""Install the CLI and the Blender plugin from this checkout. Run it after every pull.

    python3 dev_install.py                 # install / update both
    python3 dev_install.py --test          # ...and run the test suites
    python3 dev_install.py --copy          # install the packaged zip instead of linking
    python3 dev_install.py --uninstall     # remove the plugin from Blender and delete .venv

What it does:

1. CLI: creates `.venv/` in this folder (once) and installs blender-to-json-cli
   into it in editable mode, with the PSD and test extras. Python changes
   from a pull are live immediately; re-running picks up new dependencies.
2. Copies the CLI's shared `core/` package into the plugin (sync_core.py).
3. Plugin: starts Blender in the background with your normal preferences and
   - links the plugin folder into Blender's add-on directory (so after a pull
     you only need Reset Scripts, or a restart), or installs the built zip
     with --copy,
   - enables it, sets its "blender-to-json Command" preference to the CLI in
     `.venv`, and saves your preferences.

Close Blender before the first install: if it is open, it may overwrite the
saved preferences (and forget the add-on) when you quit it. Later runs are
fine with Blender open; press Reset Scripts in the plugin to load new code.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
CLI_DIR = os.path.join(ROOT, 'blender-to-json-cli')
PLUGIN_DIR = os.path.join(ROOT, 'blender-to-json-plugin')
PLUGIN_SRC = os.path.join(PLUGIN_DIR, 'blender_to_json_plugin')
WINDOWS = platform.system() == 'Windows'

# Runs inside Blender. Receives a JSON job path after "--".
BLENDER_SCRIPT = r'''
import json, os, shutil, subprocess, sys
import addon_utils, bpy

job = json.load(open(sys.argv[sys.argv.index('--') + 1]))
result = {'log': []}
log = result['log'].append
src = os.path.realpath(job['plugin_src'])


def is_link(path):
    # Windows junctions aren't reported by islink(); they resolve elsewhere.
    return os.path.islink(path) or (os.name == 'nt' and os.path.isdir(path)
                                    and os.path.realpath(path).lower() != os.path.abspath(path).lower())


def remove(path):
    if is_link(path):
        (os.rmdir if os.name == 'nt' else os.unlink)(path)  # removes the link, never its target
        log(f'removed link {path}')
    elif os.path.isdir(path):
        if os.path.realpath(path) == src:
            raise SystemExit(f'refusing to delete the source folder {path}')
        shutil.rmtree(path)
        log(f'removed {path}')


def link(target, path):
    try:
        os.symlink(target, path, target_is_directory=True)
    except OSError:
        if os.name != 'nt':
            raise
        # Windows without developer mode can't symlink; a junction works.
        subprocess.run(['cmd', '/c', 'mklink', '/J', path, target], check=True, capture_output=True)
    log(f'linked {path} -> {target}')


extensions = bpy.app.version >= (4, 2, 0)
legacy_dir = bpy.utils.user_resource('SCRIPTS', path='addons', create=True)
legacy_path = os.path.join(legacy_dir, 'blender_to_json_plugin')
if extensions:
    repo_dir = bpy.utils.user_resource('EXTENSIONS', path='user_default', create=True)
    ext_path = os.path.join(repo_dir, 'blender_to_json')
    module = 'bl_ext.user_default.blender_to_json'
else:
    ext_path = None
    module = 'blender_to_json_plugin'

# Start clean: disable and remove any earlier install, linked or copied.
for name in ('bl_ext.user_default.blender_to_json', 'blender_to_json_plugin'):
    if name in bpy.context.preferences.addons:
        addon_utils.disable(name, default_set=True)
for path in (ext_path, legacy_path):
    if path and os.path.lexists(path):
        remove(path)
if extensions:
    bpy.ops.extensions.repo_refresh_all()

if job['mode'] != 'uninstall':
    if job['mode'] == 'link':
        link(src, ext_path or legacy_path)
        if extensions:
            bpy.ops.extensions.repo_refresh_all()
    elif extensions:
        bpy.ops.extensions.package_install_files(filepath=job['zip'], repo='user_default',
                                                 enable_on_install=False, overwrite=True)
        log(f'installed {job["zip"]}')
    else:
        bpy.ops.preferences.addon_install(filepath=job['zip'], overwrite=True)
        log(f'installed {job["zip"]}')

    if addon_utils.enable(module, default_set=True) is None:
        raise SystemExit(f'could not enable {module}')
    log(f'enabled {module}')
    prefs = bpy.context.preferences.addons[module].preferences
    if job.get('cli'):
        prefs.cli_command = job['cli']
        log(f'set blender-to-json Command to {job["cli"]}')

bpy.ops.wm.save_userpref()
log('saved preferences')
result['blender'] = bpy.app.version_string
result['module'] = module
json.dump(result, open(job['result'], 'w'))
'''


def step(message):
    print(f'\n==> {message}')


def run(cmd, **kwargs):
    print('$ ' + ' '.join(cmd))
    return subprocess.run(cmd, check=True, **kwargs)


def venv_paths(venv):
    bin_dir = os.path.join(venv, 'Scripts' if WINDOWS else 'bin')
    exe = '.exe' if WINDOWS else ''
    return os.path.join(bin_dir, 'python' + exe), os.path.join(bin_dir, 'blender-to-json' + exe)


def install_cli(venv):
    step('Installing the CLI')
    python, cli = venv_paths(venv)
    if not os.path.isfile(python):
        run([sys.executable, '-m', 'venv', venv])
    run([python, '-m', 'pip', 'install', '--quiet', '--upgrade', 'pip'])
    run([python, '-m', 'pip', 'install', '--quiet', '-e', f'{CLI_DIR}[psd,test]'])
    print(f'CLI: {cli}')
    return python, cli


def sync_core():
    step('Syncing the shared core into the plugin')
    sys.path.insert(0, PLUGIN_DIR)
    import sync_core  # noqa: E402  (blender-to-json-plugin/sync_core.py)
    sys.path.pop(0)
    before = {name: open(os.path.join(sync_core.TARGET, name), 'rb').read()
              for name in sync_core.core_files(sync_core.TARGET)} if os.path.isdir(sync_core.TARGET) else {}
    sync_core.main()
    after = {name: open(os.path.join(sync_core.TARGET, name), 'rb').read()
             for name in sync_core.core_files(sync_core.TARGET)}
    changed = sorted(n for n in set(before) | set(after) if before.get(n) != after.get(n))
    if changed:
        print('Note: the plugin\'s core copy was out of date and has been updated: ' + ', '.join(changed))


def find_blender(explicit):
    sys.path.insert(0, os.path.join(CLI_DIR, 'src'))
    from blender_to_json.blender_runner import BlenderError, find_blender as find  # noqa: E402
    sys.path.pop(0)
    try:
        return find(explicit)
    except BlenderError as e:
        sys.exit(f'error: {e}')


def blender_running():
    try:
        if WINDOWS:
            out = subprocess.run(['tasklist'], capture_output=True, text=True).stdout.lower()
            return 'blender.exe' in out
        out = subprocess.run(['ps', '-A', '-o', 'comm='], capture_output=True, text=True).stdout
        return any(os.path.basename(line.strip()).lower() == 'blender' for line in out.splitlines())
    except OSError:
        return False


def build_zip():
    sys.path.insert(0, PLUGIN_DIR)
    import build  # noqa: E402  (blender-to-json-plugin/build.py)
    sys.path.pop(0)
    return build.main()


def configure_blender(blender, mode, cli=None):
    step({'link': 'Linking the plugin into Blender', 'copy': 'Installing the plugin zip into Blender',
          'uninstall': 'Removing the plugin from Blender'}[mode])
    with tempfile.TemporaryDirectory(prefix='b2j-dev-') as tmp:
        job = {'mode': mode, 'plugin_src': PLUGIN_SRC, 'cli': cli, 'result': os.path.join(tmp, 'result.json')}
        if mode == 'copy':
            job['zip'] = build_zip()
        script = os.path.join(tmp, 'install_plugin.py')
        with open(script, 'w') as f:
            f.write(BLENDER_SCRIPT)
        job_path = os.path.join(tmp, 'job.json')
        with open(job_path, 'w') as f:
            json.dump(job, f)
        proc = subprocess.run([blender, '-b', '--python-exit-code', '1', '--python', script, '--', job_path],
                              capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.isfile(job['result']):
            print(proc.stdout[-3000:], proc.stderr[-3000:], sep='\n')
            sys.exit('error: Blender could not install the plugin (output above)')
        with open(job['result']) as f:
            result = json.load(f)
    for line in result['log']:
        print('  ' + line)
    print(f"Blender {result['blender']}: {result['module']}")


def run_tests(python):
    step('Running tests')
    failed = False
    for folder in (CLI_DIR, PLUGIN_DIR):
        code = subprocess.run([python, '-m', 'pytest', '-q'], cwd=folder).returncode
        failed = failed or code not in (0, 5)  # 5: nothing collected
    if failed:
        sys.exit('error: tests failed')
    print('The Blender-backed tests are skipped unless the `bpy` module is installed in .venv '
          '(pip install bpy; needs Python 3.11).')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--blender', help='Blender executable (default: same search as the CLI)')
    parser.add_argument('--venv', default=os.path.join(ROOT, '.venv'), help='virtualenv for the CLI (default: .venv)')
    parser.add_argument('--copy', action='store_true',
                        help='install the built zip instead of linking the source folder')
    parser.add_argument('--skip-cli', action='store_true', help="don't touch the CLI")
    parser.add_argument('--skip-plugin', action='store_true', help="don't touch Blender")
    parser.add_argument('--test', action='store_true', help='run both test suites afterwards')
    parser.add_argument('--uninstall', action='store_true', help='remove the plugin from Blender and delete the venv')
    args = parser.parse_args()
    venv = os.path.abspath(args.venv)

    if args.uninstall:
        if not args.skip_plugin:
            configure_blender(find_blender(args.blender), 'uninstall')
        if not args.skip_cli and os.path.isdir(venv):
            step(f'Deleting {venv}')
            shutil.rmtree(venv)
        print('\nDone. Restart Blender if it is open.')
        return

    python, cli = (None, None)
    if not args.skip_cli:
        python, cli = install_cli(venv)
    elif os.path.isfile(venv_paths(venv)[1]):
        python, cli = venv_paths(venv)

    sync_core()

    if not args.skip_plugin:
        blender = find_blender(args.blender)
        if blender_running():
            print('\nNote: Blender seems to be running. If this is the first install, quit it and run this '
                  'script again, or it may forget the add-on when it saves its preferences on exit.')
        configure_blender(blender, 'copy' if args.copy else 'link', cli)

    if args.test:
        if python is None:
            sys.exit('error: --test needs the CLI venv (drop --skip-cli)')
        run_tests(python)

    print('\nDone.')
    if not args.skip_plugin:
        print('In Blender: restart it, or press Reset Scripts at the bottom of the Blender to JSON tab.')
    if cli:
        activate = os.path.join(venv, 'Scripts', 'activate') if WINDOWS else f'source {os.path.join(venv, "bin", "activate")}'
        print(f'CLI: {cli}\n     (or activate the venv: {activate})')


if __name__ == '__main__':
    main()
