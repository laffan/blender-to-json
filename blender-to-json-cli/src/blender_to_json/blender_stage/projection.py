"""Camera projection and render-region math. Runs inside Blender."""

import math

from mathutils import Vector


def render_resolution(scene):
    render = scene.render
    pct = render.resolution_percentage / 100.0
    return int(render.resolution_x * pct), int(render.resolution_y * pct)


class Projector:
    """Projects world-space points into the camera's pixel frame.

    Pixel space has its origin at the top-left of the rendered frame, with y
    pointing down. `depth` is the distance along the camera's view axis in
    world units (positive in front of the camera), for both perspective and
    orthographic cameras.
    """

    def __init__(self, scene, camera_obj, scale=1.0):
        cam = camera_obj.data
        if cam.type == 'PANO':
            raise ValueError(f"Camera '{camera_obj.name}' is panoramic; only perspective "
                             "and orthographic cameras are supported.")
        self.camera_obj = camera_obj
        self.ortho = cam.type == 'ORTHO'
        base_width, base_height = render_resolution(scene)
        # `scale` resizes the whole export (used to make the base tile exactly
        # `tileWidth` pixels wide) without rounding the pixel density.
        self.scale = scale
        self.width = round(base_width * scale)
        self.height = round(base_height * scale)
        self._width_f = base_width * scale
        self.inverse = camera_obj.matrix_world.normalized().inverted()

        # view_frame() accounts for sensor fit, shift and aspect. Corners are in
        # camera space; for perspective cameras rescale them to depth 1.
        frame = cam.view_frame(scene=scene)
        if not self.ortho:
            frame = [v / -v.z for v in frame]
        xs = [v.x for v in frame]
        ys = [v.y for v in frame]
        self.min_x, self.max_x = min(xs), max(xs)
        self.min_y, self.max_y = min(ys), max(ys)
        # Size of one pixel on the frame plane (world units for ortho, units at
        # depth 1 for perspective).
        self.pixel_size = (self.max_x - self.min_x) / self._width_f

    def project(self, world_co):
        """Return (x, y, depth). x/y are None if the point is behind the camera."""
        local = self.inverse @ Vector(world_co)
        depth = -local.z
        if self.ortho:
            fx, fy = local.x, local.y
        else:
            if depth <= 1e-9:
                return None, None, depth
            fx, fy = local.x / depth, local.y / depth
        x = (fx - self.min_x) / self.pixel_size
        y = (self.max_y - fy) / self.pixel_size
        return x, y, depth

    def project_many(self, world_coords):
        """Project a sequence of points, dropping any behind the camera."""
        out = []
        for co in world_coords:
            x, y, depth = self.project(co)
            if x is not None:
                out.append((x, y, depth))
        return out


def pixel_region(left, top, right, bottom, padding, limit=None, frame=None):
    """Snap a float pixel rectangle outward to whole pixels and pad it.

    If `frame` is given as (width, height) the region is clipped to it.
    Returns (left, top, right, bottom) as ints, or None if empty.
    """
    l = math.floor(left) - padding
    t = math.floor(top) - padding
    r = math.ceil(right) + padding
    b = math.ceil(bottom) + padding
    if frame is not None:
        l, t = max(l, 0), max(t, 0)
        r, b = min(r, frame[0]), min(b, frame[1])
    if r <= l or b <= t:
        return None
    if limit is not None and (r - l > limit or b - t > limit):
        raise ValueError(f"render region {r - l}x{b - t}px exceeds maxRenderSize ({limit}px)")
    return l, t, r, b


class CameraRegion:
    """Temporarily re-aims the camera so the render covers a pixel rectangle.

    The rectangle is expressed in the original frame's pixel space and may
    extend beyond it; pixel density is preserved, so the rendered image lines
    up 1:1 with the original frame at offset (left, top).
    """

    def __init__(self, scene, projector, region):
        self.scene = scene
        self.projector = projector
        self.region = region
        self._saved = None

    def __enter__(self):
        scene = self.scene
        cam_obj = self.projector.camera_obj
        cam = cam_obj.data
        render = scene.render
        self._saved = {
            'resolution_x': render.resolution_x,
            'resolution_y': render.resolution_y,
            'resolution_percentage': render.resolution_percentage,
            'use_border': render.use_border,
            'sensor_fit': cam.sensor_fit,
            'sensor_width': cam.sensor_width,
            'ortho_scale': cam.ortho_scale,
            'shift_x': cam.shift_x,
            'shift_y': cam.shift_y,
        }

        p = self.projector
        left, top, right, bottom = self.region
        width, height = right - left, bottom - top

        # New frame bounds on the frame plane (see Projector).
        new_min_x = p.min_x + left * p.pixel_size
        new_max_x = p.min_x + right * p.pixel_size
        new_max_y = p.max_y - top * p.pixel_size
        new_min_y = p.max_y - bottom * p.pixel_size
        frame_width = new_max_x - new_min_x

        render.resolution_x = width
        render.resolution_y = height
        render.resolution_percentage = 100
        render.use_border = False

        # With a horizontal sensor fit, the sensor (or ortho scale) spans the
        # frame width, and shift is expressed as a fraction of that width.
        cam.sensor_fit = 'HORIZONTAL'
        if p.ortho:
            cam.ortho_scale = frame_width
        else:
            cam.sensor_width = frame_width * cam.lens
        cam.shift_x = (new_min_x + new_max_x) / 2 / frame_width
        cam.shift_y = (new_min_y + new_max_y) / 2 / frame_width
        return self

    def __exit__(self, *exc):
        scene = self.scene
        cam = self.projector.camera_obj.data
        render = scene.render
        s = self._saved
        render.resolution_x = s['resolution_x']
        render.resolution_y = s['resolution_y']
        render.resolution_percentage = s['resolution_percentage']
        render.use_border = s['use_border']
        cam.sensor_fit = s['sensor_fit']
        cam.sensor_width = s['sensor_width']
        cam.ortho_scale = s['ortho_scale']
        cam.shift_x = s['shift_x']
        cam.shift_y = s['shift_y']
        return False
