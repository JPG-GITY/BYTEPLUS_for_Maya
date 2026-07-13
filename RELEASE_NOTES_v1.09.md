## BYTEPLUS for Maya v1.09 (Technology Preview)

Drag-and-drop Maya module for BytePlus ModelArk generative AI (Maya 2025+, Windows + macOS).

### Install
1. Unzip.
2. In Maya, drag **`install.py`** into the viewport.
3. Restart Maya once. The **BYTEPLUS** menu loads automatically.

Full walkthrough in **USER_GUIDE.docx / .html** (inside the zip).

### What's new in this build
- **Seedream 5.0 Pro** + a per-window **model picker** (Pro / Lite) and JPEG/PNG output option.
- **Interactive Edit** — draw edit marks (box / arrow / pencil / text / marker) directly on an image.
- **Seed Character** generator — character sheets, a game A-pose turnaround for 3D, prop/clothing sheets.
- **Trusted Characters** — upload an AI character once → a permanent `asset://` that Seedance trusts forever (no 24h expiry), consistent identity across videos.
- **Text to Image / Image to Image** menu split.
- **Animate reliability**: fixed the submit freeze (re-entrancy-safe dialogs) and added a **concurrency pool** (up to 3 / 10 Seedance jobs at once, set in Settings).
- Rewritten, fully illustrated **User Guide**.

> Bundled LGPL ffmpeg (Windows) is included in the zip. Nothing else to install.
