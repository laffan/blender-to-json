import re

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty,
                       StringProperty)

from . import sync
from .core import datapath

NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _relative_path_options():
    # Newer Blender versions want paths that accept "//" to say so; older ones
    # don't know the option.
    try:
        StringProperty(options={'PATH_SUPPORTS_BLEND_RELATIVE'})
    except TypeError:
        return set()
    return {'PATH_SUPPORTS_BLEND_RELATIVE'}


PATH_OPTIONS = _relative_path_options()


def _on_change(self, context):
    scene = self.id_data
    if isinstance(scene, bpy.types.Scene):
        sync.write_scene(scene)


def _is_camera(_self, obj):
    return obj.type == 'CAMERA'


class B2J_Parameter(bpy.types.PropertyGroup):
    """A named handle on any Blender property.

    The CLI can set it with `--param name=value` and read it as `@name`.
    """
    # `name` is built into PropertyGroup; redefine it to get an update callback.
    name: StringProperty(
        name='Name',
        description='Refer to this parameter as @name in the config file, or set it with --param name=value',
        default='param', update=_on_change)
    # A real reference, so renaming the datablock doesn't break the parameter;
    # id_type/id_name are refreshed from it whenever the mirror is written.
    id_ref: PointerProperty(name='Datablock', type=bpy.types.ID, update=_on_change)
    id_type: StringProperty(name='Datablock Type', description='bpy.data collection, e.g. "objects"',
                            update=_on_change)
    id_name: StringProperty(name='Datablock', update=_on_change)
    path: StringProperty(name='Data Path', description='Property path relative to the datablock',
                         update=_on_change)
    description: StringProperty(name='Description', description='Optional note for yourself and collaborators',
                                update=_on_change)

    def target(self):
        """The datablock this parameter tracks, or None if it's gone."""
        if self.id_ref is not None:
            return self.id_ref
        if not self.id_type or not self.id_name:
            return None
        return datapath.find_id(self.id_type, self.id_name)

    def refresh_name(self):
        """Follow renames of the tracked datablock."""
        if self.id_ref is not None and self.id_ref.name != self.id_name:
            self.id_name = self.id_ref.name

    def full_path(self):
        return datapath.full_path(self.id_type, self.id_name, self.path)

    def value(self):
        """Current value of the tracked property (JSON-compatible)."""
        id_block = self.target()
        if id_block is None:
            return None
        try:
            return datapath.get_value(id_block, self.path)
        except datapath.DataPathError:
            return None

    def label(self):
        id_block = self.target()
        if id_block is None:
            return f'{self.id_name} (missing)'
        return datapath.describe(id_block, self.path)

    def problem(self, scene_settings):
        """Short description of what is wrong with this parameter, or None."""
        if not NAME_PATTERN.match(self.name):
            return 'Use letters, digits and underscores only, not starting with a digit'
        if sum(1 for p in scene_settings.parameters if p.name == self.name) > 1:
            return 'Another parameter has the same name'
        id_block = self.target()
        if id_block is None:
            return f'{self.id_type}["{self.id_name}"] no longer exists'
        try:
            id_block.path_resolve(self.path)
        except ValueError:
            return f'"{self.path}" no longer resolves on {self.id_name}'
        return None


class B2J_NameItem(bpy.types.PropertyGroup):
    name: StringProperty(update=_on_change)


CAMERA_PRESETS = [
    ('SIDE', 'Side', 'Orthographic camera looking along +Y (side-scrolling / platformer tiles)'),
    ('TOP_DOWN', 'Top-down', 'Orthographic camera looking straight down'),
    ('ISOMETRIC', 'Isometric', 'True isometric: 54.736° tilt, 45° turn'),
    ('DIMETRIC', '2:1 Isometric', 'Pixel-art "isometric" (2:1 dimetric): 60° tilt, 45° turn'),
]


class B2J_ExportSettings(bpy.types.PropertyGroup):
    """Export settings stored in the .blend.

    Anything changed from its default is mirrored into the scene's JSON so the
    CLI uses it too (below a config file and --set).
    """
    output_dir: StringProperty(
        name='Output Folder', subtype='DIR_PATH', default='', update=_on_change, options=PATH_OPTIONS,
        description='Where assets are written. Relative paths (//) are relative to this .blend')
    config_path: StringProperty(
        name='Config File', subtype='FILE_PATH', default='', options=PATH_OPTIONS,
        description='Optional blender-to-json.config used when exporting from Blender. '
                    'Its values override these settings')
    camera: PointerProperty(
        name='Camera', type=bpy.types.Object, poll=_is_camera, update=_on_change,
        description='Camera to render and measure from (empty: the scene camera)')
    render_bounds: EnumProperty(
        name='Render Bounds', default='object', update=_on_change,
        items=[('object', 'Whole Object', 'Render items in full, even past the edge of the camera frame'),
               ('frame', 'Camera Frame', 'Clip renders to the camera frame')])
    render_padding: IntProperty(
        name='Padding', default=2, min=0, max=256, update=_on_change,
        description='Extra pixels rendered around each item before trimming')
    cast_shadows: BoolProperty(
        name='Include Cast Shadows', default=False, update=_on_change,
        description='Other objects stay invisible but still cast shadows and bounce light onto the item '
                    'being rendered')
    holdout_collection: PointerProperty(
        name='Ground', type=bpy.types.Collection, update=_on_change,
        description='Crop with ground: objects in this collection mask everything they cover in other '
                    'renders, and its layers are drawn underneath everything else')
    base_tile: PointerProperty(
        name='Base Tile', type=bpy.types.Object, update=_on_change,
        description='Reference tile: sets the output scale (with Tile Width) and the grid for snapping')
    tile_width: IntProperty(
        name='Tile Width', default=0, min=0, max=4096, subtype='PIXEL', update=_on_change,
        description='Scale the whole export so the base tile is this many pixels wide (0: no scaling)')
    snap_to_grid: BoolProperty(
        name='Snap Sprites to Tile Grid', default=False, update=_on_change,
        description="Pad sprites so their edges fall on the base tile's grid, anchored at each sprite's origin")
    tile_slice_size: IntProperty(
        name='Tile Slice Size', default=512, min=16, max=8192, subtype='PIXEL', update=_on_change,
        description='Size of the tiles that T layers are sliced into')
    psd: BoolProperty(
        name='Also Write a PSD', default=False, update=_on_change,
        description='Write a layered PSD named with the psd-to-json scheme (needs psd-tools)')
    pass_through: BoolProperty(
        name='Look Inside Unnamed Collections', default=False, update=_on_change,
        description='Export named items inside collections that have no category')
    ignore_layers: CollectionProperty(type=B2J_NameItem)
    open_folder: BoolProperty(name='Open Folder After Export', default=True)
    camera_preset: EnumProperty(name='Camera', items=CAMERA_PRESETS, default='ISOMETRIC')


class B2J_SceneSettings(bpy.types.PropertyGroup):
    parameters: CollectionProperty(type=B2J_Parameter)
    active_index: IntProperty(default=0)
    export: PointerProperty(type=B2J_ExportSettings)


classes = (B2J_Parameter, B2J_NameItem, B2J_ExportSettings, B2J_SceneSettings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blender_to_json_settings = PointerProperty(type=B2J_SceneSettings)


def unregister():
    del bpy.types.Scene.blender_to_json_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
