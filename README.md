# Blender to JSON

Export a Blender scene as 2D game assets plus a JSON manifest. This is the Blender counterpart of [psd-to-json](https://github.com/laffan/psd-to-json): collections and objects are named with the same `category | name | type | attributes` scheme, rendered through a camera, and described in a `data.json` that [psd-to-phaser](https://github.com/laffan/psd-to-phaser) can read.

```
README.md
dev_install.py            installs both from this checkout (run after every pull)
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

# 3. Check how it's parsed, then export
blender-to-json scenes/level1.blend --dryrun
blender-to-json scenes/level1.blend -o assets
blender-to-json scenes/level1.blend -o assets --only house   # re-export one asset
```

The [Blender to JSON plugin](blender-to-json-plugin) works inside Blender:

- **Parameters.** Pick any property with an eyedropper (or right-click it) and give it a name. The CLI can then set it (`--param resolutionX=1024`) or read it (`"camera": "@camera"`).
- **Export Preview.** A live tree of how the CLI will parse the scene.
- **Export, Export Selected and Dry Run buttons**, plus the settings and tools from [blender-2d-tile-tools](https://github.com/laffan/blender-2d-tile-tools), which this project replaces: tile camera presets, base tile scaling, grid snapping, crop with ground, cast shadows and PSD output.

See [blender-to-json-cli/README.md](blender-to-json-cli/README.md) for the full configuration reference and output format, and [blender-to-json-plugin/README.md](blender-to-json-plugin/README.md) for the add-on.

## Development install

Run this after cloning and after every `git pull`:

```bash
python3 dev_install.py            # add --test to also run both test suites
```

It needs Python 3.9+ and Blender. It finds Blender the same way the CLI does; pass `--blender /path/to/blender` if it can't. Each run:

1. installs the CLI in editable mode into `.venv/` in this folder (created on the first run), with the PSD and test extras,
2. refreshes the plugin's copy of the shared `core/` code,
3. runs Blender in the background with your normal preferences to **link** the plugin folder into Blender's add-ons (`extensions/user_default/blender_to_json`, or `scripts/addons` before Blender 4.2), enable it, point its *blender-to-json Command* preference at `.venv`, and save your preferences.

Because the plugin is linked rather than copied, pulled changes only need **Reset Scripts** (bottom of the Blender to JSON tab, or in the add-on preferences) or a Blender restart. Re-running the script after a pull is still worthwhile, because it picks up new Python dependencies and keeps the core copy in sync.

**Quit Blender before the first run.** An open Blender saves its own preferences when it quits, and that would undo the add-on being enabled. Later runs are fine with Blender open.

Options:

| Flag | |
| --- | --- |
| `--test` | Run the CLI and plugin test suites afterwards. The Blender-backed tests need `pip install bpy` in `.venv` (Python 3.11) and are skipped otherwise. |
| `--copy` | Install the built zip instead of linking, to test the packaged add-on. |
| `--blender PATH` | Blender executable to install into. |
| `--venv PATH` | Use another virtualenv for the CLI. |
| `--skip-cli` / `--skip-plugin` | Only do one half. |
| `--uninstall` | Remove the plugin from Blender and delete `.venv`. |

To uninstall from inside Blender, use **Uninstall** in the add-on's preferences. For a linked install it only removes the link; your checkout is never deleted.

## Credits

The render-isolation approach and the tile features come from [blender-2d-tile-tools](https://github.com/laffan/blender-2d-tile-tools). The naming scheme and output format come from [psd-to-json](https://github.com/laffan/psd-to-json).
