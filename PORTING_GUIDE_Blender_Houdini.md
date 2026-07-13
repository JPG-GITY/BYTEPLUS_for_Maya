# BYTEPLUS for DCCs — Application Audit & Port Guide (Maya → Blender / Houdini)

> Scope: audit of the current single-file Maya plugin `byteplus_maya.py` (~9,200
> lines, v1.09) and a concrete, step-by-step plan to port it to **Blender** (`bpy`)
> and **Houdini** (`hou`). Written 2026-07 against the live source.

---

# PART 1 — APPLICATION AUDIT

## 1.1 Architecture at a glance

The plugin is a single Python module, but it is already **layered** — and that is
the single most important fact for porting. Roughly:

```
┌─────────────────────────────────────────────────────────────────────┐
│  A. PORTABLE CORE  (~55–60% of the code — ZERO DCC coupling)         │
│     BytePlus API, hosting, ffmpeg, prefs, telemetry, prompt builders │
├─────────────────────────────────────────────────────────────────────┤
│  B. Qt UI LAYER  (~25% — ~30 QDialog/QWidget classes)               │
│     Portable in spirit; only "who is the parent window" differs      │
├─────────────────────────────────────────────────────────────────────┤
│  C. DCC-SPECIFIC LAYER  (~15–20% — the real port surface)           │
│     maya.cmds / mel / OpenMayaUI: viewport, playblast, render,       │
│     shaders, 3D import, scene queries, menu, threading, undo         │
└─────────────────────────────────────────────────────────────────────┘
```

**The port is essentially: keep A, re-host B, and re-implement C behind an
adapter.** Layer C is where 100% of the effort goes.

## 1.2 Module / component inventory

Grouped by layer (function/class names are real, from the source).

### Layer A — Portable core (moves as-is)
- **HTTP / API**: `_open`, `_request`, `_get_bytes`, `_api_key`, `_ssl_context`,
  `_find_video_url`.
- **Image gen (Seedream)**: `_seedream`, `_is_pro`, `_pro_size`, `_image_size`,
  `_img_ref_uri`, `_asset_uri`, `_data_uri`, `_ref_data_uri`.
- **Video gen (Seedance)**: `_seedance_generate`, `_seedance_edit`,
  `_should_retry_failure`, `_bind_refs`, `_seedance_edit_wrap`.
- **LLM (Seed 2.0)**: `_chat`, `_chat_with_tools`, `_caption_viewport`,
  `_caption_motion`, `_describe_scene_motion`, the `_enhance_*` family,
  `_compose_*`, `_human_*`/`_item_*` prompt builders.
- **3D gen (Seed 3D)**: `_seed3d_generate`, `_find_model_url`,
  `_extract_3d_archive` (download half — the *import* half is Layer C).
- **Trusted Asset Library**: `_ark_call` + Volcengine signing, `_asset_*`
  (create/list/get/delete), `_asset_store_*` (local cache).
- **Hosting**: `_r2_*` (hand-rolled AWS SigV4), `_tos_*` (SDK), `_host_video`,
  `_motion_host_*`, `_sigv4_signing_key`.
- **ffmpeg**: `_ffmpeg_exe`, `_ffmpeg_h264_encoder`, `_ensure_seedance_video`,
  `_ffprobe_exe`, `_video_duration`, `_probe_video_dims`, `_extract_video_frames`,
  `_extract_poster_frame`, `_fit_video_seconds`, `_mux_audio_from`,
  `_has_audio_stream`, `_is_dark_image`.
- **Persistence / state**: `_load_prefs`, `_save_prefs`, `_load/_save_usage`,
  `_track`, `usage_snapshot`, `_load_hidden`/`_hide_paths`, the `_*_sidecar`
  helpers, `_url_is_fresh`.
- **Telemetry**: `_posthog_*`, `_telemetry_*`, `_maybe_identify`.
- **Cost model**: `_est_video_cost`, `_est_image_cost`, `_fmt_cost`, `CONFIG`.

### Layer B — Qt UI (re-host; ~30 classes)
`PreviewWindow`, `_ActivityHUD`, `_ProgressHandle`, `_ZoomView`, `_ABCompare`,
`ABCompareDialog`, `VideoEditDialog`, `VideoGallery`, `AnimateDialog`,
`_ModelPicker`, `DreamDialog`, `RefineDialog`, `_AnnotateCanvas`,
`InteractiveEditDialog`, `DreamGallery`, `TrustedCharacterDialog`,
`LayoutStillDialog`, `ComposeSceneDialog`, `SeedCharacterDialog`, `TextureDialog`,
`SettingsDialog`, `MotionHostWizard`, `SeedChatDialog`, `_ChatInput`,
`Seed3DDialog`, `_CodeApprovalDialog`, `SeedAssistantDialog`,
`_BlockoutPreviewDialog`. All PySide6/PySide2.

### Layer C — DCC-specific (the port surface)
| Concern | Maya entry points |
|---|---|
| Host-window bridge | `_main_window` (`omui.MQtUtil.mainWindow` + `wrapInstance`) |
| Menu / install | `install`, `uninstall`, `register menu` (`cmds.menu/menuItem`, `mel.eval $gMainWindow`), `initializePlugin`/`uninitializePlugin`, `_style_tp_item` |
| Thread marshalling | `maya.utils` (main-thread execution), `_Worker(QThread)` |
| Viewport snapshot | `_viewport_snapshot`, `_playblast_frame`, `_active_model_panel`, `_isolate_polys`, `_restore_panel` (`cmds.modelEditor/getPanel`) |
| Playblast (motion) | `_playblast_movie`, `_playblast_is_valid` (`cmds.playblast`) |
| Render (look) | `_render_frame`, `_arnold_render_to_file`, `_render_one` (`cmds.render/arnoldRender/vrend/rsRender`, `colorManagementPrefs`, `renderWindowEditor`) |
| Scene / anim queries | `_anim_range`, `_scene_fps`, `_anim_seconds`, `_has_animation`, `_active_camera`, `_maya_focal_length`, `_frame_samples` (`currentTime`, `playbackOptions`, `currentUnit`, `upAxis`, `getAttr`) |
| PBR shader | `_build_openpbr`, `_make_file_texture`, `_first_existing_attr` (`shadingNode`, `connectAttr`, `sets`, `bump2d`) |
| 3D import | `_save_and_import_3d` (`cmds.file(i=True)`, `pluginInfo/loadPlugin`, `mayaUsdPlugin`) |
| Blockout | `_build_blockout`, `_build_blockout_camera`, `_project_image_on_blockout` (`polyPlane/Cube/…`, `camera`, `lookThru`, `xform`, `matchTransform`) |
| Scene assistant | `_tool_scene_info`, `SeedAssistantDialog` (generates & runs `maya.cmds`!) |
| Undo | `cmds.undoInfo(openChunk/closeChunk)` |
| Toasts / project | `cmds.inViewMessage`, `_project_subdir` (`cmds.workspace`), `_scene_stem` (`cmds.file(q)`), `cmds.about` |

## 1.3 External dependencies

| Dependency | Required? | Used for | Port note |
|---|---|---|---|
| `maya.cmds` / `maya.mel` / `maya.OpenMayaUI` / `maya.utils` | **Maya-only** | everything in Layer C | **replace** with `bpy` / `hou` |
| PySide6 **or** PySide2 + shiboken6/2 | yes (UI) | all dialogs | Houdini ships PySide; **Blender does not** (see §2.5) |
| **ffmpeg / ffprobe** (bundled LGPL binary) | yes (video) | transcode AVI/MOV→MP4 H.264, probe, poster, retime, mux | **fully portable** — bundle the same binary |
| `certifi` | optional | SSL CA bundle when host Python lacks one | portable |
| `tos` (BytePlus SDK) | optional | TOS hosting (R2 needs nothing) | portable |
| stdlib only otherwise | — | `urllib`, `hashlib`, `hmac`, `json`, `subprocess`, `ssl`, `base64`, `datetime`, `tempfile`, `threading` | portable |

**No PIL / numpy / requests.** Image ops go through **ffmpeg + Qt QPixmap**, not
PIL. Network is pure `urllib`. This keeps the core dependency-light and portable.

## 1.4 Maya API surface (quantified)

- **248** `cmds.*` calls · **1** `mel.eval` (only to fetch `$gMainWindow`) · a
  thin `OpenMayaUI`/`shiboken` bridge (main window + one menu-item restyle).
- By family (approx.): **~40** menu (`menu`/`menuItem`/`deleteUI`), **~40**
  `inViewMessage` (toasts), **~25** shader (`shadingNode`/`connectAttr`/`setAttr`/
  `sets`), **~25** blockout primitives (`poly*`/`move`/`parent`/`camera`/`lookThru`
  /`xform`), **~20** render (`render`/`arnoldRender`/`vrend`/`rsRender`/
  `renderWindowEditor`/`colorManagementPrefs`), **~10** scene/anim
  (`currentTime`/`playbackOptions`/`currentUnit`/`upAxis`), playblast (`playblast`
  ×4), `file` (import/query ×5), `undoInfo`, `pluginInfo`/`loadPlugin`.

**Takeaway:** the coupling is broad but **shallow and command-style** (almost no
deep OpenMaya/OM2). That is the good case for porting: most calls map 1:1 to a
`bpy`/`hou` equivalent.

## 1.5 Critical invariants — DO NOT BREAK

These are load-bearing across the whole app and must be preserved in any port:

1. **Main-thread-only DCC calls.** `cmds.*`/`mel`/OpenMaya/playblast/render are
   main-thread-only; calling them from a `_Worker` (QThread) **hard-crashes** Maya.
   Only **network** work runs in workers. The same rule holds for `bpy` (Blender
   is *very* strict — off-thread `bpy` = crash/corruption) and `hou` (must use its
   deferred-execution API). **Any DCC operation a worker needs must be marshalled
   back to the main thread.**
2. **Modal re-entrancy (`_msgbox`).** A modal opened from inside another modal's
   `exec()` loop, plus toggling `WindowStaysOnTopHint` on a live modal, freezes the
   UI (fixed this session via `activeModalWidget()` guard). Keep the guard when
   re-hosting the UI.
3. **Seedance "trusted output" chain.** Face-bearing images are only animatable if
   passed **byte-identical / URL-passthrough** (fresh Seedream URL or permanent
   `asset://`). **Never re-encode/re-host** a trusted image or clip — it strips the
   trust and moderation rejects it. (`_img_ref_uri` passes `http`/`asset://`
   through untouched.)
4. **Seedance concurrency cap** (3 individual / 10 enterprise) — the worker pool +
   `SEEDANCE_MAX_CONCURRENT` guard.
5. **ffmpeg is mandatory for video.** Seedance needs MP4/H.264; the bundled LGPL
   build uses `libopenh264` (there is no libx264). Keep `_ffmpeg_h264_encoder`'s
   encoder selection.
6. **Prefs override.** `~/.byteplus_maya.json` (+ `_assets`, `_usage`, `_hidden`)
   overrides code defaults for `_PERSISTED` keys. Portable as-is.
7. **Playblast duration must match an integer output duration** or Seedance
   time-warps the motion (`_fit_video_seconds`/`fit_motion`).

## 1.6 Failure points & incompatibilities (for the port)

- **Blender has no Qt.** This is the single biggest incompatibility. Blender ships
  its own UI toolkit (`bpy.types.Panel`/`Operator`) and **no PySide**. You must
  either (a) run Qt inside Blender via a managed `QApplication` (the `bqt`/
  "blender-qt" pattern — fragile, event-loop integration issues) or (b) **rewrite
  Layer B natively**. Houdini, by contrast, ships PySide2/6 and `hou.qt` — Layer B
  is nearly drop-in there.
- **Renderer plumbing differs the most.** Maya drives Arnold/V-Ray/Redshift/
  Maya-HW via `cmds.render`/`arnoldRender`. Blender = Cycles/EEVEE via
  `bpy.ops.render.render`. Houdini = Karma/Mantra/Arnold via render ROPs. The
  *concept* ("render N keyframes to disk for the look") ports; the API does not.
- **Playblast/OpenGL capture differs.** `cmds.playblast` → Blender
  `bpy.ops.render.opengl(animation=True)` → Houdini flipbook / OpenGL ROP. Output
  containers differ (Blender writes frames or FFmpeg via its own encoder; you'll
  likely capture frames and reuse the plugin's ffmpeg step).
- **Shader graphs are node-model-specific.** Maya `openPBRSurface` + `bump2d` +
  `file` → Blender **Principled BSDF** + **Image Texture** + **Normal Map** nodes
  (in `material.node_tree`) → Houdini **Principled Shader**/**MaterialX**/Karma
  material builder. Same maps, different graph API.
- **Color management differs.** Maya OCIO (`colorManagementPrefs`) vs Blender's
  built-in OCIO (Filmic/AgX) vs Houdini OCIO. The "bake the view transform into the
  saved frame" behavior needs per-DCC handling (or accept raw sRGB).
- **Threading marshalling API differs** (see §2.6). `maya.utils
  .executeInMainThreadWithResult` has no direct Blender equivalent — Blender uses
  `bpy.app.timers` + a result queue; Houdini uses `hdefereval.executeDeferred`.
- **The Seed Assistant runs DCC code the LLM writes.** Its system prompt tells the
  model to "write minimal `maya.cmds` code." Ported, the model must emit **`bpy`**
  or **`hou`** code — a different prompt, tool schema, and safety review. Treat as a
  per-DCC rewrite, not a mapping.
- **Undo model differs.** Maya `undoInfo(openChunk/closeChunk)` → Blender relies on
  operator undo (`bpy.ops.ed.undo_push`) → Houdini `hou.undos.group()`.
- **Menu/entry-point model differs** (§2.7). Maya module + `initializePlugin` →
  Blender add-on (`bl_info`, `register()`) → Houdini package JSON + shelf/menu XML.
- **File-path & unit conventions.** up-axis (Maya Y-up, often; Blender Z-up;
  Houdini Y-up), scene units, project/workspace roots (`cmds.workspace` →
  `bpy.path`/`bpy.data.filepath` → `hou.hipFile`/`$HIP`).

---

# PART 2 — PORTING GUIDE (Maya → Blender & Houdini)

## 2.1 Strategy: one adapter, three back-ends

**Do NOT fork the file three ways.** Introduce a thin **DCC adapter** and route
every Layer-C call through it. The portable core (A) and UI (B) import only the
adapter, never `cmds`/`bpy`/`hou` directly.

```
byteplus_core/                 # Layer A + B, DCC-agnostic (shared, unchanged)
  api.py  seedream.py  seedance.py  seed3d.py  assets.py  hosting.py
  ffmpeg.py  prefs.py  telemetry.py  ui/*.py
  dcc.py                       # <-- the adapter INTERFACE (abstract)
adapters/
  dcc_maya.py                  # implements dcc.py with maya.cmds  (refactor of today)
  dcc_blender.py               # implements dcc.py with bpy
  dcc_houdini.py               # implements dcc.py with hou
byteplus_maya.py  byteplus_blender.py  byteplus_houdini.py   # thin entry points
```

`dcc.py` exposes one object (e.g. `DCC`) resolved at import time:

```python
# byteplus_core/dcc.py
def get_dcc():
    try:
        import maya.cmds            # noqa
        from adapters.dcc_maya import MayaDCC
        return MayaDCC()
    except ImportError:
        pass
    try:
        import bpy                  # noqa
        from adapters.dcc_blender import BlenderDCC
        return BlenderDCC()
    except ImportError:
        pass
    import hou                      # noqa
    from adapters.dcc_houdini import HoudiniDCC
    return HoudiniDCC()

DCC = get_dcc()
```

**Step 0 of the port is a refactor with NO behavior change:** move every
`cmds.*`/`mel`/`omui` call in `byteplus_maya.py` behind `DCC.<method>()`,
implement `MayaDCC` with today's exact code, and verify the Maya build is
byte-for-byte equivalent. Only then start `dcc_blender.py` / `dcc_houdini.py`.

## 2.2 What ports as-is (Layer A)

The entire portable core moves with **zero changes**: `_seedream`,
`_seedance_generate`, `_seed3d_generate`, `_chat`, `_ark_call` + Volc signing, all
`_asset_*`, `_r2_*`/`_tos_*` hosting, all ffmpeg helpers, prefs/usage/telemetry,
cost model, and every prompt builder/enhancer. These touch only `urllib`,
`hashlib`, `subprocess`, and the filesystem. **~55–60% of the plugin is done for
free on both targets.**

## 2.3 The DCC adapter interface

Define these ~25 methods (grouping the Layer-C surface). Every one has a Maya
implementation today; the port is filling in the Blender/Houdini columns.

```python
class DCCBase:
    # --- host / UI ---
    def main_window(self): ...                 # QWidget or None
    def inview_message(self, text): ...         # transient toast
    def run_in_main_thread(self, fn): ...       # marshal a callable, return result
    def undo_chunk(self): ...                   # context manager (one Ctrl+Z)

    # --- scene / animation queries ---
    def scene_name(self): ...                   # stem for filenames
    def project_dir(self, kind): ...            # images/movies/models roots
    def fps(self): ...
    def frame_range(self): ...                  # (start, end)
    def has_animation(self): ...
    def current_time(self, t=None): ...         # get/set
    def active_camera(self): ...
    def camera_focal_length(self, cam): ...
    def up_axis(self): ...                       # 'y' | 'z'

    # --- capture ---
    def viewport_snapshot(self, path): ...       # 1 still (look/layout ref)
    def playblast_movie(self, start, end, path): ...   # motion clip
    def sample_frame(self, frame, path): ...     # 1 frame for motion sampling
    def render_frame(self, frame, cam, path): ...      # look keyframe (active renderer)

    # --- authoring ---
    def build_pbr_material(self, target, maps, bump_depth): ...  # albedo/rough/metal/normal
    def import_3d(self, path, fmt): ...           # returns new nodes/objects
    def build_blockout(self, objects): ...        # primitives + camera + optional projection

    # --- lifecycle ---
    def register_menu(self, items): ...
    def unregister_menu(self): ...
```

## 2.4 Per-operation mapping (Maya → Blender → Houdini)

### (a) Host window / Qt parent
| Maya | Blender | Houdini |
|---|---|---|
| `wrapInstance(int(omui.MQtUtil.mainWindow()), QWidget)` | no Qt main window — parent to `None` and manage a `QApplication` yourself, **or** rewrite UI native | `hou.qt.mainWindow()` |

```python
# MayaDCC
def main_window(self):
    import maya.OpenMayaUI as omui
    from shiboken6 import wrapInstance
    return wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)

# HoudiniDCC
def main_window(self):
    import hou
    return hou.qt.mainWindow()

# BlenderDCC  (Qt path) — no host QWidget; keep dialogs parentless + always-on-top
def main_window(self):
    return None
```

### (b) Thread marshalling (CRITICAL)
| Maya | Blender | Houdini |
|---|---|---|
| `maya.utils.executeInMainThreadWithResult(fn)` | `bpy.app.timers.register` + result queue | `hdefereval.executeDeferred(fn)` |

```python
# MayaDCC
def run_in_main_thread(self, fn):
    import maya.utils
    return maya.utils.executeInMainThreadWithResult(fn)

# HoudiniDCC
def run_in_main_thread(self, fn):
    import hdefereval, hou
    return hdefereval.executeDeferred(fn)  # or executeInMainThreadWithResult

# BlenderDCC — Blender has no synchronous marshaller; push work to a timer queue
import queue
_MAIN_Q = queue.Queue()
def _drain():
    while not _MAIN_Q.empty():
        fn, box = _MAIN_Q.get()
        try: box['r'] = fn()
        except Exception as e: box['e'] = e
    return 0.05  # reschedule
bpy.app.timers.register(_drain, persistent=True)
def run_in_main_thread(self, fn):
    box = {}; _MAIN_Q.put((fn, box))
    # for fire-and-forget UI updates this is enough; for a blocking result,
    # spin a short wait or (better) restructure the caller to be callback-based.
```

> **Design consequence:** on Maya/Houdini the existing `_Worker.done`→main-thread
> slot pattern works directly (Qt delivers the queued signal on the main thread).
> On Blender-with-Qt you must guarantee the Qt event loop is pumped; the timer
> queue above is the safety net.

### (c) Viewport snapshot (look/layout reference)
| Maya | Blender | Houdini |
|---|---|---|
| `cmds.playblast(frame=…, format='image', …)` single frame; `modelEditor` to isolate | `bpy.ops.render.opengl(write_still=True)` after `scene.render.filepath=…` | `hou.SceneViewer` OpenGL ROP / flipbook 1 frame |

```python
# BlenderDCC
def viewport_snapshot(self, path):
    import bpy
    sc = bpy.context.scene
    sc.render.filepath = path
    # OpenGL (viewport) render == Maya's playblast-still
    bpy.ops.render.opengl(write_still=True, view_context=True)
    return path
```

### (d) Playblast movie (motion reference)
| Maya | Blender | Houdini |
|---|---|---|
| `cmds.playblast(startTime,endTime,format='qt'/'avi',…)` | `bpy.ops.render.opengl(animation=True)` → frames, then reuse `_ensure_seedance_video` (ffmpeg → MP4) | flipbook to frames → `_ensure_seedance_video` |

> Reuse the plugin's **existing ffmpeg step** everywhere: capture frames or a raw
> clip, then `_ensure_seedance_video(path)` produces the Seedance-safe MP4/H.264.
> This keeps the "container/codec" logic in Layer A and out of the adapters.

### (e) Render frame (look keyframe, active renderer)
| Maya | Blender | Houdini |
|---|---|---|
| `cmds.arnoldRender` / `cmds.render` / `vrend` / `rsRender`; `renderWindowEditor` writeImage | `bpy.ops.render.render(write_still=True)` (Cycles/EEVEE) | `rop.render()` on a Karma/Mantra/Arnold ROP |

```python
# BlenderDCC
def render_frame(self, frame, cam, path):
    import bpy
    sc = bpy.context.scene
    sc.frame_set(frame)
    if cam: sc.camera = bpy.data.objects[cam]
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path

# HoudiniDCC
def render_frame(self, frame, cam, path):
    import hou
    rop = hou.node('/out/byteplus_render') or hou.node('/out').createNode('karma', 'byteplus_render')
    rop.parm('camera').set(cam);  rop.parmTuple('f').set((frame, frame, 1))
    rop.parm('picture').set(path); rop.render()
    return path
```

### (f) Scene / animation queries
| Concern | Maya | Blender | Houdini |
|---|---|---|---|
| fps | `mel getAttr time` / `currentUnit` | `scene.render.fps / fps_base` | `hou.fps()` |
| frame range | `playbackOptions -q -min/-max` | `scene.frame_start/frame_end` | `hou.playbar.frameRange()` |
| set time | `cmds.currentTime(f)` | `scene.frame_set(f)` | `hou.setFrame(f)` |
| active camera | panel `lookThru`/`modelEditor -q -camera` | `scene.camera` | viewer `curViewport().defaultCamera()` |
| focal length | `getAttr cam.focalLength` | `cam.data.lens` | `/obj/cam.parm('focal')` |
| up axis | `cmds.upAxis(q,axis=True)` | Z-up (constant) | Y-up (constant) |

### (g) PBR material (Generate Texture + Seed 3D material)
Maya today (`_build_openpbr`): `openPBRSurface` + `file` textures + `bump2d`,
wired via `connectAttr`, assigned with `sets`.

```python
# BlenderDCC — Principled BSDF equivalent
def build_pbr_material(self, target_obj, maps, bump_depth):
    import bpy
    mat = bpy.data.materials.new("byteplus_pbr"); mat.use_nodes = True
    nt = mat.node_tree; bsdf = nt.nodes["Principled BSDF"]
    def tex(fp, colorspace):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(fp); n.image.colorspace_settings.name = colorspace
        return n
    nt.links.new(tex(maps["baseColor"], "sRGB").outputs["Color"], bsdf.inputs["Base Color"])
    if maps.get("specularRoughness"):
        nt.links.new(tex(maps["specularRoughness"], "Non-Color").outputs["Color"], bsdf.inputs["Roughness"])
    if maps.get("baseMetalness"):
        nt.links.new(tex(maps["baseMetalness"], "Non-Color").outputs["Color"], bsdf.inputs["Metallic"])
    if maps.get("normal"):
        nm = nt.nodes.new("ShaderNodeNormalMap"); nm.inputs["Strength"].default_value = bump_depth
        nt.links.new(tex(maps["normal"], "Non-Color").outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    obj = bpy.data.objects[target_obj]
    obj.data.materials.clear(); obj.data.materials.append(mat)
```
Houdini: build a **MaterialX** or **Principled Shader** subnet (a
`mtlximage`→`mtlxstandard_surface`, or `principledshader::2.0` with texture parms),
then assign via a Material SOP / `obj.parm('shop_materialpath')`.

### (h) 3D import (Seed 3D)
Maya today (`_save_and_import_3d`): `cmds.file(i=True, type=…)` with
`mayaUsdPlugin` for USD; ext→(plugin,type) map `_3D_IMPORT`.

| fmt | Maya | Blender | Houdini |
|---|---|---|---|
| USD/USDZ | `file(i, type='USD Import')` (`mayaUsdPlugin`) | `bpy.ops.wm.usd_import(filepath=…)` | LOP `reference`, or `usdimport`/Solaris |
| FBX | `file(i, type='FBX')` | `bpy.ops.import_scene.fbx(filepath=…)` | File SOP / `kinefx`/FBX import |
| OBJ | `file(i, type='OBJ')` | `bpy.ops.wm.obj_import(filepath=…)` | File SOP |

Wrap the import in the DCC's undo group so it stays one Ctrl+Z (see (j)).

### (i) Blockout (primitives + camera + image projection)
Maya today: `polyPlane/Cube/Cylinder/Sphere/Cone`, `move/rotate/parent/xform`,
`camera`+`lookThru`, and a projection material for the 2.5D matte.

| Op | Maya | Blender | Houdini |
|---|---|---|---|
| box/plane/etc. | `cmds.polyCube(...)` | `bpy.ops.mesh.primitive_cube_add(...)` | `hou.node('/obj').createNode('geo')` + Box SOP |
| transform | `cmds.move/rotate/xform` | `obj.location/rotation_euler/matrix_world` | `geo.parmTuple('t'/'r').set(...)` |
| camera + look-through | `cmds.camera` + `cmds.lookThru` | `bpy.data.cameras.new` + set `scene.camera` + align view | `/obj` camera + set viewport camera |
| project photo | file→projection shader | camera-projection via UV Project / Empty | camera-based UV / COPs projection |

### (j) inview toast + undo chunk
```python
# toast
MayaDCC:    cmds.inViewMessage(amg=text, pos="midCenter", fade=True)
BlenderDCC: bpy.context.workspace.status_text_set(text)   # or operator self.report
HoudiniDCC: hou.ui.setStatusMessage(text)

# undo chunk (context manager)
MayaDCC:    cmds.undoInfo(openChunk=True) ... cmds.undoInfo(closeChunk=True)
HoudiniDCC: with hou.undos.group("BYTEPLUS import"): ...
BlenderDCC: operators are auto-undo; wrap batch ops and call bpy.ops.ed.undo_push(message=…)
```

## 2.5 Qt & UI per DCC (Layer B)

- **Houdini — easy.** Ships PySide2/6 + `hou.qt`. Keep all ~30 dialogs. Change only
  `_main_window()` → `hou.qt.mainWindow()`. Watch stylesheet differences and that
  dialogs are parented so they don't fall behind Houdini panels (you already solved
  the always-on-top/`_msgbox` problem — reuse it).
- **Blender — the hard decision.** Blender has **no Qt**. Two routes:
  1. **Qt-in-Blender** (`bqt`/managed `QApplication`): keep the dialogs, but you own
     the event loop. Fragile: modal `exec()` loops fight Blender's loop, crashes on
     some platforms, and threading/`_Worker` needs the timer pump from §2.4(b).
     Fastest to a demo, riskiest to ship.
  2. **Native rewrite** (`bpy.types.Panel` + `Operator` + `PropertyGroup`): robust,
     Blender-idiomatic, but Layer B is re-authored (galleries, canvases, wizards).
     The **annotation canvas** (`_AnnotateCanvas`, QGraphicsView) and the A/B compare
     slider are the costly pieces — reimplement with Blender's image editor / gizmos
     or defer them. Recommended for a shippable Blender add-on.
- Keep Layer A untouched under either route — dialogs only ever call core functions
  and `DCC`.

## 2.6 Threading model per DCC

- **Maya / Houdini:** keep `_Worker(QThread)`; network runs off-thread; `.done`/
  `.failed` slots run on the main thread (Qt queued connection) and are safe to
  touch UI + `run_in_main_thread` for any DCC op. Unchanged.
- **Blender-native:** no Qt signals. Use a background `threading.Thread` for the
  network call, hand results to `bpy.app.timers` (the §2.4(b) queue), and update a
  `PropertyGroup` the panel reads. **Never** call `bpy` off-thread.

## 2.7 Packaging & install per DCC

| | Maya (today) | Blender | Houdini |
|---|---|---|---|
| Unit | module (`BYTEPLUS.mod` + `install.py` drag-drop) | **add-on** (`bl_info`, `register()/unregister()`, zip installed via Preferences) | **package** (`byteplus.json` in `packages/`) + shelf/menu |
| Entry | `initializePlugin`/`register menu` | `register()` adds `bpy.types` + menu draw | `123.py`/shelf tool + `MainMenuCommon.xml` |
| ffmpeg | bundled `bin/win/ffmpeg.exe` | same, bundle in the add-on | same, in the package |
| Auto-load | `userSetup.py` block | enabled in Preferences (persist) | package auto-loads |
| Crash guard | `MAYA_DISABLE_ADP=1` in `Maya.env` | n/a | n/a |

## 2.8 Feature port-difficulty matrix

| Feature | Core reuse | Port cost — Houdini | Port cost — Blender |
|---|---|---|---|
| Text-to-Image / Image-to-Image / Dream / Layout→Still / Refine / Interactive Edit / Seed Character | ~95% | **Low** (viewport snapshot only) | **Low-core / Med-UI** (Qt-less canvas) |
| Dream & Video galleries, Compare | ~90% | Low | Med (native rewrite of grids/slider) |
| Animate (Seedance) | ~85% | **Med** (playblast) | Med |
| Render with Seedance | ~70% | **Med-High** (render ROP) | **Med-High** (Cycles/EEVEE) |
| Generate Texture (PBR shader) | ~60% | Med (MaterialX/Karma) | Med (Principled node graph) |
| Seed 3D (download+import) | ~85% | Med (USD/FBX import) | Low-Med (native importers) |
| Blockout from image | ~55% | Med (SOP primitives) | Med (mesh ops + projection) |
| Trusted Characters | ~98% | Low | Low |
| Seed Chat | ~95% | Low | Low-core / Med-UI |
| **Seed Assistant** | ~40% | **High** (LLM must emit `hou` code) | **High** (LLM must emit `bpy` code) |
| Motion hosting wizard / Settings / Usage / About | ~95% | Low | Med-UI |

## 2.9 Recommended phasing

1. **Phase 0 — Refactor (Maya only, no behavior change).** Extract `DCC` adapter;
   move all `cmds`/`mel`/`omui` behind `MayaDCC`. Ship as the same v1.x.
2. **Phase 1 — Houdini image-only.** `dcc_houdini.py` for main-window, toast,
   snapshot, scene queries, thread-marshal. Enables every image feature + Trusted
   Characters + Seed Chat. Fast win (Qt is native).
3. **Phase 2 — Houdini video + 3D.** Add playblast/flipbook, render ROP, USD/FBX
   import, MaterialX texture. Now Animate/Render/Seed 3D/Texture work.
4. **Phase 3 — Blender core + native UI.** Decide Qt-in-Blender vs native; build the
   panels for image features first (native), reuse `dcc_blender.py` for snapshot/
   scene. Ship image-only Blender add-on.
5. **Phase 4 — Blender video/3D/texture**, then **Phase 5 — Seed Assistant** per
   DCC (new codegen prompt + tool schema + review).

## 2.10 Gotchas & pitfalls (carry these forward)

- **Never call `bpy`/`hou`/`cmds` off the main thread.** Marshal everything.
- **Never re-encode a trusted image/clip** — breaks Seedance face trust.
- **Keep the ffmpeg step in Layer A** — don't reimplement transcode per DCC.
- **Blender modal + Qt `exec()`** loops conflict; prefer native UI or a well-managed
  QApplication with the timer pump.
- **Up-axis / units**: Blender Z-up vs Maya/Houdini Y-up affects blockout camera
  math and 3D import orientation — normalize on import.
- **Color management**: decide early whether to bake the view transform (OCIO) into
  saved frames or ship raw sRGB; it differs in all three.
- **Re-use the `_msgbox` always-on-top / re-entrancy fix** wherever Qt is hosted.
- **Renderer detection**: Maya probes Arnold/V-Ray/Redshift; Blender is Cycles/EEVEE
  only; Houdini needs the user's chosen ROP — surface it in Settings per DCC.

---

*Bottom line: ~55–60% (Layer A) is portable untouched; Houdini is the low-risk
first target (native PySide) at roughly **2–4 weeks** for image+video+3D; Blender
adds a UI-toolkit rewrite that dominates its cost. The Seed Assistant is the only
feature that is a genuine per-DCC rebuild rather than a mapping.*
