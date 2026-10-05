"""Blender to JSON: companion add-on for the blender-to-json CLI.

- Parameters: track any Blender property (eyedropper or right-click) so the CLI
  can set it with --param name=value and read it as @name.
- Export Preview: a live view of how the CLI will parse the scene.
- Export: run the CLI from Blender, with the settings and tools that used to
  live in blender-2d-tile-tools (camera presets, base tile, ground crop, PSD).
"""

bl_info = {
    'name': 'Blender to JSON',
    'description': 'Export collections and objects as 2D game assets with a JSON manifest',
    'author': 'Nate Laffan',
    'version': (0, 2, 0),
    'blender': (3, 6, 0),
    'location': 'View3D > Sidebar > Blender to JSON',
    'category': 'Import-Export',
}

from . import export_ops, params_ops, preview, properties, sync, ui  # noqa: E402

_modules = (properties, sync, params_ops, preview, export_ops, ui)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
