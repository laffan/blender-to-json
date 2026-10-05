"""Build a small test scene that exercises every category, and save it.

Run with Blender:   blender -b --python make_fixture.py -- out.blend [ortho|persp]
or with the bpy module:   python make_fixture.py out.blend [ortho|persp]
"""

import json
import math
import sys

import bpy


def link(obj, collection):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    collection.objects.link(obj)


def new_collection(name, parent):
    col = bpy.data.collections.new(name)
    parent.children.link(col)
    return col


def cube(name, location, size, collection):
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    obj = bpy.context.active_object
    obj.name = name
    link(obj, collection)
    return obj


def build(path, camera_type='ORTHO'):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    root = scene.collection

    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 1
    scene.cycles.device = 'CPU'
    scene.render.resolution_x = 200
    scene.render.resolution_y = 100
    scene.render.resolution_percentage = 100

    # Camera looking straight down -Z at the XY plane.
    cam_data = bpy.data.cameras.new('Camera')
    cam_data.type = camera_type
    cam_data.ortho_scale = 20  # 20 units across 200px -> 10 px/unit
    cam_data.lens = 50
    cam = bpy.data.objects.new('Camera', cam_data)
    cam.location = (0, 0, 20)
    root.objects.link(cam)
    scene.camera = cam

    light_data = bpy.data.lights.new('Sun', 'SUN')
    light = bpy.data.objects.new('Sun', light_data)
    root.objects.link(light)

    world = new_collection('G | world | level:1', root)

    # Basic sprite from a single mesh (2x2 units at x=-5).
    cube('S | crate | weight:10', (-5, 0, 0), 2, world)
    # Duplicate name -> same exported name thanks to suffix stripping.
    cube('S | crate', (-5, 3, 0), 2, world)

    # Sprite from a collection, containing a point that must not be rendered.
    house = new_collection('S | house', world)
    cube('wall', (5, 0, 0), 2, house)
    cube('roof', (5, 1.5, 0), 1, house)
    spawn = bpy.data.objects.new('P | door', None)
    spawn.location = (5, -1, 0)
    house.objects.link(spawn)

    # Partly off-frame sprite (frame spans x in [-10, 10]).
    cube('S | edge', (10, 0, 0), 2, world)

    # Points
    p = bpy.data.objects.new('P | spawn | team:"red"', None)
    p.location = (2, 2, 1)
    world.objects.link(p)
    p['difficulty'] = '@difficulty'

    # Zone: a rotated plane.
    bpy.ops.mesh.primitive_plane_add(size=4, location=(0, -3, 0))
    zone = bpy.context.active_object
    zone.name = 'Z | lake'
    zone.rotation_euler = (0, 0, math.radians(45))
    link(zone, world)
    zone.hide_render = True

    # Tiles
    ground = new_collection('T | ground', root)
    bpy.ops.mesh.primitive_plane_add(size=16, location=(0, 0, -1))
    plane = bpy.context.active_object
    plane.name = 'groundPlane'
    link(plane, ground)

    # Atlas
    atlas = new_collection('S | props | atlas |', root)
    cube('barrel', (-7, -4, 0), 1, atlas)
    cube('rock', (-4, -4, 0), 1.5, atlas)

    # Spritesheet
    sheet = new_collection('S | gems | spritesheet |', root)
    cube('gemA', (7, -4, 0), 1, sheet)
    cube('gemB', (8.5, -4, 0), 0.6, sheet)

    # Ignored (no pipes)
    cube('helper', (0, 4, 0), 1, root)

    # Reference tile for baseTile/tileWidth/snapToTileGrid (2x2 units, unnamed).
    bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, -0.5))
    tile = bpy.context.active_object
    tile.name = 'BaseTile'
    link(tile, root)

    scene['blender_to_json'] = json.dumps({
        'version': 2,
        'parameters': {
            'mainCam': {'id_type': 'scenes', 'id_name': 'Scene', 'path': 'camera', 'value': 'Camera'},
            'width': {'id_type': 'scenes', 'id_name': 'Scene', 'path': 'render.resolution_x', 'value': 200},
            'sunPower': {'id_type': 'lights', 'id_name': 'Sun', 'path': 'energy', 'value': 1.0},
            'difficulty': {'value': 3},
            'tileSize': {'value': 64},
        },
    })

    bpy.ops.wm.save_as_mainfile(filepath=path)


if __name__ == '__main__':
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    build(args[0], (args[1] if len(args) > 1 else 'ortho').upper())
