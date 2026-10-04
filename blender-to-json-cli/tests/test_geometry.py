from blender_to_json.geometry import bounds, convex_hull


def test_square_hull_drops_interior_points():
    pts = [(0, 0, 1), (10, 0, 2), (10, 10, 3), (0, 10, 4), (5, 5, 0), (5, 0, 9)]
    hull = convex_hull(pts)
    assert sorted(p[:2] for p in hull) == [(0, 0), (0, 10), (10, 0), (10, 10)]
    # depth rides along with its vertex
    assert dict(((p[0], p[1]), p[2]) for p in hull)[(10, 10)] == 3


def test_duplicate_xy_keeps_nearest_depth():
    hull = convex_hull([(0, 0, 5), (0, 0, 2), (4, 0, 1), (0, 4, 1)])
    assert (0, 0, 2) in hull


def test_degenerate():
    assert convex_hull([]) == []
    assert convex_hull([(1, 1, 0)]) == [(1, 1, 0)]
    assert bounds([]) is None
    assert bounds([(1, 5), (3, 2)]) == (1, 2, 3, 5)
