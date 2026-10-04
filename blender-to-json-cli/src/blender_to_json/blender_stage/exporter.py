"""Scene traversal, isolated renders and projection. Runs inside Blender.

Produces `raw.json` plus untrimmed renders in a work directory; the
post-processing stage (system Python + Pillow) turns those into the final
assets and `data.json`.
"""

import json
import os
from collections import defaultdict

import bpy
from mathutils import Vector

from ..geometry import bounds, convex_hull
from ..naming import parse_layer_name
from .parameters import ParameterError, merge_parameters, read_scene_parameters, resolve_references
from .projection import CameraRegion, Projector, pixel_region, render_resolution

NON_RENDERABLE_TYPES = {'LIGHT', 'CAMERA', 'LIGHT_PROBE', 'LIGHTPROBE', 'SPEAKER'}
MESH_CONVERTIBLE_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'CURVES', 'POINTCLOUD'}
PLUGIN_PROPERTY_KEYS = {'blender_to_json', 'cycles', '_RNA_UI'}


class ExportError(Exception):
    pass


def _round(value, places=2):
    return None if value is None else round(value, places)


def _xyd(x, y, depth):
    return {'x': _round(x), 'y': _round(y), 'depth': _round(depth, 4)}


def _jsonable(value):
    if hasattr(value, 'to_dict'):
        value = value.to_dict()
    elif hasattr(value, 'to_list'):
        value = value.to_list()
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return None
    return value


class Exporter:
    def __init__(self, scene, camera_obj, config, params, work_dir):
        self.scene = scene
        self.config = config
        self.params = params
        self.work_dir = work_dir
        self.render_dir = os.path.join(work_dir, 'renders')
        self.warnings = []
        self.render_count = 0

        self.projector = Projector(scene, camera_obj)
        self.metadata_only = bool(config.get('metadataOnly'))
        self.render_bounds = config.get('renderBounds', 'object')
        if self.render_bounds not in ('object', 'frame'):
            raise ExportError(f"renderBounds must be 'object' or 'frame', got {self.render_bounds!r}")
        self.padding = int(config.get('renderPadding', 2))
        self.max_render_size = int(config.get('maxRenderSize', 16384))
        self.ignore = set(config.get('ignoreLayers', []))
        self.pass_through = bool(config.get('passThroughUnnamedCollections', False))
        self.use_custom_props = bool(config.get('customPropertiesAsAttributes', True))
        self.cast_shadows = bool(config.get('castShadowsFromHidden', False))

        render = scene.render
        if abs(render.pixel_aspect_x - render.pixel_aspect_y) > 1e-6:
            self.warn('non-square pixel aspect is not supported; positions will be distorted')

        if scene == bpy.context.scene:
            self.depsgraph = bpy.context.evaluated_depsgraph_get()
        else:
            self.depsgraph = scene.view_layers[0].depsgraph
            self.depsgraph.update()
        self._corners = self._index_bound_box_corners()

    def warn(self, message):
        print(f"[blender-to-json] WARNING: {message}")
        self.warnings.append(message)

    # ------------------------------------------------------------------ geometry

    def _index_bound_box_corners(self):
        """Map original object pointer -> world-space bounding-box corners.

        Instances (collection instances, geometry-node instances, particles)
        are attributed to the object that instances them.
        """
        index = defaultdict(list)
        self._directly_visible = set()
        for inst in self.depsgraph.object_instances:
            owner = inst.parent if inst.is_instance else inst.object
            if owner is None:
                continue
            if not inst.is_instance:
                self._directly_visible.add(owner.original.as_pointer())
            obj = inst.object
            if obj.type in NON_RENDERABLE_TYPES:
                continue
            matrix = inst.matrix_world
            corners = [matrix @ Vector(c) for c in obj.bound_box]
            index[owner.original.as_pointer()].extend(corners)
        return index

    def _object_corners(self, obj):
        corners = self._corners.get(obj.as_pointer())
        if corners:
            return corners
        if obj.type in NON_RENDERABLE_TYPES:
            return []
        # Not in the evaluated depsgraph (e.g. disabled in viewports).
        return [obj.matrix_world @ Vector(c) for c in obj.bound_box]

    def _object_vertices(self, obj):
        """World-space vertex positions of an object's evaluated geometry,
        including anything it instances. Falls back to the origin."""
        pointer = obj.as_pointer()
        verts = []
        found = False
        for inst in self.depsgraph.object_instances:
            owner = inst.parent if inst.is_instance else inst.object
            if owner is None or owner.original.as_pointer() != pointer:
                continue
            found = True
            verts.extend(self._evaluated_vertices(inst.object, inst.matrix_world))
        if not found and obj.type == 'MESH':
            verts.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        if not verts:
            verts.append(obj.matrix_world.translation.copy())
        return verts

    @staticmethod
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

    def _corners_for(self, objects):
        corners = []
        for obj in objects:
            corners.extend(self._object_corners(obj))
        return corners

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
        if x is None:
            return None
        return x, y, depth

    def _projected_bounds(self, corners, label):
        projected = self.projector.project_many(corners)
        if len(projected) < len(corners):
            self.warn(f"'{label}' is partly behind the camera; its bounds are approximate")
        if not projected:
            return None, None
        box = bounds(projected)
        depths = [p[2] for p in projected]
        return box, (min(depths), max(depths))

    # ------------------------------------------------------------------ traversal

    def _children(self, collection):
        items = [('collection', c) for c in collection.children]
        items += [('object', o) for o in collection.objects]
        return items

    def _parse(self, item):
        parsed = parse_layer_name(item.name)
        if parsed is None or parsed['name'] in self.ignore:
            return None
        attributes = {}
        if self.use_custom_props:
            for key in item.keys():
                if key.startswith('_') or key in PLUGIN_PROPERTY_KEYS:
                    continue
                value = _jsonable(item[key])
                if value is not None:
                    attributes[key] = value
        attributes.update(parsed['attributes'])
        try:
            parsed['attributes'] = resolve_references(attributes, self.params, f"'{item.name}' attributes")
        except ParameterError as e:
            self.warn(str(e))
            parsed['attributes'] = attributes
        return parsed

    def walk(self, collection):
        nodes = []
        for kind, item in self._children(collection):
            parsed = self._parse(item)
            if parsed is None:
                if kind == 'collection' and self.pass_through:
                    nodes.extend(self.walk(item))
                continue
            node = self._build(kind, item, parsed)
            if node is not None:
                nodes.append(node)
        return nodes

    def _build(self, kind, item, parsed):
        category = parsed['category']
        node = {
            'name': parsed['name'],
            'category': category,
            'attributes': parsed['attributes'],
            'source': {'kind': kind, 'name': item.name},
        }
        if 'type' in parsed:
            node['type'] = parsed['type']
        if kind == 'object':
            node['source']['objectType'] = item.type

        builder = {
            'group': self._build_group,
            'point': self._build_point,
            'zone': self._build_zone,
            'sprite': self._build_sprite,
            'tileset': self._build_tileset,
        }[category]
        return builder(kind, item, node)

    def _add_geometry_info(self, node, kind, item, objects):
        corners = self._corners_for(objects)
        anchor = self._anchor(kind, item, corners)
        node['origin'] = _xyd(*anchor) if anchor else None
        box, depth_range = self._projected_bounds(corners, item.name)
        node['bounds'] = None if box is None else {
            'left': _round(box[0]), 'top': _round(box[1]),
            'right': _round(box[2]), 'bottom': _round(box[3]),
        }
        node['depthRange'] = None if depth_range is None else {
            'near': _round(depth_range[0], 4), 'far': _round(depth_range[1], 4),
        }
        return box

    def _build_group(self, kind, item, node):
        if kind != 'collection':
            self.warn(f"'{item.name}': G must be a collection; skipped")
            return None
        self._add_geometry_info(node, kind, item, self._render_objects(item))
        node['children'] = self.walk(item)
        return node

    def _build_point(self, kind, item, node):
        if kind != 'object':
            self.warn(f"'{item.name}': P must be a single object (empty or mesh); skipped")
            return None
        x, y, depth = self.projector.project(item.matrix_world.translation)
        if x is None:
            self.warn(f"point '{item.name}' is behind the camera; skipped")
            return None
        node['origin'] = _xyd(x, y, depth)
        return node

    def _build_zone(self, kind, item, node):
        objects = [item] if kind == 'object' else list(item.all_objects)
        verts = []
        for obj in objects:
            verts.extend(self._object_vertices(obj))
        projected = self.projector.project_many(verts)
        if len(projected) < len(verts):
            self.warn(f"zone '{item.name}' is partly behind the camera; hidden vertices ignored")
        if not projected:
            self.warn(f"zone '{item.name}' has no vertices in front of the camera; skipped")
            return None
        hull = convex_hull([(_round(x), _round(y), depth) for x, y, depth in projected])
        node['points'] = [{'x': x, 'y': y, 'depth': _round(d, 4)} for x, y, d in hull]
        depths = [p[2] for p in projected]
        node['depthRange'] = {'near': _round(min(depths), 4), 'far': _round(max(depths), 4)}
        anchor = self._anchor(kind, item, verts) if kind == 'collection' else \
            self.projector.project(item.matrix_world.translation)
        node['origin'] = _xyd(*anchor) if anchor and anchor[0] is not None else None
        return node

    def _build_sprite(self, kind, item, node):
        sprite_type = node.get('type', 'basic')
        if sprite_type in ('atlas', 'spritesheet'):
            if kind != 'collection':
                self.warn(f"'{item.name}': {sprite_type} sprites must be collections; skipped")
                return None
            self._add_geometry_info(node, kind, item, self._render_objects(item))
            node['frames'] = self._build_frames(item)
            return node
        if sprite_type == 'animation':
            self.warn(f"'{item.name}': animation sprites are not supported yet; exported without image")
            self._add_geometry_info(node, kind, item, self._render_objects_for(kind, item))
            return node
        return self._build_rendered(kind, item, node)

    def _build_tileset(self, kind, item, node):
        return self._build_rendered(kind, item, node)

    def _build_rendered(self, kind, item, node):
        objects = self._render_objects_for(kind, item)
        box = self._add_geometry_info(node, kind, item, objects)
        node['render'] = self._render(objects, box, item.name)
        if kind == 'collection':
            children = self.walk(item)
            if children:
                node['children'] = children
        return node

    def _build_frames(self, collection):
        frames = []
        for kind, child in self._children(collection):
            parsed = parse_layer_name(child.name)
            if parsed is not None and parsed['category'] in ('point', 'zone'):
                continue
            if parsed is not None and parsed['name'] in self.ignore:
                continue
            frame = {
                'name': parsed['name'] if parsed else child.name,
                'attributes': parsed['attributes'] if parsed else {},
                'source': {'kind': kind, 'name': child.name},
            }
            objects = self._render_objects_for(kind, child)
            box = self._add_geometry_info(frame, kind, child, objects)
            frame['render'] = self._render(objects, box, child.name)
            frames.append(frame)
        return frames

    # ------------------------------------------------------------------ rendering

    def _render_objects(self, collection):
        """All objects a collection contributes to a render: everything inside
        it except points/zones (and anything inside P/Z collections)."""
        excluded = set()
        for sub in collection.children_recursive:
            parsed = parse_layer_name(sub.name)
            if parsed and parsed['category'] in ('point', 'zone'):
                excluded.update(o.as_pointer() for o in sub.all_objects)
        result = []
        for obj in collection.all_objects:
            parsed = parse_layer_name(obj.name)
            if parsed and parsed['category'] in ('point', 'zone'):
                continue
            if obj.as_pointer() in excluded or obj.type in NON_RENDERABLE_TYPES:
                continue
            result.append(obj)
        return result

    def _render_objects_for(self, kind, item):
        return [item] if kind == 'object' else self._render_objects(item)

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
        info = {'left': left, 'top': top, 'width': right - left, 'height': bottom - top}
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
        shown = sources & self._directly_visible
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
        stack = [o for o in objects]
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
            saved[obj.name] = (obj.hide_render, obj.visible_camera)
            if obj.as_pointer() in targets:
                continue  # keep the user's own visibility settings
            if self.cast_shadows:
                obj.visible_camera = False
            else:
                obj.hide_render = True
        return saved

    def _restore(self, saved):
        for name, (hide_render, visible_camera) in saved.items():
            obj = self.scene.objects.get(name)
            if obj is not None:
                obj.hide_render = hide_render
                obj.visible_camera = visible_camera

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
        return info


def _pick_scene(name):
    if not name:
        return bpy.context.scene
    scene = bpy.data.scenes.get(name)
    if scene is None:
        raise ExportError(f"scene '{name}' not found")
    return scene


def _pick_camera(scene, name):
    if name:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != 'CAMERA':
            raise ExportError(f"camera '{name}' not found (or is not a camera)")
        return obj
    if scene.camera is None:
        raise ExportError(f"scene '{scene.name}' has no active camera")
    return scene.camera


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


def resolve_job(job):
    """Resolve the scene, parameters and config for a job."""
    config = dict(job.get('config', {}))
    scene_name = config.get('scene')
    if isinstance(scene_name, str) and scene_name.startswith('@'):
        # A scene reference can only be resolved against the active scene.
        scene_name = resolve_references(scene_name, merge_parameters(
            read_scene_parameters(bpy.context.scene), job.get('parameters')), 'scene')
    scene = _pick_scene(scene_name)
    params = merge_parameters(read_scene_parameters(scene), job.get('parameters'))
    config.pop('parameters', None)  # merged into job['parameters'] by the CLI
    resolved = resolve_references(config, params)
    return scene, params, resolved


def list_parameters(job):
    scene = _pick_scene(job.get('config', {}).get('scene'))
    return {
        'scene': scene.name,
        'parameters': read_scene_parameters(scene),
    }


def export(job):
    work_dir = job['work_dir']
    os.makedirs(os.path.join(work_dir, 'renders'), exist_ok=True)

    scene, params, config = resolve_job(job)
    camera_obj = _pick_camera(scene, config.get('camera'))
    scene.camera = camera_obj
    _apply_render_settings(scene, config)

    exporter = Exporter(scene, camera_obj, config, params, work_dir)
    layers = exporter.walk(scene.collection)
    width, height = render_resolution(scene)

    return {
        'name': job['name'],
        'source': bpy.data.filepath,
        'scene': scene.name,
        'width': width,
        'height': height,
        'camera': exporter.camera_info(),
        'config': config,
        'parameters': params,
        'layers': layers,
        'warnings': exporter.warnings,
    }
