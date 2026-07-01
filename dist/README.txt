BYTEPLUS for Maya
=================
AI image (Seedream) and video (Seedance) generation inside Autodesk Maya.


REQUIREMENTS
------------
- Autodesk Maya 2025+ (Windows or macOS).
- A BytePlus ModelArk API key (https://console.byteplus.com/ark).
- (Video, Windows) ffmpeg - BUNDLED with this package, nothing to install.
  On macOS, Maya's own playblast is already compatible; no ffmpeg needed.


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
Choose Cloudflare R2 (nothing to install), paste your keys, and press Test.
(BytePlus TOS is also supported but needs the 'tos' Python package.)
Without hosting, Animate still works using a text motion description (motion
will be approximate).


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
BYTEPLUS sends anonymous usage analytics (feature counts, no scene data, no
prompts, no API keys) to help us improve the tool. On first run you may
optionally share your name/email, or choose "Stay anonymous".


LICENSES
--------
This package bundles ffmpeg (https://ffmpeg.org) under the LGPL v2.1+. See
bin/win/LICENSE-ffmpeg.txt for details and the source offer.
