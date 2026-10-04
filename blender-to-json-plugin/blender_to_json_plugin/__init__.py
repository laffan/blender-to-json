"""Blender to JSON: companion add-on for the blender-to-json CLI.

For now it manages named parameters stored in the .blend file, which the CLI
can refer to as "@name" in its config file or on the command line.
"""

bl_info = {
    'name': 'Blender to JSON',
    'description': 'Named parameters for the blender-to-json command-line exporter',
    'author': 'Nate Laffan',
    'version': (0, 1, 0),
    'blender': (3, 6, 0),
    'location': 'View3D > Sidebar > Blender to JSON',
    'category': 'Import-Export',
}

from . import operators, properties, sync, ui  # noqa: E402

_modules = (properties, operators, ui, sync)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
