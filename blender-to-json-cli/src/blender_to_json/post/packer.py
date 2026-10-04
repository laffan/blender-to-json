"""A simple shelf packer for texture atlases."""

import math


def pack(sizes, padding=2):
    """Pack rectangles given as [(width, height), ...].

    Returns (positions, atlas_width, atlas_height) where positions[i] is the
    (x, y) of rectangle i.
    """
    if not sizes:
        return [], 0, 0
    area = sum((w + padding) * (h + padding) for w, h in sizes)
    widest = max(w for w, _ in sizes)
    target_width = max(widest, math.ceil(math.sqrt(area)))

    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
    positions = [None] * len(sizes)
    x = y = shelf_height = used_width = 0
    for i in order:
        w, h = sizes[i]
        if x > 0 and x + w > target_width:
            y += shelf_height + padding
            x = shelf_height = 0
        positions[i] = (x, y)
        used_width = max(used_width, x + w)
        shelf_height = max(shelf_height, h)
        x += w + padding
    return positions, used_width, y + shelf_height
