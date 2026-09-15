# BYTEPLUS for Maya — Notice & Disclaimer

**Technology Preview** — developed by John Paul Giancarlo on behalf of ByteDance.

This is a Technology Preview shared as-is. It is **not** sold or licensed
commercially, and there is no license key or activation.

## 1. As-is, at your own risk
This software is provided **"AS IS" and "AS AVAILABLE", without warranties of any
kind**, express or implied (including merchantability, fitness for a particular
purpose, and non-infringement). You use it **at your own risk**. It may be
incomplete, change, or stop working at any time.

## 2. No liability
To the maximum extent permitted by law, the authors and ByteDance are **not
liable** for any direct, indirect, incidental, or consequential damages, or any
loss of data, profits, or goodwill, arising from use of the software.

## 3. Your BytePlus usage is yours
The software calls BytePlus ModelArk APIs (Seedream, Seedance, the Seed LLM, and
Seed Audio) **using your own API key**. You are responsible for your keys and for
**all usage, tokens, and charges** incurred under them. Those services are
governed by **BytePlus's own terms**; generated content is subject to their
content and biometric policies.

## 4. Third-party software
Runs inside Autodesk Maya, under Autodesk's separate license. Other brand names,
product names, and trademarks belong to their respective owners.

The package also bundles the following third-party software, each under its own
license. It is included unmodified; the license texts ship with the package.

**FFmpeg** (https://ffmpeg.org) — run as a separate program, Windows package only
(`BYTEPLUS/bin/win/ffmpeg.exe`): BtbN FFmpeg-Builds "win64-lgpl", build
N-125350-g3f6bf150cb-20260629, licensed under the **LGPL-3.0-or-later**. See
`BYTEPLUS/bin/win/LICENSE-ffmpeg.txt` (checksum and source links) and
`BYTEPLUS/bin/win/LICENSE.txt`. The macOS package does not bundle ffmpeg; it uses an
ffmpeg you install yourself, under that build's own license.

**Python libraries** (`BYTEPLUS/lib`) — the BytePlus TOS Python SDK and its
dependencies. Each license file is in `BYTEPLUS/lib/<package>-<version>.dist-info/`.

| Package | Version | License |
|---|---|---|
| tos (BytePlus TOS SDK) | 2.9.2 | Apache-2.0 |
| requests | 2.34.2 | Apache-2.0 (with NOTICE) |
| urllib3 | 2.7.0 | MIT |
| idna | 3.18 | BSD-3-Clause |
| charset-normalizer | 3.4.7 | MIT |
| certifi | 2026.5.20 | MPL-2.0 (source: https://github.com/certifi/python-certifi) |
| wrapt | 1.16.0 | BSD-2-Clause |
| Deprecated | 1.3.1 | MIT |
| pytz | 2026.2 | MIT |
| crcmod | 1.7 | MIT |
| six | 1.17.0 | MIT |

## 5. Usage data
To improve the software, it sends **usage analytics** (features used, model ids,
token counts). It does **not** send your prompts, scenes, images, videos, or API
keys. It is anonymous unless you choose to add your name, email and company
(editable in Settings, or stay anonymous).

---

_Questions: john.giancarlo@bytedance.com_
