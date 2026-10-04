# Blender to JSON

Export a Blender scene as 2D game assets plus a JSON manifest. This is the Blender counterpart of [psd-to-json](https://github.com/laffan/psd-to-json): collections and objects are named with the same `category | name | type | attributes` scheme, rendered through a camera, and described in a `data.json` that [psd-to-phaser](https://github.com/laffan/psd-to-phaser) can read.

```
README.md
blender-to-json-cli/      command-line exporter (Python package: blender-to-json)
blender-to-json-plugin/   companion Blender add-on
```

## How the naming scheme maps to Blender

| | psd-to-json | Blender |
| --- | --- | --- |
| **G** | layer group | a collection containing other collections and objects |
| **S** | layer or group, flattened to a PNG | a collection or object rendered on its own; `atlas` and `spritesheet` collections render each child as a frame |
| **T** | layer or group, sliced into tiles | a collection or object, rendered and then sliced |
| **P** | centre of the layer | an empty's (or mesh's) origin projected through the camera |
| **Z** | vector path or bounding box | the convex hull of every projected vertex |

Everything is measured from the scene camera (or another one you choose), in that camera's pixel space. Every point also gets a camera-space `depth`, and `initialDepth` (layer order) is derived from it.

## Quick start

```bash
# 1. Install the CLI
cd blender-to-json-cli && pip install -e .

# 2. Name things in Blender, e.g.
#      G | level
#        S | house           (collection)
#          P | door          (empty)
#        S | crate | weight:10
#        Z | lake            (plane, can be hidden from render)
#      T | ground | jpg |    (collection)

# 3. Export
blender-to-json scenes/level1.blend -o assets
```

The [Blender to JSON plugin](blender-to-json-plugin) adds named parameters to a `.blend` file (a camera, a collection, numbers and so on). You can refer to them from the CLI as `@name`:

```bash
blender-to-json scenes/level1.blend --set camera=@topDown --set tile_slice_size=@tileSize
```

See [blender-to-json-cli/README.md](blender-to-json-cli/README.md) for the full configuration reference and output format, and [blender-to-json-plugin/README.md](blender-to-json-plugin/README.md) for the add-on.

## Credits

The render-isolation approach comes from [blender-2d-tile-tools](https://github.com/laffan/blender-2d-tile-tools). The naming scheme and output format come from [psd-to-json](https://github.com/laffan/psd-to-json).
