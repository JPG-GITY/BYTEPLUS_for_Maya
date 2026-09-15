BYTEPLUS for Maya  -  2.02 (Technology Preview)
===============================================
AI image (Seedream), video (Seedance), audio (Seed Audio), 3D (Seed 3D) and
chat (Seed 2.0) inside Autodesk Maya.


WHAT'S NEW IN 2.02
------------------
- Seedance 2.5: clips up to 30 s at 480p / 720p (Seedance 2.0 keeps 1080p / 4K).
- Dialogue Audio: give trusted characters a voice, write a script, and attach
  the spoken lines in Animate / Video GEN for lip-synced video.
- Seed Audio runs in the background; the new Audio Gallery opens when ready.
- Trusted Characters: Find..., Make permanent from the Dream Gallery, temporary
  STS keys, image checks before upload, and deleted characters handled cleanly.
- BytePlus TOS hosting works out of the box: its Python SDK is now bundled.
- macOS: finds Homebrew/MacPorts ffmpeg; corporate VPN / proxy connection fixes.
- Seed 3D uses the current model id (old saved ids are migrated).
Details: WHATS_NEW.md  -  How-to: USER_GUIDE.md (or USER_GUIDE.html / .docx).


REQUIREMENTS
------------
- Autodesk Maya 2025 or newer (Windows or macOS).
- A BytePlus ModelArk API key (https://console.byteplus.com/ark).
- (Optional) A Seed Audio API key from the BytePlus Voice console, for
  Seed Audio and Dialogue Audio.
- ffmpeg: BUNDLED on Windows (BYTEPLUS/bin/win). On macOS install it once, e.g.
  with Homebrew:  brew install ffmpeg   (the plugin also looks in /opt/homebrew,
  /usr/local and MacPorts, even when Maya is opened from the Dock). Without it,
  Extend, joining clips and dialogue-track extraction are unavailable on macOS.
- The BytePlus TOS Python SDK and its dependencies are BUNDLED in BYTEPLUS/lib,
  nothing to pip install. (A copy you installed yourself takes priority.)


INSTALL
-------
1. Unzip this package anywhere.
2. Drag  install.py  into the Maya viewport.
3. When it finishes, RESTART Maya once (applies the crash-prevention setting).
   - If Maya asks about "Secure UserSetup Checksum verification", click Yes.
4. Open  BYTEPLUS > Settings  and paste your BytePlus API key.

The BYTEPLUS menu auto-loads on every Maya start from then on.


VIDEO MOTION (optional)
-----------------------
"Animate with Seedance" can use a playblast of your scene as a faithful motion
reference. That needs public hosting - the easiest way is the guided wizard:
  BYTEPLUS > Set up motion hosting...
Choose Cloudflare R2, paste your keys, and press Test connection.
BytePlus TOS is also supported (SDK bundled, nothing to install). Temporary
STS keys (AKTP...) also need their Session token and expire after ~12 h.
Without hosting, Animate still works using a text motion description (motion
will be approximate). Dialogue audio clips and Edit video also need hosting.


UNINSTALL
---------
1. Delete the folder:   <user>/Documents/maya/modules/BYTEPLUS
2. Delete the file:     <user>/Documents/maya/modules/BYTEPLUS.mod
3. In  <user>/Documents/maya/<version>/scripts/userSetup.py  remove the block
   between the lines:
       # >>> BYTEPLUS for Maya (auto-load) >>>
       # <<< BYTEPLUS for Maya (auto-load) <<<


PRIVACY / TELEMETRY
-------------------
BYTEPLUS sends usage data (features used, models and token counts - no scene
data, no prompts, no images or videos, no API keys) to help us improve the
tool. On first run you may optionally share your name/email, or choose
"Stay anonymous". See NOTICE.md.


LICENSES
--------
BYTEPLUS for Maya is a Technology Preview provided as-is; see NOTICE.md.

ffmpeg (https://ffmpeg.org) is bundled in the Windows package as a separate
program: an LGPL build (BtbN FFmpeg-Builds "win64-lgpl"), licensed under the LGPL
version 3 or later. See BYTEPLUS/bin/win/LICENSE-ffmpeg.txt (build id, checksum and
source links) and BYTEPLUS/bin/win/LICENSE.txt (LGPL v3 text). The macOS package
does not bundle ffmpeg; it uses the one you install.

Unmodified open-source Python libraries are bundled in BYTEPLUS/lib:
tos 2.9.2 (Apache-2.0), requests 2.34.2 (Apache-2.0, with NOTICE),
urllib3 2.7.0 (MIT), idna 3.18 (BSD-3-Clause), charset-normalizer 3.4.7 (MIT),
certifi 2026.5.20 (MPL-2.0, source: https://github.com/certifi/python-certifi),
wrapt 1.16.0 (BSD-2-Clause), Deprecated 1.3.1 (MIT), pytz 2026.2 (MIT),
crcmod 1.7 (MIT), six 1.17.0 (MIT). Each license text is in
BYTEPLUS/lib/<package>-<version>.dist-info/.
