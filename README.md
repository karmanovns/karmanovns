# TouchDesigner Light Bridge for Blender

This repository intentionally contains only text source files, so it can be uploaded
to services that reject binary files. Build the installable archive locally first:

```bash
python scripts/build_addon.py
```

This creates the untracked file `dist/td_light_bridge.zip`. Install that archive with
**Edit → Preferences → Add-ons → Install…**, then enable **TouchDesigner Light
Bridge**. Open the **TD Light** tab in the 3D View sidebar (`N`) to configure it.

## Mapping names independently

The add-on does not use Blender object names to decode packets. Add one mapping for
each source and enter the TouchDesigner channel in **TD Channel**; choose any Blender
light in **Blender Light**. For example, a packet `LIGHT,red,500` can control an
object named `Stage_Key_01` by mapping `red` to that object. Channel matching ignores
letter case and surrounding whitespace.

## UDP protocol

Start the receiver, then send UTF-8 UDP packets to `127.0.0.1:9001` by default:

```text
LIGHT,red,500
LIGHT,yellow,0
LIGHT,green,1200.5
```

The bind address and port are available in the add-on Preferences. Restart the
receiver after changing them.

## Baking light animation

1. Start the receiver and create the desired mappings.
2. Set **Start** and **End** in the TD Light panel.
3. Click **Bake Animation** exactly when playback/capture should begin.
4. Send values from TouchDesigner. Each received value is inserted as an `energy`
   keyframe using the scene's FPS, beginning at Start. Capture ends automatically
   after End; click **Stop Baking** to stop early.

Existing animation is preserved. If several packets arrive in the same frame, the
last inserted value for that light is Blender's resulting keyframe value.
