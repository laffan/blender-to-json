"""Reset Scripts and Uninstall.

Both act on the add-on's own code, so the real work is deferred to a timer:
the operator finishes first, then the add-on is reloaded or removed.
"""

import os

import addon_utils
import bpy

from . import export_ops

PACKAGE = __package__
ADDON_DIR = os.path.dirname(os.path.abspath(__file__))


def is_link(path):
    # Windows junctions (made by dev_install.py without symlink rights) aren't
    # reported by islink(); they resolve to somewhere else.
    return os.path.islink(path) or (os.name == 'nt' and os.path.isdir(path)
                                    and os.path.realpath(path).lower() != os.path.abspath(path).lower())


def install_info(module=PACKAGE, path=ADDON_DIR):
    """Describe how the add-on is installed: (kind, detail).

    kind is 'extension', 'addon' or 'linked' (a symlink made by dev_install.py).
    """
    if is_link(path):
        return 'linked', os.path.realpath(path)
    if module.startswith('bl_ext.'):
        return 'extension', path
    return 'addon', path


def reset_scripts():
    """Reload every add-on's scripts, like Blender's Reload Scripts.

    That operator only schedules this same call on a timer; we already run
    from one, so call it directly.
    """
    bpy.utils.load_scripts(reload_scripts=True)
    for window in getattr(bpy.context.window_manager, 'windows', ()):
        for area in window.screen.areas:
            area.tag_redraw()


def uninstall(module=PACKAGE, path=ADDON_DIR):
    """Disable the add-on and delete its installed files.

    A symlinked development install only loses the link; the source folder it
    points to is never touched.
    """
    if is_link(path):
        addon_utils.disable(module, default_set=True)
        (os.rmdir if os.name == 'nt' else os.unlink)(path)  # removes the link, never its target
        if module.startswith('bl_ext.'):
            bpy.ops.extensions.repo_refresh_all()
        return
    if module.startswith('bl_ext.'):
        _, repo_module, pkg_id = module.split('.', 2)
        repos = [repo.module for repo in bpy.context.preferences.extensions.repos]
        if repo_module in repos:
            bpy.ops.extensions.package_uninstall(repo_index=repos.index(repo_module), pkg_id=pkg_id)
            return
    addon_utils.disable(module, default_set=True)
    bpy.ops.preferences.addon_remove(module=module)


def _deferred(func):
    def run():
        try:
            func()
        except Exception as e:  # noqa: BLE001 - nothing else would report it
            print(f'[blender-to-json] {func.__name__} failed: {e}')
        return None
    bpy.app.timers.register(run, first_interval=0.05)


class B2J_OT_reset_scripts(bpy.types.Operator):
    bl_idname = 'blender_to_json.reset_scripts'
    bl_label = 'Reset Scripts'
    bl_description = ("Reload all add-on scripts (Blender's Reload Scripts), picking up changes to this "
                      "add-on's files after a git pull")

    def execute(self, context):
        if export_ops.is_running():
            self.report({'WARNING'}, 'Cancel the running export first')
            return {'CANCELLED'}
        _deferred(reset_scripts)
        return {'FINISHED'}


class B2J_OT_uninstall(bpy.types.Operator):
    bl_idname = 'blender_to_json.uninstall'
    bl_label = 'Uninstall Blender to JSON'
    bl_description = 'Disable this add-on and remove its files (a linked development copy only loses the link)'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if export_ops.is_running():
            self.report({'WARNING'}, 'Cancel the running export first')
            return {'CANCELLED'}
        kind, detail = install_info()
        self.report({'INFO'}, 'Removing the link to ' + detail if kind == 'linked' else 'Uninstalling Blender to JSON')
        _deferred(uninstall)
        return {'FINISHED'}


def draw_preferences(layout):
    kind, detail = install_info()
    box = layout.box()
    col = box.column(align=True)
    if kind == 'linked':
        col.label(text='Development install, linked to:', icon='LINKED')
        col.label(text=detail)
    else:
        col.label(text=f'Installed at: {detail}', icon='PACKAGE')
    row = box.row()
    row.operator(B2J_OT_reset_scripts.bl_idname, icon='FILE_REFRESH')
    row.alert = True
    row.operator(B2J_OT_uninstall.bl_idname, text='Uninstall', icon='TRASH')


classes = (B2J_OT_reset_scripts, B2J_OT_uninstall)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
