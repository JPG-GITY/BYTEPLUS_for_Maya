# Changelog — BYTEPLUS for Maya

All user-facing changes, newest first. `dist/USER_GUIDE.md` is the canonical
guide; `dist/USER_GUIDE.html` / `.docx` are generated from it, and the root
`USER_GUIDE.md` is only a pointer. The client-facing release notes ship as
`dist/WHATS_NEW.md` (no internal file names or lab notes there).

## 2.02 — 2026-09-15

Client release **2.02 (Technology Preview)**. It includes everything since 2.01
(2026-07-17), and the dated sections below have the details. Packages:
`BYTEPLUS_for_Maya_2.02_Windows.zip` and `BYTEPLUS_for_Maya_2.02_macOS.zip` (same
plugin, docs and `BYTEPLUS/lib`; only the bundled ffmpeg differs). Requires Maya
2025+ (Python 3.10+).

- **Seedance 2.5 support**: model picker in Settings and Video GEN, 4–30 s,
  **480p / 720p only** (1080p/4K requests step down to 720p), base-mesh mode for
  playblasts, `mov` output, model-aware resolution/duration lists. Seedance 2.0
  keeps 480p / 720p / 1080p / 4K (4–15 s).
- **Corporate VPN / proxy**: macOS keychain certificates are trusted (SSL fix),
  and gzip-compressed API responses (including error bodies) are decoded.
- **Seed 3D**: default model id `hyper3d-gen2-260112`; a saved
  `Hyper3d-Rodin-Gen2` (404) is migrated automatically.
- **Trusted Characters**:
  - temporary STS credentials (Session token fields for TOS and the Asset
    Library), with a clear message when they expire;
  - the list shows only this install's characters, and **🔍 Find…** imports one
    by name;
  - Dream Gallery **🎭 Make permanent** asks which character, shows progress and
    confirms;
  - error messages are driven by the server's error code.
- **Trusted Characters robustness (new in 2.02)**:
  - deleting an image or character invalidates its saved permanent links;
  - a Seedance "The specified asset … is not found" error makes the plugin forget
    the asset and say so, with no doomed retry;
  - images are checked before upload against the documented Asset Library limits
    (JPEG/PNG/WEBP/BMP/TIFF/GIF/HEIC/HEIF, 300–6000 px per side, aspect ratio
    0.4–2.5, < 30 MB);
  - a made-permanent image picked as an extra reference is sent as its
    `asset://`;
  - reopening Trusted Characters after adding keys refreshes the list;
  - *Auto-make Extend last frames permanent* (renamed from "Auto-make faces I use
    permanent") runs only with Asset Library keys, or with the TOS-key fallback
    once a Trusted Character exists, and never registers the same last frame twice;
  - picking 🎭 Trusted character in Animate makes Analyze/Compose describe that
    character.

  Known limitation: the Asset Library project stays `default` (not configurable).
- **Seed Audio**: generation runs as an activity-HUD job; the new **Audio
  Gallery** opens by itself when the clip is ready.
- **Dialogue Audio** (replaces Dialogue Scene): per-line Seed Audio clips plus a
  mixed track, attached in Animate / Video GEN as **🎙️ Dialogue audio** (2.0: 3
  clips / 15 s; 2.5: 10 clips / 30 s). The clips are local files and need motion
  hosting (R2 or TOS).
- **Motion hosting**: the **BytePlus TOS Python SDK is bundled** in
  `BYTEPLUS/lib` (tos 2.9.2 + requests, urllib3, idna, charset-normalizer,
  certifi, wrapt, Deprecated, pytz, crcmod, six), so there is nothing to pip
  install, and a user-installed `tos` wins. TOS falls back to R2 on upload
  failure.
- **macOS ffmpeg lookup**: no ffmpeg is bundled for macOS (the only static build
  available was x86_64 and does not run on Apple Silicon without Rosetta). The
  plugin now finds Homebrew / MacPorts ffmpeg even when Maya is opened from the
  Dock (minimal PATH), and a bundled binary is only used if it actually runs.
- **License fixes**:
  - the Windows ffmpeg notice now correctly says **LGPL-3.0-or-later** (build
    N-125350-g3f6bf150cb-20260629, sha256 pinned);
  - README and NOTICE list the bundled Python libraries with their licenses;
  - NOTICE mentions Seed Audio.
- **Docs**:
  - `dist/USER_GUIDE.md` merged into one v2.02 guide;
  - new `dist/WHATS_NEW.md`;
  - README gains a "What's new in 2.02" section;
  - Diagnostics is documented as opt-in (*Settings > Analytics & Webhook >
    Developer mode*).
- Also since 2.01: content-moderation diagnostics, honest output-policy errors
  (`OutputVideoSensitiveContentDetected` is no longer blamed on your inputs),
  empty-gallery hints, and VideoPilot retired (Edit video / Extend run on
  Seedance video-to-video).

## 2026-09-11

### Dialogue Audio (replaces "Dialogue Scene")
- **Dialogue is now audio first.** BYTEPLUS > **Dialogue Audio**: pick a cast of
  Trusted Characters (each with a voice), write `@Name: line` per line, and Seed
  Audio speaks every line in that character's own voice. You get one WAV per line
  plus a mixed scene track, all in the **Audio Gallery** (with a record of who
  says what). Cheap to iterate (Seed Audio ≈ $0.0025/s) and no video is generated
  here.
- **Animate and Video GEN (Multimodal) gained 🎙️ Dialogue audio**: pick those
  clips and they go to Seedance as reference audio (Audio 1, 2, …) next to your
  playblast, environment and character references. The plugin writes the speaker
  mapping into the prompt for you ("Image 1 is Alice; Audio 1 is Alice's line: …")
  and turns Generate audio on. Verified live: Seedance 2.5 speaks the clip
  verbatim with synced lips (transcribed back word for word).
- Limits are enforced per model: 2.0 → 3 clips / 15 s of audio per job; 2.5 → 10
  clips / 30 s. Dialogue Audio tells you which model your script fits.
- Audio Gallery shows dialogue clips with a badge (speaker + line, or "dialogue
  mix") and their duration; deleting a clip removes its record too.
- Why: a dialogue is one more reference for a shot, not a separate kind of shot —
  one video front-end (Animate / Video GEN) instead of two.

### Trusted Characters (permanent digital characters)
- **Temporary STS credentials work.** Settings > Storage & Hosting gained a
  **Session token** field for TOS and for the Asset Library (the hosting wizard
  too). Permanent IAM keys leave it blank. Temporary keys (`AKTP…`) expire — when
  they do, the plugin now says *"credentials expired, mint a fresh set"* instead
  of a cryptic signature error.
- **Leave the Asset Library keys blank to reuse the TOS keys** — same account,
  one place to update.
- **The character list shows only YOUR characters** (created on this machine),
  validated against the server in one call. On a shared BytePlus account a
  project can hold thousands of groups; listing them all took minutes and could
  crash Maya. Use **🔍 Find…** to bring in one specific group created elsewhere
  (console, another machine) — search by name, pick one.
- **Dream Gallery > 🎭 Make permanent** now asks **which character** to add the
  image to (or creates a new one by name), shows progress on the button and
  reports the result in a dialog — no more silent registrations.
- **+ From gallery** works without the Dream Gallery window open (it scans the
  scene's images folder).
- Pickers only accept ✅ **Active** images; a still-processing image is reported
  as such, never as failed. Deleting your auto group no longer leaves a stale id.
- Error messages are now driven by the server's error code: wrong key, missing
  IAM policy (`ark:*Asset*`), rate limit, or the one-time authorization letter —
  each gets its own advice.
- **Diagnostics > Test Trusted Asset Library**: proves your keys and IAM policy
  with a read-only call, no side effects.

### Dialogue Scene
- The spoken track of a finished scene is extracted (WAV) and filed in the
  **Audio Gallery** next to the video in the Video Gallery.
- Progress: the job is a row in the activity HUD (cancel with ✕); the button
  reads *Generating…*; the result lands in the Video Gallery.
- **Honest errors.** When Seedance's *output* filter flags the generated
  video/audio (`OutputVideoSensitiveContentDetected.PolicyViolation`, usually
  "copyright"), the plugin no longer claims your trusted characters were
  rejected — the inputs were accepted and the job ran; the message now says so
  and suggests a retry / rephrasing / audio off. Applies to every Seedance
  dialog.

### Seed Audio
- **Trusted Characters > Generate voice…** shows progress: a row in the
  activity HUD (cancel with ✕), the button reads *Generating…*, and the voice
  line / status say what is being generated.
- **Generate** now runs as a row in the activity HUD (cancel with ✕, queue
  several); the Seed Audio window stays usable and the **Audio Gallery opens by
  itself** when the clip is ready. The system media player no longer pops up.

### Motion hosting (TOS / R2)
- TOS: if an upload fails (for example an expired session token) the plugin
  **falls back to Cloudflare R2** automatically when R2 is configured.
- R2 uploads now carry a correct `Content-Type`.

### Seed 3D
- The documented model id `Hyper3d-Rodin-Gen2` returned *404 model not found*;
  the plugin now uses the live catalog id `hyper3d-gen2-260112`, and a saved
  preference holding the old id is migrated automatically.

### Networking
- Corporate proxies that **gzip API responses** no longer break every call
  (`'utf-8' codec can't decode byte 0x8b`). Only active when the response says
  it is compressed; other networks are unaffected.
- macOS + corporate VPN: the system keychain's certificates are trusted (see
  `SSL_CORPORATE_CA_FIX.md`).

### Under the hood
- Preferences and the local character store are written atomically.

## 2026-08-07
- Seedance 2.5 support (model picker, 4–30 s, base-mesh mode for playblasts,
  timestamps, `mov` output), content-moderation diagnostics, empty-gallery hints,
  VideoPilot retired. See `SEEDANCE_2.5_INTEGRATION.md`.
