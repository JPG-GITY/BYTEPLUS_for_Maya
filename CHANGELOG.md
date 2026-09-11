# Changelog — BYTEPLUS for Maya

All user-facing changes, newest first. `USER_GUIDE.md` is the canonical guide;
`USER_GUIDE.html` / `.docx` are older snapshots and will be regenerated.

## 2026-09-11

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

### Seed Audio
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
- Seedance 2.5 now accepts **1080p**; the resolution list follows the model.

## 2026-08-07
- Seedance 2.5 support (model picker, 4–30 s, base-mesh mode for playblasts,
  timestamps, `mov` output), content-moderation diagnostics, empty-gallery hints,
  VideoPilot retired. See `SEEDANCE_2.5_INTEGRATION.md`.
