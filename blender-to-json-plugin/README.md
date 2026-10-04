# Blender to JSON (plugin)

A Blender add-on that goes with the [blender-to-json CLI](../blender-to-json-cli).

For now it does one thing: it stores **named parameters** in a `.blend` file (a camera, an object, a collection, text, a number or a toggle). You can then refer to them as `@name` from the CLI's config file or command line:

```bash
blender-to-json level1.blend --set camera=@topDown --set tile_slice_size=@tileSize
```

This lets each `.blend` decide which camera to use, how large its tiles are and so on, while one shared config works for every file.

## Install

Blender 4.2 and newer (extensions):

```bash
cd blender-to-json-plugin
python build.py        # writes dist/blender_to_json_plugin-0.1.0.zip
```

Then use **Edit › Preferences › Get Extensions › ⌄ › Install from Disk…** and pick the zip.

Blender 3.6–4.1: **Edit › Preferences › Add-ons › Install…**, pick the same zip, and enable "Blender to JSON".

For development you can also symlink `blender_to_json_plugin/` into your add-ons (or extensions) folder.

## Use

Open the **Blender to JSON** tab in the 3D Viewport sidebar (press `N`).

- **+** adds a parameter. The camera button adds a camera parameter set to the selected camera, or to the scene camera if no camera is selected.
- Each parameter has a **name** (letters, digits and underscores), a **type** and a **value**, plus an optional description.
- The copy buttons put `@name`, or a ready-made `--param name=value`, on the clipboard.
- **Copy CLI Command** (at the top of the panel) copies a `blender-to-json "<this file>"` command line.

Problems such as an invalid or duplicate name, or an empty camera/object/collection value, are shown in red in the list.

### Referencing parameters from the CLI

| Where | Example |
| --- | --- |
| Config file | `"camera": "@topDown"` |
| `--set` | `--set camera=@topDown` |
| Layer attributes | `P | spawn | level:@difficulty`, or a custom property whose value is `"@difficulty"` |
| Override from the CLI | `--param difficulty=5` |
| Inspect a file | `blender-to-json level1.blend --list-params` |

Camera, object and collection parameters resolve to the datablock's name. The resolved values are also written to `data.json` under `"parameters"`.

## Where the data lives

The list you edit in the panel belongs to the add-on. The CLI runs Blender without the add-on, so the plugin also writes a plain JSON copy into a scene custom property called `blender_to_json`:

```json
{
  "version": 1,
  "parameters": {
    "topDown":  { "type": "CAMERA", "value": "Camera.002" },
    "tileSize": { "type": "INT",    "value": 256, "description": "Tile size for this level" }
  }
}
```

The copy is updated whenever you edit a parameter, and again every time the file is saved, which picks up renamed cameras and objects. **Refresh Stored Parameters** does the same thing by hand.

The copy is ordinary data, so scripts can write it too. If a file has the JSON property but an empty list (for example, it was written by a script), the plugin fills the list from the JSON when the file is opened.

## Tests

```bash
pip install bpy pytest   # bpy needs Python 3.11
pytest tests
```
