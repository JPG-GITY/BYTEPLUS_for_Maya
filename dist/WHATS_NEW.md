# What's new in BYTEPLUS for Maya 2.02

*Technology Preview v2.02 — September 2026. Requires Autodesk Maya 2025 or newer
(Windows or macOS). For step-by-step instructions see **USER_GUIDE.md**.*

## Seedance 2.5
- Pick **Seedance 2.5** in *Settings > API & Models > Seedance (video) model*, or
  **2.5** in Video GEN: clips from **4 to 30 seconds** at **480p or 720p**.
- **Seedance 2.0** is still there for **1080p and 4K** (4–15 s), plus the cheaper
  **Fast** and **Mini** tiers.
- The resolution and duration lists follow the model you pick. A 1080p/4K request
  on 2.5 is rendered at 720p.

## Dialogue Audio — spoken scenes with synced lips
- New **BYTEPLUS > Dialogue Audio** (replaces *Dialogue Scene*): pick a cast of
  Trusted Characters, write `@Name: line` for each line, and Seed Audio speaks every
  line in that character's own voice. You get one clip per line plus a mixed scene
  track in the Audio Gallery. It is cheap to iterate, and no video is generated at
  this step.
- **Animate** and **Video GEN › Multimodal (refs)** gained **🎙️ Dialogue audio**:
  attach those clips next to your playblast and references, and Seedance speaks
  them with synced lips. The plugin writes the speaker mapping into the prompt and
  turns *Generate audio* on for you.
- Limits per video: Seedance 2.0 — 3 clips / 15 s of audio; Seedance 2.5 — 10 clips
  / 30 s. Dialogue Audio tells you which model your script fits.
- Dialogue clips are uploaded like the playblast, so they need **motion hosting**
  (Cloudflare R2 or BytePlus TOS).

## Seed Audio & the Audio Gallery
- **Generate** runs in the background as a row in the activity HUD (cancel with ✕,
  queue several). The Seed Audio window stays usable, and the **Audio Gallery**
  opens by itself when the clip is ready.
- **BYTEPLUS > Open Audio Gallery** lists voice, music, SFX and dialogue clips with
  their durations. Dialogue clips show who says what.
- **Trusted Characters > Generate voice…** shows its progress in the HUD.

## Trusted Characters (permanent digital characters)
- **Dream Gallery > 🎭 Make permanent** asks which character to add the image to
  (or creates a new one), shows progress, and confirms the result.
- The list shows **your** characters. Use **🔍 Find…** to bring in one created in
  the console or on another machine, by name.
- **Temporary STS keys** (`AKTP…`) are supported through the new **Session token**
  fields. When they expire, the plugin says so clearly.
- **Images are checked before upload** against the Asset Library limits: JPEG / PNG
  / WEBP / BMP / TIFF / GIF / HEIC / HEIF, 300–6000 px per side, aspect ratio
  0.4–2.5, under 30 MB.
- **Deleting** an image or a character also invalidates its saved permanent links.
  If Seedance reports a character as deleted, the plugin forgets it and tells you,
  instead of retrying.
- An image you made permanent is sent as its permanent link when you use it as an
  extra reference image.
- Picking **🎭 Trusted character** in Animate makes **✨ Analyze** / **✦ Compose**
  describe that character.
- Reopening Trusted Characters after adding your keys refreshes the list.
- **Auto-make Extend last frames permanent** only runs for people who use the Asset
  Library — Asset Library keys set, or TOS keys reused once you have a Trusted
  Character — and never registers the same last frame twice. A TOS setup made only for
  playblast hosting no longer registers assets in the background.
- Clearer error messages for a wrong key, a missing IAM policy, rate limits and the
  one-time authorization letter.
- *Known limitation:* characters live in your account's **default** project, which
  is not configurable yet. Use an API key and endpoints from the default project.

## Motion hosting
- **BytePlus TOS works out of the box:** the TOS Python SDK is bundled with the
  plugin, so there's nothing to pip install.
- If a TOS upload fails (for example, expired temporary keys), the plugin **falls
  back to Cloudflare R2** when R2 is also configured.

## Seed 3D
- Seed 3D uses the current model id **`hyper3d-gen2-260112`**. A saved setting with
  the old id is migrated automatically.

## macOS & networking
- **ffmpeg on macOS is found automatically** in Homebrew or MacPorts, even when Maya
  is opened from the Dock. Install it once (`brew install ffmpeg`) to use Extend and
  clip joining on a Mac. (Windows keeps its bundled ffmpeg.)
- **Corporate VPNs and proxies:** certificates from the macOS keychain are trusted,
  and compressed (gzip) responses no longer break API calls.

## Also
- Clearer messages when Seedance's *output* filter flags a finished clip (for
  example "copyright"). Your inputs were accepted, and the message suggests a retry,
  rephrasing, or turning audio off.
- The Diagnostics menu is for troubleshooting and appears after you tick *Settings >
  Analytics & Webhook > Developer mode*.
- Updated license notices: Windows ffmpeg (LGPL-3.0-or-later) and the bundled Python
  libraries. See **NOTICE.md** and **README.txt**.
