"""Isolated renders and projection, driven by the shared plan. Runs inside Blender.

Produces `raw.json` plus untrimmed renders in a work directory; the
post-processing stage (system Python + Pillow) turns those into the final
assets and `data.json`.
"""

import os
from collections import defaultdict

import bpy
from mathutils import Vector

from ..core import plan as planner
from ..core.geometry import bounds, convex_hull
from ..core.parameters import (ParameterError, apply_parameters, read_scene_parameters, read_scene_settings,
                               resolve_references)
from .projection import CameraRegion, Projector, pixel_region

NON_RENDERABLE_TYPES = planner.NON_RENDERABLE_TYPES
MESH_CONVERTIBLE_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'CURVES', 'POINTCLOUD'}


class ExportError(Exception):
    pass


def _round(value, places=2):
    return None if value is None else round(value, places)


def _xyd(x, y, depth):
    return {'x': _round(x), 'y': _round(y), 'depth': _round(depth, 4)}


class Geometry:
    """World-space geometry lookups backed by the evaluated depsgraph."""

    def __init__(self, depsgraph):
        self.depsgraph = depsgraph
        self.corners = defaultdict(list)
        self.directly_visible = set()
        # Instances (collection instances, geometry-node instances, particles)
        # are attributed to the object that instances them.
        for inst in depsgraph.object_instances:
            owner = inst.parent if inst.is_instance else inst.object
            if owner is None:
                continue
            if not inst.is_instance:
                self.directly_visible.add(owner.original.as_pointer())
            obj = inst.object
            if obj.type in NON_RENDERABLE_TYPES:
                continue
            matrix = inst.matrix_world
            self.corners[owner.original.as_pointer()].extend(matrix @ Vector(c) for c in obj.bound_box)

    def object_corners(self, obj):
        corners = self.corners.get(obj.as_pointer())
        if corners:
            return corners
        if obj.type in NON_RENDERABLE_TYPES:
            return []
        # Not in the evaluated depsgraph (e.g. disabled in viewports).
        return [obj.matrix_world @ Vector(c) for c in obj.bound_box]

    def corners_for(self, objects):
        corners = []
        for obj in objects:
            corners.extend(self.object_corners(obj))
        return corners

    def object_vertices(self, obj):
        """World-space vertices of an object's evaluated geometry, including
        anything it instances. Falls back to the origin."""
        pointer = obj.as_pointer()
        verts = []
        found = False
        for inst in self.depsgraph.object_instances:
            owner = inst.parent if inst.is_instance else inst.object
            if owner is None or owner.original.as_pointer() != pointer:
                continue
            found = True
            verts.extend(_evaluated_vertices(inst.object, inst.matrix_world))
        if not found and obj.type == 'MESH':
            verts.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        if not verts:
            verts.append(obj.matrix_world.translation.copy())
        return verts


def _evaluated_vertices(eval_obj, matrix):
    if eval_obj.type not in MESH_CONVERTIBLE_TYPES:
        return [matrix.translation.copy()]
    if eval_obj.type == 'MESH':
        return [matrix @ v.co for v in eval_obj.data.vertices]
    try:
        mesh = eval_obj.to_mesh()
    except RuntimeError:
        return [matrix.translation.copy()]
    try:
        return [matrix @ v.co for v in mesh.vertices] if mesh else []
    finally:
        eval_obj.to_mesh_clear()


class Exporter:
    def __init__(self, scene, projector, geometry, config, params, work_dir, holdout=None, dryrun=False):
        self.scene = scene
        self.projector = projector
        self.geometry = geometry
        self.config = config
        self.params = params
        self.work_dir = work_dir
        self.render_dir = os.path.join(work_dir, 'renders')
        self.holdout = holdout
        self.dryrun = dryrun
        self.warnings = []
        self.render_count = 0

        self.metadata_only = dryrun or bool(config.get('metadataOnly'))
        self.render_bounds = config.get('renderBounds', 'object')
        if self.render_bounds not in ('object', 'frame'):
            raise ExportError(f"renderBounds must be 'object' or 'frame', got {self.render_bounds!r}")
        self.padding = int(config.get('renderPadding', 2))
        self.max_render_size = int(config.get('maxRenderSize', 16384))
        self.cast_shadows = bool(config.get('castShadowsFromHidden', False))
        self._holdout_objects = {o.as_pointer() for o in holdout.all_objects} if holdout else set()

    def warn(self, message):
        print(f"[blender-to-json] WARNING: {message}")
        self.warnings.append(message)

    # ------------------------------------------------------------------ geometry

    def _anchor(self, kind, item, corners):
        """Projected anchor: the origin for objects, the bounding-box centre
        for collections. Returns (x, y, depth) or None."""
        if kind == 'object':
            co = item.matrix_world.translation
        elif corners:
            lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
            hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
            co = (lo + hi) / 2
        else:
            return None
        x, y, depth = self.projector.project(co)
        return None if x is None else (x, y, depth)

    def _add_geometry_info(self, node, kind, item, objects):
        corners = self.geometry.corners_for(objects)
        anchor = self._anchor(kind, item, corners)
        node['origin'] = _xyd(*anchor) if anchor else None
        projected = self.projector.project_many(corners)
        if len(projected) < len(corners):
            self.warn(f"'{item.name}' is partly behind the camera; its bounds are approximate")
        if not projected:
            node['bounds'] = node['depthRange'] = None
            return None
        box = bounds(projected)
        depths = [p[2] for p in projected]
        node['bounds'] = {'left': _round(box[0]), 'top': _round(box[1]),
                          'right': _round(box[2]), 'bottom': _round(box[3])}
        node['depthRange'] = {'near': _round(min(depths), 4), 'far': _round(max(depths), 4)}
        return box

    # ------------------------------------------------------------------ plan -> nodes

    def emit(self, plan_nodes):
        out = []
        for p in plan_nodes:
            if p.warning and p.status != planner.EXPORT:
                self.warn(f"'{p.blender_name}': {p.warning}; skipped")
            if p.status == planner.HOIST and not self.dryrun:
                out.extend(self.emit(p.children))
                continue
            if p.status == planner.CONTENT and not self.dryrun:
                # Already in the parent's render; named layers inside still count.
                out.extend(self.emit(p.children))
                continue
            if p.status != planner.EXPORT:
                if self.dryrun:
                    out.append(self._skipped_node(p))
                continue
            if p.warning:
                self.warn(f"'{p.blender_name}': {p.warning}")
            node = self._build(p)
            if node is not None:
                out.append(node)
        return out

    def _skipped_node(self, p):
        node = p.to_dict()
        node.pop('children', None)
        node.pop('frames', None)
        if p.children:
            node['children'] = self.emit(p.children)
        return node

    def _resolve_attributes(self, p):
        try:
            return resolve_references(p.attributes, self.params, f"'{p.blender_name}' attributes")
        except ParameterError as e:
            self.warn(str(e))
            return p.attributes

    def _build(self, p):
        node = {
            'name': p.name,
            'category': p.category,
            'attributes': self._resolve_attributes(p),
            'source': {'kind': p.kind, 'name': p.blender_name},
        }
        if p.type:
            node['type'] = p.type
        if p.kind == 'object':
            node['source']['objectType'] = p.item.type
        if p.only_root:
            node['onlyRoot'] = True
        if p.holdout:
            node['holdout'] = True
        if self.dryrun:
            node['status'] = planner.EXPORT

        builder = {
            'group': self._build_group,
            'point': self._build_point,
            'zone': self._build_zone,
            'sprite': self._build_sprite,
            'tileset': self._build_rendered,
        }[p.category]
        return builder(p, node)

    def _build_group(self, p, node):
        self._add_geometry_info(node, p.kind, p.item, planner.render_objects(p.kind, p.item))
        node['children'] = self.emit(p.children)
        return node

    def _build_point(self, p, node):
        x, y, depth = self.projector.project(p.item.matrix_world.translation)
        if x is None:
            self.warn(f"point '{p.blender_name}' is behind the camera; skipped")
            return None
        node['origin'] = _xyd(x, y, depth)
        return node

    def _build_zone(self, p, node):
        objects = [p.item] if p.kind == 'object' else list(p.item.all_objects)
        verts = []
        for obj in objects:
            verts.extend(self.geometry.object_vertices(obj))
        projected = self.projector.project_many(verts)
        if len(projected) < len(verts):
            self.warn(f"zone '{p.blender_name}' is partly behind the camera; hidden vertices ignored")
        if not projected:
            self.warn(f"zone '{p.blender_name}' has no vertices in front of the camera; skipped")
            return None
        hull = convex_hull([(_round(x), _round(y), depth) for x, y, depth in projected])
        node['points'] = [{'x': x, 'y': y, 'depth': _round(d, 4)} for x, y, d in hull]
        depths = [pt[2] for pt in projected]
        node['depthRange'] = {'near': _round(min(depths), 4), 'far': _round(max(depths), 4)}
        anchor = self._anchor(p.kind, p.item, verts)
        node['origin'] = _xyd(*anchor) if anchor else None
        return node

    def _build_sprite(self, p, node):
        if p.type in ('atlas', 'spritesheet'):
            self._add_geometry_info(node, p.kind, p.item, planner.render_objects(p.kind, p.item))
            node['frames'] = [self._build_frame(f) for f in p.frames]
            return node
        if p.type == 'animation':
            self._add_geometry_info(node, p.kind, p.item, planner.render_objects(p.kind, p.item))
            return node
        return self._build_rendered(p, node)

    def _build_rendered(self, p, node):
        objects = planner.render_objects(p.kind, p.item)
        box = self._add_geometry_info(node, p.kind, p.item, objects)
        node['render'] = self._render(objects, box, p.blender_name)
        children = self.emit(p.children)
        if children:
            node['children'] = children
        return node

    def _build_frame(self, f):
        frame = {
            'name': f.name,
            'attributes': self._resolve_attributes(f),
            'source': {'kind': f.kind, 'name': f.blender_name},
        }
        objects = planner.render_objects(f.kind, f.item)
        box = self._add_geometry_info(frame, f.kind, f.item, objects)
        frame['render'] = self._render(objects, box, f.blender_name)
        return frame

    # ------------------------------------------------------------------ rendering

    def _render(self, objects, box, label):
        if not objects or box is None:
            self.warn(f"'{label}' has no renderable geometry")
            return None
        frame = (self.projector.width, self.projector.height)
        try:
            region = pixel_region(*box, self.padding, self.max_render_size,
                                  frame if self.render_bounds == 'frame' else None)
        except ValueError as e:
            self.warn(f"'{label}': {e}; skipped")
            return None
        if region is None:
            self.warn(f"'{label}' is outside the camera frame; not rendered")
            return None

        left, top, right, bottom = region
        info = {'left': left, 'top': top, 'width': right - left, 'height': bottom - top,
                'objects': len(objects)}
        if self.metadata_only:
            return info

        self.render_count += 1
        filename = f"{self.render_count:04d}.png"
        filepath = os.path.join(self.render_dir, filename)
        print(f"[blender-to-json] rendering '{label}' ({info['width']}x{info['height']})")

        targets = {o.as_pointer() for o in objects}
        # Hiding an instanced collection's objects also hides the instances,
        # so those sources have to stay visible.
        sources = self._instance_sources(objects) - targets
        shown = sources & self.geometry.directly_visible
        if shown:
            names = ', '.join(sorted(o.name for o in self.scene.objects if o.as_pointer() in shown))
            self.warn(f"'{label}' instances objects that are also visible in the scene ({names}); "
                      "they may appear in its render. Exclude their collection from the view layer.")
        saved = self._isolate(targets | sources)
        try:
            with CameraRegion(self.scene, self.projector, region):
                self.scene.render.filepath = filepath
                bpy.ops.render.render(write_still=True, scene=self.scene.name)
        finally:
            self._restore(saved)

        info['file'] = os.path.join('renders', filename)
        return info

    @staticmethod
    def _instance_sources(objects):
        sources = set()
        seen = set()
        stack = list(objects)
        while stack:
            obj = stack.pop()
            col = obj.instance_collection if obj.instance_type == 'COLLECTION' else None
            if col is None or col.as_pointer() in seen:
                continue
            seen.add(col.as_pointer())
            for child in col.all_objects:
                sources.add(child.as_pointer())
                stack.append(child)
        return sources

    def _isolate(self, targets):
        saved = {}
        for obj in self.scene.objects:
            if obj.type in NON_RENDERABLE_TYPES:
                continue
            saved[obj.name] = (obj.hide_render, obj.visible_camera, obj.is_holdout)
            pointer = obj.as_pointer()
            if pointer in targets:
                continue  # keep the user's own visibility settings
            if pointer in self._holdout_objects:
                # Ground objects cut away whatever is behind/below them.
                obj.is_holdout = True
                obj.visible_camera = True
            elif self.cast_shadows:
                obj.visible_camera = False
            else:
                obj.hide_render = True
        return saved

    def _restore(self, saved):
        for name, (hide_render, visible_camera, is_holdout) in saved.items():
            obj = self.scene.objects.get(name)
            if obj is not None:
                obj.hide_render = hide_render
                obj.visible_camera = visible_camera
                obj.is_holdout = is_holdout

    # ------------------------------------------------------------------ output

    def camera_info(self):
        cam_obj = self.projector.camera_obj
        cam = cam_obj.data
        loc, rot, _scale = cam_obj.matrix_world.decompose()
        info = {
            'name': cam_obj.name,
            'type': 'orthographic' if self.projector.ortho else 'perspective',
            'location': [_round(v, 4) for v in loc],
            'rotation': [_round(v, 6) for v in rot],  # quaternion w, x, y, z
            'clipStart': _round(cam.clip_start, 4),
            'clipEnd': _round(cam.clip_end, 4),
        }
        if self.projector.ortho:
            info['orthoScale'] = _round(cam.ortho_scale, 4)
            info['pixelsPerUnit'] = _round(1 / self.projector.pixel_size, 4)
        else:
            info['lens'] = _round(cam.lens, 4)
            info['sensorWidth'] = _round(cam.sensor_width, 4)
            info['fieldOfView'] = _round(cam.angle, 6)
        if self.projector.scale != 1:
            info['scale'] = _round(self.projector.scale, 6)
        return info


# ---------------------------------------------------------------------- job setup

def _pick_scene(name):
    if not name:
        return bpy.context.scene
    scene = bpy.data.scenes.get(name)
    if scene is None:
        raise ExportError(f"scene '{name}' not found")
    return scene


def _pick_object(name, label, camera=False):
    if not name:
        return None
    obj = bpy.data.objects.get(name)
    if obj is None or (camera and obj.type != 'CAMERA'):
        raise ExportError(f"{label} '{name}' not found" + (' (or is not a camera)' if camera else ''))
    return obj


def _pick_collection(name, label):
    if not name:
        return None
    col = bpy.data.collections.get(name)
    if col is None:
        raise ExportError(f"{label} collection '{name}' not found")
    return col


def _apply_render_settings(scene, config):
    render = scene.render
    resolution = config.get('resolution')
    if resolution:
        render.resolution_x, render.resolution_y = int(resolution[0]), int(resolution[1])
    if config.get('resolutionPercentage'):
        render.resolution_percentage = int(config['resolutionPercentage'])
    if config.get('renderEngine'):
        render.engine = config['renderEngine']
    samples = config.get('samples')
    if samples:
        if render.engine == 'CYCLES':
            scene.cycles.samples = int(samples)
        elif hasattr(scene, 'eevee'):
            scene.eevee.taa_render_samples = int(samples)
    render.film_transparent = True
    render.use_border = False
    settings = render.image_settings
    settings.file_format = 'PNG'
    settings.color_mode = 'RGBA'
    settings.color_depth = '8'


def merge_blend_settings(config, settings, explicit):
    """Layer the plugin's stored settings under the config file and --set.

    Precedence: defaults < blend settings < config file < --set.
    ignoreLayers lists are combined rather than replaced.
    """
    config = dict(config)
    for key, value in settings.items():
        if key == 'ignoreLayers':
            config[key] = list(dict.fromkeys(list(config.get(key) or []) + list(value or [])))
        elif key not in explicit:
            config[key] = value
    if isinstance(config.get('output_dir'), str) and config['output_dir'].startswith('//') \
            and 'output_dir' not in explicit:
        config['output_dir'] = bpy.path.abspath(config['output_dir'])
    return config


def resolve_job(job):
    """Resolve the scene, parameters and config for a job.

    Returns (scene, params, config, problems).
    """
    config = dict(job.get('config', {}))
    config.pop('parameters', None)  # passed separately as job['parameters']
    scene_name = config.get('scene')
    if isinstance(scene_name, str) and scene_name.startswith('@'):
        # A scene reference can only be resolved against the active scene.
        values, _ = apply_parameters(read_scene_parameters(bpy.context.scene), {})
        scene_name = resolve_references(scene_name, values, 'scene')
    scene = _pick_scene(scene_name)

    config = merge_blend_settings(config, read_scene_settings(scene), set(job.get('explicit', ())))
    params, problems = apply_parameters(read_scene_parameters(scene), job.get('parameters'))
    config = resolve_references(config, params)
    return scene, params, config, problems


def list_parameters(job):
    scene = _pick_scene(job.get('config', {}).get('scene'))
    entries = read_scene_parameters(scene)
    values, problems = apply_parameters(entries, {})
    for name, entry in entries.items():
        entry['value'] = values.get(name)
    return {'scene': scene.name, 'parameters': entries, 'settings': read_scene_settings(scene),
            'warnings': problems}


def _depsgraph(scene):
    if scene == bpy.context.scene:
        return bpy.context.evaluated_depsgraph_get()
    depsgraph = scene.view_layers[0].depsgraph
    depsgraph.update()
    return depsgraph


def _base_tile_info(scene, camera_obj, geometry, config):
    """Measure the base tile and work out the export scale.

    Returns (scale, info) where info describes the base tile in final pixels.
    """
    base = _pick_object(config.get('baseTile'), 'base tile')
    if base is None:
        if config.get('tileWidth') or config.get('snapToTileGrid'):
            raise ExportError('tileWidth and snapToTileGrid need a baseTile object')
        return 1.0, None
    unscaled = Projector(scene, camera_obj)
    projected = unscaled.project_many(geometry.object_vertices(base))
    box = bounds(projected)
    if box is None or box[2] - box[0] <= 0:
        raise ExportError(f"base tile '{base.name}' has no visible width from the camera")
    tile_width = config.get('tileWidth')
    scale = float(tile_width) / (box[2] - box[0]) if tile_width else 1.0

    ox, oy, _ = unscaled.project(base.matrix_world.translation)
    info = {
        'name': base.name,
        'width': _round((box[2] - box[0]) * scale, 3),
        'height': _round((box[3] - box[1]) * scale, 3),
        'originX': _round((ox - box[0]) * scale, 3),
        'originY': _round((oy - box[1]) * scale, 3),
    }
    return scale, info


def export(job):
    work_dir = job['work_dir']
    dryrun = job.get('mode') == 'dryrun'
    os.makedirs(os.path.join(work_dir, 'renders'), exist_ok=True)

    scene, params, config, problems = resolve_job(job)
    camera_obj = _pick_object(config.get('camera'), 'camera', camera=True) or scene.camera
    if camera_obj is None:
        raise ExportError(f"scene '{scene.name}' has no active camera")
    scene.camera = camera_obj
    _apply_render_settings(scene, config)
    holdout = _pick_collection(config.get('holdoutCollection'), 'holdout')

    geometry = Geometry(_depsgraph(scene))
    scale, base_tile = _base_tile_info(scene, camera_obj, geometry, config)
    projector = Projector(scene, camera_obj, scale)
    if abs(scene.render.pixel_aspect_x - scene.render.pixel_aspect_y) > 1e-6:
        problems.append('non-square pixel aspect is not supported; positions will be distorted')

    options = planner.PlanOptions.from_config(config, holdout)
    plan = planner.build_plan(scene.collection, options)
    for name in sorted(options.only - options.only_matched):
        problems.append(f"--only '{name}' didn't match any collection or object")

    exporter = Exporter(scene, projector, geometry, config, params, work_dir, holdout, dryrun)
    for message in problems:
        exporter.warn(message)
    layers = exporter.emit(plan)

    result = {
        'name': str(config.get('name') or job['name']),
        'source': bpy.data.filepath,
        'scene': scene.name,
        'width': projector.width,
        'height': projector.height,
        'camera': exporter.camera_info(),
        'config': config,
        'parameters': params,
        'layers': layers,
        'warnings': exporter.warnings,
    }
    if base_tile:
        result['baseTile'] = base_tile
    if config.get('only'):
        result['only'] = list(config['only'])
    if dryrun:
        result['summary'] = planner.summarize(plan)
    return result
