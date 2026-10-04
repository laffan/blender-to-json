"""Slice a rendered tileset into fixed-size tiles (psd-to-json layout).

Files are written to tiles/<name>/<size>/<name>_tile_<col>_<row>.<ext>.
"""

import math
import os

from PIL import Image

from .images import optimize_png


def slice_tiles(image, name, layer_dir, config, use_jpg):
    size = int(config.get('tile_slice_size', 512))
    columns = math.ceil(image.width / size)
    rows = math.ceil(image.height / size)
    ext = 'jpg' if use_jpg else 'png'

    if not config.get('metadataOnly'):
        _write(image, os.path.join(layer_dir, 'tiles', name, str(size)), name, size, columns, rows,
               ext, config, scale=1.0)
        for scaled in config.get('tile_scaled_versions', []) or []:
            _write(image, os.path.join(layer_dir, 'tiles', name, str(scaled)), name, size, columns,
                   rows, ext, config, scale=scaled / size)

    return {'columns': columns, 'rows': rows, 'filetype': ext}


def _write(image, out_dir, name, size, columns, rows, ext, config, scale):
    os.makedirs(out_dir, exist_ok=True)
    for row in range(rows):
        for col in range(columns):
            box = (col * size, row * size,
                   min((col + 1) * size, image.width), min((row + 1) * size, image.height))
            tile = image.crop(box)
            if scale != 1.0:
                # Scale proportionally so partial edge tiles keep their aspect.
                tile = tile.resize((max(1, round(tile.width * scale)), max(1, round(tile.height * scale))),
                                   Image.LANCZOS)
            path = os.path.join(out_dir, f"{name}_tile_{col}_{row}.{ext}")
            if ext == 'jpg':
                tile.convert('RGB').save(path, 'JPEG', quality=int(config.get('jpgQuality', 85)))
            else:
                tile.save(path, 'PNG')
                if config.get('optimizePngs', True):
                    optimize_png(path, config)
