"""Locate Blender and run the in-Blender stage as a subprocess."""

import glob
import json
import os
import platform
import shutil
import subprocess
import sys

ENTRY_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'blender_stage', 'entry.py')
LOG_PREFIX = '[blender-to-json]'


class BlenderError(Exception):
    pass


def find_blender(explicit=None):
    """Find a Blender executable.

    Order: explicit path (--blender or config blender_path), $BLENDER_PATH,
    `blender` on PATH, then common install locations.
    """
    for candidate in (explicit, os.environ.get('BLENDER_PATH')):
        if candidate:
            candidate = os.path.expanduser(candidate)
            if os.path.isfile(candidate) or shutil.which(candidate):
                return candidate
            raise BlenderError(f"Blender not found at '{candidate}'")

    on_path = shutil.which('blender')
    if on_path:
        return on_path

    system = platform.system()
    patterns = []
    if system == 'Darwin':
        patterns = ['/Applications/Blender*.app/Contents/MacOS/Blender',
                    os.path.expanduser('~/Applications/Blender*.app/Contents/MacOS/Blender')]
    elif system == 'Windows':
        patterns = [r'C:\Program Files\Blender Foundation\Blender*\blender.exe']
    else:
        patterns = ['/snap/bin/blender', '/opt/blender*/blender', os.path.expanduser('~/blender*/blender')]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]

    raise BlenderError("could not find Blender. Pass --blender /path/to/blender, set "
                       "blender_path in the config, or set the BLENDER_PATH environment variable.")


def run_job(blender, blend_file, job, work_dir, config, verbose=False):
    """Run one job inside Blender and return its result dict."""
    job = dict(job)
    job['result_path'] = os.path.join(work_dir, 'result.json')
    job_path = os.path.join(work_dir, 'job.json')
    with open(job_path, 'w') as f:
        json.dump(job, f, indent=2)

    cmd = [blender, '-b', blend_file]
    if config.get('factoryStartup', True):
        cmd.append('--factory-startup')
    if config.get('enableAutoexec'):
        cmd.append('--enable-autoexec')
    cmd += ['-noaudio', '--python-exit-code', '1', '--python', ENTRY_SCRIPT, '--', job_path]

    if verbose:
        print('$ ' + ' '.join(cmd))
    tail = []
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               errors='replace')
    for line in process.stdout:
        line = line.rstrip('\n')
        tail = (tail + [line])[-40:]
        if verbose or line.startswith(LOG_PREFIX):
            print(line)
    process.wait()

    result = None
    if os.path.isfile(job['result_path']):
        with open(job['result_path']) as f:
            result = json.load(f)

    if result is None or 'error' in result or process.returncode != 0:
        message = (result or {}).get('error') or f"Blender exited with code {process.returncode}"
        if not verbose and not (result or {}).get('expected'):
            print('\n'.join(tail), file=sys.stderr)
        raise BlenderError(message)
    return result
