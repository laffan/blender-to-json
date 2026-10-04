# blender-to-json (CLI)

Render the collections and objects in a `.blend` file as game assets (sprites, atlases, spritesheets, sliced tiles), and describe points and zones as 2D positions in the camera's view. The output is a `data.json` manifest in the same shape as [psd-to-json](https://github.com/laffan/psd-to-json), so [psd-to-phaser](https://github.com/laffan/psd-to-phaser) can load it.

Everything runs from the command line. Blender is started headlessly (`blender -b`) for each file.

## Installation

```bash
cd blender-to-json-cli
python3 -m venv venv && source venv/bin/activate
pip install -e .
```

Requirements:

- **Blender** 3.6 or newer. The CLI looks for it in this order: `--blender`, `blender_path` in the config, the `BLENDER_PATH` environment variable, `blender` on your `PATH`, then the usual install locations (`/Applications/Blender.app` on macOS, `C:\Program Files\Blender Foundation\…` on Windows).
- **Python 3.9+** with Pillow (installed automatically) for the post-processing stage.
- **[pngquant](https://pngquant.org/)** (optional). PNGs are compressed with it if it's on your `PATH`; otherwise they're left as they are.

## Usage

```bash
blender-to-json                                   # uses ./blender-to-json.config
blender-to-json level1.blend level2.blend         # explicit files
blender-to-json level1.blend -o assets            # output directory
blender-to-json --config game.config --set camera=@topDown
blender-to-json level1.blend --param difficulty=3
blender-to-json level1.blend --metadata-only      # no rendering, just data.json
blender-to-json level1.blend --list-params        # show parameters stored in the file
blender-to-json --watch                           # re-export when a .blend is saved
```

| Flag | Meaning |
| --- | --- |
| `files…` | `.blend` files. If omitted, `blend_files` from the config is used. |
| `-c, --config PATH` | Config file. Defaults to `./blender-to-json.config` if it exists. |
| `-s, --set KEY=VALUE` | Override any config value. Dotted keys reach into objects (`pngQualityRange.low=80`). Values are parsed as JSON when possible, otherwise used as strings. |
| `-p, --param NAME=VALUE` | Override (or define) a parameter stored in the blend file. |
| `-o, --output-dir DIR` | Output directory, relative to the current directory. |
| `--blender PATH` | Blender executable. |
| `--metadata-only` | Skip rendering and image processing. Sprite and tile rectangles come from projected bounding boxes instead of trimmed renders. |
| `--watch` | Keep running and re-export a file whenever it changes (same as `"generateOnSave": true`). |
| `--list-params` | Print each file's parameters and exit. |
| `--keep-temp` | Keep the intermediate work directory (raw renders and `raw.json`) for debugging. |
| `-v, --verbose` | Show all of Blender's output. |

## Configuration

A JSON file. Paths inside it are relative to the config file. Every key is optional.

```json
{
  "output_dir": "assets",
  "blend_files": ["scenes/level1.blend"],
  "camera": "@mainCam",
  "tile_slice_size": 512,
  "tile_scaled_versions": [128],
  "pngQualityRange": { "low": 85, "high": 90 },
  "jpgQuality": 80,
  "ignoreLayers": ["debugOnly"],
  "parameters": { "difficulty": 2 }
}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `output_dir` | `"output"` | A folder named after each `.blend` is created inside it. |
| `blend_files` | `[]` | Files to export when none are given on the command line. |
| `blender_path` | `null` | Blender executable. |
| `scene` | active scene | Scene to export, by name. |
| `camera` | scene camera | Camera object to render and project from, by name. |
| `resolution` | scene setting | `[width, height]` override. |
| `resolutionPercentage` | scene setting | Render-scale override. |
| `renderEngine` | scene setting | e.g. `"CYCLES"`, `"BLENDER_WORKBENCH"`, `"BLENDER_EEVEE"` (`"BLENDER_EEVEE_NEXT"` in Blender 4.2–4.5). |
| `samples` | scene setting | Render samples override (Cycles or EEVEE). |
| `renderBounds` | `"object"` | `"object"` renders each item in full, even past the edge of the camera frame (as psd-to-json does for layers that hang off the canvas). `"frame"` clips renders to the camera frame. |
| `renderPadding` | `2` | Extra pixels rendered around each item's projected bounds before trimming. Raise it if bevels, displacement or glow get clipped. |
| `maxRenderSize` | `16384` | Items whose render would be larger than this (in pixels, either side) are skipped with a warning. |
| `castShadowsFromHidden` | `false` | When rendering an item, make other objects invisible to the camera but keep them casting shadows and bounce light, instead of hiding them entirely. |
| `trimTransparent` | `true` | Crop renders to their non-transparent pixels. |
| `tile_slice_size` | `512` | Tile size for `T` layers. |
| `tile_scaled_versions` | `[]` | Extra copies of each tile set, scaled so a tile is this many pixels wide (for minimaps etc.). |
| `jpgQuality` | `85` | Quality for `jpg` tiles. |
| `pngQualityRange` | `{"low": 45, "high": 65}` | pngquant quality range. |
| `optimizePngs` | `true` | Run pngquant if it's installed. |
| `atlasPadding` | `2` | Pixels between frames in atlases. |
| `ignoreLayers` | `[]` | Layer names (the name part, not the full Blender name) to skip. |
| `passThroughUnnamedCollections` | `false` | By default a collection without a valid name is ignored along with everything inside it, as in psd-to-json. Set to `true` to look inside unnamed collections instead. |
| `customPropertiesAsAttributes` | `true` | Merge an object's or collection's custom properties into its attributes (name attributes win). Properties starting with `_` are skipped. |
| `metadataOnly` | `false` | Same as `--metadata-only`. |
| `generateOnSave` | `false` | Same as `--watch`. |
| `factoryStartup` | `true` | Start Blender with `--factory-startup` (ignores your user preferences and add-ons) for repeatable results. |
| `enableAutoexec` | `false` | Allow Python drivers and scripts stored in the file to run. |
| `parameters` | `{}` | Overrides for the parameters stored in the blend file (see below). |

Precedence, lowest to highest: built-in defaults, config file, `--set`. For parameters: values stored in the blend file, then the config's `parameters`, then `--param`.

### Parameters and `@references`

The [Blender-to-JSON plugin](../blender-to-json-plugin) stores named parameters inside a `.blend` file: a camera, an object, a collection, text, a number or a toggle. Any string value in the config or in a `--set` flag that starts with `@` is replaced with that parameter's value:

```bash
blender-to-json level1.blend --set camera=@topDown --set tile_slice_size=@tileSize
```

```json
{ "camera": "@topDown", "output_dir": "@exportFolder" }
```

- Camera, object and collection parameters resolve to the datablock's name.
- `@@text` gives you the literal string `@text`.
- An unknown reference stops the export of that file with an error listing the available names.
- `@references` also work in layer attributes, including custom properties: `P | spawn | level:@difficulty`.
- Resolved parameters are written to `data.json` under `"parameters"`, so the game can read them too.
- References are resolved separately for each `.blend`, so `"camera": "@mainCam"` can point to a different camera in each file.

## Naming scheme

Same rules as psd-to-json, applied to collection and object names:

```
category | name
category | name | attributes
category | name | type | attributes
```

Names without a pipe are ignored. Child collections are read before objects, in outliner order.

| Category | Applies to | Output |
| --- | --- | --- |
| **G** Group | a collection | A group with `children`. Its rectangle and depth cover everything inside it. |
| **S** Sprite | a collection or object | Rendered in isolation, trimmed and saved as `sprites/<name>.png`. Types: `atlas` and `spritesheet` (collections only; each direct child becomes a frame). `animation` is not implemented yet: the layer is exported without an image and with a `note`. |
| **T** Tiles | a collection or object | Rendered in isolation, then sliced into `tiles/<name>/<tile_slice_size>/<name>_tile_<col>_<row>.png`. Type `jpg` writes JPEGs. |
| **P** Point | a single object (usually an empty) | The object's origin projected through the camera: `x`, `y`, `depth`. |
| **Z** Zone | an object or a collection | All evaluated vertices are projected and reduced to their 2D convex hull. Each hull point has `x`, `y`, `depth`. |

Notes specific to Blender:

- **Duplicate names.** Blender won't let two objects share a name; it adds `.001`, `.002`. A trailing three-digit suffix is stripped, so `S | crate` and `S | crate.001` both export as `crate`. As in psd-to-json, same-named sprites share one file (the last render wins) but each keeps its own position. Only the exact `.NNN` form is stripped, so `scale:1.5` is safe, but a name that ends in a three-decimal number such as `scale:1.500` loses it.
- **Name length.** Blender names are limited to 63 bytes (255 from Blender 5.0). Use custom properties for long attribute lists; they're merged into `attributes`.
- **What goes into a collection render.** Every object inside the collection, at any depth, except objects named `P | …` or `Z | …` and anything inside `P`/`Z` collections, so markers never show up in sprites. Objects you've disabled for rendering stay hidden. Collection instances work. If the instanced collection is also visible in the view layer you'll get a warning, because it may appear in the render; exclude it from the view layer.
- **Isolation.** Each item is rendered with everything else hidden (lights stay on). This matches blender-2d-tile-tools, but it means items lose shadows and bounce light from their surroundings. `castShadowsFromHidden: true` keeps other objects contributing light without appearing.
- **Children of S and T collections.** As in psd-to-json, named layers inside a basic `S` or `T` collection also appear as its `children`, e.g. a `P | door` inside `S | house`. Atlas and spritesheet children are frames, not layers.

## Output

```
<output_dir>/<blend name>/
  data.json
  sprites/<name>.png
  tiles/<name>/<size>/<name>_tile_<col>_<row>.png
```

### Coordinates and depth

- **Pixel space** is the render frame of the chosen camera at its render resolution (resolution × percentage). The origin is the top-left corner and y points down. Values can be negative or larger than the frame for things outside the view.
- **`depth`** is distance along the camera's viewing axis in Blender units: positive in front of the camera, larger means farther. It's computed the same way for perspective and orthographic cameras.
- **`initialDepth`** ranks all layers (groups included) by `depth`: 0 is the farthest, higher numbers are drawn on top. psd-to-phaser uses this value as the Phaser depth.
- **`origin`** is the projected anchor point: an object's origin, or the centre of a collection's bounding box. `depth` for a layer is the depth of its origin.
- **`depthRange`** (`near`, `far`) is the depth range of the layer's geometry. For sprites, tiles and groups it comes from bounding boxes; for zones it comes from the actual vertices.

Supported cameras: perspective and orthographic, including lens shift and any sensor fit. Panoramic cameras aren't supported. Non-square pixel aspect produces a warning.

### `data.json`

```jsonc
{
  "name": "level1",
  "width": 1920, "height": 1080,
  "camera": { "name": "Camera", "type": "orthographic", "orthoScale": 20, "pixelsPerUnit": 96, ... },
  "tile_slice_size": 512,
  "tile_scaled_versions": [],
  "parameters": { "difficulty": 3 },
  "layers": [
    { "name": "spawn", "category": "point", "x": 960, "y": 300, "depth": 19.0,
      "initialDepth": 7, "attributes": { "team": "red" },
      "source": { "kind": "object", "name": "P | spawn | team:\"red\"", "objectType": "EMPTY" } },

    { "name": "crate", "category": "sprite", "x": 400, "y": 380, "width": 192, "height": 192,
      "filePath": "sprites/crate.png",
      "origin": { "x": 496, "y": 476, "depth": 20.0 }, "depth": 20.0,
      "depthRange": { "near": 19.0, "far": 21.0 }, "initialDepth": 3, "attributes": {} },

    { "name": "lake", "category": "zone", "x": 717, "y": 517, "width": 566, "height": 566,
      "points": [ { "x": 717.2, "y": 800, "depth": 20.0 }, ... ],
      "subpaths": [[[717.2, 800], ...]],
      "bbox": { "left": 717.2, "top": 517.2, "right": 1282.8, "bottom": 1082.8 }, ... },

    { "name": "ground", "category": "tileset", "x": 0, "y": 0, "width": 1920, "height": 1080,
      "columns": 4, "rows": 3, "filetype": "png", ... },

    { "name": "props", "category": "sprite", "type": "atlas", "filePath": "sprites/props.png",
      "frames": { "barrel": { "x": 0, "y": 0, "width": 96, "height": 96 }, ... },
      "instances": [ { "name": "barrel", "x": 220, "y": 790, "depth": 20.0, "origin": {...} } ], ... }
  ]
}
```

Fields shared with psd-to-json: `name`, `category`, `type`, `x`, `y`, `width`, `height`, `initialDepth`, `attributes`, `children`, `filePath`, `columns`/`rows`/`filetype` for tiles, `frames`/`instances` for atlases, `frame_width`/`frame_height`/`frame_count`/`columns`/`rows` for spritesheets, and `subpaths`/`bbox` for zones.

Fields added here: `depth`, `depthRange`, `origin`, zone `points` with per-point depth, `source` (the Blender datablock the layer came from), the top-level `camera` and `parameters`, and `warnings` when something was skipped.

Differences from psd-to-json:

- Scaled tile versions are resized proportionally, so partial tiles at the right and bottom edges keep their aspect ratio. psd-to-json stretches them to a square.
- Atlases are shelf-packed with padding.
- No layer masks, opacity or blend modes, since there's no Blender equivalent here yet.

## How it works

1. **Inside Blender** (`blender_stage/`, needs only `bpy`): resolve parameters, walk the collection tree, project points, zones and bounds through the camera, and render each sprite, tile set or frame on its own. Each render covers only the item's projected bounding box. The camera's sensor, shift and resolution are adjusted for that render so pixels line up exactly with the full frame. Output goes to a temporary folder as `raw.json` plus untrimmed PNGs.
2. **In your Python** (`post/`, needs Pillow): trim, slice tiles, pack atlases and spritesheets, compress, assign `initialDepth`, and write `data.json`.

## Development

```bash
pip install -e '.[test]'
pytest
```

The unit tests don't need Blender. `tests/test_end_to_end.py` builds a scene and runs the whole CLI, using the [`bpy` module](https://pypi.org/project/bpy/) in place of the Blender executable (`tests/blender/fake_blender.py`). It's skipped unless `bpy` is installed, and `bpy` needs a matching Python version (3.11 for bpy 4.x/5.x).
