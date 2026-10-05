"""Decide how a scene's collections and objects will be exported.

No rendering or projection happens here, only name parsing and tree walking,
so this is cheap enough to run on every redraw of the plugin's preview panel.
The CLI's exporter consumes the same plan, so the preview, `--dryrun` and the
real export always agree.

Needs bpy data access only (no bpy.ops, no mathutils).
"""

import json

from .naming import parse_layer_name

EXPORT = 'export'    # exported as a layer
IGNORED = 'ignored'  # not exported (see `reason`)
HOIST = 'hoist'      # not a layer itself, but its exported contents move up a level
CONTENT = 'content'  # unnamed, but drawn as part of its parent's render

NON_RENDERABLE_TYPES = {'LIGHT', 'CAMERA', 'LIGHT_PROBE', 'LIGHTPROBE', 'SPEAKER'}
PRIVATE_PROPERTY_KEYS = {'blender_to_json', 'cycles', '_RNA_UI'}


class PlanOptions:
    def __init__(self, ignore=(), only=(), pass_through=False, custom_props=True, holdout=None):
        self.ignore = set(ignore or ())
        self.only = set(only or ())
        self.pass_through = bool(pass_through)
        self.custom_props = bool(custom_props)
        self.holdout = holdout  # a bpy Collection or None
        self.only_matched = set()
        self._holdout_objects = set()
        self._holdout_collections = set()
        if holdout is not None:
            self._holdout_objects = {o.as_pointer() for o in holdout.all_objects}
            self._holdout_collections = {c.as_pointer() for c in holdout.children_recursive}
            self._holdout_collections.add(holdout.as_pointer())

    @classmethod
    def from_config(cls, config, holdout=None):
        return cls(
            ignore=config.get('ignoreLayers') or (),
            only=config.get('only') or (),
            pass_through=config.get('passThroughUnnamedCollections', False),
            custom_props=config.get('customPropertiesAsAttributes', True),
            holdout=holdout,
        )

    def in_holdout(self, kind, item):
        if kind == 'object':
            return item.as_pointer() in self._holdout_objects
        return item.as_pointer() in self._holdout_collections


class PlanNode:
    def __init__(self, kind, item, parsed):
        self.kind = kind            # 'collection' or 'object'
        self.item = item            # the bpy datablock
        self.blender_name = item.name
        self.parsed = parsed        # from parse_layer_name, or None
        self.status = IGNORED
        self.reason = None          # why it is ignored / hoisted
        self.warning = None         # a problem the user should fix
        self.attributes = {}
        self.children = []
        self.frames = []            # atlas/spritesheet frames (PlanNodes)
        self.only_root = False      # matched a --only name
        self.holdout = False        # inside the holdout ("ground") collection
        self.hidden_count = 0       # items inside an ignored collection

    @property
    def category(self):
        return self.parsed['category'] if self.parsed else None

    @property
    def name(self):
        return self.parsed['name'] if self.parsed else self.blender_name

    @property
    def type(self):
        return self.parsed.get('type') if self.parsed else None

    @property
    def renders(self):
        """True if exporting this node renders an image of it."""
        if self.status != EXPORT:
            return False
        if self.category == 'tileset':
            return True
        return self.category == 'sprite' and self.type not in ('atlas', 'spritesheet', 'animation')

    def to_dict(self):
        d = {
            'kind': self.kind,
            'blenderName': self.blender_name,
            'status': self.status,
        }
        if self.parsed:
            d['category'] = self.category
            d['name'] = self.name
            if self.type:
                d['type'] = self.type
        for key in ('reason', 'warning'):
            if getattr(self, key):
                d[key] = getattr(self, key)
        if self.attributes:
            d['attributes'] = self.attributes
        if self.only_root:
            d['onlyRoot'] = True
        if self.holdout:
            d['holdout'] = True
        if self.hidden_count:
            d['hiddenCount'] = self.hidden_count
        if self.frames:
            d['frames'] = [f.to_dict() for f in self.frames]
        if self.children:
            d['children'] = [c.to_dict() for c in self.children]
        return d


def children_of(collection):
    """Child collections first, then objects, in outliner order."""
    return [('collection', c) for c in collection.children] + [('object', o) for o in collection.objects]


def custom_attributes(item):
    """An item's custom properties as JSON-compatible attributes."""
    attributes = {}
    for key in item.keys():
        if key.startswith('_') or key in PRIVATE_PROPERTY_KEYS:
            continue
        value = item[key]
        if hasattr(value, 'to_dict'):
            value = value.to_dict()
        elif hasattr(value, 'to_list'):
            value = value.to_list()
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        attributes[key] = value
    return attributes


def is_marker(item):
    parsed = parse_layer_name(item.name)
    return parsed is not None and parsed['category'] in ('point', 'zone')


def render_objects(kind, item):
    """Objects that go into an item's render.

    For a collection: everything inside it, at any depth, except points and
    zones (and anything inside P/Z collections), so markers never show up in
    sprites.
    """
    if kind == 'object':
        return [item]
    excluded = set()
    for sub in item.children_recursive:
        if is_marker(sub):
            excluded.update(o.as_pointer() for o in sub.all_objects)
    return [obj for obj in item.all_objects
            if obj.type not in NON_RENDERABLE_TYPES
            and obj.as_pointer() not in excluded
            and not is_marker(obj)]


def _matches(item, parsed, names):
    return item.name in names or (parsed is not None and parsed['name'] in names)


def _contains(collection, names):
    for sub in collection.children_recursive:
        if _matches(sub, parse_layer_name(sub.name), names):
            return True
    for obj in collection.all_objects:
        if _matches(obj, parse_layer_name(obj.name), names):
            return True
    return False


def _count_items(collection):
    return len(collection.children_recursive) + len(collection.all_objects)


def build_plan(collection, options):
    """Plan every child of `collection` (usually `scene.collection`)."""
    return _walk(collection, options, inside_only=False)


def _walk(collection, options, inside_only, render_parent=None):
    return [_plan_item(kind, item, options, inside_only, render_parent)
            for kind, item in children_of(collection)]


def _plan_item(kind, item, options, inside_only, render_parent=None):
    parsed = parse_layer_name(item.name)
    node = PlanNode(kind, item, parsed)
    node.holdout = options.in_holdout(kind, item)

    if _matches(item, parsed, options.ignore):
        node.reason = 'listed in ignoreLayers'
        if kind == 'collection':
            node.hidden_count = _count_items(item)
        return node

    is_only = bool(options.only) and not inside_only and _matches(item, parsed, options.only)
    if is_only:
        options.only_matched.update(n for n in options.only if n in (item.name, node.name))
    if options.only and not inside_only and not is_only:
        if kind == 'collection' and _contains(item, options.only):
            node.children = _walk(item, options, inside_only=False)
            if parsed is not None and parsed['category'] == 'group':
                node.status = EXPORT
                node.attributes = _attributes(item, parsed, options)
            else:
                node.status = HOIST
            node.reason = 'only contains --only items'
        else:
            node.reason = 'not selected by --only'
            if kind == 'collection':
                node.hidden_count = _count_items(item)
        return node

    node.only_root = is_only
    inside = inside_only or is_only

    if parsed is None and render_parent is not None and not is_only:
        node.status = CONTENT
        node.reason = f"part of the '{render_parent}' render"
        if kind == 'collection':
            node.children = _walk(item, options, inside, render_parent)
        return node

    if parsed is None:
        if kind == 'collection' and (options.pass_through or is_only):
            node.status = HOIST
            node.reason = 'no category; contents exported'
            node.children = _walk(item, options, inside)
        elif kind == 'collection':
            node.reason = 'no category; collection and contents ignored'
            node.hidden_count = _count_items(item)
        elif item.type in ('LIGHT', 'CAMERA'):
            node.reason = f'{item.type.lower()}; lights and cameras are only used for rendering'
        else:
            node.reason = 'no category'
        return node

    node.attributes = _attributes(item, parsed, options)
    category = parsed['category']
    sprite_type = parsed.get('type')

    if category == 'group':
        if kind != 'collection':
            return _invalid(node, 'G must be a collection')
        node.status = EXPORT
        node.children = _walk(item, options, inside)
    elif category == 'point':
        if kind != 'object':
            return _invalid(node, 'P must be a single object (an empty or mesh)')
        node.status = EXPORT
    elif category == 'zone':
        node.status = EXPORT
    elif category == 'sprite' and sprite_type in ('atlas', 'spritesheet'):
        if kind != 'collection':
            return _invalid(node, f'{sprite_type} sprites must be collections')
        node.status = EXPORT
        node.frames = _frames(item, options)
        if not node.frames:
            node.warning = f'{sprite_type} has no frames'
    else:  # basic/animation sprite, or tileset
        node.status = EXPORT
        if category == 'sprite' and sprite_type == 'animation':
            node.warning = 'animation sprites are not supported yet; exported without an image'
        elif category == 'sprite' and sprite_type not in (None, 'basic'):
            node.warning = f"unknown sprite type '{sprite_type}'; exported as a basic sprite"
        if not render_objects(kind, item):
            node.warning = 'nothing to render'
        if kind == 'collection':
            parent = item.name if category == 'tileset' or sprite_type != 'animation' else None
            node.children = _walk(item, options, inside, parent)
    return node


def _invalid(node, message):
    node.status = IGNORED
    node.reason = message
    node.warning = message
    return node


def _attributes(item, parsed, options):
    attributes = custom_attributes(item) if options.custom_props else {}
    attributes.update(parsed['attributes'])
    return attributes


def _frames(collection, options):
    frames = []
    for kind, child in children_of(collection):
        parsed = parse_layer_name(child.name)
        if parsed is not None and parsed['category'] in ('point', 'zone'):
            continue
        if _matches(child, parsed, options.ignore):
            continue
        frame = PlanNode(kind, child, parsed)
        frame.status = EXPORT
        frame.attributes = parsed['attributes'] if parsed else {}
        frame.holdout = options.in_holdout(kind, child)
        frames.append(frame)
    return frames


def iter_nodes(nodes):
    for node in nodes:
        yield node
        yield from iter_nodes(node.frames)
        yield from iter_nodes(node.children)


def summarize(nodes):
    """Counts used by the preview panel and --dryrun."""
    counts = {'layers': 0, 'renders': 0, 'ignored': 0, 'warnings': 0}

    def visit(items):
        for node in items:
            if node.status == EXPORT:
                counts['layers'] += 1
            elif node.status == IGNORED:
                counts['ignored'] += 1
            if node.renders:
                counts['renders'] += 1
            if node.warning:
                counts['warnings'] += 1
            counts['renders'] += len(node.frames)
            visit(node.children)

    visit(nodes)
    return counts
