"""TouchDesigner UDP light bridge for Blender.

Messages use the form ``LIGHT,<channel>,<energy>``, for example
``LIGHT,front_red,500``.  Channels are mapped to Blender light objects in the
sidebar UI, so neither side needs to use the other's object names.
"""

bl_info = {
    "name": "TouchDesigner Light Bridge",
    "author": "KarmanovNS",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > TD Light",
    "description": "Receive TouchDesigner UDP light values and bake them to keyframes",
    "category": "Animation",
}

import bpy
import queue
import socket
import threading
import time


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9001
_messages = queue.Queue()
_server_thread = None
_stop_event = threading.Event()
_bake_started_at = None
_last_baked_frame = {}


class TDLightMapping(bpy.types.PropertyGroup):
    """A TouchDesigner channel and the Blender light it controls."""

    channel: bpy.props.StringProperty(
        name="TD Channel",
        description="Channel received after LIGHT, (for example front_red)",
        default="light",
    )
    light: bpy.props.PointerProperty(
        name="Blender Light",
        description="Light object controlled by this channel",
        type=bpy.types.Object,
        poll=lambda _self, obj: obj.type == "LIGHT",
    )


class TDLightBridgePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    host: bpy.props.StringProperty(name="Bind address", default=DEFAULT_HOST)
    port: bpy.props.IntProperty(name="UDP port", default=DEFAULT_PORT, min=1, max=65535)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Restart the receiver after changing these settings.")
        layout.prop(self, "host")
        layout.prop(self, "port")


def _preferences():
    return bpy.context.preferences.addons[__package__].preferences


def _receiver(host, port, stop_event):
    """Receive packets off Blender's main thread; never call bpy from here."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.settimeout(0.1)
    except OSError as error:
        print(f"TD Light Bridge: could not bind {host}:{port}: {error}")
        return

    print(f"TD Light Bridge: listening on {host}:{port}")
    with sock:
        while not stop_event.is_set():
            try:
                data, _address = sock.recvfrom(1024)
                _messages.put((data.decode("utf-8").strip(), time.monotonic()))
            except socket.timeout:
                continue
            except UnicodeDecodeError:
                print("TD Light Bridge: ignored non-UTF-8 packet")
            except OSError as error:
                if not stop_event.is_set():
                    print(f"TD Light Bridge: UDP error: {error}")
                return


def _find_mapping(scene, channel):
    channel = channel.casefold()
    return next((item for item in scene.td_light_mappings
                 if item.light and item.channel.strip().casefold() == channel), None)


def _apply_message(scene, message, received_at):
    parts = [part.strip() for part in message.split(",")]
    if len(parts) != 3 or parts[0].upper() != "LIGHT":
        print(f"TD Light Bridge: ignored invalid packet: {message!r}")
        return
    try:
        energy = float(parts[2])
    except ValueError:
        print(f"TD Light Bridge: invalid energy in packet: {message!r}")
        return

    mapping = _find_mapping(scene, parts[1])
    if mapping is None:
        print(f"TD Light Bridge: no mapping for channel {parts[1]!r}")
        return

    mapping.light.data.energy = energy
    if scene.td_light_is_baking:
        _insert_bake_keyframe(scene, mapping.light, received_at)


def _insert_bake_keyframe(scene, light, received_at):
    fps = scene.render.fps / scene.render.fps_base
    frame = scene.td_light_bake_start + int((received_at - _bake_started_at) * fps)
    if frame > scene.td_light_bake_end:
        _finish_bake(scene)
        return
    # Multiple UDP packets in a frame should leave only the most recent value.
    light.data.keyframe_insert(data_path="energy", frame=frame)
    _last_baked_frame[light.name] = frame


def _finish_bake(scene):
    global _bake_started_at
    scene.td_light_is_baking = False
    _bake_started_at = None
    _last_baked_frame.clear()
    print("TD Light Bridge: bake complete")


def _update_lights():
    scene = bpy.context.scene
    while True:
        try:
            message, received_at = _messages.get_nowait()
        except queue.Empty:
            break
        _apply_message(scene, message, received_at)

    if scene.td_light_is_baking and _bake_started_at is not None:
        fps = scene.render.fps / scene.render.fps_base
        if scene.td_light_bake_start + int((time.monotonic() - _bake_started_at) * fps) > scene.td_light_bake_end:
            _finish_bake(scene)
    return 1 / 60


def _start_receiver():
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        return False
    prefs = _preferences()
    _stop_event.clear()
    _server_thread = threading.Thread(
        target=_receiver, args=(prefs.host, prefs.port, _stop_event), daemon=True,
        name="TDLightBridgeUDP",
    )
    _server_thread.start()
    return True


def _stop_receiver():
    global _server_thread
    _stop_event.set()
    if _server_thread:
        _server_thread.join(timeout=0.25)
    _server_thread = None


class TDLIGHT_OT_add_mapping(bpy.types.Operator):
    bl_idname = "td_light.add_mapping"
    bl_label = "Add Light Mapping"

    def execute(self, context):
        context.scene.td_light_mappings.add()
        context.scene.td_light_mapping_index = len(context.scene.td_light_mappings) - 1
        return {'FINISHED'}


class TDLIGHT_OT_remove_mapping(bpy.types.Operator):
    bl_idname = "td_light.remove_mapping"
    bl_label = "Remove Light Mapping"

    def execute(self, context):
        scene = context.scene
        if scene.td_light_mappings:
            scene.td_light_mappings.remove(scene.td_light_mapping_index)
            scene.td_light_mapping_index = min(scene.td_light_mapping_index, len(scene.td_light_mappings) - 1)
        return {'FINISHED'}


class TDLIGHT_OT_toggle_receiver(bpy.types.Operator):
    bl_idname = "td_light.toggle_receiver"
    bl_label = "Start/Stop UDP Receiver"

    def execute(self, context):
        if _server_thread and _server_thread.is_alive():
            _stop_receiver()
            self.report({'INFO'}, "TouchDesigner receiver stopped")
        else:
            _start_receiver()
            self.report({'INFO'}, "TouchDesigner receiver started")
        return {'FINISHED'}


class TDLIGHT_OT_bake(bpy.types.Operator):
    bl_idname = "td_light.bake"
    bl_label = "Bake Light Animation"

    def execute(self, context):
        global _bake_started_at
        scene = context.scene
        if scene.td_light_bake_end < scene.td_light_bake_start:
            self.report({'ERROR'}, "End frame must not be before start frame")
            return {'CANCELLED'}
        if scene.td_light_is_baking:
            _finish_bake(scene)
            self.report({'INFO'}, "Light bake stopped")
        else:
            scene.td_light_is_baking = True
            _bake_started_at = time.monotonic()
            self.report({'INFO'}, "Recording TouchDesigner values to light keyframes")
        return {'FINISHED'}


class TDLIGHT_PT_panel(bpy.types.Panel):
    bl_label = "TouchDesigner Light"
    bl_idname = "TDLIGHT_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "TD Light"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        running = _server_thread is not None and _server_thread.is_alive()
        layout.operator("td_light.toggle_receiver", text="Stop Receiver" if running else "Start Receiver",
                        icon='PAUSE' if running else 'PLAY')
        layout.label(text="Mappings: TD channel → Blender light")
        for item in scene.td_light_mappings:
            row = layout.row(align=True)
            row.prop(item, "channel", text="")
            row.prop(item, "light", text="")
        row = layout.row(align=True)
        row.operator("td_light.add_mapping", icon='ADD', text="Add Mapping")
        row.operator("td_light.remove_mapping", icon='REMOVE', text="")
        layout.separator()
        layout.label(text="Bake received values")
        row = layout.row(align=True)
        row.prop(scene, "td_light_bake_start", text="Start")
        row.prop(scene, "td_light_bake_end", text="End")
        layout.operator("td_light.bake", text="Stop Baking" if scene.td_light_is_baking else "Bake Animation",
                        icon='CANCEL' if scene.td_light_is_baking else 'REC')


_classes = (
    TDLightMapping, TDLightBridgePreferences, TDLIGHT_OT_add_mapping,
    TDLIGHT_OT_remove_mapping, TDLIGHT_OT_toggle_receiver, TDLIGHT_OT_bake,
    TDLIGHT_PT_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.td_light_mappings = bpy.props.CollectionProperty(type=TDLightMapping)
    bpy.types.Scene.td_light_mapping_index = bpy.props.IntProperty(default=0)
    bpy.types.Scene.td_light_bake_start = bpy.props.IntProperty(name="Bake Start", default=1)
    bpy.types.Scene.td_light_bake_end = bpy.props.IntProperty(name="Bake End", default=250)
    bpy.types.Scene.td_light_is_baking = bpy.props.BoolProperty(default=False)
    if not bpy.app.timers.is_registered(_update_lights):
        bpy.app.timers.register(_update_lights, persistent=True)


def unregister():
    _stop_receiver()
    if bpy.app.timers.is_registered(_update_lights):
        bpy.app.timers.unregister(_update_lights)
    for name in ("td_light_is_baking", "td_light_bake_end", "td_light_bake_start",
                 "td_light_mapping_index", "td_light_mappings"):
        delattr(bpy.types.Scene, name)
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
