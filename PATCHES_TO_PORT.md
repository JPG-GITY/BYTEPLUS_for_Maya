# Getting the Mac work onto the Windows master

**Short version: it is all in git now — `git pull` on the Windows machine.**
`JPG-GITY/BYTEPLUS_for_Maya` (private) holds every change below on `main`, in both
`byteplus_maya.py` and `dist/BYTEPLUS/scripts/byteplus_maya.py`. Hand-copying is no
longer necessary; this file is the inventory of *what* changed and *why*.

> **Line endings matter.** The repo is **CRLF**. Editing the file on macOS with tools
> that rewrite it can flip it to LF, which turns a 500-line change into a 28,000-line
> diff. Convert back to CRLF before committing, or the Windows master gets a
> meaningless whole-file rewrite.

---

## 1. Corporate-VPN SSL failure (macOS only) — CRITICAL

Full write-up: **SSL_CORPORATE_CA_FIX.md**.

The VPN's TLS-inspection proxy re-signs certificates with its own CA. macOS keeps it in
the **keychain**, but Maya's Python verifies against **certifi**, so every request died
with `A failure in the SSL library occurred` while curl/Safari worked.

`_ssl_context()` now merges the keychain CAs via `_os_trust_ca_pem()` / `_add_os_trust()`,
so it works with verification left **ON**. Verified: Windows/Linux are byte-for-byte
unchanged (the helper returns `""` unless `sys.platform == "darwin"`, and a simulated
`win32` build produced an identical 149-CA context).

## 2. Empty-gallery hint

The galleries read `<maya project>/movies|images/byteplus/<scene>/`. With a project
copied from another machine and **Set Project** pointing elsewhere, the gallery was
simply blank and looked like the plugin had lost the files. It now prints the folder it
searched and the active project. `_ZoomView` gained `show_text()` so the Dream preview
(a `QGraphicsView`) can render it.

## 3. Seedance 2.5 support

`dreamina-seedance-2-5-260628` — verified live on this account.

**Capability layer** (this is the part that makes 2.5 safe to select at all):

| Added | What it does |
|---|---|
| `SEEDANCE_MODEL_25`, `SEEDANCE_MODEL_20` | 2.0's id is now **immutable**. It must never be `CONFIG.SEEDANCE_MODEL` in a picker — that is the *current selection*, so both rows would point at whatever was saved last and there would be no way back to 2.0. |
| `SEEDANCE_CAPS` | per-model envelope: resolutions, duration window, output formats, reference caps |
| `_seedance_caps()` / `_is_seedance_25()` / `_seedance_name()` / `_seedance_dur_text()` | one place for "what does the selected model allow / what is it called" |
| `_fit_resolution()` / `_fit_duration()` | snap a request into the model's envelope; `-1` passes through |
| `COST_VIDEO_RATES_25` (10.7 / 6.4 USD per M tokens) and `COST_DIMS_25` (2.5's 480p is 854×480, not 864×496) | model-aware pricing |
| `output_format` on `_seedance_generate` | `mov` (2.5 only) |

Applied **inside `_seedance_generate`**, so all 8 call sites are model-safe without
their own clamps.

**Verified against the live API, not assumed:** `duration: 30` + 720p accepted ·
`1080p` rejected outright (`InvalidParameter — resolution … not valid for model
dreamina-seedance-2-5`) · `adaptive` + `-1` + `mov` accepted · `DELETE` on a running
2.5 task returns **409**, so the create-then-abort diagnostic pattern does not work.

**Base-mesh mode.** `_basemesh_clause()` frames the Maya playblast as 2.5's native
white-model previs ("render the finished shot on top of it, frame for frame") and is
wired into Animate and Render. **On 2.0 the wording is unchanged**, so nothing about
the old path moves.

**Model pickers.** Settings has a plain pick-one dropdown (labels generated from
`SEEDANCE_CAPS` so they cannot drift); Video GEN gained a `v25` tier with `_MAXDUR`,
and `_sync_model()` now rebuilds the duration list. Video GEN opens on whichever model
Settings holds.

**Model-awareness sweep** (a 5-facet audit found 85 candidates; these were confirmed):
window titles that said "Seedance 2.0" on a 2.5 session; seven `max(4, min(15, …))`
clamps that silently truncated any take over 15 s — including **Render, which has no
duration UI at all**, so that clamp was its only bound; the Edit spinbox refusing past
15 s (so editing a 24 s clip returned a 9-second-shorter one); Extend capping each
segment at 15 s on a model that does 30; and a cost label printing "(4k, 15s)" beside a
720p price.

## 4. Content-moderation diagnostics

`_content_labels()` records what went into each `content[]` slot, and
`_explain_moderation()` turns a rejection into advice that matches **what was actually
rejected** — the API names the offender only as `content[4]`, and the old message always
blamed "this image" even when a **video** had been flagged. Wired once in
`_seedance_generate._run`, so every dialog inherits it.

**The rule it now states** (learned the hard way, see below): a character in a playblast
needs **some colour or texture on the mesh**. A bare default-grey humanoid reads as a
nude body and is rejected; a plain coloured shader clears it. `_isolate_polys()` now
forces `displayTextures=True` for the capture (saved/restored like every other flag).

Also measured, worth knowing:

- **2.5's input-video moderation is stricter than 2.0's.** Identical 14 s file, same
  payload, same account: 2.0 accepted and generated (720p/5 s, 411,300 tokens); 2.5
  rejected it. BytePlus on-call confirmed 2.5 filters more strictly and that
  "untextured humanoid meshes may be misclassified".
- Input-video cap: **~15 s on 2.0** (its error says 15.2), **30 s on 2.5**.
- A 30 s 720p 2.5 job takes **~8 minutes**. The Seedance poll loop has no timeout, so
  slow is not broken.
- Post-processing the video (tint, grain, crop) does **not** clear the filter.

## 5. Reload script

`byteplus_Reload.py` was loading a **v1.07 copy from July** because it did
`sys.path.insert(0, "~/Documents/Maya Plugin")` — edits appeared to do nothing. It now
resolves the installed module file, loads that exact path with `importlib`, clears
`__pycache__`, closes stale BYTEPLUS windows, and prints which file it used.

---

## Still open

- **`bin/mac/ffmpeg` is GPL and x86_64-only** (runs via Rosetta on Apple Silicon). The
  Windows bundle ships an LGPL build; a matching LGPL universal macOS build is still TODO.
- Two copies of `byteplus_maya.py` are tracked (`./` and `dist/BYTEPLUS/scripts/`).
  They are kept identical; decide which is canonical and drop the other.
- Seedance 2.5 next steps (see **SEEDANCE_2.5_INTEGRATION.md**): timestamped shot lists
  from the Maya timeline, keyframe reference, `MAX_IMAGE_REFS` 30.

---

## 2026-09-10/11 — VPN gzip, Seed 3D model id, Trusted Asset Library (STS) — all in git

- **Corporate VPN now gzips API responses** (`Server: feilian-agw`) even without
  `Accept-Encoding`; urllib does not inflate, so every JSON call died with
  `'utf-8' codec can't decode byte 0x8b`. `_undo_content_encoding()` inside `_open`
  (the single `urlopen`) inflates only when the header says so; other networks unchanged.
- **Seed 3D:** the documented id `Hyper3d-Rodin-Gen2` 404s; the live catalog id is
  `hyper3d-gen2-260112` (verified text->3D -> usdz + 4 PBR maps -> imported).
  `_DEAD_MODEL_IDS` migrates a stale saved pref on load (Windows installs included).
- **Trusted Asset Library, audited (126-agent read-only audit) and live-tested:**
  session-token support for temporary STS keys (`X-Security-Token` signed, TOS
  `security_token`; new "Session token" fields in Settings and the hosting wizard);
  credential pairs never mixed; `_AssetApiError` with the server Code and
  `_asset_error_hint()` replacing the 'sign'/'authoriz' substring guesses; bare-host
  sanitising; ListAssetGroups paginated (100/page cap); per-install auto group
  `BYTEPLUS Auto <INSTALL_ID[:8]>` matched by exact name and validated (shared account);
  GetAsset polling with backoff, hosted source removed only on a terminal status, a
  timeout returns Processing (never Failed); deleting the auto group clears its id;
  trusted pickers accept only Active; `asset://` no longer reaches `_data_uri` (Analyze /
  Compose); atomic asset store + prefs; R2 PUT sends a real Content-Type; Diagnostics >
  "Test Trusted Asset Library" (GetAssetQuota, no side effects).
  Measured 2026-09-11 with STS: quota read OK, asset Active in 5 s, Seedance 2.5 and 2.0
  both generate from `asset://` with identity preserved.
- **TSP STS tokens live ~1 h (measured), not 12 h.** `ExpiredToken` is classified as a
  credential error, and `_host_video()` falls back to R2 when a TOS upload fails, so a dead
  token no longer blocks every playblast. TOS bucket for this account: `maya-byteplus`.
- **Still open:** the `tos` SDK is NOT bundled (Mac: user-site install only) -> vendor it
  like ffmpeg; `_host_video()` prefers TOS over R2 silently when both are configured;
  8 minor audit findings (sidecar invalidation, picker greying, ASSET_PROJECT setting).
