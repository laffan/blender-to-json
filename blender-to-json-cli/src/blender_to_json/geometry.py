"""2D geometry helpers (pure Python, usable inside and outside Blender)."""


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(points):
    """Andrew's monotone chain.

    `points` are tuples whose first two items are x and y; any extra items
    (e.g. depth) ride along with the hull vertex they belong to. When several
    input points share the same x/y, the one nearest the camera (smallest
    third item, if present) is kept.

    Returns hull vertices in clockwise order in image space (y down), which is
    counter-clockwise in Blender's y-up camera space.
    """
    unique = {}
    for p in points:
        key = (p[0], p[1])
        if key not in unique or (len(p) > 2 and p[2] < unique[key][2]):
            unique[key] = p
    pts = sorted(unique.values(), key=lambda p: (p[0], p[1]))
    if len(pts) <= 2:
        return pts

    lower = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def bounds(points):
    """Return (left, top, right, bottom) of the x/y of `points`, or None."""
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)
