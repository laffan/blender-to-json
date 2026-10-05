# Blender to JSON (plugin)

A Blender add-on that goes with the [blender-to-json CLI](../blender-to-json-cli). It replaces [blender-2d-tile-tools](https://github.com/laffan/blender-2d-tile-tools).

Everything is in the **Blender to JSON** tab of the 3D Viewport sidebar (press `N`):

| Panel | What it does |
| --- | --- |
| **Blender to JSON** | Export, Export Selected, Dry Run, Open Folder, Copy Command. |
| **Setup** | Create a tile camera (side, top-down, isometric, 2:1 isometric), turn on transparent film. |
| **Export Settings** | Output folder, camera, base tile and tile width, grid snapping, crop with ground, cast shadows, PSD output… Saved in the `.blend` and used by the CLI too. |
| **Parameters** | Track any Blender property under a name the CLI can set (`--param`) and read (`@name`). |
| **Export Preview** | A live, collapsible tree showing how the CLI will parse the scene. |

## Install

1. Install the CLI (see its README). The plugin runs it to export.
2. Build the add-on zip:

   ```bash
   cd blender-to-json-plugin
   python build.py        # writes dist/blender_to_json_plugin-0.2.0.zip
   ```

3. In Blender 4.2 or newer: **Edit › Preferences › Get Extensions › ⌄ › Install from Disk…** and pick the zip. In Blender 3.6–4.1: **Edit › Preferences › Add-ons › Install…**.
4. In the add-on's preferences, set **blender-to-json Command** to the CLI executable, e.g. `/path/to/venv/bin/blender-to-json`. If it's on your `PATH` you can leave this empty. On macOS, Blender started from the Dock doesn't see your shell's `PATH`, so give the full path.

If you used blender-2d-tile-tools, disable it. The two don't conflict, but this one covers the same ground (see the [mapping table](../blender-to-json-cli/README.md#tile-tools-from-blender-2d-tile-tools)).

## Parameters

A parameter is a name attached to one Blender property: the render width, a light's power, the scene camera, a material input, a modifier setting, a custom property. The list shows each property's **live value with its own widget**, so you can see it's being tracked, and edit it right there.

Adding one:

- **Pick Property** (eyedropper button), then click any property field anywhere in Blender: the Properties editor, a node, the sidebar… Esc or right-click cancels.
- **Right-click any property › Track as Blender to JSON Parameter.**
- **Paste button**: paste a full data path (hover a property and press `Ctrl+Shift+Alt+C` to copy one), e.g. `bpy.data.lights["Sun"].energy`.

The name is suggested from the property (`resolution_x` → `resolutionX`); rename it to whatever you want to type on the command line. Then:

```bash
blender-to-json level1.blend --param resolutionX=1024     # sets the property for this export
```

```json
{ "tile_slice_size": "@tileSize", "camera": "@camera" }    // reads its current value
```

The copy buttons put `"@name"`, or a `--param name=<current value>` flag, on the clipboard. Parameters follow renamed objects and materials. If the tracked datablock is deleted, the row turns red.

## Export Preview

A tree of the scene's collections and objects, rebuilt every time the panel redraws, using the same code the CLI uses for `--dryrun`:

- Each named item shows its category (`G`, `S`, `T`, `P`, `Z`), name, type, whether it gets rendered, and its attributes.
- Unnamed objects inside a sprite or tile collection are marked *in render*.
- Everything else that won't be exported is greyed out with the reason (*no category*, *G must be a collection*…). Problems are shown in red.
- Click a name to select the object or make the collection active. Use the triangles to collapse branches.
- The checkbox excludes an item from the export. Exclusions are stored with the file (as `ignoreLayers`) and listed under Export Settings.

The preview reflects the settings stored in the file. A separate config file can change the result (for example its own `ignoreLayers`); the CLI's `--dryrun` shows the exact outcome.

## Exporting from Blender

- **Export** renders everything and writes `data.json` to the output folder.
- **Export Selected** works out which exported layers the selected objects belong to (selecting a wall inside `S | house` exports the house) and runs the CLI with `--only`. The results are merged into the existing `data.json`.
- **Dry Run** runs `--dryrun` and puts the report in a Text Editor block called *blender-to-json dry run*.

The export runs in a separate background Blender, so the interface stays usable. Progress shows in the panel, and the running export can be cancelled. If the file has unsaved changes, a temporary copy is exported, so what you see is what gets exported. If the export fails, the full log is put in the same Text Editor block.

## Where the data lives

The panels edit add-on properties. The CLI runs Blender without the add-on, so the plugin also keeps a plain JSON copy in a scene custom property called `blender_to_json`, refreshed whenever you change something and every time the file is saved:

```json
{
  "version": 2,
  "parameters": {
    "resolutionX": { "id_type": "scenes", "id_name": "Scene", "path": "render.resolution_x", "value": 1920 },
    "sunPower":    { "id_type": "lights", "id_name": "Sun", "path": "energy", "value": 3.0 },
    "level":       { "value": 2 }
  },
  "settings": { "output_dir": "//assets", "baseTile": "Tile", "tileWidth": 64 }
}
```

`value` is the property's value at the last save, used by `--list-params` and as a fallback if the datablock disappears. Entries with only a `value` are constants; scripts can add them and the plugin keeps them. Only settings you changed from their defaults are written.

## Development

The plugin carries a copy of the CLI's `core` package (naming, export plan, data paths, parameters), so the preview and the CLI always agree. Edit the CLI's copy, then:

```bash
python sync_core.py
pip install bpy pytest pillow   # bpy needs Python 3.11
pytest tests
```

The tests run headless with the `bpy` module. They cover tracking, the JSON copy, renames, the preview tree, camera presets, panel drawing (against a fake layout) and a real export through the CLI. They can't click in a real Blender window, so the eyedropper's click handling and the right-click menu entry are untested. They use Blender's own *Copy Data Path* operator and context menu hook, but please report it if either doesn't pick up a property.
