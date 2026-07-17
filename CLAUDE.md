# CLAUDE.md — BYTEPLUS for Maya (working rules)

Single-file Maya 2025+ plugin (`byteplus_maya.py`, ~9k lines, PySide6/PySide2)
integrating BytePlus ModelArk AI (Seedream image, Seedance video, Seed 3D, Seed
2.0 LLM, Seed Audio). Read this before editing.

## Golden rules (from the plugin owner)
- **Don't break what works** ("no romper nada que funciona"). Prefer ADDITIVE
  changes (new windows/functions) over touching working flows.
- **Ask permission before advancing** on anything non-trivial; present a plan first.
- **Don't invent — verify.** Ground every API claim in the `byteplus-models-genius`
  skill (`byteplus-models-genius-skill/.../references/*.md`) or a real probe. If
  unsure, ask.

## Dev loop (ALWAYS)
1. Edit `d:\Maya plugin\BYTEPLUS_for_Maya\byteplus_maya.py`.
2. `python -m py_compile byteplus_maya.py` — must pass.
3. Copy to the INSTALLED module: `C:\Users\johnf\Documents\maya\modules\BYTEPLUS\
   scripts\byteplus_maya.py` (Maya loads THIS, not the d:\ copy).
4. User runs `hard_reload` in Maya. Do NOT touch `dist/` or the zip unless packaging.

## NEVER-BREAK invariants
1. **Main-thread-only DCC calls.** `cmds`/`mel`/`OpenMaya`/`playblast`/`render`
   crash Maya off-thread. Only NETWORK runs in `_Worker` (QThread). Resolve any
   scene paths/queries (`_scene_*_dir`, `_scene_tag`, playblast, `_anim_range`) on
   the MAIN thread and pass the result into the worker — never call cmds inside one.
2. **NEVER force `WindowStaysOnTopHint`. Parent to Maya instead.** Every window is
   built as `QDialog(parent or _main_window())` — a parented child already stays
   above Maya, so the flag only hijacks the whole OS (a real client complaint) and
   it caused a bug chain: on-top windows made message boxes open *behind* a gallery
   ("Maya looks frozen") → `_msgbox` grew a workaround that toggled the flag on
   every window → toggling `WindowStaysOnTopHint`+`show()` RECREATES the native
   handle, which on a window driving a modal `exec()` loop drops its modal grab and
   **FREEZES Maya** (the "Animate freeze"). All 40 flags and the dance are gone
   (v2.0); `_msgbox` now just parents to `activeModalWidget() or _main_window()`.
   Don't reintroduce either. Still true: don't pop modals from worker callbacks
   over another open modal.
3. **Trusted-output chain (faces).** Never re-encode/re-host a trusted image/clip —
   it strips Seedance's face exemption. `_img_ref_uri` passes `http`/`asset://`
   THROUGH untouched. Real external faces are always rejected; use Text to Image /
   Trusted Characters. A moderation error isn't always a face (mirrors/reflections
   false-positive) — surface the real API error, don't hardcode "HUMAN FACE".
4. **ffmpeg is mandatory for video** (bundled LGPL `libopenh264`, no libx264). Keep
   `_ffmpeg_h264_encoder`'s encoder selection; Seedance needs MP4/H.264.
5. **Seedance concurrency pool.** Video jobs go through `_video_jobs_active` /
   `_register_video_job` / `_discard_video_job`; cap = `SEEDANCE_MAX_CONCURRENT`
   (3 individual / 10 enterprise). New video paths must use it.
6. **Extend `_seedance_generate` additively** — new params default to CONFIG/None so
   Animate/Render/Dialogue/Video-GEN callers are unaffected. Respect Seedance's
   mutually-exclusive modes (first_frame / first+last / multimodal).
7. **Prefs override.** `~/.byteplus_maya.json` overrides CONFIG for `_PERSISTED`
   keys; secrets saved only if `REMEMBER_API_KEY`. New CONFIG key → add to
   `_PERSISTED` (and the secrets load/save lists if it's a key).

## Three SEPARATE auth paths — don't mix them
- **ark Bearer API key** — Seedream/Seedance/Seed 3D/Seed 2.0. Host
  `ark.ap-southeast.bytepluses.com`.
- **Voice X-Api-Key** — Seed Audio ONLY. Host `voice.ap-southeast-1.bytepluses.com`.
- **AK/SK (Volcengine HMAC signing)** — Trusted Asset Library. Host
  `ark.ap-southeast-1.byteplusapi.com`.

## Model/API facts (verified)
- Seedream 5.0 Pro = slow (standard-mode, ~170-220s; `HTTP_TIMEOUT=600`); no
  stream/seed/sequential. Lite = fast, supports stream (use Lite for heavy
  multi-image to avoid Cloudflare 524 gateway timeouts).
- Seedance 2.0: modes text/image/first+last/multimodal; Base 480-4k, Fast/Mini
  480/720; `generate_audio` (dialogue in "double quotes"); ES/JA/ID/PT + EN.
- Seed Audio 1.0: EN & CH only right now (ES ~end of July). Billed $0.0025/s.
- `asset://<id>` (Trusted Characters) = permanent Seedance-trusted face; no 24h
  expiry (the fresh-Seedream-URL path expires in 24h).

## Deeper context
Session memory lives in `C:\Users\johnf\.claude\projects\d--Maya-plugin-BYTEPLUS-for-Maya\memory\` (see `MEMORY.md` index) — crash root-causes, pricing, model IDs, per-feature notes. Consult it before diagnosing.
