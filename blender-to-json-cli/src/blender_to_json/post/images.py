"""Image helpers for the post-processing stage."""

import os
import shutil
import subprocess

from PIL import Image

_pngquant_warned = False


def load_render(work_dir, render, trim=True):
    """Open a render and (optionally) trim transparent borders.

    Returns (image, left, top) with left/top in camera-frame pixels, or
    (None, None, None) if the render is fully transparent.
    """
    image = Image.open(os.path.join(work_dir, render['file'])).convert('RGBA')
    left, top = render['left'], render['top']
    if not trim:
        return image, left, top
    bbox = image.getchannel('A').getbbox()
    if bbox is None:
        return None, None, None
    return image.crop(bbox), left + bbox[0], top + bbox[1]


def save_png(image, path, config):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path, 'PNG')
    if config.get('optimizePngs', True):
        optimize_png(path, config)


def optimize_png(path, config):
    """Compress a PNG in place with pngquant, if it is installed."""
    global _pngquant_warned
    if shutil.which('pngquant') is None:
        if not _pngquant_warned:
            print("[blender-to-json] pngquant not found; PNGs will not be optimized")
            _pngquant_warned = True
        return
    quality = config.get('pngQualityRange', {})
    low, high = quality.get('low', 45), quality.get('high', 65)
    result = subprocess.run(
        ['pngquant', '--quality', f'{low}-{high}', '--speed', '1', '--force', '--ext', '.png', path],
        capture_output=True, text=True)
    # Exit code 99 means the quality floor couldn't be met; the original is kept.
    if result.returncode not in (0, 99):
        print(f"[blender-to-json] pngquant failed on {path}: {result.stderr.strip()}")
