"""Run the blender-to-json CLI from inside Blender, plus scene-setup helpers.

Rendering happens in a separate background Blender started by the CLI, so the
interface stays responsive and the export is identical to a command-line run.
Unsaved changes are exported by saving a temporary copy of the file.
"""

import json
import math
import os
import platform
import queue
import shlex
import shutil
import subprocess
import tempfile
import threading

import bpy
from bpy.props import EnumProperty

from . import preview
from .core import plan as planner

TEXT_NAME = 'blender-to-json dry run'


class _Job:
    """The one export that can run at a time."""
    process = None
    lines = None
    log = []
    status = ''
    output_dir = ''
    temp_dir = None
    mode = ''


def is_running():
    return _Job.process is not None


def status_text():
    return _Job.status


def find_cli(prefs):
    command = (prefs.cli_command or '').strip() if prefs else ''
    if command:
        return shlex.split(command)
    found = shutil.which('blender-to-json')
    if found:
        return [found]
    for candidate in ('~/.local/bin/blender-to-json', '/opt/homebrew/bin/blender-to-json',
                      '/usr/local/bin/blender-to-json'):
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return [path]
    return None


def _prefs(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _selected_layer_names(context):
    """Names to pass to --only: each selected object's nearest exported layer."""
    nodes = preview.build(context.scene)
    parents = {}

    def index(items, parent):
        for node in items:
            parents[(node.kind, node.blender_name)] = (node, parent)
            index(node.frames, node)
            index(node.children, node)

    index(nodes, None)
    names = []
    for obj in context.selected_objects:
        entry = parents.get(('object', obj.name))
        node = entry[0] if entry else None
        while node is not None and not (node.status == planner.EXPORT and node.category != 'group'):
            entry = parents.get((node.kind, node.blender_name))
            node = entry[1] if entry else None
        if node is not None and node.blender_name not in names:
            names.append(node.blender_name)
    return names


def _open_folder(path):
    if platform.system() == 'Windows':
        os.startfile(path)  # noqa: S606
    elif platform.system() == 'Darwin':
        subprocess.Popen(['open', path])
    else:
        subprocess.Popen(['xdg-open', path])


def _reader(stream, lines):
    for line in iter(stream.readline, ''):
        lines.put(line.rstrip('\n'))
    stream.close()


class ExportSetupError(Exception):
    def __init__(self, message, level='ERROR'):
        super().__init__(message)
        self.level = level


def prepare_export(context, mode, cli=None):
    """Build the blender-to-json command for this scene.

    Returns (command, cwd, output_folder, temp_dir). temp_dir holds a saved
    copy of the scene when there are unsaved changes; delete it afterwards.
    """
    cli = cli or find_cli(_prefs(context))
    if cli is None:
        raise ExportSetupError('blender-to-json not found. Install the CLI (pip install -e '
                               'blender-to-json-cli) and set its path in the add-on preferences')

    settings = context.scene.blender_to_json_settings.export
    if not settings.output_dir and mode != 'DRYRUN':
        raise ExportSetupError('Choose an output folder in Export Settings first')
    if settings.output_dir.startswith('//') and not bpy.data.filepath:
        raise ExportSetupError('Save the file first (the output folder is relative to it)')
    output_dir = bpy.path.abspath(settings.output_dir) if settings.output_dir else tempfile.gettempdir()

    only = []
    if mode == 'SELECTED':
        only = _selected_layer_names(context)
        if not only:
            raise ExportSetupError('None of the selected objects belong to an exported layer', 'WARNING')

    # Export what's on screen: save a temporary copy if there are unsaved changes.
    name = os.path.splitext(os.path.basename(bpy.data.filepath))[0] or 'untitled'
    temp_dir = None
    blend = bpy.data.filepath
    if not blend or bpy.data.is_dirty:
        temp_dir = tempfile.mkdtemp(prefix='b2j-plugin-')
        blend = os.path.join(temp_dir, f'{name}.blend')
        bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True, relative_remap=True, check_existing=False)

    cmd = list(cli) + [blend, '--blender', bpy.app.binary_path, '-o', output_dir,
                       '--set', f'name={json.dumps(name)}']
    if len(bpy.data.scenes) > 1:
        cmd += ['--set', f'scene={json.dumps(context.scene.name)}']
    if settings.config_path:
        cmd += ['--config', bpy.path.abspath(settings.config_path)]
    if only:
        cmd += ['--only', ','.join(only)]
    if mode == 'DRYRUN':
        cmd.append('--dryrun')
    return cmd, os.path.dirname(blend), os.path.join(output_dir, name), temp_dir


class B2J_OT_export(bpy.types.Operator):
    bl_idname = 'blender_to_json.export'
    bl_label = 'Export'
    bl_options = {'REGISTER'}

    mode: EnumProperty(items=[
        ('ALL', 'Export', 'Export everything named in this scene'),
        ('SELECTED', 'Export Selected', 'Export only the layers the selected objects belong to (--only), '
                                        'merging them into the existing data.json'),
        ('DRYRUN', 'Dry Run', 'Show what would be exported, without rendering (--dryrun)'),
    ])

    @classmethod
    def description(cls, context, properties):
        return {
            'ALL': 'Render and export everything named in this scene',
            'SELECTED': "Export only the selected objects' layers and merge them into the existing data.json",
            'DRYRUN': 'Show what would be exported and rendered, without rendering anything',
        }[properties.mode]

    @classmethod
    def poll(cls, context):
        return not is_running()

    def execute(self, context):
        try:
            cmd, cwd, output_folder, temp_dir = prepare_export(context, self.mode)
        except ExportSetupError as e:
            self.report({e.level}, str(e))
            return {'CANCELLED'}
        cli = cmd[:1]
        print('[blender-to-json] $ ' + ' '.join(shlex.quote(c) for c in cmd))
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       errors='replace', cwd=cwd)
        except OSError as e:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            self.report({'ERROR'}, f"Couldn't start {cli[0]}: {e}")
            return {'CANCELLED'}

        _Job.process = process
        _Job.lines = queue.Queue()
        _Job.log = []
        _Job.mode = self.mode
        _Job.status = 'Starting…'
        _Job.output_dir = output_folder
        _Job.temp_dir = temp_dir
        threading.Thread(target=_reader, args=(process.stdout, _Job.lines), daemon=True).start()

        self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        while not _Job.lines.empty():
            line = _Job.lines.get_nowait()
            _Job.log.append(line)
            print(line)
            if line.startswith('[blender-to-json]'):
                _Job.status = line[len('[blender-to-json] '):]
        _redraw(context)
        if _Job.process.poll() is None:
            return {'PASS_THROUGH'}

        context.window_manager.event_timer_remove(self._timer)
        while not _Job.lines.empty():
            _Job.log.append(_Job.lines.get_nowait())
        code = _Job.process.returncode
        _Job.process = None
        if _Job.temp_dir:
            shutil.rmtree(_Job.temp_dir, ignore_errors=True)

        if _Job.mode == 'DRYRUN' or code != 0:
            text = bpy.data.texts.get(TEXT_NAME) or bpy.data.texts.new(TEXT_NAME)
            text.from_string('\n'.join(_Job.log))
        if code != 0:
            _Job.status = f'Failed (exit code {code}). Full log in the Text Editor: "{TEXT_NAME}"'
            self.report({'ERROR'}, _Job.status)
        elif _Job.mode == 'DRYRUN':
            _Job.status = f'Dry run finished. Open "{TEXT_NAME}" in the Text Editor to read it'
            self.report({'INFO'}, _Job.status)
        else:
            _Job.status = f'Exported to {_Job.output_dir}'
            self.report({'INFO'}, _Job.status)
            if context.scene.blender_to_json_settings.export.open_folder and os.path.isdir(_Job.output_dir):
                _open_folder(_Job.output_dir)
        _redraw(context)
        return {'FINISHED'}


def _redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class B2J_OT_cancel(bpy.types.Operator):
    bl_idname = 'blender_to_json.cancel'
    bl_label = 'Cancel Export'
    bl_description = 'Stop the running export'

    @classmethod
    def poll(cls, context):
        return is_running()

    def execute(self, context):
        _Job.process.terminate()
        _Job.status = 'Cancelled'
        return {'FINISHED'}


class B2J_OT_open_folder(bpy.types.Operator):
    bl_idname = 'blender_to_json.open_folder'
    bl_label = 'Open Folder'
    bl_description = 'Open the output folder for this file'

    def execute(self, context):
        settings = context.scene.blender_to_json_settings.export
        if not settings.output_dir:
            self.report({'WARNING'}, 'No output folder set')
            return {'CANCELLED'}
        name = os.path.splitext(os.path.basename(bpy.data.filepath))[0] or 'untitled'
        path = os.path.join(bpy.path.abspath(settings.output_dir), name)
        if not os.path.isdir(path):
            path = bpy.path.abspath(settings.output_dir)
        if not os.path.isdir(path):
            self.report({'WARNING'}, f'{path} does not exist yet')
            return {'CANCELLED'}
        _open_folder(path)
        return {'FINISHED'}


class B2J_OT_copy_command(bpy.types.Operator):
    bl_idname = 'blender_to_json.copy_command'
    bl_label = 'Copy CLI Command'
    bl_description = 'Copy a blender-to-json command for this file to the clipboard'

    def execute(self, context):
        path = bpy.data.filepath
        if not path:
            self.report({'WARNING'}, 'Save the file first')
            return {'CANCELLED'}
        text = f'blender-to-json "{path}"'
        if len(bpy.data.scenes) > 1:
            text += f' --set scene={json.dumps(context.scene.name)}'
        context.window_manager.clipboard = text
        self.report({'INFO'}, f'Copied: {text}')
        return {'FINISHED'}


# ---------------------------------------------------------------------- scene setup

# rotation (degrees XYZ), location, ortho scale — from blender-2d-tile-tools,
# plus top-down and 2:1 presets.
CAMERA_PRESETS = {
    'SIDE': ((90, 0, 0), (0, -10, 1)),
    'TOP_DOWN': ((0, 0, 0), (0, 0, 10)),
    'ISOMETRIC': ((54.736, 0, 45), (10, -10, 10)),
    'DIMETRIC': ((60, 0, 45), (10, -10, 8.165)),
}


class B2J_OT_create_camera(bpy.types.Operator):
    bl_idname = 'blender_to_json.create_camera'
    bl_label = 'Create Camera'
    bl_description = 'Add an orthographic camera for the chosen tile view and make it the scene camera'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.blender_to_json_settings.export
        preset = settings.camera_preset
        rotation, location = CAMERA_PRESETS[preset]
        name = {'SIDE': 'SideCamera', 'TOP_DOWN': 'TopDownCamera', 'ISOMETRIC': 'IsometricCamera',
                'DIMETRIC': 'DimetricCamera'}[preset]
        data = bpy.data.cameras.new(name)
        data.type = 'ORTHO'
        data.ortho_scale = 10
        obj = bpy.data.objects.new(name, data)
        obj.rotation_euler = tuple(math.radians(a) for a in rotation)
        obj.location = location
        context.collection.objects.link(obj)
        context.scene.camera = obj
        self.report({'INFO'}, f'Added {name} as the scene camera')
        return {'FINISHED'}


class B2J_OT_transparent_film(bpy.types.Operator):
    bl_idname = 'blender_to_json.transparent_film'
    bl_label = 'Render Transparent'
    bl_description = 'Turn on transparent film so test renders match the export (the CLI always does this)'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.render.film_transparent = True
        return {'FINISHED'}


class B2J_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    cli_command: bpy.props.StringProperty(
        name='blender-to-json Command', subtype='FILE_PATH', default='',
        description='Path to the blender-to-json executable (for example inside the virtualenv you installed '
                    'it into). Leave empty to look on PATH')

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'cli_command')
        found = find_cli(self)
        if found:
            layout.label(text=f'Using: {" ".join(found)}', icon='CHECKMARK')
        else:
            layout.label(text='blender-to-json not found on PATH. Install it and point to it here.', icon='ERROR')
            layout.label(text='macOS apps launched from the Dock don\'t see your shell PATH, so set the full path.')
        from . import maintenance
        maintenance.draw_preferences(layout)


classes = (B2J_OT_export, B2J_OT_cancel, B2J_OT_open_folder, B2J_OT_copy_command, B2J_OT_create_camera,
           B2J_OT_transparent_film, B2J_Preferences)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    if _Job.process is not None:
        _Job.process.terminate()
        _Job.process = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
