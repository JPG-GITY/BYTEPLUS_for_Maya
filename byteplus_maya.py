"""
byteplus_maya.py
================
A Maya 2027 (Python 3.11 / PySide6) plugin that adds a **BYTEPLUS** menu to the
main Maya window, wiring the BytePlus ModelArk generative models directly into a
3D artist's workflow.

Menu: BYTEPLUS
  - Render with Seedance 2.0   -> renders up to 9 evenly spaced ref frames + a
                                  playblast, feeds them to Seedance 2.0, returns
                                  a 1080p video.
  - Dream with Seedreams 5.0   -> snapshots the viewport, asks for a prompt
                                  (with best-practice coaching), generates an
                                  image with Seedream 5.0 Lite.
  - Generate Texture           -> describes a texture for the selected object,
                                  generates it, and wires the result into a new
                                  OpenPBR (openPBRSurface) shader.

Every Seedream / Seedance result opens in a **Preview window with Save As**.

------------------------------------------------------------------------------
INSTALL
------------------------------------------------------------------------------
1. Copy this file somewhere on Maya's PYTHONPATH (e.g. the Maya scripts folder),
   or anywhere and add its folder to sys.path.
2. Set your API key once, in a shell before launching Maya:
       export ARK_API_KEY="your-key-here"        (macOS / Linux)
       setx   ARK_API_KEY "your-key-here"         (Windows)
3. In Maya's Script Editor (Python tab) run:
       import byteplus_maya
       byteplus_maya.install()                    # builds the BYTEPLUS menu
   To auto-load on startup, put those two lines in your userSetup.py.

   You can also load it as a true plugin (Plug-in Manager) -- the bottom of this
   file exposes initializePlugin / uninitializePlugin.

------------------------------------------------------------------------------
NOTE ON ENDPOINTS / MODEL IDS  (configurable -- see CONFIG below)
------------------------------------------------------------------------------
Endpoints, base URL and model IDs are grounded in the BytePlus ModelArk
references but are pinned in one CONFIG block so you can adjust them without
touching logic if your account/region differs.
"""

from __future__ import annotations

import os
import sys
import ssl
import json
import time
import uuid
import hmac
import base64
import hashlib
import datetime
import tempfile
import threading
import traceback
import urllib.parse
import urllib.request
import urllib.error

import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMayaUI as omui
import maya.utils

# --- Qt (Maya 2025+ ships PySide6; fall back to PySide2 for older builds) -----
try:
    from PySide6 import QtWidgets, QtCore, QtGui
    from shiboken6 import wrapInstance
except ImportError:  # pragma: no cover - older Maya
    from PySide2 import QtWidgets, QtCore, QtGui
    from shiboken2 import wrapInstance


# =============================================================================
# CONFIG  -- the single place to change endpoints / models / defaults
# =============================================================================
class CONFIG:
    # Data-plane base URL for BytePlus ModelArk (Southeast region shown).
    BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"

    # Auth: data plane uses a simple Bearer API key. Resolution order:
    #   1. CONFIG.API_KEY (set via Settings dialog, optionally remembered on disk)
    #   2. the ARK_API_KEY environment variable
    API_KEY = ""
    API_KEY_ENV = "ARK_API_KEY"
    REMEMBER_API_KEY = False        # persist the key to PREFS_PATH (plaintext!)

    # --- Model IDs ------------------------------------------------------------
    SEEDANCE_MODEL = "dreamina-seedance-2-0-260128"      # video
    SEEDREAM_MODEL = "seedream-5-0-260128"               # image (Seedream 5.0 base) -- general Dream/Refine/Texture
    # Faces to be animated MUST come from Seedream 5.0 *Lite*: Seedance 2.0 only
    # trusts face images from 5.0 Lite (Trusted Outputs, video-seedance.md 7). The
    # face-safe Text-to-Image path uses this so its output is animatable.
    SEEDREAM_FACE_MODEL = "seedream-5-0-lite-260128"     # image (Seedream 5.0 Lite) -- face-safe T2I, animatable
    LLM_MODEL = "seed-1-6-250915"                        # multimodal (auto-prompt)
    SEED_CHAT_MODEL = "seed-2-0-pro-260328"              # Seed Chat window: agentic multimodal (tool-calling ready)
    # Seed 3D. NOTE: the documented IDs (Hyper3d-Rodin-Gen2 / Hitem3d-2.0) returned
    # HTTP 404 on this account -- set the REAL model ID (or 'ep-...' inference
    # endpoint) from your ModelArk console in Settings > 3D model before using it.
    THREE_D_MODEL = "Hyper3d-Rodin-Gen2"                 # text->3D + image->3D (UNVERIFIED)

    # --- Endpoints (relative to BASE_URL) ------------------------------------
    VIDEO_TASKS = "/contents/generations/tasks"          # POST create / GET poll
    IMAGE_GEN = "/images/generations"                    # POST (sync)
    CHAT_COMPLETIONS = "/chat/completions"               # POST (LLM, multimodal)
    THREE_D_TASKS = "/contents/generations/tasks"        # POST create / GET poll (same as video)

    # --- Output options -------------------------------------------------------
    # Seedream/Seedance stamp an "AI generated" watermark by default; the API
    # exposes a `watermark` flag to disable it. False = no watermark.
    WATERMARK = False
    # Seedance generates audio by default; its safety filter can reject the
    # OUTPUT audio (OutputAudioSensitiveContentDetected) and fail the whole job.
    # We disable audio by default -- the reference workflow doesn't need it.
    GENERATE_AUDIO = False

    # --- Seedance defaults ----------------------------------------------------
    VIDEO_RESOLUTION = "1080p"
    VIDEO_RATIO = "16:9"
    VIDEO_FPS = 24                                        # Seedance base rate
    MAX_IMAGE_REFS = 9                                    # Seedance hard cap

    # --- Cost estimate (APPROXIMATE; BytePlus billing is the source of truth) --
    # tokens = (in_dur + out_dur) * W * H * fps / 1024 ;  USD = tokens * rate.
    # Update these if BytePlus changes prices.
    SHOW_COST = True
    COST_CONFIRM_USD = 1.50                               # confirm if est > this
    COST_IMAGE_USD = 0.035                                # per Seedream image
    COST_VIDEO_RATES = {                                  # USD / 1M tokens: (no input video, with video)
        "480p": (7.0, 4.3), "720p": (7.0, 4.3),
        "1080p": (7.7, 4.7), "4k": (4.0, 2.4),
    }
    COST_DIMS = {                                         # width x height per resolution+ratio (Seedance 2.0)
        "480p": {"16:9": (864, 496), "4:3": (752, 560), "1:1": (640, 640),
                 "3:4": (560, 752), "9:16": (496, 864), "21:9": (992, 432)},
        "720p": {"16:9": (1280, 720), "4:3": (1112, 834), "1:1": (960, 960),
                 "3:4": (834, 1112), "9:16": (720, 1280), "21:9": (1470, 630)},
        "1080p": {"16:9": (1920, 1080), "4:3": (1664, 1248), "1:1": (1440, 1440),
                  "3:4": (1248, 1664), "9:16": (1080, 1920), "21:9": (2206, 946)},
        "4k": {"16:9": (3840, 2160), "4:3": (3326, 2494), "1:1": (2880, 2880),
               "3:4": (2494, 3326), "9:16": (2160, 3840), "21:9": (4398, 1886)},
    }

    # --- Seedream image aspect ------------------------------------------------
    # Seedream's `size` has two modes: descriptive ("2K" -> the model INFERS the
    # aspect from the content, which is inconsistent) or exact "WxH" pixels. We
    # send exact pixels for Dream/Refine so the aspect is consistent. If the API
    # ever rejects the exact size, _seedream falls back to "2K" automatically.
    IMAGE_RATIO = "16:9"
    # Seedream requires >= 3,686,400 px and <= 4096 per side. Seedream bills per
    # image (not per pixel), so larger costs the same -- we use comfortable ~3K
    # dimensions that clear the minimum for every aspect.
    IMAGE_DIMS = {
        "16:9": "3200x1800", "4:3": "3072x2304", "1:1": "2560x2560",
        "3:4": "2304x3072", "9:16": "1800x3200", "21:9": "3360x1440",
    }

    # --- Render defaults ------------------------------------------------------
    REF_WIDTH, REF_HEIGHT = 1280, 720                    # 720p reference frames

    # --- Texture defaults -----------------------------------------------------
    BUMP_DEPTH = 1.0                                     # bump2d depth for normals

    # --- Seed 3D defaults -----------------------------------------------------
    THREE_D_FORMAT = "usdz"                             # usdz (mayaUsdPlugin) / fbx / obj
    THREE_D_MATERIAL = "PBR"                            # PBR / Shaded / None
    COST_3D_USD = 0.40                                  # ~ $0.399 per generated model (grounded)

    # --- Networking -----------------------------------------------------------
    POLL_SECONDS = 5
    HTTP_TIMEOUT = 120
    # Maya's bundled Python on macOS often ships without a CA bundle, so HTTPS
    # fails with CERTIFICATE_VERIFY_FAILED. We try `certifi` first; if it's not
    # installed and this is False, verification is skipped as a last resort.
    SSL_VERIFY = True

    # --- BytePlus TOS object storage (optional) -------------------------------
    # When configured, large refs are uploaded to TOS and passed as pre-signed
    # GET URLs instead of base64 data URIs -- avoids the 64 MB body / HTTP 413
    # ceiling. Requires the official `tos` SDK (pip install tos into Maya's
    # interpreter). If unset or the SDK is missing, falls back to base64.
    USE_TOS = False
    # Credentials: prefer values entered in Settings, else the env vars below.
    TOS_AK = ""
    TOS_SK = ""
    TOS_AK_ENV = "TOS_ACCESS_KEY"
    TOS_SK_ENV = "TOS_SECRET_KEY"
    TOS_ENDPOINT = "tos-ap-southeast-1.bytepluses.com"
    TOS_REGION = "ap-southeast-1"
    TOS_BUCKET = ""                                      # e.g. "my-maya-bucket"
    TOS_PRESIGN_TTL = 3600                               # seconds the GET URL lives

    # --- Cloudflare R2 (optional, private; for the motion video reference) -----
    # S3-compatible. We sign requests with AWS SigV4 directly (no SDK needed).
    # OFF by default; enable in Settings. The playblast is uploaded, passed to
    # Seedance as a private pre-signed URL, then DELETED when the job finishes.
    MOTION_HOST = "off"                                  # "off" | "r2"
    R2_ACCOUNT_ID = ""
    R2_ACCESS_KEY = ""
    R2_SECRET_KEY = ""
    R2_BUCKET = ""
    R2_PRESIGN_TTL = 3600

    # --- Webhook (optional; polling stays the default fallback) ---------------
    # A desktop plugin cannot receive an inbound POST directly. Only set this if
    # you run a public relay/tunnel. When set, it is passed as `callback_url`;
    # polling still runs so results arrive regardless.
    CALLBACK_URL = ""

    # --- App / preview --------------------------------------------------------
    VERSION = "1.07 (Technology Preview)"
    BUG_EMAIL = "john.giancarlo@bytedance.com"          # temporary bug reports

    # --- Color management (Arnold/OCIO) ---------------------------------------
    # When on, saved reference frames carry the artist's display/view transform
    # (OCIO config, custom view transforms / LUTs) so they match the viewport.
    COLOR_MANAGE = True

    # --- Telemetry (anonymous usage analytics) --------------------------------
    # Events are written to R2 under TELEMETRY_PREFIX/<install_id>/... so the
    # account owner can aggregate usage across users. Async + batched (never
    # blocks generation). No prompts / scene content / API keys are sent.
    # Anonymous usage telemetry is ALWAYS ON and not user-disableable: it is the
    # data the account owner needs (install id + customer + tokens). It is NOT in
    # _PERSISTED, so a stale prefs value can never turn it off. Personal identity
    # (email / company) stays OPTIONAL -- see _maybe_identify.
    TELEMETRY = True
    INSTALL_ID = ""                                     # random, generated once
    # How BYTEPLUS > Usage opens: "both" | "global" | "project" (client choice).
    USAGE_VIEW = "both"
    TELEMETRY_PREFIX = "telemetry"
    TELEMETRY_BUCKET = ""                               # blank -> reuse R2_BUCKET
    # Backend for telemetry: "posthog" (real-time dashboards, public client key,
    # safe to ship) or "r2" (raw JSON to your bucket; needs R2 secrets).
    TELEMETRY_BACKEND = "posthog"
    # PostHog ingestion. The project API key is a PUBLIC, write-only client key
    # (designed to be embedded in client apps) -- it can capture events but
    # cannot read/query, so it is safe to distribute inside the plugin.
    POSTHOG_HOST = "https://us.i.posthog.com"           # or https://eu.i.posthog.com
    POSTHOG_API_KEY = "phc_BBNrAPJAKBrS4puSSVov3TcmzS8ALSWT6MyMMPsdHGmH"  # public write-only project key
    # Tag each distribution so events map to a named customer in the dashboard.
    CUSTOMER_ID = ""                                    # e.g. "acme-studios"
    # Self-service identity, captured ONCE (with consent) on first run -- scales
    # without editing CUSTOMER_ID per build. Sent to PostHog via $identify.
    USER_EMAIL = ""
    USER_NAME = ""
    USER_ROLE = ""
    USER_COMPANY = ""
    IDENTIFIED = False                                  # first-run prompt answered

    # --- Developer / partner mode ---------------------------------------------
    # When False (client builds), the Diagnostics submenu is hidden. Devs and
    # partners building on top can flip this in Settings or set BYTEPLUS_DEBUG=1.
    DEBUG = False

    # --- Persisted prefs ------------------------------------------------------
    PREFS_PATH = os.path.join(os.path.expanduser("~"), ".byteplus_maya.json")
    USAGE_PATH = os.path.join(os.path.expanduser("~"), ".byteplus_maya_usage.json")

    MENU_NAME = "byteplusMenu"
    MENU_LABEL = "BYTEPLUS"


# Keys that the Settings dialog persists to PREFS_PATH and restores on install.
_PERSISTED = (
    "VIDEO_RESOLUTION", "VIDEO_RATIO", "MAX_IMAGE_REFS",
    "REF_WIDTH", "REF_HEIGHT", "USE_TOS", "TOS_BUCKET",
    "TOS_ENDPOINT", "TOS_REGION", "CALLBACK_URL", "REMEMBER_API_KEY",
    "SSL_VERIFY", "BASE_URL", "SEEDREAM_MODEL", "SEEDREAM_FACE_MODEL",
    "SEEDANCE_MODEL", "LLM_MODEL",
    "SEED_CHAT_MODEL", "THREE_D_MODEL",
    "MOTION_HOST", "R2_ACCOUNT_ID", "R2_BUCKET", "BUMP_DEPTH",
    "SHOW_COST", "COST_CONFIRM_USD", "IMAGE_RATIO",
    "COLOR_MANAGE", "USAGE_VIEW", "INSTALL_ID", "TELEMETRY_PREFIX", "TELEMETRY_BUCKET",
    "TELEMETRY_BACKEND", "POSTHOG_HOST", "POSTHOG_API_KEY", "CUSTOMER_ID",
    "USER_EMAIL", "USER_NAME", "USER_ROLE", "USER_COMPANY", "IDENTIFIED", "DEBUG",
    # NOTE: TELEMETRY is intentionally NOT persisted -- it's an always-on policy,
    # so a stale prefs value can't override it.
)


def _load_prefs():
    try:
        with open(CONFIG.PREFS_PATH) as f:
            data = json.load(f)
        for k, v in data.items():
            if k in _PERSISTED:
                setattr(CONFIG, k, v)
        # Secrets are persisted only if the user opted in (Remember).
        if data.get("REMEMBER_API_KEY"):
            CONFIG.API_KEY = data.get("API_KEY", CONFIG.API_KEY)
            CONFIG.TOS_AK = data.get("TOS_AK", CONFIG.TOS_AK)
            CONFIG.TOS_SK = data.get("TOS_SK", CONFIG.TOS_SK)
            CONFIG.R2_ACCESS_KEY = data.get("R2_ACCESS_KEY", CONFIG.R2_ACCESS_KEY)
            CONFIG.R2_SECRET_KEY = data.get("R2_SECRET_KEY", CONFIG.R2_SECRET_KEY)
    except (OSError, ValueError):
        pass


def _save_prefs():
    data = {k: getattr(CONFIG, k) for k in _PERSISTED}
    # Only write secrets when the user explicitly asked to remember them.
    if CONFIG.REMEMBER_API_KEY:
        for k in ("API_KEY", "TOS_AK", "TOS_SK", "R2_ACCESS_KEY", "R2_SECRET_KEY"):
            if getattr(CONFIG, k):
                data[k] = getattr(CONFIG, k)
    try:
        with open(CONFIG.PREFS_PATH, "w") as f:
            json.dump(data, f, indent=2)
        # Best-effort: lock the file down (no-op on Windows).
        try:
            os.chmod(CONFIG.PREFS_PATH, 0o600)
        except OSError:
            pass
    except OSError:
        pass


# Gallery "hidden" list: files removed from a gallery WITHOUT deleting from disk.
# The galleries rescan their folder on open, so we persist these paths and skip
# them; entries whose file no longer exists are pruned (self-cleaning).
_HIDDEN_PATH = os.path.join(os.path.expanduser("~"), ".byteplus_maya_hidden.json")


def _load_hidden() -> set:
    try:
        with open(_HIDDEN_PATH) as f:
            return {p for p in json.load(f) if os.path.exists(p)}
    except (OSError, ValueError):
        return set()


def _hide_paths(paths):
    """Mark file paths as hidden from the galleries (persisted)."""
    cur = _load_hidden()
    cur.update(p for p in paths if p)
    try:
        with open(_HIDDEN_PATH, "w") as f:
            json.dump(sorted(cur), f)
    except OSError:
        pass


# Each saved Dream image gets a sidecar "<image>.url" holding the ORIGINAL
# Seedream platform URL. Passing that exact URL to Seedance keeps the face
# "Trusted Outputs" chain valid; without it (e.g. on gallery reopen) a re-encoded
# copy is rejected. Purely additive: if the sidecar is absent, behaviour is
# exactly as before (url=None).
def _write_url_sidecar(path: str, url: str):
    if not (path and url):
        return
    try:
        with open(path + ".url", "w") as f:
            f.write(url)
    except OSError:
        pass


def _read_url_sidecar(path: str):
    try:
        with open(path + ".url") as f:
            return f.read().strip() or None
    except OSError:
        return None


# Per-result prompt, stored as a "<file>.txt" sidecar so the artist can recall
# (and copy) the exact prompt that produced an image/video, even after reopening.
def _write_prompt_sidecar(path: str, prompt: str):
    if not (path and prompt):
        return
    try:
        with open(path + ".txt", "w", encoding="utf-8") as f:
            f.write(prompt)
    except OSError:
        pass


def _read_prompt_sidecar(path: str):
    try:
        with open(path + ".txt", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _url_is_fresh(url: str, margin: int = 300) -> bool:
    """True if a pre-signed Seedream/TOS URL hasn't expired yet. These URLs carry
    X-Tos-Date + X-Tos-Expires (typically 24h); after that the host returns 403,
    which Seedream/Seedance report as a download error. Unrecognized URLs are
    assumed usable."""
    try:
        from urllib.parse import urlparse, parse_qs
        import datetime
        import calendar
        q = parse_qs(urlparse(url).query)
        d = (q.get("X-Tos-Date") or q.get("X-Amz-Date") or [None])[0]
        e = (q.get("X-Tos-Expires") or q.get("X-Amz-Expires") or [None])[0]
        if not d or not e:
            return True                       # not a presigned URL we track
        t = datetime.datetime.strptime(d, "%Y%m%dT%H%M%SZ")
        expiry = calendar.timegm(t.timetuple()) + int(e)
        return (time.time() + margin) < expiry
    except Exception:
        return True                           # never block on a parse hiccup


# =============================================================================
# Low-level HTTP (urllib only -- Maya's bundled Python has no `requests`)
# =============================================================================
def _api_key() -> str:
    key = (CONFIG.API_KEY or "").strip() or os.environ.get(CONFIG.API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(
            "No API key found. Open BYTEPLUS > Settings... and paste your API "
            "key, or set the {} environment variable.".format(CONFIG.API_KEY_ENV)
        )
    return key


def _ssl_context() -> ssl.SSLContext:
    """Build an SSL context that works inside Maya's bundled Python.

    Order: use `certifi`'s CA bundle if available (secure); else the system
    default; and only if CONFIG.SSL_VERIFY is False, fall back to an unverified
    context (last resort for Maya's CA-less Python on macOS)."""
    if not CONFIG.SSL_VERIFY:
        return ssl._create_unverified_context()
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _open(req_or_url):
    try:
        return urllib.request.urlopen(req_or_url, timeout=CONFIG.HTTP_TIMEOUT,
                                      context=_ssl_context())
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.SSLCertVerificationError) or \
                "CERTIFICATE_VERIFY_FAILED" in str(reason):
            raise RuntimeError(
                "SSL certificate verification failed -- Maya's bundled Python "
                "has no CA bundle.\n\nFix (pick one):\n"
                "  1. Install certifi into Maya's Python:\n"
                "       /Applications/Autodesk/maya2027/Maya.app/Contents/"
                "Frameworks/Python.framework/Versions/Current/bin/python3 "
                "-m pip install --user certifi\n"
                "  2. Or open BYTEPLUS > Settings... and untick 'Verify SSL "
                "certificates' (less secure)."
            )
        raise


def _request(method: str, url: str, body: dict | None = None) -> dict:
    """Blocking JSON request. Always call from a worker thread, never the UI."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + _api_key())
    req.add_header("Content-Type", "application/json")
    try:
        with _open(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        msg = "HTTP {} {}\n  URL : {} {}\n  Body: {}".format(
            e.code, e.reason, method, url, detail)
        # Always echo to the Script Editor so the server's message is never lost
        # (the popup truncates and tracebacks hide the body).
        sys.stderr.write("\n[BYTEPLUS] " + msg + "\n")
        raise RuntimeError(msg)


def _get_bytes(url: str) -> bytes:
    """Download a result asset (image/video) by URL."""
    with _open(url) as resp:
        return resp.read()


def _find_video_url(obj) -> str | None:
    """Recursively dig a video URL out of an arbitrary task-result structure.
    Robust to whichever key/nesting Seedance uses (video_url, url, content...)."""
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("http") and any(
                e in s.lower() for e in (".mp4", ".mov", ".webm", "video")):
            return s
        return None
    if isinstance(obj, dict):
        # prefer obviously-named keys first
        for k in ("video_url", "videoUrl", "url"):
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        for v in obj.values():
            found = _find_video_url(v)
            if found:
                return found
    if isinstance(obj, (list, tuple)):
        for v in obj:
            found = _find_video_url(v)
            if found:
                return found
    return None


def diagnose(model: str | None = None):
    """Connectivity probe -- prints the raw image-endpoint response so we can see
    exactly why a call is failing. Uses the key from Settings / env (set it in
    BYTEPLUS > Settings... first, no need to paste it into code).

    Pass a model ID to test a candidate without changing settings, e.g.:
        import byteplus_maya
        byteplus_maya.diagnose("ep-20250101-abcde")
    """
    model = model or CONFIG.SEEDREAM_MODEL
    print("=" * 60)
    print("BYTEPLUS diagnose")
    print("  BASE_URL :", CONFIG.BASE_URL)
    print("  IMAGE_GEN:", CONFIG.IMAGE_GEN)
    print("  model    :", model)
    print("  ssl_verify:", CONFIG.SSL_VERIFY)
    try:
        key = _api_key()
        print("  api_key  : set (...{}, {} chars)".format(key[-4:], len(key)))
    except Exception as e:
        print("  api_key  : MISSING ->", e)
        print("  Set it in BYTEPLUS > Settings... then run diagnose() again.")
        print("=" * 60)
        return
    try:
        out = _request("POST", CONFIG.BASE_URL + CONFIG.IMAGE_GEN, {
            "model": model,
            "prompt": "a red apple on a table",
            "size": "2K",
            "response_format": "b64_json",
        })
        print("  RESULT   : SUCCESS  top-level keys =", list(out.keys()))
        print("  -> Put this model ID in BYTEPLUS > Settings (Seedream model).")
    except Exception as e:
        print("  RESULT   : FAILED")
        print(e)
    print("=" * 60)


def diagnose_video(model: str | None = None):
    """Validate a Seedance (video) model ID cheaply: create a tiny text-only
    task, confirm it's accepted, then immediately abort it (DELETE) so no full
    render is billed.

        import byteplus_maya
        byteplus_maya.diagnose_video("dreamina-seedance-2-0-260128")
    """
    model = model or CONFIG.SEEDANCE_MODEL
    print("=" * 60)
    print("BYTEPLUS diagnose_video")
    print("  model    :", model)
    try:
        _api_key()
    except Exception as e:
        print("  api_key  : MISSING ->", e)
        print("=" * 60)
        return
    url = CONFIG.BASE_URL + CONFIG.VIDEO_TASKS
    try:
        created = _request("POST", url, {
            "model": model,
            "content": [{"type": "text", "text": "a red apple on a table, slow zoom"}],
            "resolution": "480p", "ratio": "16:9", "duration": 4,
        })
        task_id = created.get("id") or created.get("task_id")
        print("  RESULT   : ACCEPTED  task_id =", task_id)
        if task_id:                                   # abort so it isn't billed
            try:
                _request("DELETE", "{}/{}".format(url, task_id))
                print("  cleanup  : task aborted (DELETE ok)")
            except Exception as ce:
                print("  cleanup  : could not abort ->", ce)
        print("  -> Put this model ID in BYTEPLUS > Settings (Seedance model).")
    except Exception as e:
        print("  RESULT   : FAILED")
        print(e)
    print("=" * 60)


# 1x1 px PNG (red) as a data URI -- a minimal valid image reference for probing.
# A 16x16 grey PNG used by the diagnostics as a throwaway reference image. NOTE:
# it must be >= 14px per side -- the models now reject smaller images (a 1x1 PNG
# 400s with "Image dimensions are too small"). Real features send real snapshots,
# never this; only the Diagnostics menu uses it.
_TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAAAAAA6mKC9"
             "AAAAD0lEQVR42mNoQAMMI1sAAAUMgAHjM1mKAAAAAElFTkSuQmCC")


def diagnose_video_ref(model: str | None = None):
    """Isolate WHY a Seedance task with references 400s. Submits text + one tiny
    image reference (no big payload), prints the raw server body, and aborts.

        import byteplus_maya
        byteplus_maya.diagnose_video_ref()
    """
    model = model or CONFIG.SEEDANCE_MODEL
    url = CONFIG.BASE_URL + CONFIG.VIDEO_TASKS
    print("=" * 60)
    print("BYTEPLUS diagnose_video_ref")
    print("  model    :", model)
    body = {
        "model": model,
        "content": [
            {"type": "text", "text": "a red apple on a table, slow zoom"},
            {"type": "image_url", "role": "reference_image", "image_url": {"url": _TINY_PNG}},
        ],
        "resolution": "480p", "ratio": "16:9", "duration": 4,
    }
    try:
        created = _request("POST", url, body)
        task_id = created.get("id") or created.get("task_id")
        print("  RESULT   : ACCEPTED (image_url schema is correct)  task_id =", task_id)
        if task_id:
            try:
                _request("DELETE", "{}/{}".format(url, task_id))
                print("  cleanup  : task aborted")
            except Exception as ce:
                print("  cleanup  : could not abort ->", ce)
    except Exception as e:
        print("  RESULT   : FAILED  (the body below tells us the right schema)")
        print(e)
    print("=" * 60)


_CAPTION_SYSTEM = (
    "You are an expert prompt engineer for the Seedream image model. Given a "
    "screenshot of a 3D Maya viewport (often a rough blockout with placeholder "
    "mannequins/props), write ONE concise English prompt (under 120 words) that "
    "would turn it into a finished, photorealistic image. State subject, "
    "composition, lighting, lens and style. If there are placeholder figures, "
    "mention how many there are. Output ONLY the prompt text, nothing else.")


def _caption_viewport(image_uri: str) -> str:
    """Use the multimodal LLM to turn the viewport screenshot into a Seedream
    prompt. `image_uri` is a data URI or URL. NETWORK ONLY -- call off-thread."""
    body = {
        "model": CONFIG.LLM_MODEL,
        "messages": [
            {"role": "system", "content": _CAPTION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Write the Seedream prompt for this scene."},
                {"type": "image_url", "image_url": {"url": image_uri}},
            ]},
        ],
    }
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, CONFIG.LLM_MODEL)
    return (resp["choices"][0]["message"]["content"] or "").strip()


_MOTION_SYSTEM = (
    "You are a film cinematographer. Given a still image, propose ONE short, "
    "natural way to animate it into a 4-6 second video clip: a camera move plus "
    "any subtle subject motion that fits the scene. One concise sentence in "
    "imperative style (e.g. 'Slow dolly-in as the robot turns its head, leaves "
    "drifting'). Output ONLY that sentence.")


def _caption_motion(image_uri: str) -> str:
    """Use the multimodal LLM to suggest a MOTION prompt for animating an image
    with Seedance. NETWORK ONLY -- call off-thread."""
    body = {
        "model": CONFIG.LLM_MODEL,
        "messages": [
            {"role": "system", "content": _MOTION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Describe the motion to animate this image."},
                {"type": "image_url", "image_url": {"url": image_uri}},
            ]},
        ],
    }
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, CONFIG.LLM_MODEL)
    return (resp["choices"][0]["message"]["content"] or "").strip()


_SCENE_MOTION_SYSTEM = (
    "You are a cinematographer. The images are SEQUENTIAL frames of a 3D "
    "animation (in order). Describe, in ONE concise sentence, the subject's "
    "motion and the camera movement across them (e.g. 'the horse gallops "
    "forward then rears up; camera tracks alongside, low angle'). Output ONLY "
    "that sentence.")


def _describe_scene_motion(frame_paths: list) -> str:
    """Describe the ACTUAL motion of the scene from sampled playblast frames, so
    Seedance follows it. NETWORK ONLY -- call off-thread."""
    user = [{"type": "text", "text": "Describe the motion across these ordered frames."}]
    for p in frame_paths[:6]:                        # a handful is enough
        user.append({"type": "image_url",
                     "image_url": {"url": _data_uri(p, "image/png")}})
    body = {
        "model": CONFIG.LLM_MODEL,
        "messages": [
            {"role": "system", "content": _SCENE_MOTION_SYSTEM},
            {"role": "user", "content": user},
        ],
    }
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, CONFIG.LLM_MODEL)
    return (resp["choices"][0]["message"]["content"] or "").strip()


_ENHANCE_SYSTEM = (
    "You are an expert prompt engineer for the Seedream image model. Improve the "
    "WORDING and structure of the user's prompt so Seedream renders it better. "
    "CRITICAL: preserve the user's exact meaning, subject and intent -- do NOT "
    "change the subject, do NOT add unrelated content, and do NOT describe any "
    "other scene. Keep everything they wrote; only clarify and add faithful, "
    "helpful detail (composition, lighting, lens, style) consistent with what "
    "they asked. Be concise (well under 150 words). Output ONLY the improved "
    "prompt -- no preamble, no quotes.")


def _enhance_prompt(user_text: str) -> str:
    """Improve the WRITING of the user's Seedream prompt. TEXT-ONLY -- it must not
    look at the scene; it just polishes what the user wrote. NETWORK-only."""
    body = {
        "model": CONFIG.LLM_MODEL,
        "messages": [
            {"role": "system", "content": _ENHANCE_SYSTEM},
            {"role": "user", "content": "Improve this Seedream prompt:\n" + user_text},
        ],
    }
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, CONFIG.LLM_MODEL)
    return (resp["choices"][0]["message"]["content"] or "").strip()


_ENHANCE_SCENE_SYSTEM = (
    "You improve the WORDING of a Seedream image prompt, focusing ONLY on the "
    "SUBJECT and SCENE: what is in frame, materials, surfaces, environment, "
    "action, and spatial layout. Preserve the user's exact subject and intent; "
    "clarify and add faithful descriptive detail about the subject and scene. "
    "Do NOT add or change camera, lens, shot type, framing, angle, lighting, "
    "mood, color grade, film stock, or style terms — those are controlled "
    "separately by the artist. Be concise (well under 120 words). Output ONLY "
    "the improved prompt — no preamble, no quotes.")


def _enhance_scene(user_text: str) -> str:
    """Improve ONLY the scene/subject wording (no camera/lighting/look) -- those
    are owned by the Camera dropdowns. TEXT-ONLY. NETWORK-only."""
    body = {
        "model": CONFIG.LLM_MODEL,
        "messages": [
            {"role": "system", "content": _ENHANCE_SCENE_SYSTEM},
            {"role": "user", "content": "Improve this scene description:\n" + user_text},
        ],
    }
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, CONFIG.LLM_MODEL)
    return (resp["choices"][0]["message"]["content"] or "").strip()


_ENHANCE_EDIT_SYSTEM = (
    "You are an expert at writing concise image-EDIT instructions for the "
    "Seedream model. Improve the user's edit instruction so it is clearer and "
    "more specific, but KEEP IT AS A SHORT EDIT INSTRUCTION about WHAT TO CHANGE. "
    "Do NOT rewrite it into a full scene description, do NOT add unrelated "
    "changes, and do NOT change the user's intent. One or two sentences max. "
    "Output ONLY the improved instruction -- no preamble, no quotes.")


def _enhance_edit(user_text: str) -> str:
    """Sharpen a Refine EDIT instruction (text-only). NETWORK-only."""
    body = {
        "model": CONFIG.LLM_MODEL,
        "messages": [
            {"role": "system", "content": _ENHANCE_EDIT_SYSTEM},
            {"role": "user", "content": "Improve this edit instruction:\n" + user_text},
        ],
    }
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, CONFIG.LLM_MODEL)
    return (resp["choices"][0]["message"]["content"] or "").strip()


_SEEDANCE_EDIT_SYSTEM = (
    "You are an expert at writing Seedance 2.0 VIDEO-TO-VIDEO prompts that "
    "TRANSFORM footage the user already has, using the frames of their clip shown "
    "to you. Their clip is attached to Seedance as the reference video, and one "
    "frame as the reference image. Your job: keep everything that makes the source "
    "recognizable and change ONLY the one element the user names.\n\n"
    "Read the attached frames and describe what is really there -- subject and "
    "identity, wardrobe, framing, lens and camera motion, time of day and key-light "
    "direction. Do NOT invent content the frames don't show.\n\n"
    "Write ONE prompt in English, plain text (no markdown, no bullets, no code "
    "block), ready to copy, structured as:\n"
    "1. An opening lock line: 'Keep the reference video exactly as it is -- same "
    "subject, face and identity, wardrobe, performance, framing, lens and camera "
    "motion -- and change only <the named element>.'\n"
    "2. A compact specs line: 'Photoreal. <aspect>. <duration>s. <look/grade>. "
    "NON-IP -- generic <X>, not based on any brand or character.' Match the duration "
    "to the source clip. Include the NON-IP clause whenever a creature, vehicle, "
    "armor or character design is added.\n"
    "3. The scene as ONE continuous shot: restate the preserved performance and the "
    "SAME camera move as the source, then the transformation described with its "
    "physics and how it interacts with the plate (the light it throws, contact "
    "shadows, parallax), then a lock-down clause repeating 'face and identity "
    "unchanged; everything else identical to the reference video.'\n"
    "4. A final line beginning 'SFX only:' (or 'SFX and source dialogue only:' when "
    "a spoken line must survive) with specific, ordered, behavioural sounds.\n\n"
    "Rules: preserve, then change one thing. Keep the subject's original light and "
    "grade only the new element to match the existing key when identity matters; "
    "name the key direction (e.g. screen-left). Make added elements photoreal and "
    "integrated -- matching sun direction, colour temperature, soft-edged contact "
    "shadows, atmospheric haze, depth of field and grain -- never CG, plastic or "
    "cartoonish. State scale explicitly for giant creatures. For a timed change, "
    "anchor it both semantically ('on the snap') and numerically ('at about T "
    "seconds'). Be terse and physically precise; no 'beautiful/stunning/amazing'. "
    "Output ONLY the prompt.")


def _seedance_edit_prompt_auto(video_path, poster, instruction, duration=None):
    """Write a full Seedance 2.0 video-to-video prompt from the user's one-line
    change plus a few frames of the clip (the skill-style 'preserve, change one
    thing' grammar). NETWORK ONLY -- call from a worker."""
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="byteplus_vedit_frames_")
    try:
        frames = []
        if poster and os.path.exists(poster):
            frames.append(poster)
        frames += _extract_video_frames(video_path, tmp, n=3)
        frames = frames[:4]
        dur = duration or _video_duration(video_path)
        dur_txt = ("{}s".format(max(4, min(15, int(round(dur))))) if dur
                   else "match the source clip")
        user = [{"type": "text", "text":
                 "The one change I want: {}\n\nSource clip duration: {}. Write the "
                 "full Seedance 2.0 video-to-video prompt for this clip.".format(
                     instruction.strip(), dur_txt)}]
        for p in frames:
            user.append({"type": "image_url",
                         "image_url": {"url": _data_uri(p, "image/jpeg")}})
        body = {
            "model": CONFIG.LLM_MODEL,
            "messages": [
                {"role": "system", "content": _SEEDANCE_EDIT_SYSTEM},
                {"role": "user", "content": user},
            ],
        }
        resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
        _track("llm", resp, CONFIG.LLM_MODEL)
        return (resp["choices"][0]["message"]["content"] or "").strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_ENHANCE_TEXTURE_SYSTEM = (
    "You are an expert at writing prompts for SEAMLESS PBR TEXTURE / material "
    "generation (base color / albedo). Improve the wording of the user's material "
    "description so it reads as a tileable surface texture, not a scene. KEEP the "
    "user's exact material and intent; only clarify and add faithful surface "
    "detail (material, finish, wear, scale, color) plus helpful texture terms like "
    "'seamless, tileable, flat even lighting, top-down, high detail'. Do NOT add a "
    "scene, objects, horizon, or lighting drama. Be concise (under 80 words). "
    "Output ONLY the improved prompt -- no preamble, no quotes.")


def _enhance_texture(user_text: str) -> str:
    """Sharpen a texture/material description (text-only). NETWORK-only."""
    body = {
        "model": CONFIG.LLM_MODEL,
        "messages": [
            {"role": "system", "content": _ENHANCE_TEXTURE_SYSTEM},
            {"role": "user", "content": "Improve this material/texture prompt:\n" + user_text},
        ],
    }
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, CONFIG.LLM_MODEL)
    return (resp["choices"][0]["message"]["content"] or "").strip()


def diagnose_llm(model: str | None = None):
    """Validate the multimodal LLM (auto-prompt) -- sends text + a tiny image and
    prints the reply or the raw error body.

        import byteplus_maya; byteplus_maya.diagnose_llm()
    """
    model = model or CONFIG.LLM_MODEL
    print("=" * 60)
    print("BYTEPLUS diagnose_llm")
    print("  model    :", model, " endpoint:", CONFIG.CHAT_COMPLETIONS)
    try:
        _api_key()
    except Exception as e:
        print("  api_key  : MISSING ->", e)
        print("=" * 60)
        return
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Reply with the single word: OK"},
            {"type": "image_url", "image_url": {"url": _TINY_PNG}},
        ]}],
    }
    try:
        resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
        print("  RESULT   : OK ->", resp["choices"][0]["message"]["content"][:80])
    except Exception as e:
        print("  RESULT   : FAILED")
        print(e)
    print("=" * 60)


def diagnose_images(model: str | None = None, n: int = 9):
    """Replicate the image-only render payload (n base64 image refs + your
    resolution/ratio) and print the raw server body. Fast -- no playblast.

        import byteplus_maya
        byteplus_maya.diagnose_images()
    """
    model = model or CONFIG.SEEDANCE_MODEL
    url = CONFIG.BASE_URL + CONFIG.VIDEO_TASKS
    print("=" * 60)
    print("BYTEPLUS diagnose_images")
    print("  model      :", model)
    print("  n images   :", n, " resolution:", CONFIG.VIDEO_RESOLUTION,
          " ratio:", CONFIG.VIDEO_RATIO)
    content = [{"type": "text", "text": "a red apple on a table, slow zoom"}]
    for _ in range(n):
        content.append({"type": "image_url", "role": "reference_image",
                        "image_url": {"url": _TINY_PNG}})
    body = {
        "model": model, "content": content,
        "resolution": CONFIG.VIDEO_RESOLUTION, "ratio": CONFIG.VIDEO_RATIO,
        "duration": 5,
    }
    try:
        created = _request("POST", url, body)
        task_id = created.get("id") or created.get("task_id")
        print("  RESULT     : ACCEPTED  task_id =", task_id)
        if task_id:
            try:
                _request("DELETE", "{}/{}".format(url, task_id))
                print("  cleanup    : task aborted")
            except Exception as ce:
                print("  cleanup    : could not abort ->", ce)
    except Exception as e:
        print("  RESULT     : FAILED")
        print(e)
    print("=" * 60)


def diagnose_video_movie(model: str | None = None):
    """Test the `video_url` reference item. Seedance requires the video to be a
    PUBLIC web URL, so this uploads the playblast to TOS first. Without TOS it
    cannot pass -- it tells you so instead of sending base64 (which always 400s).

        import byteplus_maya
        byteplus_maya.diagnose_video_movie()
    """
    model = model or CONFIG.SEEDANCE_MODEL
    url = CONFIG.BASE_URL + CONFIG.VIDEO_TASKS
    print("=" * 60)
    print("BYTEPLUS diagnose_video_movie")
    print("  model    :", model)
    movie = _playblast_movie()
    print("  movie    :", movie, "({:.1f} MB)".format(os.path.getsize(movie) / 1e6))
    host = "TOS" if _tos_available() else ("R2" if _r2_available() else None)
    print("  host     :", host or "(none configured)")
    cleanup = None
    try:
        movie_url, cleanup = _host_video(movie)      # prefers TOS, then R2
        print("  upload   : {} OK ->".format(host), movie_url[:80], "...")
    except Exception as e:
        print("  upload   : NO HOST -> video references are impossible without "
              "TOS or R2.")
        print("            ", e)
        print("  Configure TOS or R2 in BYTEPLUS > Settings to enable the video "
              "ref.")
        print("  (Image-only render works WITHOUT a host -- just run the menu "
              "item.)")
        print("=" * 60)
        return
    body = {
        "model": model,
        "content": [
            {"type": "text", "text": "slow cinematic zoom"},
            {"type": "video_url", "role": "reference_video",
             "video_url": {"url": movie_url}},
        ],
        "resolution": "480p", "ratio": "16:9", "duration": 4,
    }
    try:
        created = _request("POST", url, body)
        task_id = created.get("id") or created.get("task_id")
        print("  RESULT   : ACCEPTED (video_url schema is correct)  task_id =", task_id)
        if task_id:
            try:
                _request("DELETE", "{}/{}".format(url, task_id))
                print("  cleanup  : task aborted")
            except Exception as ce:
                print("  cleanup  : could not abort ->", ce)
    except Exception as e:
        print("  RESULT   : FAILED  (body below shows the correct video schema)")
        print(e)
    finally:
        if cleanup:                                  # remove the hosted R2 file
            try:
                cleanup()
                print("  host del : hosted video removed")
            except Exception as ce:
                print("  host del : could not remove hosted video ->", ce)
    print("=" * 60)


def diagnose_r2():
    """Validate Cloudflare R2 hosting end-to-end: upload a tiny file, pre-sign a
    GET, fetch it back, then delete it. Prints each step.

        import byteplus_maya; byteplus_maya.diagnose_r2()
    """
    print("=" * 60)
    print("BYTEPLUS diagnose_r2")
    print("  motion_host:", CONFIG.MOTION_HOST, " bucket:", CONFIG.R2_BUCKET,
          " account:", (CONFIG.R2_ACCOUNT_ID[:6] + "...") if CONFIG.R2_ACCOUNT_ID else "(unset)")
    if not _r2_available():
        print("  R2 not configured/enabled. Set Motion host = r2 + account/keys/"
              "bucket in Settings.")
        print("=" * 60)
        return
    key = "maya/diag_{}.txt".format(int(time.time()))
    try:
        _r2_request("PUT", key, b"byteplus r2 ok")
        print("  upload   : PUT ok ->", key)
        signed = _r2_presign_get(key, 300)
        print("  presign  :", signed[:90], "...")
        got = _get_bytes(signed)
        print("  fetch    : got", len(got), "bytes ->",
              "MATCH" if got == b"byteplus r2 ok" else "MISMATCH")
        _r2_request("DELETE", key)
        print("  delete   : DELETE ok")
        print("  RESULT   : R2 hosting works \U0001F389")
    except Exception as e:
        print("  RESULT   : FAILED")
        print(e)
    print("=" * 60)


def _data_uri(path: str, mime: str) -> str:
    """Base64 a local file into a data URI for the `content`/`image` arrays.
    Fine for 720p stills/short playblasts; for production prefer TOS pre-signed
    URLs (body limit is 64 MB, single image 30 MB)."""
    with open(path, "rb") as f:
        return "data:{};base64,{}".format(mime, base64.b64encode(f.read()).decode())


def _tos_creds() -> tuple:
    """(access_key, secret_key) -- Settings values take precedence over env."""
    ak = (CONFIG.TOS_AK or "").strip() or os.environ.get(CONFIG.TOS_AK_ENV, "").strip()
    sk = (CONFIG.TOS_SK or "").strip() or os.environ.get(CONFIG.TOS_SK_ENV, "").strip()
    return ak, sk


def _tos_available() -> bool:
    """True if TOS can actually be used (SDK installed + AK/SK + bucket). Used to
    warn the user up front when the motion playblast will be skipped."""
    try:
        import tos  # noqa: F401
    except Exception:
        return False
    ak, sk = _tos_creds()
    return bool(ak and sk and CONFIG.TOS_BUCKET)


def _tos_upload_presigned(path: str) -> str:
    """Upload `path` to BytePlus TOS and return a pre-signed GET URL.
    Uses the official `tos` SDK so signing/region handling is correct. Raises
    if the SDK or config is missing -- the caller falls back to base64."""
    import tos  # official BytePlus TOS SDK: pip install tos
    ak, sk = _tos_creds()
    if not (ak and sk and CONFIG.TOS_BUCKET):
        raise RuntimeError("TOS not fully configured (AK/SK + bucket).")

    client = tos.TosClientV2(ak, sk, CONFIG.TOS_ENDPOINT, CONFIG.TOS_REGION)
    key = "maya/{}/{}".format(int(time.time()), os.path.basename(path))
    client.put_object_from_file(CONFIG.TOS_BUCKET, key, path)
    signed = client.pre_signed_url(
        tos.HttpMethodType.Http_Method_Get, CONFIG.TOS_BUCKET, key,
        expires=CONFIG.TOS_PRESIGN_TTL)
    return signed.signed_url


# =============================================================================
# Cloudflare R2 (S3-compatible) -- AWS SigV4 signed, no SDK required.
# Used to host the playblast as a PRIVATE pre-signed URL for Seedance's video
# reference, then delete it when the job finishes. Opt-in (MOTION_HOST == "r2").
# =============================================================================
def _r2_available() -> bool:
    return bool(CONFIG.MOTION_HOST == "r2" and CONFIG.R2_ACCOUNT_ID
                and CONFIG.R2_ACCESS_KEY and CONFIG.R2_SECRET_KEY
                and CONFIG.R2_BUCKET)


def _r2_host() -> str:
    return "{}.r2.cloudflarestorage.com".format(CONFIG.R2_ACCOUNT_ID)


def _sigv4_signing_key(secret, datestamp, region, service):
    def _h(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    k_date = _h(("AWS4" + secret).encode("utf-8"), datestamp)
    k_region = _h(k_date, region)
    k_service = _h(k_region, service)
    return _h(k_service, "aws4_request")


def _r2_request(method: str, key: str, payload: bytes = b"", retries: int = 3,
                bucket: str = ""):
    """Signed (SigV4) request to R2 for PUT/DELETE. region='auto', service='s3'.
    Retries transient SSL/network failures (re-signing each attempt). HTTP errors
    (auth/permission) are NOT retried -- they won't fix themselves."""
    host = _r2_host()
    region, service = "auto", "s3"
    bucket = bucket or CONFIG.R2_BUCKET
    canonical_uri = "/" + bucket + "/" + urllib.parse.quote(key, safe="/")
    payload_hash = hashlib.sha256(payload).hexdigest()
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    last_err = None
    for attempt in range(retries):
        now = datetime.datetime.now(datetime.timezone.utc)
        amzdate = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")
        canonical_headers = ("host:{}\nx-amz-content-sha256:{}\nx-amz-date:{}\n"
                             .format(host, payload_hash, amzdate))
        canonical_request = "\n".join([method, canonical_uri, "", canonical_headers,
                                       signed_headers, payload_hash])
        scope = "{}/{}/{}/aws4_request".format(datestamp, region, service)
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256", amzdate, scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
        signature = hmac.new(_sigv4_signing_key(CONFIG.R2_SECRET_KEY, datestamp,
                             region, service),
                             string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = ("AWS4-HMAC-SHA256 Credential={}/{}, SignedHeaders={}, "
                         "Signature={}".format(CONFIG.R2_ACCESS_KEY, scope,
                                               signed_headers, signature))
        req = urllib.request.Request("https://" + host + canonical_uri,
                                     data=(payload if method != "DELETE" else None),
                                     method=method)
        req.add_header("Host", host)
        req.add_header("x-amz-content-sha256", payload_hash)
        req.add_header("x-amz-date", amzdate)
        req.add_header("Authorization", authorization)
        try:
            with _open(req) as resp:
                resp.read()
            return
        except urllib.error.HTTPError:
            raise                                    # 4xx/5xx -> don't retry
        except Exception as e:                       # transient SSL / network
            last_err = e
            sys.stderr.write("[BYTEPLUS] R2 {} attempt {}/{} failed: {}\n".format(
                method, attempt + 1, retries, e))
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def _r2_presign_get(key: str, expires: int) -> str:
    """Build a SigV4 pre-signed GET URL (private, time-limited) for `key`."""
    host = _r2_host()
    region, service = "auto", "s3"
    now = datetime.datetime.now(datetime.timezone.utc)
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    canonical_uri = "/" + CONFIG.R2_BUCKET + "/" + urllib.parse.quote(key, safe="/")
    scope = "{}/{}/{}/aws4_request".format(datestamp, region, service)
    q = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": "{}/{}".format(CONFIG.R2_ACCESS_KEY, scope),
        "X-Amz-Date": amzdate,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_qs = "&".join("{}={}".format(
        urllib.parse.quote(k, safe=""), urllib.parse.quote(v, safe=""))
        for k, v in sorted(q.items()))
    canonical_request = "\n".join([
        "GET", canonical_uri, canonical_qs,
        "host:{}\n".format(host), "host", "UNSIGNED-PAYLOAD"])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amzdate, scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
    signature = hmac.new(_sigv4_signing_key(CONFIG.R2_SECRET_KEY, datestamp,
                         region, service),
                         string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return "https://{}{}?{}&X-Amz-Signature={}".format(
        host, canonical_uri, canonical_qs, signature)


def _r2_upload_presigned(path: str):
    """Upload `path` to R2 and return (presigned_get_url, delete_callable)."""
    key = "maya/{}/{}".format(int(time.time()), os.path.basename(path))
    with open(path, "rb") as f:
        payload = f.read()
    _r2_request("PUT", key, payload)
    url = _r2_presign_get(key, CONFIG.R2_PRESIGN_TTL)
    return url, (lambda: _r2_request("DELETE", key))


def _host_video(path: str):
    """Host the playblast on a service Seedance can fetch, returning
    (public_url, cleanup_callable). Prefers TOS, then R2. Raises if neither is
    configured. cleanup_callable() removes the remote file (no-op for TOS, which
    expires via its pre-sign TTL)."""
    if _tos_available():
        return _tos_upload_presigned(path), (lambda: None)
    if _r2_available():
        return _r2_upload_presigned(path)
    raise RuntimeError("no motion-video host configured (TOS or R2)")


def _motion_host_ready() -> bool:
    """True if a host exists to deliver the playblast video to Seedance."""
    return _tos_available() or _r2_available()


def _motion_host_selftest(kind: str):
    """Upload a tiny file to the chosen host (kind: 'r2'|'tos'), fetch it back to
    prove it is publicly reachable, then delete it. Raises on any failure.
    NETWORK ONLY -- call from a worker. Reads the live CONFIG values."""
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".txt", prefix="byteplus_hosttest_")
    os.close(fd)
    with open(p, "wb") as f:
        f.write(b"byteplus motion-host self test")
    try:
        if kind == "tos":
            url, cleanup = _tos_upload_presigned(p), (lambda: None)
        else:
            url, cleanup = _r2_upload_presigned(p)
        try:
            with _open(url) as resp:                  # must be publicly fetchable
                if not resp.read():
                    raise RuntimeError("the uploaded file came back empty")
        finally:
            try:
                cleanup()
            except Exception:
                pass
    finally:
        try:
            os.remove(p)
        except Exception:
            pass


# =============================================================================
# Usage counter + anonymous telemetry
#   - Usage: in-memory counters persisted to USAGE_PATH, shown in 'Usage...'.
#   - Telemetry: anonymized events buffered and flushed to R2 in a daemon
#     thread (never blocks generation). No prompts / scene / keys are sent.
# =============================================================================
# Per-project counter fields (a sub-bucket per Maya scene under "projects").
_PROJECT_FIELDS = ("images", "videos", "textures", "llm",
                   "tokens_in", "tokens_out", "tokens_total")
_USAGE = {"images": 0, "videos": 0, "textures": 0, "llm": 0,
          "tokens_in": 0, "tokens_out": 0, "tokens_total": 0,
          "projects": {}}
_USAGE_LOCK = threading.Lock()
# The Maya scene that owns the work currently being submitted. Captured on the
# MAIN thread (Maya cmds are not thread-safe); _track (worker thread) only reads
# this cached string, never calls Maya.
_ACTIVE_PROJECT = ""
_TELE_BUF = []
_TELE_LOCK = threading.Lock()
_TELE_THREAD = None


def _mark_active_project():
    """Cache the current Maya scene as the active project for usage attribution.
    MAIN THREAD ONLY (reads Maya via _scene_tag)."""
    global _ACTIVE_PROJECT
    try:
        _ACTIVE_PROJECT = _scene_tag() or "untitled"
    except Exception:
        pass


def _install_id() -> str:
    if not CONFIG.INSTALL_ID:
        CONFIG.INSTALL_ID = uuid.uuid4().hex
        _save_prefs()
    return CONFIG.INSTALL_ID


def _load_usage():
    try:
        with open(CONFIG.USAGE_PATH) as f:
            data = json.load(f)
        with _USAGE_LOCK:
            for k in _USAGE:
                _USAGE[k] = data.get(k, _USAGE[k])
            if not isinstance(_USAGE.get("projects"), dict):   # old files / bad data
                _USAGE["projects"] = {}
    except (OSError, ValueError):
        pass


def _save_usage():
    try:
        with open(CONFIG.USAGE_PATH, "w") as f:
            json.dump(_USAGE, f, indent=2)
    except OSError:
        pass


def _usage_tokens(resp):
    """Extract (in, out, total) tokens from a ModelArk response 'usage' block."""
    u = (resp or {}).get("usage") or {}
    ti = u.get("prompt_tokens") or u.get("input_tokens") or 0
    to = u.get("completion_tokens") or u.get("output_tokens") or 0
    tt = u.get("total_tokens") or (ti + to)
    try:
        return int(ti), int(to), int(tt)
    except (TypeError, ValueError):
        return 0, 0, 0


def _track(kind: str, resp=None, model="", extra=None):
    """Record one event: bump the local counter and enqueue a telemetry event.
    `kind` in {'images','videos','textures','llm'}. Cheap + non-blocking."""
    ti, to, tt = _usage_tokens(resp)
    with _USAGE_LOCK:
        if kind in _USAGE:
            _USAGE[kind] += 1
        _USAGE["tokens_in"] += ti
        _USAGE["tokens_out"] += to
        _USAGE["tokens_total"] += tt
        # Per-project bucket (local only; never sent in telemetry).
        proj = _ACTIVE_PROJECT or "untitled"
        pb = _USAGE["projects"].setdefault(
            proj, {f: 0 for f in _PROJECT_FIELDS})
        if kind in pb:
            pb[kind] += 1
        pb["tokens_in"] += ti
        pb["tokens_out"] += to
        pb["tokens_total"] += tt
        _save_usage()
    if CONFIG.TELEMETRY:
        # customer = company they gave on first run, else the build's CUSTOMER_ID.
        customer = (CONFIG.USER_COMPANY or CONFIG.CUSTOMER_ID or "").strip()
        ev = {"id": _install_id(), "ts": int(time.time()), "v": CONFIG.VERSION,
              "host": "maya", "event": kind, "model": model or "",
              "customer": customer, "email": CONFIG.USER_EMAIL or "",
              "role": CONFIG.USER_ROLE or "",
              "tokens": {"in": ti, "out": to, "total": tt}}
        if extra:
            ev.update(extra)
        with _TELE_LOCK:
            _TELE_BUF.append(ev)
        _telemetry_start()


def usage_snapshot() -> dict:
    with _USAGE_LOCK:
        return dict(_USAGE)


def _fmt_compact(n: int) -> str:
    """1234 -> '1.2K', 14076869 -> '14.1M' (small numbers stay as-is)."""
    n = int(n or 0)
    if n >= 1_000_000:
        return "{:.1f}M".format(n / 1_000_000).replace(".0M", "M")
    if n >= 1_000:
        return "{:.1f}K".format(n / 1_000).replace(".0K", "K")
    return str(n)


def _video_dims(resolution, ratio):
    r = CONFIG.COST_DIMS.get(resolution, {})
    return r.get(ratio) or r.get("16:9") or (1280, 720)


def _est_video_cost(resolution, ratio, duration, has_video):
    """Approx (tokens, USD) for a Seedance video. has_video = a reference video
    (playblast) is attached -> cheaper rate but counts input duration too."""
    w, h = _video_dims(resolution, ratio)
    out_dur = max(1, int(round(duration)))
    in_dur = out_dur if has_video else 0
    tokens = (in_dur + out_dur) * w * h * CONFIG.VIDEO_FPS / 1024.0
    rate_no, rate_yes = CONFIG.COST_VIDEO_RATES.get(resolution, (7.0, 4.3))
    usd = tokens / 1_000_000.0 * (rate_yes if has_video else rate_no)
    return tokens, usd


def _est_image_cost(n=1):
    return n * CONFIG.COST_IMAGE_USD


def _fmt_cost(tokens, usd):
    if tokens:
        return "Estimated cost: ≈ {} tokens · ≈ ${:.2f}".format(
            _fmt_compact(int(tokens)), usd)
    return "Estimated cost: ≈ ${:.2f}".format(usd)


def _msgbox(icon, title, text, buttons=None):
    """A QMessageBox guaranteed to appear ABOVE everything. Our galleries/previews
    are always-on-top, so a modal (even one with stay-on-top) can still open behind
    a gallery that was raised more recently -- making Maya look frozen. So for the
    duration of the dialog we DROP always-on-top from every other visible window
    and restore it afterward. Returns the clicked StandardButton."""
    lifted = []
    for w in QtWidgets.QApplication.topLevelWidgets():
        try:
            if (w.isVisible() and w.isWindow()
                    and bool(w.windowFlags() & QtCore.Qt.WindowStaysOnTopHint)):
                w.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, False)
                w.show()                              # re-apply the cleared flag
                lifted.append(w)
        except Exception:
            pass
    try:
        box = QtWidgets.QMessageBox(_main_window())
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons if buttons is not None else QtWidgets.QMessageBox.Ok)
        box.setWindowModality(QtCore.Qt.ApplicationModal)
        box.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        box.raise_()
        box.activateWindow()
        return box.exec()
    finally:
        for w in lifted:                              # restore the galleries' flag
            try:
                w.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
                w.show()
            except Exception:
                pass


def _confirm_cost(usd, what):
    """Cost-confirmation pop-up is disabled by request. The estimate is still shown
    as a label inside the generation dialogs, but we never block with a dialog.
    Always returns True so callers proceed."""
    return True


def _usage_title(base: str) -> str:
    """Append a compact usage summary to a gallery window title. Tokens are
    abbreviated (14.1M); the exact breakdown lives in BYTEPLUS > Usage..."""
    u = usage_snapshot()
    return "{}    ·    {} imgs · {} vids · {} tok".format(
        base, u["images"], u["videos"], _fmt_compact(u["tokens_total"]))


_EVENT_NAMES = {"images": "image_generated", "videos": "video_generated",
                "textures": "texture_generated", "llm": "llm_call"}


def _telemetry_ready() -> bool:
    """True if the selected telemetry backend is configured enough to send."""
    if not CONFIG.TELEMETRY:
        return False
    if CONFIG.TELEMETRY_BACKEND == "posthog":
        return bool((CONFIG.POSTHOG_API_KEY or "").strip())
    bucket = CONFIG.TELEMETRY_BUCKET or CONFIG.R2_BUCKET
    return bool(CONFIG.R2_ACCOUNT_ID and CONFIG.R2_ACCESS_KEY
                and CONFIG.R2_SECRET_KEY and bucket)


def _posthog_event(ev: dict) -> dict:
    """Map our internal event to a PostHog capture object. distinct_id is the
    stable per-seat install id; identity (email / company / role) rides along as
    properties and is also attached to the person via $identify (see
    _posthog_identify), so you can break down by customer or email."""
    import datetime
    tok = ev.get("tokens") or {}
    props = {
        "model": ev.get("model", ""), "version": ev.get("v", ""),
        "host": ev.get("host", "maya"), "customer": ev.get("customer", ""),
        "email": ev.get("email", ""), "role": ev.get("role", ""),
        "install_id": ev.get("id", ""),
        "tokens_in": tok.get("in", 0), "tokens_out": tok.get("out", 0),
        "tokens_total": tok.get("total", 0),
        "$lib": "byteplus-maya",
    }
    return {
        "event": _EVENT_NAMES.get(ev.get("event"), ev.get("event", "event")),
        "distinct_id": ev.get("id") or "anonymous",
        "properties": props,
        "timestamp": datetime.datetime.utcfromtimestamp(
            ev.get("ts", int(time.time()))).isoformat() + "Z",
    }


def _posthog_flush(batch: list):
    """POST a batch of events to PostHog's ingestion endpoint. The project key
    is public/write-only, sent in the body (no Authorization header)."""
    url = CONFIG.POSTHOG_HOST.rstrip("/") + "/batch/"
    body = {"api_key": CONFIG.POSTHOG_API_KEY,
            "batch": [_posthog_event(e) for e in batch]}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with _open(req) as resp:
        resp.read()


def _r2_telemetry_flush(batch: list):
    """Write a batch of events to R2 as one newline-delimited JSON object."""
    bucket = CONFIG.TELEMETRY_BUCKET or CONFIG.R2_BUCKET
    prefix = CONFIG.TELEMETRY_PREFIX or "telemetry"
    key = "{}/{}/{}_{}.json".format(prefix, _install_id(), int(time.time()),
                                    len(batch))
    payload = ("\n".join(json.dumps(e) for e in batch)).encode("utf-8")
    _r2_request("PUT", key, payload, bucket=bucket)


def _telemetry_flush_loop():
    """Daemon: every ~10s, send buffered events to the configured backend
    (PostHog or R2). Best-effort; never blocks generation."""
    while True:
        time.sleep(10)
        with _TELE_LOCK:
            batch = _TELE_BUF[:]
        if not batch:
            continue
        if not _telemetry_ready():
            continue
        try:
            if CONFIG.TELEMETRY_BACKEND == "posthog":
                _posthog_flush(batch)
            else:
                _r2_telemetry_flush(batch)
            with _TELE_LOCK:
                del _TELE_BUF[:len(batch)]          # drop only what we sent
        except Exception as e:
            sys.stderr.write("[BYTEPLUS] telemetry flush deferred: {}\n".format(e))
            with _TELE_LOCK:                        # cap buffer so it can't grow forever
                if len(_TELE_BUF) > 500:
                    del _TELE_BUF[:len(_TELE_BUF) - 500]


def _telemetry_start():
    global _TELE_THREAD
    if _TELE_THREAD is None or not _TELE_THREAD.is_alive():
        _TELE_THREAD = threading.Thread(target=_telemetry_flush_loop, daemon=True)
        _TELE_THREAD.start()


def _posthog_identify():
    """Attach the user's identity (email / name / role / company) to their
    PostHog person via a $identify event. Fire-and-forget on a daemon thread so
    the UI never blocks. Only sends fields the user actually provided."""
    if CONFIG.TELEMETRY_BACKEND != "posthog" or not (CONFIG.POSTHOG_API_KEY or "").strip():
        return
    setp = {k: v for k, v in {
        "email": (CONFIG.USER_EMAIL or "").strip(),
        "name": (CONFIG.USER_NAME or "").strip(),
        "role": (CONFIG.USER_ROLE or "").strip(),
        "company": (CONFIG.USER_COMPANY or "").strip(),
        "plugin_version": CONFIG.VERSION,
    }.items() if v}
    if not setp:
        return

    def _send():
        try:
            url = CONFIG.POSTHOG_HOST.rstrip("/") + "/i/v0/e/"
            body = {"api_key": CONFIG.POSTHOG_API_KEY, "event": "$identify",
                    "distinct_id": _install_id(), "properties": {"$set": setp}}
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                         method="POST")
            req.add_header("Content-Type", "application/json")
            with _open(req) as resp:
                resp.read()
        except Exception as e:
            sys.stderr.write("[BYTEPLUS] identify deferred: {}\n".format(e))

    threading.Thread(target=_send, daemon=True).start()


def _maybe_identify():
    """First-run, consent-based identity prompt. Shown once: after the user
    answers (either way) IDENTIFIED is set so it never nags again. Declining
    keeps telemetry fully anonymous (install id only)."""
    if CONFIG.IDENTIFIED or not CONFIG.TELEMETRY:
        return
    try:
        dlg = QtWidgets.QDialog(_main_window())
        dlg.setWindowTitle("BYTEPLUS — Help improve the plugin")
        dlg.setMinimumWidth(460)
        v = QtWidgets.QVBoxLayout(dlg)
        intro = QtWidgets.QLabel(
            "BYTEPLUS is a Technology Preview. To help us improve it, you can "
            "optionally tell us who you are. We collect anonymous usage only "
            "(features used, models, token counts) — never your prompts, scenes, "
            "images or videos.\n\nSharing your details is optional and you can "
            "change or clear them anytime in Settings > Analytics.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        form = QtWidgets.QFormLayout()
        e_email = QtWidgets.QLineEdit(CONFIG.USER_EMAIL)
        e_email.setPlaceholderText("you@studio.com (optional)")
        e_name = QtWidgets.QLineEdit(CONFIG.USER_NAME)
        e_name.setPlaceholderText("optional")
        e_role = QtWidgets.QLineEdit(CONFIG.USER_ROLE)
        e_role.setPlaceholderText("e.g. Lighting TD (optional)")
        e_company = QtWidgets.QLineEdit(CONFIG.USER_COMPANY)
        e_company.setPlaceholderText("your studio / company (optional)")
        form.addRow("Email", e_email)
        form.addRow("Name", e_name)
        form.addRow("Role", e_role)
        form.addRow("Company", e_company)
        v.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        b_anon = QtWidgets.QPushButton("Stay anonymous")
        b_send = QtWidgets.QPushButton("Send & help improve")
        b_send.setDefault(True)
        row.addStretch(1); row.addWidget(b_anon); row.addWidget(b_send)
        v.addLayout(row)

        result = {"share": False}
        b_anon.clicked.connect(dlg.reject)
        b_send.clicked.connect(lambda: (result.update(share=True), dlg.accept()))
        dlg.exec()

        if result["share"]:
            CONFIG.USER_EMAIL = e_email.text().strip()
            CONFIG.USER_NAME = e_name.text().strip()
            CONFIG.USER_ROLE = e_role.text().strip()
            CONFIG.USER_COMPANY = e_company.text().strip()
        # Persist the answer FIRST, before any side effect, so the choice can
        # never be lost once the dialog is dismissed (defensive: _posthog_identify
        # is fire-and-forget and shouldn't raise, but this removes all doubt).
        CONFIG.IDENTIFIED = True
        _save_prefs()
        if result["share"]:
            try:
                _posthog_identify()
            except Exception:
                sys.stderr.write("[BYTEPLUS] identify send failed (your choice "
                                 "was still saved):\n" + traceback.format_exc())
    except Exception:
        sys.stderr.write("[BYTEPLUS] identify prompt skipped:\n"
                         + traceback.format_exc())


def _asset_uri(path: str, mime: str) -> str:
    """Return a URL/URI usable in a ModelArk reference array. Prefers a TOS
    pre-signed URL when USE_TOS is on; otherwise (or on any TOS error) falls
    back to an inline base64 data URI."""
    if CONFIG.USE_TOS:
        try:
            return _tos_upload_presigned(path)
        except Exception as e:  # SDK missing / misconfig / network -> graceful
            sys.stderr.write("[BYTEPLUS] TOS upload failed, using base64: "
                             "{}\n".format(e))
    return _data_uri(path, mime)


# =============================================================================
# Threaded worker -- keeps the Maya UI responsive during network calls
# =============================================================================
class _Worker(QtCore.QThread):
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, fn, parent=None, cancel_event=None):
        super().__init__(parent)
        self._fn = fn
        self.cancel = cancel_event or threading.Event()
        self._bound = cancel_event is not None     # explicitly bound (batch jobs)

    def start(self, *a, **k):
        # start() always runs on the MAIN (UI) thread, so capture the active Maya
        # scene here for usage attribution. This covers EVERY worker-based job --
        # including standalone Enhance/Auto LLM calls that don't open a progress
        # dialog -- so their tokens land on the real project, not "untitled".
        _mark_active_project()
        # Adopt the cancel token of the _progress() created just before us, so the
        # HUD's ✕ on that row can stop THIS worker. Consume it so a later worker
        # with no progress (e.g. Enhance) doesn't inherit a stale token.
        global _PENDING_HANDLE
        if not self._bound and _PENDING_HANDLE is not None:
            self.cancel = _PENDING_HANDLE.cancel
            _PENDING_HANDLE.worker = self
        _PENDING_HANDLE = None
        super().start(*a, **k)

    def run(self):
        _CANCEL_TLS.event = self.cancel
        try:
            result = self._fn()
            if self.cancel.is_set():           # cancelled mid-flight -> discard
                return
            self.done.emit(result)
        except _Cancelled:
            pass                               # cooperative cancel -> emit nothing
        except Exception:
            if not self.cancel.is_set():       # don't surface errors for a cancel
                self.failed.emit(traceback.format_exc())
        finally:
            _CANCEL_TLS.event = None


# =============================================================================
# Maya helpers
# =============================================================================
def _main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def _debug_on() -> bool:
    """Developer/partner mode: show Diagnostics. CONFIG.DEBUG or env override."""
    return bool(CONFIG.DEBUG or os.environ.get("BYTEPLUS_DEBUG"))


def _tmp(suffix: str) -> str:
    fd, path = tempfile.mkstemp(prefix="byteplus_", suffix=suffix)
    os.close(fd)
    return path


def _project_subdir(rule: str, default: str, sub: str = "byteplus") -> str:
    """A '<project>/<rule>/<sub>' folder, created if missing. `rule` is a Maya
    workspace file rule (e.g. 'images', 'movies'); `sub` keeps BYTEPLUS output
    tidy inside it. Everything lands under the current Maya project."""
    root = cmds.workspace(q=True, fullName=True) or os.path.expanduser("~")
    try:
        loc = cmds.workspace(fileRuleEntry=rule) or default
    except Exception:
        loc = default
    base = loc if os.path.isabs(loc) else os.path.join(root, loc)
    path = os.path.join(base, sub) if sub else base
    os.makedirs(path, exist_ok=True)
    return path


def _project_images_dir() -> str:
    """<project>/images/byteplus -- where rendered frames & generated images go."""
    return _project_subdir("images", "images")


def _project_movies_dir() -> str:
    """<project>/movies/byteplus -- where playblasts go (Maya-standard location)."""
    return _project_subdir("movies", "movies")


def _scene_stem() -> str:
    """Sanitized Maya scene file name (no extension), or '' if unsaved."""
    p = cmds.file(q=True, sceneName=True) or ""
    if not p:
        return ""
    base = os.path.splitext(os.path.basename(p))[0]
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in base)


def _scene_tag() -> str:
    """Scene name for folders/filenames; 'untitled' when the scene is unsaved."""
    return _scene_stem() or "untitled"


def _scene_images_dir() -> str:
    """images/byteplus/<scene>/ -- generated images, grouped per Maya scene."""
    return _project_subdir("images", "images",
                           os.path.join("byteplus", _scene_tag()))


def _scene_movies_dir() -> str:
    """movies/byteplus/<scene>/ -- generated videos, grouped per Maya scene."""
    return _project_subdir("movies", "movies",
                           os.path.join("byteplus", _scene_tag()))


def _texture_dir(material: str) -> str:
    """images/textures/<material>/ -- one folder per generated texture set."""
    return _project_subdir("images", "images",
                           os.path.join("textures", _safe_name(material)))


def _scene_ok_to_proceed() -> bool:
    """If the scene is unsaved, warn (outputs go under 'untitled'). Returns True
    to proceed, False if the user cancels."""
    if _scene_stem():
        return True
    return _msgbox(
        QtWidgets.QMessageBox.Warning, "BYTEPLUS - scene not saved",
        "Your Maya scene isn't saved yet, so outputs will be organized under an "
        "'untitled' folder instead of your scene name.\n\nSave the scene first "
        "for tidy, per-scene folders. Continue anyway?",
        QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel
    ) == QtWidgets.QMessageBox.Ok


_PATH_LOCK = threading.Lock()
_PATH_RESERVED = set()


def _unique_path(directory: str, stem: str, ext: str = ".png") -> str:
    """A non-clobbering path: <dir>/<stem>.png, then <stem>_001.png, ...

    Thread-safe: reserves the chosen name under a lock so parallel callers
    (e.g. batched Dream variations) never hand out the same path before either
    has written its file."""
    with _PATH_LOCK:
        cand = os.path.join(directory, stem + ext)
        i = 1
        while os.path.exists(cand) or cand in _PATH_RESERVED:
            cand = os.path.join(directory, "{}_{:03d}{}".format(stem, i, ext))
            i += 1
        _PATH_RESERVED.add(cand)
        return cand


def _safe_name(node: str) -> str:
    """Maya node name -> filesystem-safe stem."""
    base = node.split("|")[-1].split(":")[-1]
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in base) or "obj"


def _anim_range() -> tuple:
    """(start, end) frames to sample. Prefers the play-slider range when it
    actually spans something; otherwise falls back to the full scene animation
    range (animationStart/EndTime) -- so a collapsed slider doesn't yield a
    single frame."""
    a = cmds.playbackOptions(q=True, minTime=True)
    b = cmds.playbackOptions(q=True, maxTime=True)
    if b - a > 0:
        return a, b
    a = cmds.playbackOptions(q=True, animationStartTime=True)
    b = cmds.playbackOptions(q=True, animationEndTime=True)
    return a, b


def _frame_samples(n_max: int) -> list[int]:
    """Up to `n_max` integer frames evenly spaced across the animation range,
    inclusive of first and last."""
    start_f, end_f = _anim_range()
    start, end = int(start_f), int(end_f)
    span = end - start
    if span <= 0:
        return [start]
    n = min(n_max, span + 1)
    if n == 1:
        return [start]
    return [round(start + span * i / (n - 1)) for i in range(n)]


_FPS_NAMED = {"game": 15, "film": 24, "pal": 25, "ntsc": 30, "show": 48,
              "palf": 50, "ntscf": 60}


def _scene_fps() -> float:
    """Frames per second of the current scene (handles named and 'Nfps' units)."""
    unit = cmds.currentUnit(q=True, time=True) or "film"
    if unit in _FPS_NAMED:
        return float(_FPS_NAMED[unit])
    if unit.endswith("fps"):
        try:
            return float(unit[:-3])
        except ValueError:
            pass
    return 24.0


def _anim_seconds() -> float:
    """Length of the animation range in seconds, using the scene FPS."""
    start, end = _anim_range()
    return max(0.0, (end - start) / _scene_fps())


def _has_animation() -> bool:
    """True if the scene has a non-trivial animation range to capture."""
    start, end = _anim_range()
    return (end - start) > 0


def _ref_count(seconds: float, cap: int) -> int:
    """How many reference frames to render: 3 at <=5s, 9 at >=15s, linear
    between. Never more than `cap` (the Settings max)."""
    if seconds <= 5:
        n = 3
    elif seconds >= 15:
        n = 9
    else:
        n = int(round(3 + (seconds - 5) / 10.0 * 6))
    return max(1, min(cap, n))


def _active_camera() -> str:
    """The camera of the focused (or first) model panel -- matches what the
    artist is looking at; falls back to a renderable camera, then persp."""
    panel = cmds.getPanel(withFocus=True)
    if not panel or cmds.getPanel(typeOf=panel) != "modelPanel":
        panels = cmds.getPanel(type="modelPanel") or []
        panel = panels[0] if panels else None
    if panel:
        cam = cmds.modelEditor(panel, q=True, camera=True)
        if cam:
            return cam
    renderable = [c for c in (cmds.ls(type="camera") or [])
                  if cmds.getAttr(c + ".renderable")]
    if renderable:
        return cmds.listRelatives(renderable[0], parent=True, fullPath=True)[0]
    return "persp"


def _maya_focal_length():
    """Focal length (mm) of the active viewport camera, or None. MAIN THREAD."""
    try:
        cam = _active_camera()
        shapes = (cmds.ls(cam, type="camera")
                  or cmds.listRelatives(cam, shapes=True, type="camera") or [])
        shape = shapes[0] if shapes else cam
        return float(cmds.getAttr(shape + ".focalLength"))
    except Exception:
        return None


def _render_one(cam: str):
    """Render the current frame through the CURRENT renderer into the Maya
    Render View, respecting the scene's Render Settings. Uses the renderer's
    native command so the result matches a real render (not the legacy quick
    `cmds.render`, which ignores Arnold shaders/lights -> flat clay look)."""
    renderer = cmds.getAttr("defaultRenderGlobals.currentRenderer")
    w, h = CONFIG.REF_WIDTH, CONFIG.REF_HEIGHT
    if renderer == "arnold":
        if not cmds.pluginInfo("mtoa", q=True, loaded=True):
            cmds.loadPlugin("mtoa", quiet=True)
        # arnoldRender does a full-quality Arnold render of the current frame to
        # the Render View, honoring Render Settings (AA samples, lights, shaders).
        cmds.arnoldRender(camera=cam, width=w, height=h)
        return
    if renderer in ("vray",):
        try:
            cmds.vrend(camera=cam)          # V-Ray's render-to-VFB command
            return
        except Exception:
            pass
    if renderer in ("redshift",):
        try:
            cmds.rsRender(render=True, camera=cam, width=w, height=h)
            return
        except Exception:
            pass
    cmds.render(cam, x=w, y=h)              # generic / Maya Software fallback


def _images_rule_dir() -> str:
    """The Maya 'images' file-rule directory (parent of our byteplus subfolder).
    Arnold's imageFilePrefix is relative to this."""
    root = cmds.workspace(q=True, fullName=True) or os.path.expanduser("~")
    try:
        loc = cmds.workspace(fileRuleEntry="images") or "images"
    except Exception:
        loc = "images"
    return loc if os.path.isabs(loc) else os.path.join(root, loc)


def _arnold_render_to_file(frame: int, img_dir: str, cam: str) -> str:
    """Batch-render ONE Arnold frame straight to an 8-bit JPEG through Arnold's
    OUTPUT DRIVER, so the Imager stack (tonemap, lens effects, color grade...) and
    the output/display transform are BAKED into the file -- matching the Arnold
    RenderView, not the raw (dark) legacy Render View buffer.

    Restores every render-setting it touches. Raises on any problem so the caller
    can fall back to the Render View capture."""
    if not cmds.pluginInfo("mtoa", q=True, loaded=True):
        cmds.loadPlugin("mtoa", quiet=True)
    w, h = CONFIG.REF_WIDTH, CONFIG.REF_HEIGHT
    stem = "{}_ref_f{:04d}".format(_scene_tag(), int(frame))
    rel = os.path.relpath(os.path.join(img_dir, stem),
                          _images_rule_dir()).replace("\\", "/")

    touch = ("defaultArnoldDriver.aiTranslator",
             "defaultArnoldDriver.colorManagement",
             "defaultRenderGlobals.imageFilePrefix",
             "defaultRenderGlobals.animation",
             "defaultRenderGlobals.useFrameExt",
             "defaultRenderGlobals.outFormatControl")
    saved = {}
    for a in touch:
        try:
            saved[a] = cmds.getAttr(a)
        except Exception:
            saved[a] = None

    try:
        cmds.setAttr("defaultArnoldDriver.aiTranslator", "jpeg", type="string")
        try:
            # Color Space = "Use View Transform" (enum 1): bake the SAME view
            # transform the Arnold RenderView shows (e.g. sRGB gamma legacy), so
            # the file matches the display. Enum 2 ("Use Output Transform") used a
            # different transform and crushed the shadows.
            cmds.setAttr("defaultArnoldDriver.colorManagement", 1)
        except Exception:
            pass
        cmds.setAttr("defaultRenderGlobals.imageFilePrefix", rel, type="string")
        try:
            cmds.setAttr("defaultRenderGlobals.animation", 0)
            cmds.setAttr("defaultRenderGlobals.useFrameExt", 0)
        except Exception:
            pass
        # batch=True writes the frame to disk through the driver (imagers baked).
        cmds.arnoldRender(batch=True, camera=cam, width=w, height=h)
    finally:
        for a, v in saved.items():
            if v is None:
                continue
            try:
                if isinstance(v, str):
                    cmds.setAttr(a, v, type="string")
                else:
                    cmds.setAttr(a, v)
            except Exception:
                pass

    import glob as _glob
    cands = _glob.glob(os.path.join(img_dir, stem + ".*")) or \
        _glob.glob(os.path.join(img_dir, "**", stem + ".*"), recursive=True)
    cands = [c for c in cands
             if not c.endswith(".url") and os.path.exists(c)
             and os.path.getsize(c) > 0]
    if not cands:
        raise RuntimeError("Arnold batch render produced no file for " + stem)
    return sorted(cands, key=os.path.getmtime)[-1]


def _render_frame(frame: int, img_dir: str) -> str:
    """Render ONE frame with the CURRENT renderer at the reference resolution and
    save it as an 8-bit image. Returns the path. This is the 'real render look'
    input for Seedance.

    Arnold: render to FILE via the output driver so Imagers + output transform are
    baked in (the legacy Render View buffer is raw/dark). If that fails, or for
    other renderers, fall back to capturing the Render View buffer (8-bit display
    data, which also dodges Arnold's EXR/float driver -> UnsupportedImageFormat)."""
    cmds.currentTime(frame, edit=True)
    cam = _active_camera()

    if cmds.getAttr("defaultRenderGlobals.currentRenderer") == "arnold":
        try:
            return _arnold_render_to_file(frame, img_dir, cam)
        except Exception as e:
            sys.stderr.write("[BYTEPLUS] Arnold render-to-file failed ({}); "
                             "falling back to Render View capture.\n".format(e))

    _render_one(cam)                        # -> Maya Render View (real renderer)

    # Color management: when on, bake the artist's display/view transform into
    # the saved JPG so it matches the viewport. Maya applies the active OCIO
    # config (incl. custom view transforms / LUTs) to the Render View, so a
    # color-managed writeImage inherits it. Toggle off to save the raw buffer.
    if CONFIG.COLOR_MANAGE:
        try:
            if cmds.colorManagementPrefs(q=True, cmEnabled=True):
                # CM is on -> ensure the Render View save bakes the display
                # transform. (Don't force-enable CM if the artist turned it off.)
                cmds.renderWindowEditor("renderView", edit=True, colorManage=True)
        except Exception as e:                  # build w/o the flag -> writeImage default
            sys.stderr.write("[BYTEPLUS] color-manage note: {}\n".format(e))

    base = _unique_path(img_dir, "byteplus_ref_f{:04d}".format(int(frame)), ext="")
    prev_fmt = cmds.getAttr("defaultRenderGlobals.imageFormat")
    try:
        cmds.setAttr("defaultRenderGlobals.imageFormat", 8)    # 8 = JPEG
        # writeImage saves the Render View; with JPEG format it appends '.jpg'.
        cmds.renderWindowEditor("renderView", edit=True, writeImage=base)
    finally:
        cmds.setAttr("defaultRenderGlobals.imageFormat", prev_fmt)

    for cand in (base + ".jpg", base + ".jpeg", base):
        if os.path.exists(cand) and os.path.getsize(cand) > 0:
            return cand
    raise RuntimeError(
        "Could not save frame {} as JPG -- the Render View buffer was empty "
        "after rendering. Check that '{}' rendered to the Render View.".format(
            frame, cmds.getAttr("defaultRenderGlobals.currentRenderer")))


# Viewport display types hidden during a capture so the model sees clean
# polygons only (no gizmos / grid / locators / NURBS / lights confusing it).
_PB_HIDE = (
    "nurbsCurves", "nurbsSurfaces", "cv", "hulls", "controlVertices",
    "subdivSurfaces", "planes", "lights", "cameras", "imagePlane", "joints",
    "ikHandles", "deformers", "dynamics", "fluids", "hairSystems", "follicles",
    "nCloths", "nParticles", "nRigids", "dynamicConstraints", "locators",
    "dimensions", "handles", "pivots", "strokes", "motionTrails", "grid",
    "manipulators", "greasePencils", "pluginShapes", "clipGhosts",
)


def _active_model_panel():
    """The model editor playblast will use (so we can configure its display)."""
    try:
        return cmds.playblast(activeEditor=True)
    except Exception:
        return None


def _isolate_polys(panel):
    """Hide everything but polymeshes for a clean reference capture. Returns the
    saved state to restore afterwards (so the artist's viewport is untouched)."""
    saved = {}
    if not panel:
        return saved
    for flag in _PB_HIDE + ("polymeshes",):
        try:
            saved[flag] = cmds.modelEditor(panel, q=True, **{flag: True})
        except Exception:
            continue
        try:
            cmds.modelEditor(panel, e=True, **{flag: (flag == "polymeshes")})
        except Exception:
            saved.pop(flag, None)
    return saved


def _restore_panel(panel, saved):
    if not panel:
        return
    for flag, val in saved.items():
        try:
            cmds.modelEditor(panel, e=True, **{flag: val})
        except Exception:
            pass


def _playblast_frame(frame: int) -> str:
    """Render a single 720p still of the active viewport at `frame` (polys only)."""
    out = _tmp(".png")
    base = out[:-4]  # playblast appends frame numbers; strip ext
    panel = _active_model_panel()
    saved = _isolate_polys(panel)
    try:
        cmds.currentTime(frame, edit=True)
        cmds.playblast(
            frame=frame, format="image", compression="png",
            completeFilename=out, widthHeight=(CONFIG.REF_WIDTH, CONFIG.REF_HEIGHT),
            showOrnaments=False, percent=100, quality=100, viewer=False,
            # offScreen=True hard-crashes Maya on some Windows GPUs/drivers; use
            # on-screen capture there (nothing overlaps the viewport at this point).
            offScreen=not sys.platform.startswith("win"),
        )
    finally:
        _restore_panel(panel, saved)
    return out if os.path.exists(out) else base + ".{}.png".format(frame)


_IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".webp": "image/webp"}


def _image_mime(path: str) -> str:
    return _IMAGE_MIME.get(os.path.splitext(path)[1].lower(), "image/png")


def _playblast_formats() -> list:
    """Platform-appropriate (format, compression, ext) playblast attempts.
    Maya 2027 on macOS only offers avfoundation / webm (no 'qt')."""
    if sys.platform == "darwin":
        return [("avfoundation", "H.264", ".mov"), ("webm", "VP9", ".webm")]
    if sys.platform.startswith("win"):
        return [("qt", "H.264", ".mov"), ("avi", None, ".avi")]
    return [("qt", "H.264", ".mov"), ("webm", "VP9", ".webm"), ("avi", None, ".avi")]


def _ffmpeg_exe():
    """Locate an ffmpeg executable (BYTEPLUS_FFMPEG env, PATH, common Windows
    install dirs). Returns the path/name to run, or None if not found."""
    import shutil, glob
    cand = os.environ.get("BYTEPLUS_FFMPEG")
    if cand and os.path.exists(cand):
        return cand
    # Bundled with the plugin module (shipped builds): <module>/bin/<plat>/ffmpeg
    here = os.path.dirname(os.path.abspath(__file__))
    exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    sub = ("win" if sys.platform.startswith("win")
           else "mac" if sys.platform == "darwin" else "linux")
    for b in (os.path.join(here, "..", "bin", sub, exe),
              os.path.join(here, "bin", sub, exe)):
        b = os.path.normpath(b)
        if os.path.exists(b):
            return b
    found = shutil.which("ffmpeg")               # works after a PATH refresh
    if found:
        return found
    if sys.platform.startswith("win"):
        guesses = [r"C:\ffmpeg\bin\ffmpeg.exe",
                   os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
                   os.path.expandvars(r"%ProgramData%\chocolatey\bin\ffmpeg.exe")]
        # winget installs Gyan.FFmpeg under a versioned Packages dir and does not
        # always shim it into Links -> find it directly, no shell restart needed.
        guesses += glob.glob(os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\**\ffmpeg.exe"),
            recursive=True)
        for p in guesses:
            if p and os.path.exists(p):
                return p
    return None


def _ffmpeg_h264_encoder(ff: str) -> str:
    """Which H.264 encoder this ffmpeg has: 'x264' (best; full/GPL builds and the
    user's own ffmpeg) or 'openh264' (BSD/LGPL; what the bundled build ships, as
    the LGPL build excludes the GPL x264). x264 preferred when both exist."""
    out = ""
    try:
        import subprocess
        kw = dict(capture_output=True, text=True)
        if sys.platform.startswith("win"):
            kw["creationflags"] = 0x08000000
        out = subprocess.run([ff, "-hide_banner", "-encoders"], **kw).stdout or ""
    except Exception:
        pass
    if "libx264" in out:
        return "x264"
    if "libopenh264" in out:
        return "openh264"
    return "x264"


def _ensure_seedance_video(path: str) -> str:
    """Make a playblast safe for Seedance's `reference_video`: it must be MP4/MOV
    (H.264) AND <= 200MB. Windows playblast can only emit AVI (no QuickTime since
    Apple dropped it) and the raw file is huge (300MB+), so Seedance rejects it
    on either format ('video format ... not valid') or size ('video size ...
    must be <= 209715200'). Transcode to H.264 MP4 with ffmpeg, escalating
    compression until it fits under the cap. Raises if ffmpeg is absent or it
    still won't fit, so the caller can surface a clear message."""
    MAX_BYTES = 200 * 1024 * 1024                    # Seedance r2v hard limit
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mp4", ".mov") and 0 < os.path.getsize(path) <= MAX_BYTES:
        return path                                  # already fine, no re-encode
    ff = _ffmpeg_exe()
    if not ff:
        raise RuntimeError(
            "Playblast is '{}' but Seedance needs MP4/MOV (H.264), and ffmpeg "
            "was not found to convert it. Install ffmpeg (winget install "
            "Gyan.FFmpeg).".format(ext or "an unsupported format"))
    out = os.path.splitext(path)[0] + "_sd.mp4"      # distinct from any .mp4 src
    import subprocess
    kw = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000             # CREATE_NO_WINDOW (no flash)
    # Escalating quality->size passes so even a full 15s range lands under 200MB.
    # CRITICAL: Seedance's reference_video requires fps in [24, 60] and total
    # pixels in [409600, 8295044], so every pass KEEPS fps=24 and never scales
    # below 960 wide (960x540 = 518400 px). Earlier passes dropped to 16/12 fps
    # and 640x360 (230400 px) -- both invalid, which made Seedance reject/ignore
    # the motion reference. Prefer libx264 (best); fall back to libopenh264
    # (BSD/LGPL) which the bundled build ships (the LGPL build has no x264).
    if _ffmpeg_h264_encoder(ff) == "openh264":       # bitrate-based (no -crf)
        passes = [(["-c:v", "libopenh264", "-b:v", "6M"], "fps=24"),
                  (["-c:v", "libopenh264", "-b:v", "3M"], "scale=1280:-2,fps=24"),
                  (["-c:v", "libopenh264", "-b:v", "1500k"], "scale=960:-2,fps=24")]
    else:                                            # CRF-based (libx264)
        passes = [(["-c:v", "libx264", "-crf", "23", "-preset", "veryfast"], "fps=24"),
                  (["-c:v", "libx264", "-crf", "28", "-preset", "veryfast"], "scale=1280:-2,fps=24"),
                  (["-c:v", "libx264", "-crf", "32", "-preset", "veryfast"], "scale=960:-2,fps=24")]
    # Defensive: only if the source dimensions are OUTSIDE Seedance's ref-video
    # range (each side [300,6000], total pixels [409600, 8295044]) -- e.g. a
    # non-default REF_WIDTH/HEIGHT -- force a valid target for every pass. For a
    # valid source (the default 1280x720) this is a no-op and the passes above
    # are used unchanged.
    dims = _probe_video_dims(path)
    tgt = _seedance_valid_dims(*dims) if dims else None
    if tgt:
        sys.stderr.write("[BYTEPLUS] playblast {}x{} is outside Seedance's size "
                         "limits; rescaling to {}x{}.\n".format(
                             dims[0], dims[1], tgt[0], tgt[1]))
        force = "scale={}:{},fps=24".format(tgt[0], tgt[1])
        passes = [(vargs, force) for (vargs, _vf) in passes]
    common = ["-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart"]
    last = None
    for vargs, vf in passes:
        cmd = [ff, "-y", "-i", path, "-vf", vf] + vargs + common + [out]
        try:
            subprocess.run(cmd, **kw)
        except Exception as e:
            last = e
            continue
        if os.path.exists(out) and 0 < os.path.getsize(out) <= MAX_BYTES:
            mb = os.path.getsize(out) / (1024 * 1024)
            sys.stderr.write("[BYTEPLUS] transcoded playblast {} -> MP4 H.264 "
                             "({:.0f} MB).\n".format(ext or "?", mb))
            try:
                os.remove(path)                      # drop the bulky source file
            except Exception:
                pass
            return out
    raise RuntimeError(
        "Could not get the playblast under Seedance's 200MB limit even after "
        "compression (last error: {}). Try a shorter frame range.".format(last))


def _ffprobe_exe():
    """Locate ffprobe next to ffmpeg (same dir), else on PATH. May be absent in
    the bundled LGPL build -- callers fall back to parsing ffmpeg's banner."""
    import shutil
    ff = _ffmpeg_exe()
    if ff:
        d, b = os.path.split(ff)
        cand = os.path.join(d, b.replace("ffmpeg", "ffprobe"))
        if cand != ff and os.path.exists(cand):
            return cand
    return shutil.which("ffprobe")


def _video_duration(path: str):
    """Best-effort clip duration in seconds (float), or None. Tries ffprobe, then
    parses ffmpeg's -i banner. NETWORK-free; spawns a quick subprocess."""
    import subprocess, re
    kw = dict(capture_output=True, text=True)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000             # CREATE_NO_WINDOW (no flash)
    fp = _ffprobe_exe()
    if fp:
        try:
            out = subprocess.run(
                [fp, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path], **kw).stdout
            d = float((out or "").strip())
            if d > 0:
                return d
        except Exception:
            pass
    ff = _ffmpeg_exe()
    if ff:
        try:
            r = subprocess.run([ff, "-i", path], **kw)
            txt = (r.stderr or "") + (r.stdout or "")
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", txt)
            if m:
                h, mn, s = m.groups()
                return int(h) * 3600 + int(mn) * 60 + float(s)
        except Exception:
            pass
    return None


def _probe_video_dims(path: str):
    """(width, height) of a video's first video stream, or None. Tries ffprobe,
    then parses ffmpeg's banner. (Named distinctly from _video_dims(resolution,
    ratio), which returns Seedance cost dimensions -- do not merge them.)"""
    import subprocess, re
    kw = dict(capture_output=True, text=True)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000
    fp = _ffprobe_exe()
    if fp:
        try:
            out = subprocess.run(
                [fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=p=0:s=x", path], **kw).stdout
            m = re.search(r"(\d+)x(\d+)", out or "")
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    ff = _ffmpeg_exe()
    if ff:
        try:
            r = subprocess.run([ff, "-i", path], **kw)
            txt = (r.stderr or "") + (r.stdout or "")
            m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", txt)
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    return None


def _seedance_valid_dims(w: int, h: int):
    """Even (tw, th) that satisfy Seedance's reference_video limits (each side in
    [300, 6000], total pixels in [409600, 8295044]) while preserving aspect, or
    None if (w, h) is already valid. Best-effort for pathological aspect ratios."""
    import math
    MINP, MAXP, MIND, MAXD = 409600, 8295044, 300, 6000
    if (MINP <= w * h <= MAXP) and (MIND <= w <= MAXD) and (MIND <= h <= MAXD):
        return None                              # already valid -> no rescale
    s = 1.0
    if w * h < MINP:
        s = math.sqrt(MINP / float(w * h)) * 1.05
    elif w * h > MAXP:
        s = math.sqrt(MAXP / float(w * h)) * 0.98
    tw = min(MAXD, max(MIND, w * s))
    th = min(MAXD, max(MIND, h * s))
    tw = max(2, int(round(tw / 2)) * 2)          # even, ffmpeg-friendly
    th = max(2, int(round(th / 2)) * 2)
    return (tw, th)


def _extract_video_frames(video_path: str, out_dir: str, n: int = 3) -> list:
    """Grab up to n evenly-spaced JPG frames from a clip so the prompt writer can
    'see' it. Returns the frame paths (possibly fewer than n, or [] if ffmpeg is
    missing). Best-effort -- never raises."""
    ff = _ffmpeg_exe()
    if not ff:
        return []
    import subprocess
    kw = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000
    dur = _video_duration(video_path)
    if dur and dur > 0:
        times = [dur * (i + 0.5) / n for i in range(n)]   # centred, evenly spaced
    else:                                            # unknown length: first seconds
        times = [float(i) for i in range(n)]
    out = []
    for i, t in enumerate(times):
        dst = os.path.join(out_dir, "vframe_{}.jpg".format(i))
        cmd = [ff, "-y", "-ss", "{:.3f}".format(t), "-i", video_path,
               "-frames:v", "1", "-q:v", "3", dst]
        try:
            subprocess.run(cmd, check=True, **kw)
        except Exception:
            continue
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            out.append(dst)
    return out


def _extract_poster_frame(video_path: str, poster_path: str) -> bool:
    """Extract one representative frame (the video midpoint) from `video_path` into
    `poster_path` (JPG), so a Video Gallery thumbnail shows the actual result, not
    the source image. Writes a '<poster>.vframe' marker on success so the one-time
    retrofit doesn't redo it. Returns True on success. Best-effort -- never raises."""
    ff = _ffmpeg_exe()
    if not ff:
        return False
    import subprocess
    kw = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000
    dur = _video_duration(video_path)
    t = (dur * 0.5) if (dur and dur > 0) else 0.0    # midpoint avoids a black intro
    cmd = [ff, "-y", "-ss", "{:.3f}".format(t), "-i", video_path,
           "-frames:v", "1", "-q:v", "3", poster_path]
    try:
        subprocess.run(cmd, check=True, **kw)
    except Exception:
        return False
    if os.path.exists(poster_path) and os.path.getsize(poster_path) > 0:
        try:
            with open(poster_path + ".vframe", "w") as f:
                f.write("1")
        except OSError:
            pass
        return True
    return False


def _fit_video_seconds(path: str, target: int) -> str:
    """Retime a clip to EXACTLY `target` seconds (all frames kept, forced to 24fps)
    so a Seedance reference video matches the requested output duration. A mismatch
    (e.g. a 4.3s playblast against a 4s output) makes Seedance time-warp the motion
    and drift from the animation. Returns the retimed MP4 path, or the original path
    if no retime is needed or ffmpeg is unavailable. Best-effort -- never raises."""
    target = int(target)
    if target <= 0:
        return path
    dur = _video_duration(path)
    if not dur or dur <= 0:
        return path
    if abs(dur - target) < 0.08:                 # already matches (within ~2 frames)
        return path
    ff = _ffmpeg_exe()
    if not ff:
        sys.stderr.write("[BYTEPLUS] playblast is {:.2f}s but the output is {}s and "
                         "ffmpeg is missing to retime it -- motion may drift.\n"
                         .format(dur, target))
        return path
    factor = float(target) / float(dur)          # >1 slows down, <1 speeds up
    out = os.path.splitext(path)[0] + "_fit{}.mp4".format(target)
    import subprocess
    kw = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000
    venc = (["-c:v", "libopenh264", "-b:v", "6M"]
            if _ffmpeg_h264_encoder(ff) == "openh264"
            else ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast"])
    cmd = ([ff, "-y", "-i", path, "-filter:v", "setpts={:.6f}*PTS".format(factor),
            "-r", "24", "-an", "-t", str(target)]
           + venc + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
    try:
        subprocess.run(cmd, **kw)
    except Exception as e:
        sys.stderr.write("[BYTEPLUS] retime failed ({}); using the original "
                         "playblast.\n".format(e))
        return path
    if os.path.exists(out) and os.path.getsize(out) > 0:
        sys.stderr.write("[BYTEPLUS] retimed playblast {:.2f}s -> {}s to match the "
                         "output duration (faithful motion).\n".format(dur, target))
        return out
    return path


def _has_audio_stream(path: str) -> bool:
    """True if the file has at least one audio stream. Best-effort (ffprobe, else
    ffmpeg banner); False on any error or if ffmpeg is unavailable."""
    import subprocess
    kw = dict(capture_output=True, text=True)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000
    fp = _ffprobe_exe()
    if fp:
        try:
            out = subprocess.run(
                [fp, "-v", "error", "-select_streams", "a", "-show_entries",
                 "stream=index", "-of", "csv=p=0", path], **kw).stdout
            return bool((out or "").strip())
        except Exception:
            pass
    ff = _ffmpeg_exe()
    if ff:
        try:
            r = subprocess.run([ff, "-i", path], **kw)
            return "Audio:" in ((r.stderr or "") + (r.stdout or ""))
        except Exception:
            pass
    return False


def _mux_audio_from(video_bytes: bytes, source_path: str) -> bytes:
    """Return `video_bytes` (an MP4) with the AUDIO track of `source_path` muxed in
    (the video is copied unchanged). Lets an edited clip keep the ORIGINAL clip's
    soundtrack -- Seedance returns a SILENT edit. Best-effort: returns `video_bytes`
    unchanged if the source has no audio, ffmpeg is missing, or anything fails --
    never raises. `-shortest` guards against a small duration mismatch."""
    ff = _ffmpeg_exe()
    if not ff or not (source_path and os.path.exists(source_path)):
        return video_bytes
    if not _has_audio_stream(source_path):
        return video_bytes
    import tempfile, subprocess, shutil
    tmp = tempfile.mkdtemp(prefix="byteplus_mux_")
    vin = os.path.join(tmp, "edited.mp4")
    out = os.path.join(tmp, "muxed.mp4")
    kw = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if sys.platform.startswith("win"):
        kw["creationflags"] = 0x08000000
    try:
        with open(vin, "wb") as f:
            f.write(video_bytes)
        cmd = [ff, "-y", "-i", vin, "-i", source_path,
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
               "-c:a", "aac", "-b:a", "192k", "-shortest",
               "-movflags", "+faststart", out]
        subprocess.run(cmd, **kw)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            with open(out, "rb") as f:
                data = f.read()
            sys.stderr.write("[BYTEPLUS] restored the source clip's audio into the "
                             "edited video.\n")
            return data
    except Exception as e:
        sys.stderr.write("[BYTEPLUS] audio mux failed ({}); keeping the silent "
                         "edit.\n".format(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return video_bytes


def _playblast_is_valid(path: str, expected_seconds: float) -> bool:
    """True if a captured playblast looks usable: a real, non-empty file whose
    duration is close to the animation length. Catches empty / truncated captures
    (e.g. the Windows 'only a few frames' glitch) so the caller can retry. Never
    raises; on a validation hiccup it returns True (don't block a good capture)."""
    try:
        if not (path and os.path.exists(path) and os.path.getsize(path) > 0):
            return False
        if expected_seconds and expected_seconds > 0:
            d = _video_duration(path)
            if d is not None and d > 0:
                return d >= max(1.0, expected_seconds * 0.6)   # generous tolerance
        return True
    except Exception:
        return True


def _playblast_movie(start=None, end=None) -> str:
    """Playblast the animation range to a movie used as Seedance's video reference.
    Saved into the project movies/ folder (persisted) and validated non-empty.
    Tries platform-appropriate formats and trusts playblast's return path.

    The range is captured EXPLICITLY via startTime/endTime (defaulting to
    _anim_range()) so it always matches the duration the caller computed from the
    same range. Without this, a collapsed time-slider makes playblast capture only
    a frame or two while the duration is computed from the full scene range -- the
    capture then looks 'failed' even though the checkbox was on. Also settles the
    viewport at the first frame first (fixes the Windows 'only a few frames'
    glitch) and restores the artist's current frame afterwards."""
    if start is None or end is None:
        start, end = _anim_range()
    out_dir = _project_movies_dir()
    base = os.path.join(out_dir, "byteplus_playblast_{}".format(int(time.time() * 1000)))
    panel = _active_model_panel()
    saved = _isolate_polys(panel)                    # polys only -> clean motion ref
    try:
        _t0 = cmds.currentTime(q=True)
    except Exception:
        _t0 = None
    last_err = None
    try:
        try:                                         # settle the viewport first
            cmds.currentTime(start)
            cmds.refresh(force=True)
        except Exception:
            pass
        for fmt, comp, ext in _playblast_formats():
            kwargs = dict(
                format=fmt, filename=base, startTime=start, endTime=end,
                widthHeight=(CONFIG.REF_WIDTH, CONFIG.REF_HEIGHT), forceOverwrite=True,
                showOrnaments=False, percent=100, quality=100, viewer=False,
                # off-screen is unreliable on macOS and hard-crashes some Windows
                # GPUs/drivers -> only use it on Linux.
                offScreen=(sys.platform != "darwin"
                           and not sys.platform.startswith("win")),
            )
            if comp:
                kwargs["compression"] = comp
            try:
                result = cmds.playblast(**kwargs)
            except Exception as e:
                last_err = e
                continue
            for cand in ([result] if result else []) + [base + ext]:
                if cand and os.path.exists(cand) and os.path.getsize(cand) > 0:
                    return _ensure_seedance_video(cand)   # -> MP4 (H.264) for Seedance
    finally:
        _restore_panel(panel, saved)
        if _t0 is not None:                          # leave the artist's frame as it was
            try:
                cmds.currentTime(_t0)
            except Exception:
                pass
    raise RuntimeError(
        "Playblast produced no usable movie (tried {}). Last error: {}. The "
        "image references will still work without it.".format(
            [f for f, _, _ in _playblast_formats()], last_err))


def _viewport_snapshot() -> str:
    """Grab a single PNG of what the artist is currently looking at."""
    return _playblast_frame(int(cmds.currentTime(q=True)))


# =============================================================================
# Preview window with Save As  (NON-NEGOTIABLE requirement)
# =============================================================================
class PreviewWindow(QtWidgets.QDialog):
    """Shows an image or video result with a Save As button. Reused by both
    Seedream and Seedance flows."""

    def __init__(self, title, payload, kind="image", parent=None,
                 on_animate=None, animate_arg=None):
        super().__init__(parent or _main_window())
        self._payload = payload          # bytes (image) or local path (video)
        self._kind = kind
        self._on_animate = on_animate    # callback(animate_arg) for "Animate ->"
        self._animate_arg = animate_arg  # what to hand the callback (a URL/path)
        self.setWindowTitle("BYTEPLUS  -  " + title)
        self.setMinimumSize(640, 520)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)  # stay above Maya

        layout = QtWidgets.QVBoxLayout(self)
        self._view = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self._view.setStyleSheet("background:#1d1d1d;")
        layout.addWidget(self._view, 1)

        if kind == "image":
            pix = QtGui.QPixmap()
            pix.loadFromData(payload)
            self._view.setPixmap(
                pix.scaled(960, 960, QtCore.Qt.KeepAspectRatio,
                           QtCore.Qt.SmoothTransformation))
        else:
            self._view.setText(
                "Video ready:\n{}\n\n(Use Save As, or Open to play.)".format(payload))

        row = QtWidgets.QHBoxLayout()
        save = QtWidgets.QPushButton("Save As...")
        save.clicked.connect(self._save_as)
        row.addWidget(save)
        if kind == "video":
            opn = QtWidgets.QPushButton("Open")
            opn.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(payload)))
            row.addWidget(opn)
        if kind == "image" and on_animate:
            anim = QtWidgets.QPushButton("Animate with Seedance →")
            anim.setToolTip("Use this image + a playblast of the scene as "
                            "references to generate a video with Seedance 2.0")
            anim.clicked.connect(self._animate)
            row.addWidget(anim)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)

    def _animate(self):
        arg = self._animate_arg if self._animate_arg is not None else self._payload
        self.accept()                    # close preview, then kick off Seedance
        self._on_animate(arg)

    def _save_as(self):
        if self._kind == "image":
            flt, default = "PNG (*.png);;JPEG (*.jpg)", "seedream_result.png"
        else:
            flt, default = "MP4 video (*.mp4);;QuickTime (*.mov)", "seedance_result.mp4"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save As", default, flt)
        if not path:
            return
        if self._kind == "image":
            with open(path, "wb") as f:
                f.write(self._payload)
        else:
            import shutil
            shutil.copyfile(self._payload, path)
        cmds.inViewMessage(amg="Saved <hl>{}</hl>".format(path), pos="midCenter", fade=True)


class _Cancelled(Exception):
    """Raised inside a worker when the user cancels its job."""


# Per-worker cancel token, exposed to the running fn via a thread-local so the
# generation helpers can check it WITHOUT every call signature changing.
_CANCEL_TLS = threading.local()


def _current_cancel():
    """The cancel Event for the job running on THIS thread (or None)."""
    return getattr(_CANCEL_TLS, "event", None)


def _cancel_requested() -> bool:
    ev = _current_cancel()
    return ev is not None and ev.is_set()


class _ActivityHUD(QtWidgets.QDialog):
    """One compact panel (bottom-right of Maya) that summarizes ALL running
    BYTEPLUS jobs: a busy bar + 'N jobs · <latest>' header + one row per job with
    its own ✕ to cancel. Replaces per-job progress dialogs so concurrent jobs
    never stack over the viewport. (QDialog + the same frameless/stay-on-top
    flags the old per-job progress dialog used -- a proven, stable pattern.)"""
    _inst = None

    @classmethod
    def instance(cls):
        if cls._inst is None:
            try:
                cls._inst = cls(_main_window())
            except Exception:
                cls._inst = cls(None)
        return cls._inst

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setFixedWidth(360)
        self._jobs = []                                      # list[_ProgressHandle]
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10); v.setSpacing(7)
        self._header = QtWidgets.QLabel()
        self._header.setStyleSheet("color:#fff; font-weight:bold;")
        self._header.setWordWrap(True)
        v.addWidget(self._header)
        self._bar = QtWidgets.QProgressBar()
        self._bar.setRange(0, 0)                             # busy / indeterminate
        self._bar.setTextVisible(False); self._bar.setFixedHeight(6)
        v.addWidget(self._bar)
        self._rows = QtWidgets.QVBoxLayout(); self._rows.setSpacing(3)
        v.addLayout(self._rows)
        self.setStyleSheet("QWidget{background:#2b2b2b;} "
                           "QLabel{background:transparent;}")

    def add(self, handle):
        self._jobs.append(handle)
        row = QtWidgets.QWidget()
        hl = QtWidgets.QHBoxLayout(row); hl.setContentsMargins(0, 0, 0, 0)
        lbl = QtWidgets.QLabel(handle._title)
        lbl.setStyleSheet("color:#cfcfcf;")
        x = QtWidgets.QPushButton("✕"); x.setFixedSize(22, 22)
        x.setToolTip("Cancel this job")
        x.clicked.connect(handle.cancel_now)
        hl.addWidget(lbl, 1); hl.addWidget(x)
        handle._row = row; handle._lbl = lbl
        self._rows.addWidget(row)
        self._refresh(); self.show(); self._reposition()

    def remove(self, handle):
        if handle in self._jobs:
            self._jobs.remove(handle)
        row = getattr(handle, "_row", None)
        if row is not None:
            row.setParent(None); row.deleteLater(); handle._row = None
        if not self._jobs:
            self.hide()
        else:
            self._refresh(); self._reposition()

    def _refresh(self):
        n = len(self._jobs)
        latest = self._jobs[-1]._title if self._jobs else ""
        self._header.setText("BYTEPLUS — {} job{} · {}".format(
            n, "s" if n != 1 else "", latest))

    def _reposition(self):
        try:
            g = _main_window().frameGeometry()
            self.adjustSize()
            x = g.x() + g.width() - self.width() - 24
            y = g.y() + g.height() - self.height() - 120     # above the timeline
            self.move(x, y)
        except Exception:
            pass


class _ProgressHandle:
    """Returned by _progress(). Emulates the slice of QProgressDialog the callers
    use (.show() / .hide() / .close() / .setLabelText()), but renders as ONE row
    in the shared HUD. Carries a cancel Event shared with its worker(s)."""

    def __init__(self, title):
        self._title = title
        self.cancel = threading.Event()
        self.worker = None
        self._row = None
        self._lbl = None
        self._closed = False
        _ActivityHUD.instance().add(self)

    def setLabelText(self, text):
        self._title = text
        if self._lbl is not None:
            try:
                self._lbl.setText(text)
            except RuntimeError:
                pass
        try:
            _ActivityHUD.instance()._refresh()
        except Exception:
            pass

    def show(self):
        """Re-show / raise the shared Activity HUD. Callers use this to bring the
        progress panel back to the front after a modal dialog. Best-effort and a
        no-op once closed -- must never raise (it runs inside generation flows)."""
        if self._closed:
            return
        try:
            hud = _ActivityHUD.instance()
            hud.show()
            hud.raise_()
            hud._reposition()
        except Exception:
            pass

    def hide(self):
        """Temporarily hide the shared Activity HUD so a modal dialog isn't stuck
        behind it (paired with show()). Best-effort -- must never raise."""
        try:
            _ActivityHUD.instance().hide()
        except Exception:
            pass

    def cancel_now(self):
        # User clicked ✕ -> mark cancelled and drop the row immediately ("cancel
        # is cancel"). The worker stops at its next checkpoint: Seedance video
        # DELETEs the server task (frees compute, stops billing); fast image
        # calls discard their result on return.
        self.cancel.set()
        self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        global _PENDING_HANDLE
        if _PENDING_HANDLE is self:
            _PENDING_HANDLE = None
        try:
            _ActivityHUD.instance().remove(self)
        except Exception:
            pass


# The handle a freshly started _Worker binds its cancel token to (set by the
# preceding _progress() call, consumed on the next _Worker.start()).
_PENDING_HANDLE = None


def _progress(title: str) -> "_ProgressHandle":
    """One row in the shared Activity HUD. Returns a handle that emulates the bits
    of QProgressDialog the callers use (.close(), .setLabelText())."""
    global _PENDING_HANDLE
    _mark_active_project()                  # main thread: capture the owning scene
    h = _ProgressHandle(title)
    _PENDING_HANDLE = h                      # next _Worker.start() adopts its token
    return h


def _error(msg: str):
    _msgbox(QtWidgets.QMessageBox.Critical, "BYTEPLUS error", msg,
            QtWidgets.QMessageBox.Ok)


def _dictate_into(widget):
    """Voice dictation via the OS's built-in speech-to-text: focus the prompt
    field and tell the user the dictation shortcut to press. The OS handles the
    microphone and its permissions; we never touch the mic, add no dependencies,
    and there's no API cost.

    The hint is shown as a QToolTip (renders ABOVE the on-top/modal dialog) plus
    a status-line message; an inViewMessage would be hidden behind the dialog."""
    try:
        widget.setFocus(QtCore.Qt.OtherFocusReason)
    except Exception:
        pass
    if sys.platform == "darwin":
        tip = ("Voice dictation — press your macOS Dictation shortcut now "
               "(System&nbsp;Settings ▸ Keyboard ▸ Dictation; default: tap "
               "<b>Control</b> twice), then speak. Text lands in this field.")
        flat = ("Press your macOS Dictation shortcut (default: tap Control "
                "twice) and speak. Enable it in System Settings > Keyboard > "
                "Dictation.")
    elif sys.platform.startswith("win"):
        tip = ("Voice typing — press <b>Win&nbsp;+&nbsp;H</b> now, then speak. "
               "Text lands in this field.")
        flat = "Press Win + H and speak."
    else:
        tip = ("Press your desktop's voice-typing shortcut now, then speak.")
        flat = "Use your desktop's voice-typing shortcut and speak."
    # QToolTip shows on top of dialogs (unlike inViewMessage, which the dialog
    # covers). Anchor it at the cursor.
    try:
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), tip, widget)
    except Exception:
        pass
    try:
        cmds.inViewMessage(amg="\U0001F3A4  " + flat, pos="midCenterTop",
                           fade=True, fadeStayTime=5000)
    except Exception:
        pass


def _add_dictate_button(row, prompt_widget):
    """Append a small 🎤 dictation button to a button `row` (QBoxLayout) that
    feeds the given prompt QPlainTextEdit. Best-effort: if anything goes wrong it
    simply skips the button rather than breaking the dialog."""
    try:
        b = QtWidgets.QPushButton("\U0001F3A4")
        b.setToolTip("Voice input help — focuses this field and shows your OS "
                     "dictation shortcut. It does NOT record; your system's "
                     "dictation types the words for you once you press the "
                     "shortcut and speak.")
        b.setFixedWidth(34)
        b.clicked.connect(lambda: _dictate_into(prompt_widget))
        row.addWidget(b)
        return b
    except Exception:
        return None


def _show_prompt(parent, prompt: str):
    """Read-only viewer for the prompt that generated an item, with a Copy button."""
    if not prompt:
        cmds.inViewMessage(amg="No prompt saved for this item.",
                           pos="midCenter", fade=True)
        return
    dlg = QtWidgets.QDialog(parent or _main_window())
    dlg.setWindowTitle("BYTEPLUS - Prompt used")
    dlg.setMinimumSize(560, 360)
    dlg.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
    v = QtWidgets.QVBoxLayout(dlg)
    v.addWidget(QtWidgets.QLabel("The prompt that generated this result:"))
    te = QtWidgets.QPlainTextEdit(prompt)
    te.setReadOnly(True)
    v.addWidget(te, 1)
    row = QtWidgets.QHBoxLayout()
    b_copy = QtWidgets.QPushButton("Copy")
    b_copy.clicked.connect(lambda: (
        QtWidgets.QApplication.clipboard().setText(prompt),
        cmds.inViewMessage(amg="Prompt copied to clipboard.", pos="midCenter", fade=True)))
    b_close = QtWidgets.QPushButton("Close")
    b_close.clicked.connect(dlg.accept)
    row.addWidget(b_copy)
    row.addStretch(1)
    row.addWidget(b_close)
    v.addLayout(row)
    dlg.exec()


# A small floating "Prompt" button parked over a gallery's preview area.
_OVERLAY_CSS = (
    "QPushButton{background:rgba(15,27,43,170); color:#FFFFFF; "
    "border:1px solid rgba(255,255,255,70); border-radius:6px; "
    "padding:5px 12px; font-size:12px;} "
    "QPushButton:hover{background:rgba(46,139,230,220);}")


def _overlay_button(view, on_click):
    b = QtWidgets.QPushButton("\U0001F4DD Prompt", view)
    b.setStyleSheet(_OVERLAY_CSS)
    b.setCursor(QtCore.Qt.PointingHandCursor)
    b.clicked.connect(on_click)
    b.show()
    return b


def _place_overlay(view, btn, margin=12):
    btn.adjustSize()
    btn.move(max(margin, view.width() - btn.width() - margin), margin)
    btn.raise_()


def _to_pixmap(src):
    """QPixmap from raw bytes or a file path (empty pixmap if neither works)."""
    pix = QtGui.QPixmap()
    if isinstance(src, (bytes, bytearray)):
        pix.loadFromData(bytes(src))
    elif isinstance(src, str) and os.path.exists(src):
        pix.load(src)
    return pix


def _evt_x(e):
    """Mouse-event X, tolerant of Qt5 (e.x()) vs Qt6 (e.position().x())."""
    try:
        return int(e.position().x())
    except Exception:
        return int(e.x())


class _ABCompare(QtWidgets.QWidget):
    """Before/after wipe: image A fills the view, image B is drawn clipped to the
    right of a draggable vertical divider. Drag anywhere to move it."""

    def __init__(self, pix_a, pix_b, label_a="A", label_b="B", parent=None):
        super().__init__(parent)
        self._a = pix_a
        self._b = pix_b
        self._la = label_a
        self._lb = label_b
        self._split = 0.5                            # divider position, 0..1
        self.setMinimumSize(480, 320)
        self.setCursor(QtCore.Qt.SizeHorCursor)

    def set_pixmaps(self, pix_a, pix_b):
        self._a, self._b = pix_a, pix_b
        self.update()

    def _target_rect(self):
        if self._a.isNull():
            return self.rect()
        sz = self._a.size()
        sz.scale(self.size(), QtCore.Qt.KeepAspectRatio)
        x = (self.width() - sz.width()) // 2
        y = (self.height() - sz.height()) // 2
        return QtCore.QRect(x, y, sz.width(), sz.height())

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#111111"))
        tr = self._target_rect()
        if not self._a.isNull():
            p.drawPixmap(tr, self._a)
        splitx = tr.left() + int(tr.width() * self._split)
        if not self._b.isNull():
            p.save()
            p.setClipRect(QtCore.QRect(splitx, tr.top(),
                                       tr.right() - splitx + 1, tr.height()))
            p.drawPixmap(tr, self._b)
            p.restore()
        pen = QtGui.QPen(QtGui.QColor("#ffffff"))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawLine(splitx, tr.top(), splitx, tr.bottom())
        cy = tr.center().y()
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(QtCore.QPoint(splitx, cy), 9, 9)
        f = p.font()
        f.setBold(True)
        f.setPointSize(11)
        p.setFont(f)
        p.setPen(QtGui.QColor("#ffffff"))
        lr = tr.adjusted(8, 6, -8, -8)
        p.drawText(lr, QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft, self._la)
        p.drawText(lr, QtCore.Qt.AlignTop | QtCore.Qt.AlignRight, self._lb)
        p.end()

    def _set_from_x(self, x):
        tr = self._target_rect()
        if tr.width() > 0:
            self._split = min(1.0, max(0.0, (x - tr.left()) / tr.width()))
            self.update()

    def mousePressEvent(self, e):
        self._set_from_x(_evt_x(e))

    def mouseMoveEvent(self, e):
        if e.buttons() & QtCore.Qt.LeftButton:
            self._set_from_x(_evt_x(e))


class ABCompareDialog(QtWidgets.QDialog):
    """A/B compare window: a drag-slider wipe between two images (A and B). Used
    by both galleries (video A/B compares each clip's representative frame)."""

    def __init__(self, src_a, src_b, label_a="A", label_b="B", parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS - Compare A / B")
        self.setMinimumSize(720, 520)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._pa = _to_pixmap(src_a)
        self._pb = _to_pixmap(src_b)
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel(
            "Drag the divider to wipe between A (left) and B (right)."))
        self.cmp = _ABCompare(self._pa, self._pb, label_a, label_b)
        v.addWidget(self.cmp, 1)
        row = QtWidgets.QHBoxLayout()
        b_swap = QtWidgets.QPushButton("⇄ Swap A/B")
        b_swap.setToolTip("Swap which image is on each side.")
        b_swap.clicked.connect(self._swap)
        row.addWidget(b_swap)
        row.addStretch(1)
        b_close = QtWidgets.QPushButton("Close")
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        v.addLayout(row)

    def _swap(self):
        self._pa, self._pb = self._pb, self._pa
        self.cmp.set_pixmaps(self._pa, self._pb)


def _save_video(video_bytes: bytes, poster_src, mov_dir: str, prompt=None):
    """Persist a Seedance video to the project movies/ folder plus a JPG poster
    (the source image / first ref frame). Returns (video_path, poster_path|None)."""
    vid = _unique_path(mov_dir, "{}_video_{}".format(_scene_tag(), int(time.time())),
                       ext=".mp4")
    with open(vid, "wb") as f:
        f.write(video_bytes)
    _write_prompt_sidecar(vid, prompt)               # recall the prompt later
    poster = vid[:-4] + ".jpg"
    # Thumbnail = a REAL frame of the generated video (so the gallery shows the
    # result, not the source image). Fall back to the source image only if ffmpeg
    # is unavailable, so nothing breaks.
    if _extract_poster_frame(vid, poster):
        return vid, poster
    poster = None
    if poster_src and os.path.exists(poster_src):
        poster = vid[:-4] + ".jpg"
        img = QtGui.QImage(poster_src)
        if not img.isNull():
            img.save(poster, "JPG")
        else:
            try:
                import shutil
                shutil.copyfile(poster_src, poster)
            except OSError:
                poster = None
    return vid, poster


class VideoEditDialog(QtWidgets.QDialog):
    """Edit-instruction dialog for 'Edit video' (Seedance 2.0 video-to-video), with
    a ✦ Enhance that reads the clip and writes the full transform prompt."""

    def __init__(self, parent=None, video_path=None, poster=None, default_duration=5):
        super().__init__(parent or _main_window())
        self.setWindowTitle("Edit video — Seedance 2.0")
        self.setMinimumSize(560, 340)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._worker = None
        self._video_path = video_path
        self._poster = poster
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel(
            "Describe the ONE change you want (Seedance 2.0 keeps the source clip — "
            "subject, motion, camera — and transforms only what you name):\n"
            "e.g. 'set his hair on fire', 'swap the background to a desert at sunset', "
            "'turn it into a neon city'.\n"
            "Tip: press ✦ Enhance — it reads your clip and writes the full prompt."))
        self.prompt = QtWidgets.QPlainTextEdit()
        v.addWidget(self.prompt, 1)
        hb = QtWidgets.QHBoxLayout()
        self.b_enhance = QtWidgets.QPushButton("✦ Enhance")
        self.b_enhance.setToolTip("Reads your clip and writes the full Seedance "
                                  "prompt — locks identity, wardrobe and camera, "
                                  "changes only what you asked.")
        self.b_enhance.clicked.connect(self._enhance)
        hb.addWidget(self.b_enhance)
        _add_dictate_button(hb, self.prompt)
        hb.addStretch(1)
        v.addLayout(hb)

        # Seedance output length (4–15s). Default to the source clip's length so
        # the edit matches the original runtime (the skill's default).
        opts = QtWidgets.QHBoxLayout()
        opts.addWidget(QtWidgets.QLabel("Duration:"))
        self.sp_duration = QtWidgets.QSpinBox()
        self.sp_duration.setRange(4, 15)
        self.sp_duration.setSuffix(" s")
        self.sp_duration.setValue(max(4, min(15, int(default_duration or 5))))
        self.sp_duration.setToolTip("Length of the generated clip (Seedance 2.0 "
                                    "supports 4–15s). Defaults to the source clip's "
                                    "length so the edit matches it.")
        opts.addWidget(self.sp_duration)
        opts.addStretch(1)
        v.addLayout(opts)

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def text(self):
        return self.prompt.toPlainText().strip()

    def duration(self):
        return int(self.sp_duration.value())

    def _enhance(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            cmds.inViewMessage(amg="Type a change first, then <hl>✦ Enhance</hl>.",
                               pos="midCenter", fade=True)
            return
        self.b_enhance.setEnabled(False)
        self.b_enhance.setText("Enhancing...")
        self._worker = _Worker(
            lambda: _seedance_edit_prompt_auto(self._video_path, self._poster,
                                               text, self.duration()), parent=self)

        def done(t):
            if t:
                self.prompt.setPlainText(t)          # Ctrl+Z restores the original
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")

        def fail(tb):
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")
            _error("Enhance failed:\n\n" + tb)

        self._worker.done.connect(done)
        self._worker.failed.connect(fail)
        self._worker.start()


class VideoGallery(QtWidgets.QDialog):
    """Holds Seedance videos (this session + previous ones from disk). Poster
    thumbnails + Open-in-player (no embedded decoding). Regenerate-with-comments
    works for videos made this session (their config is in memory)."""

    def __init__(self, mov_dir, parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle(_usage_title("BYTEPLUS - Video Gallery"))
        self.setMinimumSize(760, 660)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._mov_dir = mov_dir
        self._items = []
        self._current = None
        self._worker = None

        v = QtWidgets.QVBoxLayout(self)
        self.view = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self.view.setStyleSheet("background:#1d1d1d; color:#aaa;")
        self.view.setMinimumHeight(380)
        v.addWidget(self.view, 1)
        self._ov = _overlay_button(self.view, self._prompt)   # floating Prompt button
        QtCore.QTimer.singleShot(0, lambda: _place_overlay(self.view, self._ov))

        self.strip = QtWidgets.QListWidget()
        self.strip.setViewMode(QtWidgets.QListView.IconMode)
        self.strip.setFlow(QtWidgets.QListView.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setFixedHeight(118)
        self.strip.setIconSize(QtCore.QSize(160, 90))
        self.strip.setMovement(QtWidgets.QListView.Static)
        self.strip.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.strip.itemClicked.connect(self._on_select)
        self.strip.itemDoubleClicked.connect(lambda _i: self._open())
        v.addWidget(self.strip)

        row = QtWidgets.QHBoxLayout()
        b_open = QtWidgets.QPushButton("▶ Open")
        b_open.clicked.connect(self._open)
        b_refine = QtWidgets.QPushButton("✎ Edit video")
        b_refine.setToolTip(
            "Edit the selected clip with Seedance 2.0 (video-to-video) — keeps the "
            "source subject, motion and camera and transforms only what you ask "
            "for. Press ✦ Enhance in the dialog to auto-write the full prompt.")
        b_refine.clicked.connect(self._regen)
        b_save = QtWidgets.QPushButton("\U0001F4BE Save As...")
        b_save.clicked.connect(self._save)
        b_cmp = QtWidgets.QPushButton("⇄ Compare")
        b_cmp.setToolTip("Select two clips (Ctrl/Shift-click) then Compare — or "
                         "compare the current one against another. Drag slider "
                         "(A/B wipe).")
        b_cmp.clicked.connect(self._compare)
        b_del = QtWidgets.QPushButton("\U0001F5D1 Delete")
        b_del.clicked.connect(self._delete)
        b_clear = QtWidgets.QPushButton("Clear all")
        b_clear.clicked.connect(self._clear_all)
        b_close = QtWidgets.QPushButton("Close")
        b_close.clicked.connect(self.accept)
        for b in (b_open, b_refine, b_save, b_cmp, b_del, b_clear):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_close)
        v.addLayout(row)

        self._load_existing()

    def _load_existing(self):
        import glob
        existing = {it["video"] for it in self._items}
        hidden = _load_hidden()
        for vid in sorted(glob.glob(os.path.join(self._mov_dir, "*video*.mp4"))):
            if vid in existing or vid in hidden:
                continue                       # cleared earlier without disk delete
            poster = vid[:-4] + ".jpg"
            self._add(vid, poster if os.path.exists(poster) else None, None,
                      select=False, prompt=_read_prompt_sidecar(vid))
        if self._items:
            self.strip.setCurrentRow(self.strip.count() - 1)
            self._show(self._items[-1])
        self._retrofit_thumbnails()

    def _retrofit_thumbnails(self):
        """One-time: replace source-image posters with a REAL frame of each video,
        off the UI thread, so the gallery shows the result. Idempotent via a
        '<poster>.jpg.vframe' marker; safe no-op when ffmpeg is missing."""
        specs = [it["video"] for it in self._items
                 if it.get("video") and os.path.exists(it["video"])
                 and not os.path.exists(it["video"][:-4] + ".jpg.vframe")]
        if not specs:
            return

        def work():
            done = []
            for vid in specs:
                if _extract_poster_frame(vid, vid[:-4] + ".jpg"):
                    done.append(vid)
            return done

        def done(updated):
            upd = set(updated or [])
            if not upd:
                return
            for i in range(self.strip.count()):
                lw = self.strip.item(i)
                it = lw.data(QtCore.Qt.UserRole) if lw else None
                if it and it.get("video") in upd:
                    poster = it["video"][:-4] + ".jpg"
                    it["poster"] = poster
                    if os.path.exists(poster):
                        lw.setIcon(QtGui.QIcon(poster))
            if self._current and self._current.get("video") in upd:
                self._show(self._current)            # refresh the big preview too

        self._retro_worker = _Worker(work, parent=self)
        self._retro_worker.done.connect(done)
        self._retro_worker.start()

    def _add(self, video, poster, regen, select=True, prompt=None):
        item = {"video": video, "poster": poster, "regen": regen, "prompt": prompt}
        self._items.append(item)
        icon = QtGui.QIcon(poster) if poster else QtGui.QIcon()
        lw = QtWidgets.QListWidgetItem(icon, "")     # no filename label
        lw.setToolTip(os.path.basename(video))       # name on hover instead
        lw.setData(QtCore.Qt.UserRole, item)
        self.strip.addItem(lw)
        self.setWindowTitle(_usage_title("BYTEPLUS - Video Gallery"))
        if select:
            self.strip.setCurrentItem(lw)
            self._show(item)

    def add_video(self, video, poster, regen, prompt=None):
        self._add(video, poster, regen, select=True, prompt=prompt)

    def _selected_items(self):
        """Selected strip items (their dicts), in row order."""
        out = []
        for i in range(self.strip.count()):
            lw = self.strip.item(i)
            if lw and lw.isSelected():
                out.append(lw.data(QtCore.Qt.UserRole))
        return out

    def _compare(self):
        """A/B wipe between two clips' frames (each clip's poster is a real frame
        of the video). Uses two selected clips if exactly two are selected;
        otherwise compares the current clip against one you pick."""
        sel = self._selected_items()
        if len(sel) == 2:
            a, b = sel[0], sel[1]
        else:
            if not self._current:
                return
            others = [{"path": it.get("poster"), "video": it.get("video")}
                      for it in self._items
                      if it is not self._current and it.get("poster")
                      and os.path.exists(it["poster"])]
            if not others:
                _error("Select two clips (Ctrl/Shift-click), or have a second "
                       "clip in the gallery, to compare.")
                return
            picked = _pick_gallery_image(others, self, warn_trust=False)
            if not picked:
                return
            a, b = self._current, picked
        pa = a.get("poster") or a.get("path")
        pb = b.get("poster") or b.get("path")
        if not (pa and os.path.exists(pa) and pb and os.path.exists(pb)):
            _error("One of the clips has no thumbnail yet — give the gallery a "
                   "moment to extract frames, then try again.")
            return
        ABCompareDialog(pa, pb, "A", "B", parent=self).exec()

    def _prompt(self):
        if self._current:
            _show_prompt(self, self._current.get("prompt"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "_ov", None):
            _place_overlay(self.view, self._ov)

    def _show(self, item):
        self._current = item
        if item.get("poster") and os.path.exists(item["poster"]):
            pix = QtGui.QPixmap(item["poster"])
            self.view.setPixmap(pix.scaled(900, 560, QtCore.Qt.KeepAspectRatio,
                                           QtCore.Qt.SmoothTransformation))
        else:
            self.view.setText("Video ready — press ▶ Open to play.")
        self.view.setToolTip(item["video"])

    def _on_select(self, lw):
        self._show(lw.data(QtCore.Qt.UserRole))

    def _open(self):
        if self._current:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(self._current["video"]))

    def _save(self):
        if not self._current:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save As", "seedance_result.mp4", "MP4 video (*.mp4)")
        if path:
            import shutil
            shutil.copyfile(self._current["video"], path)
            cmds.inViewMessage(amg="Saved <hl>{}</hl>".format(path),
                               pos="midCenter", fade=True)

    def _regen(self):
        """EDIT the selected video (video-to-video) with Seedance 2.0: attach the
        saved clip as the reference video and apply only the user's named change on
        top, keeping the source subject, motion and camera."""
        if not self._current:
            return
        if not _motion_host_ready():
            _error("Editing a clip with Seedance needs the source uploaded as a "
                   "public URL, which requires motion-video hosting (Cloudflare R2 "
                   "or BytePlus TOS).\n\nSet it up in  BYTEPLUS > Settings > Storage "
                   "& Hosting,  then try again.")
            return
        video_path = self._current["video"]
        poster = self._current.get("poster")
        dur0 = _video_duration(video_path)
        default_dur = max(4, min(15, int(round(dur0)) if dur0 else 5))
        d = VideoEditDialog(self, video_path=video_path, poster=poster,
                            default_duration=default_dur)
        if not d.exec():
            return
        comment = d.text()
        if not comment:
            return
        duration = d.duration()

        # Cost guard (an edit always attaches the source as a reference video).
        _tok, _usd = _est_video_cost(CONFIG.VIDEO_RESOLUTION, CONFIG.VIDEO_RATIO,
                                     duration, True)
        if not _confirm_cost(_usd, "Edit video with Seedance -> {} video, {}s.".format(
                CONFIG.VIDEO_RESOLUTION, duration)):
            return

        # If the box already holds a full prompt (Enhance wrote one, or the user
        # pasted a Seedance prompt), send it as-is; otherwise wrap the bare
        # instruction with a lock-down clause so the source is still preserved.
        full = ("Photoreal." in comment) or ("reference video" in comment.lower())
        final_prompt = comment if full else _seedance_edit_wrap(comment)
        # Do NOT send the poster as a reference_image: it's now a frame extracted
        # from the video (a real-looking face) that Seedance flags as a non-trusted
        # real face. The source VIDEO (reference_video) already carries the look and
        # motion for a video-to-video edit, so it is the sole reference.
        ref_img = None

        prog = _progress("Editing video with Seedance 2.0 (keeping the source)...")

        def done(vb):
            prog.close()
            edit_prompt = "Edit: " + comment
            vid, new_poster = _save_video(vb, poster, self._mov_dir, prompt=edit_prompt)
            self._add(vid, new_poster, None, select=True, prompt=edit_prompt)

        def failed(tb):
            prog.close()
            if any(s in tb for s in ("SensitiveContent", "PrivacyInformation",
                                     "real person")):
                _error(
                    "Seedance blocked this clip: it detected a REAL HUMAN FACE.\n\n"
                    "Seedance 2.0 rejects real-person faces as input references "
                    "(privacy / biometric policy) — this is a platform rule, not a "
                    "plugin bug. Editing clips WITHOUT real faces (environments, "
                    "objects, rendered or stylized characters) works normally.\n\n"
                    "Real-person footage needs enterprise verification / a contract "
                    "with BytePlus (Trusted Outputs).")
            else:
                _error(tb)

        self._worker = _Worker(
            lambda: _seedance_edit(video_path, final_prompt, duration, ref_img),
            parent=self)
        self._worker.done.connect(done)
        self._worker.failed.connect(failed)
        self._worker.start()

    def _delete(self):
        lw = self.strip.currentItem()
        if not lw:
            return
        item = lw.data(QtCore.Qt.UserRole)
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("BYTEPLUS - Delete video")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("Remove '{}' from the gallery?".format(
            os.path.basename(item["video"])))
        cb = QtWidgets.QCheckBox("Also delete the file(s) from disk")
        cb.setChecked(True)
        box.setCheckBox(cb)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        if box.exec() != QtWidgets.QMessageBox.Ok:
            return
        if cb.isChecked():
            for p in (item["video"], item.get("poster"), item["video"] + ".txt"):
                if p:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        else:
            _hide_paths([item["video"]])         # keep it off the gallery on reopen
        if item in self._items:
            self._items.remove(item)
        self.strip.takeItem(self.strip.row(lw))
        nxt = self.strip.currentItem()
        if nxt:
            self._show(nxt.data(QtCore.Qt.UserRole))
        else:
            self.view.clear()
            self.view.setText("")
            self._current = None

    def _clear_all(self):
        if not self._items:
            return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("BYTEPLUS - Clear video gallery")
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setText("Remove ALL {} videos from the gallery?".format(len(self._items)))
        cb = QtWidgets.QCheckBox("Also delete the files from disk")
        cb.setChecked(False)
        box.setCheckBox(cb)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        if box.exec() != QtWidgets.QMessageBox.Ok:
            return
        if cb.isChecked():
            for it in self._items:
                for p in (it["video"], it.get("poster"), it["video"] + ".txt"):
                    if p:
                        try:
                            os.remove(p)
                        except OSError:
                            pass
        else:
            _hide_paths([it["video"] for it in self._items])   # stay cleared on reopen
        self._items = []
        self.strip.clear()
        self.view.clear()
        self.view.setText("")
        self._current = None


def _video_gallery() -> "VideoGallery":
    """Get-or-create the single Video Gallery (so results accumulate in one)."""
    g = getattr(_video_gallery, "_inst", None)
    if g is None:
        g = VideoGallery(_scene_movies_dir())
        _video_gallery._inst = g
    g._mov_dir = _scene_movies_dir()             # follow the current scene
    return g


def _add_video_result(video_bytes: bytes, poster_src, regen, prompt=None):
    """Save a finished Seedance video + poster and add it to the Video Gallery."""
    vid, poster = _save_video(video_bytes, poster_src, _scene_movies_dir(), prompt=prompt)
    g = _video_gallery()
    g.add_video(vid, poster, regen, prompt=prompt)
    g.show()
    g.raise_()


def open_video_gallery():
    """Open the Video Gallery standalone (loads the CURRENT scene's videos)."""
    g = _video_gallery()
    # Reset to the current scene (the gallery is a singleton that may hold
    # another scene's items from earlier in the session).
    g.strip.clear()
    g._items = []
    g._current = None
    g._load_existing()
    g.show()
    g.raise_()


def _img_ref_uri(src: str) -> str:
    """Resolve an image reference source to a URL/URI for Seedance.
    - An http(s) URL is passed THROUGH UNCHANGED -- critical for Seedream face
      images, whose biometric 'Trusted Outputs' chain breaks if re-uploaded.
    - A local file path is uploaded to TOS (or base64'd) via _asset_uri."""
    if isinstance(src, str) and src.startswith("http"):
        return src
    return _asset_uri(src, _image_mime(src))


_SEEDANCE_MAX_ATTEMPTS = 2                            # bounded retry of TRANSIENT fails


def _should_retry_failure(msg: str, trusted_input: bool) -> bool:
    """Whether a Seedance failure is worth retrying:
    - Bad-input errors (params / format) -> no (they won't change).
    - Real-face / content blocks -> only when the input IS a FRESH TRUSTED Seedream
      URL. There a face rejection is a flaky moderation-exemption false negative
      (the image should be exempt), not a real face, so retrying often succeeds.
    - Transient / server / network errors -> yes."""
    # NOTE: do NOT hard-block on "InputImage" -- the FACE error code is
    # "InputImageSensitiveContentDetected.PrivacyInformation", which must fall
    # through to the face check below.
    if any(s in msg for s in ("InvalidParameter", "not valid")):
        return False
    # Face / privacy moderation is DETERMINISTIC within a session: if the
    # trusted-outputs exemption is honored the first submit passes; if it isn't,
    # every retry fails identically. So fail fast (no wasted 2nd paid attempt) --
    # a failed submit is never billed. `trusted_input` is kept in the signature
    # for callers; re-enable retry here only if the block proves flaky per-call.
    if any(s in msg for s in ("SensitiveContent", "PrivacyInformation",
                              "real person", "biometric", "ContentModeration")):
        return False
    return True


def _seedance_generate(prompt: str, image_sources: list, movie: str | None,
                       duration: int, first_frame: str | None = None,
                       require_motion_video: bool = False,
                       generate_audio: bool | None = None,
                       extra_movies: list | None = None,
                       fit_motion: bool = False,
                       trusted_input: bool = False) -> bytes:
    """Submit a Seedance job and poll until done. Returns the video bytes.
    NETWORK ONLY -- call from a worker.

    Roles, by design:
      - `first_frame`: the look-authoritative concept (the video starts as this
        and keeps its appearance). Used by Animate so the playblast's look does
        NOT override the concept. If Seedance rejects 'first_frame', we fall back
        to 'reference_image'.
      - `image_sources` -> 'reference_image' (rendered keyframes / motion stills /
        tagged gallery images). Up to 9.
      - `movie` -> 'reference_video' (the playblast motion; needs a public host).
      - `extra_movies` -> additional 'reference_video' refs (e.g. a gallery clip).
        Together with `movie`, Seedance allows at most 3 videos, total <= 15s.
      - `generate_audio`: None -> use CONFIG default; True/False overrides it. If
        the audio OUTPUT is moderated, we retry once with audio OFF so the video
        still succeeds.
      - `require_motion_video`: when True, a failed playblast upload RAISES instead
        of silently degrading to text-only -- so a produced video is always
        faithful to the animation (the caller can retry)."""
    # Match the motion reference's length to the requested output duration, or
    # Seedance time-warps it and drifts from the animation (e.g. a 4.3s playblast
    # against a 4s output). Only for motion-driven flows (Animate/Render).
    if movie and fit_motion:
        movie = _fit_video_seconds(movie, int(duration))
    # Host the motion video(s) once (public URLs, deleted when the job ends).
    cleanups = []
    movie_url = None
    if movie:
        try:
            movie_url, _cu = _host_video(movie)
            cleanups.append(_cu)
        except Exception as e:
            if require_motion_video:
                raise RuntimeError(
                    "Couldn't attach the motion playblast to Seedance, so the "
                    "result would NOT be faithful to your animation. This is "
                    "usually a transient R2/TOS hosting hiccup -- please retry. "
                    "(Verify R2/TOS in BYTEPLUS > Settings > Storage & Hosting.)"
                    "\n\nDetail: {}".format(e))
            sys.stderr.write(
                "[BYTEPLUS] no motion-video host (TOS/R2); using image refs "
                "only -> {}\n".format(e))
    # Additional reference videos (a gallery clip / loaded file) -> extra
    # reference_video refs alongside the playblast. Enforce Seedance's limits:
    # at most 3 videos total AND <= 15s combined (the playblast, retimed above,
    # counts as int(duration) seconds). Skip any extra that would bust them.
    extra_urls = []
    vid_budget = 15 - (int(duration) if movie else 0)   # seconds left for extras
    vid_slots = 3 - (1 if movie else 0)                 # video slots left (max 3)
    for mv in (extra_movies or []):
        mvdur = _video_duration(mv) or 0
        if len(extra_urls) >= vid_slots or mvdur > vid_budget + 0.1:
            sys.stderr.write("[BYTEPLUS] skipping extra reference video ({:.1f}s) -- "
                             "would exceed Seedance's 3-video / 15s-total reference "
                             "limit.\n".format(mvdur))
            continue
        try:
            _u, _cu = _host_video(mv)
            extra_urls.append(_u)
            cleanups.append(_cu)
            vid_budget -= mvdur
        except Exception as e:
            sys.stderr.write("[BYTEPLUS] extra reference video not hosted, "
                             "skipping it -> {}\n".format(e))
    # Tell the artist which motion mode actually ran -- this is the #1 reason
    # the playblast is "sometimes not respected".
    n_ref_vids = (1 if movie_url else 0) + len(extra_urls)
    if n_ref_vids:
        _parts = ((["playblast (Video 1)"] if movie_url else [])
                  + (["{} gallery clip(s)".format(len(extra_urls))] if extra_urls else []))
        sys.stderr.write("[BYTEPLUS] MOTION = {} reference video(s) attached as "
                         "Video 1..{} [{}] -- Seedance will follow them.\n".format(
                             n_ref_vids, n_ref_vids, " + ".join(_parts)))
    elif movie:
        sys.stderr.write("[BYTEPLUS] MOTION = TEXT ONLY -- playblast captured but "
                         "could NOT be hosted (configure/verify R2/TOS). Motion "
                         "will be approximate.\n")
    else:
        sys.stderr.write("[BYTEPLUS] MOTION = TEXT ONLY (no motion video attached) "
                         "-- motion is approximate, from the text prompt.\n")

    def _content(ff_role):
        c = [{"type": "text", "text": prompt}]
        if first_frame:
            c.append({"type": "image_url", "role": ff_role,
                      "image_url": {"url": _img_ref_uri(first_frame)}})
        for src in image_sources:
            c.append({"type": "image_url", "role": "reference_image",
                      "image_url": {"url": _img_ref_uri(src)}})
        if movie_url:
            c.append({"type": "video_url", "role": "reference_video",
                      "video_url": {"url": movie_url}})
        for _u in extra_urls:
            c.append({"type": "video_url", "role": "reference_video",
                      "video_url": {"url": _u}})
        return c

    _audio = CONFIG.GENERATE_AUDIO if generate_audio is None else bool(generate_audio)

    def _submit(content, audio):
        body = {
            "model": CONFIG.SEEDANCE_MODEL,
            "content": content,
            "resolution": CONFIG.VIDEO_RESOLUTION,
            "ratio": CONFIG.VIDEO_RATIO,
            "duration": int(duration),
            "watermark": CONFIG.WATERMARK,
            "generate_audio": audio,
        }
        if CONFIG.CALLBACK_URL:
            body["callback_url"] = CONFIG.CALLBACK_URL
        sys.stderr.write("[BYTEPLUS] Seedance request -> model={} resolution={} "
                         "ratio={} duration={}s audio={}\n".format(
                             CONFIG.SEEDANCE_MODEL, CONFIG.VIDEO_RESOLUTION,
                             CONFIG.VIDEO_RATIO, int(duration), audio))
        created = _request("POST", CONFIG.BASE_URL + CONFIG.VIDEO_TASKS, body)
        tid = created.get("id") or created.get("task_id")
        if not tid:
            raise RuntimeError("No task id in response: " + json.dumps(created))
        return tid

    def _run(audio):
        try:
            task_id = _submit(_content("first_frame" if first_frame else None), audio)
        except RuntimeError as e:
            if first_frame and any(s in str(e) for s in
                                   ("first_frame", "InvalidParameter", "role")):
                sys.stderr.write("[BYTEPLUS] 'first_frame' not accepted; retrying "
                                 "with reference_image.\n")
                task_id = _submit(_content("reference_image"), audio)
            else:
                raise
        url = "{}{}/{}".format(CONFIG.BASE_URL, CONFIG.VIDEO_TASKS, task_id)
        while True:                                  # poll (Seedance is async)
            time.sleep(CONFIG.POLL_SECONDS)
            if _cancel_requested():                  # user hit ✕ -> real abort
                try:
                    _request("DELETE", url)          # frees compute, stops billing
                    sys.stderr.write("[BYTEPLUS] Seedance task {} cancelled "
                                     "(aborted).\n".format(task_id))
                except Exception as ce:
                    sys.stderr.write("[BYTEPLUS] cancel: could not abort task "
                                     "{} -> {}\n".format(task_id, ce))
                raise _Cancelled()
            st = _request("GET", url)
            status = (st.get("status") or st.get("state") or "").lower()
            if status in ("succeeded", "success", "done", "completed"):
                video_url = _find_video_url(st)
                if not video_url:
                    raise RuntimeError(
                        "Task succeeded but no video URL found. Raw response:\n"
                        + json.dumps(st, indent=2))
                _track("videos", st, CONFIG.SEEDANCE_MODEL)
                _u = (st.get("usage") or {})
                sys.stderr.write("[BYTEPLUS] Seedance returned -> resolution={} "
                                 "duration={}s frames={} tokens={}  (requested "
                                 "{}s)\n".format(
                                     st.get("resolution"), st.get("duration"),
                                     st.get("frames"), _u.get("total_tokens"),
                                     int(duration)))
                return _get_bytes(video_url)
            if status in ("failed", "error", "cancelled", "canceled"):
                raise RuntimeError("Seedance task failed: " + json.dumps(st, indent=2))

    def _once(audio):
        # One full submit+poll. If Seedance moderates the OUTPUT audio, fall back to
        # a SILENT render (a moderated-audio job otherwise fails entirely). This is
        # a policy fallback, not a transient retry.
        try:
            return _run(audio)
        except RuntimeError as e:
            if audio and any(s in str(e) for s in
                             ("OutputAudioSensitiveContentDetected",
                              "AudioSensitiveContent")):
                sys.stderr.write("[BYTEPLUS] audio output moderated; producing a "
                                 "silent clip.\n")
                return _run(False)
            raise

    try:
        last = None
        for _i in range(_SEEDANCE_MAX_ATTEMPTS):     # bounded retry of TRANSIENT fails
            try:
                return _once(_audio)
            except _Cancelled:
                raise
            except RuntimeError as e:
                # Retry transient failures + face rejections on a TRUSTED fresh
                # Seedream URL (flaky exemption). Never retry a real face or a
                # bad-input error.
                if not _should_retry_failure(str(e), trusted_input):
                    raise
                last = e
                if _i < _SEEDANCE_MAX_ATTEMPTS - 1:
                    sys.stderr.write("[BYTEPLUS] Seedance failure (attempt "
                                     "{}/{}); retrying...\n".format(
                                         _i + 1, _SEEDANCE_MAX_ATTEMPTS))
                    time.sleep(6 * (_i + 1))
                    continue
                raise
        if last:                                     # defensive; loop returns/raises
            raise last
    finally:
        for _cu in cleanups:                         # remove the hosted video(s)
            try:
                _cu()
            except Exception as e:
                sys.stderr.write("[BYTEPLUS] could not delete hosted video: "
                                 "{}\n".format(e))


def _seedance_edit_wrap(instruction: str) -> str:
    """Wrap a bare edit instruction with a lock-down clause so even an un-enhanced
    instruction preserves the source (identity, motion, camera) and changes only
    the named element -- the deterministic fallback when the user skips Enhance."""
    return ("Keep the reference video exactly as it is -- same subject, face and "
            "identity, wardrobe, performance, framing, lens, camera motion and "
            "timing -- and change ONLY the following, integrating it "
            "photorealistically into the existing footage with matching light, "
            "contact shadows, haze and grain, changing nothing else: {}. Face and "
            "identity unchanged; everything else identical to the reference "
            "video.".format(instruction.strip()))


def _seedance_edit(video_path: str, prompt: str, duration: int,
                   ref_img_src=None) -> bytes:
    """EDIT an existing clip with Seedance 2.0 (video-to-video): the saved video is
    attached as the reference video (motion + composition), an optional frame as the
    reference image (locks the look), and `prompt` names the single change with the
    source locked. Returns the new video bytes. NETWORK ONLY -- call from a worker.

    Works on a COPY of the source so _ensure_seedance_video can never delete or
    re-encode the user's gallery file in place."""
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="byteplus_vedit_")
    local = os.path.join(tmp, os.path.basename(video_path))
    try:
        shutil.copyfile(video_path, local)
        mp4 = _ensure_seedance_video(local)          # MP4/H.264 <=200MB (on the copy)
        imgs = [ref_img_src] if ref_img_src else []
        # No fit_motion: gallery clips are Seedance outputs with an integer duration,
        # so there's no drift to correct, and passing the clip byte-identical keeps
        # its TRUSTED-output status (re-encoding it would strip that and get the
        # face rejected).
        out = _seedance_generate(prompt, imgs, mp4, int(duration),
                                 require_motion_video=True)
        # Seedance returns a SILENT edit -> restore the ORIGINAL clip's audio track
        # so the edited video keeps its soundtrack (best-effort; no-op if the
        # source has no audio or ffmpeg is missing). Uses the untouched source
        # (video_path), so it aligns when the edit keeps the source duration.
        return _mux_audio_from(out, video_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def diagnose_telemetry():
    """Send ONE test event to the configured telemetry backend and report.

        import byteplus_maya; byteplus_maya.diagnose_telemetry()
    """
    print("=" * 60)
    print("BYTEPLUS diagnose_telemetry")
    print("  enabled :", CONFIG.TELEMETRY, " backend:", CONFIG.TELEMETRY_BACKEND)
    print("  customer:", CONFIG.CUSTOMER_ID or "(none)", " install:", _install_id())
    if CONFIG.TELEMETRY_BACKEND == "posthog":
        print("  posthog :", CONFIG.POSTHOG_HOST,
              "key set" if (CONFIG.POSTHOG_API_KEY or "").strip() else "KEY MISSING")
    if not CONFIG.TELEMETRY:
        print("  -> Telemetry is OFF. Enable it in Settings > Analytics.")
        print("=" * 60)
        return
    if not _telemetry_ready():
        print("  -> Backend not configured (missing PostHog key or R2 creds).")
        print("=" * 60)
        return
    ev = {"id": _install_id(), "ts": int(time.time()), "v": CONFIG.VERSION,
          "host": "maya", "event": "llm", "model": "diagnostic",
          "customer": CONFIG.CUSTOMER_ID or "",
          "tokens": {"in": 1, "out": 1, "total": 2}}
    try:
        if CONFIG.TELEMETRY_BACKEND == "posthog":
            _posthog_flush([ev])
            print("  RESULT : OK -- test event sent. Check PostHog > Activity "
                  "(live events appear within seconds).")
        else:
            _r2_telemetry_flush([ev])
            print("  RESULT : OK -- test event written to R2.")
    except Exception as e:
        print("  RESULT : FAILED")
        print(e)
    print("=" * 60)


def _ordinal(n: int) -> str:
    names = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh",
             "eighth", "ninth", "tenth"]
    return names[n - 1] if 1 <= n <= len(names) else "{}th".format(n)


def _bind_refs(text: str, img_refs: list, vid_refs: list, vid_offset: int = 1) -> str:
    """Deterministic @tag binding: replace each @tag with Seedance's numbered label.
    The main image is Image 1, so tagged images start at Image 2. Video labels start
    at `vid_offset` (2 when a scene playblast holds Video 1, else 1). If the text has
    no @tags (e.g. after ✦ Compose) it's returned unchanged."""
    out = text or ""
    subs = []
    for i, r in enumerate(img_refs):
        subs.append((r["label"], "Image {}".format(i + 2)))
    for i, r in enumerate(vid_refs):
        subs.append((r["label"], "Video {}".format(vid_offset + i)))
    # Replace LONGEST labels first so "@img1" doesn't clobber "@img10".
    for label, phrase in sorted(subs, key=lambda t: len(t[0]), reverse=True):
        out = out.replace(label, phrase)
    return out


_SEEDANCE_COMPOSE_SYSTEM = (
    "You write Seedance 2.0 multimodal video-generation prompts. The user's text "
    "uses @tags that map, IN ORDER, to the reference images attached to this "
    "message (the FIRST attached image is the main subject = 'reference image 1', "
    "the next attached images follow in order). Rewrite the user's text into ONE "
    "clean English prompt that: refers to each image as 'the first/second/third "
    "reference image' matching the attachment order, briefly says what each shows "
    "based on what you actually see, and preserves the intended action and motion. "
    "If a scene playblast drives the motion, state that the reference video "
    "provides the camera and the main motion, and keep the text to the "
    "subject/scene and ambient motion (no camera-move words). Under ~150 words, "
    "plain text, no markdown, no @tags in the output. Output ONLY the prompt.")


def _compose_ref_prompt(text, img_refs, vid_refs, has_playblast, main_image=None):
    """LLM rewrite of an @-tagged motion prompt into a clean multimodal prompt,
    letting the model see the tagged images (main image first, then each @img in
    order). NETWORK ONLY -- call from a worker."""
    user = [{"type": "text", "text":
             ("The scene playblast drives the motion.\n" if has_playblast else "")
             + "Rewrite this into a Seedance prompt:\n" + (text or "")}]
    srcs = ([main_image] if main_image else []) + [r.get("path") for r in img_refs]
    for p in [s for s in srcs if s][:9]:
        try:
            uri = p if (isinstance(p, str) and p.startswith("http")) \
                else _data_uri(p, _image_mime(p))
            user.append({"type": "image_url", "image_url": {"url": uri}})
        except Exception:
            pass
    body = {"model": CONFIG.LLM_MODEL,
            "messages": [{"role": "system", "content": _SEEDANCE_COMPOSE_SYSTEM},
                         {"role": "user", "content": user}]}
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, CONFIG.LLM_MODEL)
    return (resp["choices"][0]["message"]["content"] or "").strip()


def _pick_gallery_image(items, parent, warn_trust=True):
    """Modal thumbnail picker over Dream Gallery items. Returns the chosen item
    dict ({'bytes','path','url',...}) or None. warn_trust=False hides the
    face-trust hint (irrelevant when just picking an image to compare)."""
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("Pick a reference image")
    dlg.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
    dlg.setMinimumSize(600, 400)
    lay = QtWidgets.QVBoxLayout(dlg)
    lay.addWidget(QtWidgets.QLabel("Double-click an image to use it as a reference."))
    lw = QtWidgets.QListWidget()
    lw.setViewMode(QtWidgets.QListView.IconMode)
    lw.setIconSize(QtCore.QSize(150, 96))
    lw.setResizeMode(QtWidgets.QListView.Adjust)
    lw.setMovement(QtWidgets.QListView.Static)
    for it in items:
        pix = QtGui.QPixmap()
        if it.get("bytes"):
            pix.loadFromData(it["bytes"])
        elif it.get("path") and os.path.exists(it["path"]):
            pix.load(it["path"])
        w = QtWidgets.QListWidgetItem(
            QtGui.QIcon(pix) if not pix.isNull() else QtGui.QIcon(),
            os.path.basename(it.get("path") or ""))
        if warn_trust and not (it.get("url") and _url_is_fresh(it["url"])):
            w.setToolTip("No fresh trusted link — a FACE in this image may be "
                         "rejected by Seedance.")
        w.setData(QtCore.Qt.UserRole, it)
        lw.addItem(w)
    lay.addWidget(lw)
    bb = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lw.itemDoubleClicked.connect(lambda _i: dlg.accept())
    lay.addWidget(bb)
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return None
    cur = lw.currentItem()
    return cur.data(QtCore.Qt.UserRole) if cur else None


def _pick_gallery_video(items, parent):
    """Pick a Video Gallery clip or load a file. Returns a local video path or
    None."""
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("Pick a reference video")
    dlg.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
    dlg.setMinimumSize(600, 400)
    lay = QtWidgets.QVBoxLayout(dlg)
    lay.addWidget(QtWidgets.QLabel(
        "Double-click a gallery clip, or load a file. (Gallery clips are trusted "
        "Seedance outputs; external clips with faces may be rejected.)"))
    lw = QtWidgets.QListWidget()
    lw.setViewMode(QtWidgets.QListView.IconMode)
    lw.setIconSize(QtCore.QSize(160, 90))
    lw.setResizeMode(QtWidgets.QListView.Adjust)
    lw.setMovement(QtWidgets.QListView.Static)
    for it in items:
        poster = it.get("poster")
        icon = (QtGui.QIcon(poster) if (poster and os.path.exists(poster))
                else QtGui.QIcon())
        w = QtWidgets.QListWidgetItem(icon, os.path.basename(it.get("video") or ""))
        w.setData(QtCore.Qt.UserRole, it.get("video"))
        lw.addItem(w)
    lay.addWidget(lw)
    chosen = {"path": None}

    def _load():
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            dlg, "Choose a video", "", "Video (*.mp4 *.mov)")
        if p:
            chosen["path"] = p
            dlg.accept()

    row = QtWidgets.QHBoxLayout()
    b_load = QtWidgets.QPushButton("Load file…")
    b_load.clicked.connect(_load)
    row.addWidget(b_load)
    row.addStretch(1)
    bb = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    row.addWidget(bb)
    lay.addLayout(row)
    lw.itemDoubleClicked.connect(lambda _i: dlg.accept())
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return None
    if chosen["path"]:
        return chosen["path"]
    cur = lw.currentItem()
    return cur.data(QtCore.Qt.UserRole) if cur else None


class AnimateDialog(QtWidgets.QDialog):
    """Mini-dialog for Animate: auto-analyzes the image for a motion prompt and
    offers to drive the motion from the scene's animation (playblast)."""

    def __init__(self, image_src, has_anim, parent=None, dream_items=None,
                 video_items=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("Animate with Seedance 2.0")
        self.setMinimumSize(500, 380)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._image_src = image_src
        self._worker = None
        self._dream_items = list(dream_items or [])
        self._video_items = list(video_items or [])
        self._img_refs = []
        self._vid_refs = []
        self._img_n = 0
        self._vid_n = 0
        v = QtWidgets.QVBoxLayout(self)
        self.lbl = QtWidgets.QLabel()
        v.addWidget(self.lbl)
        self.prompt = QtWidgets.QPlainTextEdit()
        v.addWidget(self.prompt, 1)
        hb = QtWidgets.QHBoxLayout()
        self.b_enhance = QtWidgets.QPushButton("✦ Enhance")
        self.b_enhance.setToolTip("Improve the wording of your motion text "
                                  "(keeps your intent; doesn't look at the image)")
        self.b_enhance.clicked.connect(self._enhance)
        hb.addWidget(self.b_enhance)
        self.b_auto = QtWidgets.QPushButton("✨ Analyze")
        self.b_auto.setToolTip("Suggest a motion from the image")
        self.b_auto.clicked.connect(self._auto)
        hb.addWidget(self.b_auto)
        _add_dictate_button(hb, self.prompt)
        self.b_guide = QtWidgets.QPushButton("ⓘ Guide")
        self.b_guide.setToolTip("How to write the motion text")
        self.b_guide.clicked.connect(self._guide)
        hb.addWidget(self.b_guide)
        hb.addStretch(1)
        v.addLayout(hb)

        # --- multi-reference (@) --------------------------------------------
        rr = QtWidgets.QHBoxLayout()
        rr.addWidget(QtWidgets.QLabel("References:"))
        self.b_add_img = QtWidgets.QPushButton("＋ Image (@)")
        self.b_add_img.setToolTip("Add a Dream Gallery image as an extra reference "
                                  "and insert its @tag into the prompt. Faces are "
                                  "only accepted from trusted (Seedream) images.")
        self.b_add_img.clicked.connect(self._add_img_ref)
        rr.addWidget(self.b_add_img)
        self.b_add_vid = QtWidgets.QPushButton("＋ Video")
        self.b_add_vid.setToolTip("Add ONE extra reference video (a Video Gallery "
                                  "clip or a file) alongside the playblast.")
        self.b_add_vid.clicked.connect(self._add_vid_ref)
        rr.addWidget(self.b_add_vid)
        self.b_compose = QtWidgets.QPushButton("✦ Compose")
        self.b_compose.setToolTip("Rewrite the prompt from your @tags using the "
                                  "tagged images (cleaner binding for Seedance).")
        self.b_compose.clicked.connect(self._compose)
        rr.addWidget(self.b_compose)
        rr.addStretch(1)
        v.addLayout(rr)
        self.ref_list = QtWidgets.QListWidget()
        self.ref_list.setFixedHeight(58)
        self.ref_list.setToolTip("Added references. Double-click one to remove it.")
        self.ref_list.itemDoubleClicked.connect(lambda _i: self._remove_ref())
        v.addWidget(self.ref_list)

        self.use_anim = QtWidgets.QCheckBox(
            "Use the scene's animation (playblast) to drive the motion")
        self.use_anim.setChecked(has_anim)
        self.use_anim.setEnabled(has_anim)
        if not has_anim:
            self.use_anim.setText(
                "Use the scene's animation  (none detected — motion from prompt)")
        self.use_anim.toggled.connect(self._sync_mode)
        v.addWidget(self.use_anim)
        # Clip length. Seedance 2.0 allows 4-15 s (verified). With the playblast ON
        # the length follows the scene animation (this is disabled); with it OFF the
        # user picks it here.
        drow = QtWidgets.QHBoxLayout()
        drow.addWidget(QtWidgets.QLabel("Clip length (s):"))
        self.duration = QtWidgets.QComboBox()
        self.duration.addItems([str(s) for s in range(4, 16)])   # 4..15
        self.duration.setCurrentText(
            str(max(4, min(15, int(round(_anim_seconds())) or 5))))
        self.duration.setToolTip(
            "Length of the generated clip (Seedance 2.0: 4-15 s). Enabled only when "
            "the playblast is OFF; with the playblast ON the length matches your "
            "scene animation.")
        self.duration.currentIndexChanged.connect(self._update_cost)
        drow.addWidget(self.duration)
        drow.addStretch(1)
        v.addLayout(drow)
        self.cb_audio = QtWidgets.QCheckBox("Generate audio (Seedance)")
        self.cb_audio.setChecked(True)
        self.cb_audio.setToolTip("Let Seedance add a soundtrack / SFX. If the audio "
                                 "output is moderated, the plugin automatically "
                                 "retries once without audio so the video still "
                                 "comes out.")
        v.addWidget(self.cb_audio)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#888;")
        v.addWidget(self.note)
        self.cost = QtWidgets.QLabel()
        self.cost.setStyleSheet("color:#2E8BE6; font-weight:bold;")
        v.addWidget(self.cost)

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Generate video")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._sync_mode()                         # sets label/placeholder + auto-fill

    def _update_cost(self):
        if not CONFIG.SHOW_COST:
            self.cost.setText("")
            return
        if self.use_anim.isChecked():
            dur = max(4, min(15, int(round(_anim_seconds())) or 4))
        else:
            dur = int(self.duration.currentText())
        has_video = self.use_anim.isChecked() and _motion_host_ready()
        tok, usd = _est_video_cost(CONFIG.VIDEO_RESOLUTION, CONFIG.VIDEO_RATIO,
                                   dur, has_video)
        self.cost.setText("{}  ({}, {}s)".format(
            _fmt_cost(tok, usd), CONFIG.VIDEO_RESOLUTION, dur))

    def _sync_mode(self, *_):
        """The text box's role depends on the playblast checkbox: when the
        playblast drives the motion the box is OPTIONAL extra direction (no
        auto-guessed motion to conflict); otherwise the box IS the motion and we
        auto-suggest one."""
        if self.use_anim.isChecked():
            self.lbl.setText("Optional extra direction "
                             "(the playblast drives the motion):")
            self.prompt.setPlaceholderText(
                "Optional — ambient motion + mood: leaves sway, dust drifts, "
                "clouds move, people walk… (NO camera moves — the playblast owns those)")
            self.note.setText(
                "Playblast drives the CAMERA & main motion. Keep the text to "
                "ambient motion + mood only; avoid camera words like 'dolly' or "
                "'orbit' (they fight the playblast).  ⓘ Guide for details.")
        else:
            self.lbl.setText("Motion for this image (auto-analyzed — edit freely):")
            self.prompt.setPlaceholderText(
                "Describe the motion (camera move, subject action, pacing)…")
            self.note.setText(
                "No playblast: the TEXT is the motion — describe camera, action "
                "and pacing freely. The image defines the LOOK.  ⓘ Guide for details.")
            if not self.prompt.toPlainText().strip():
                QtCore.QTimer.singleShot(0, self._auto)   # the box is the motion
        # Clip length is chosen manually only when the playblast is OFF; when it's
        # ON the length matches the scene animation, so grey it out.
        self.duration.setEnabled(not self.use_anim.isChecked())
        self._update_cost()

    def _uri(self):
        s = self._image_src
        return s if s.startswith("http") else _data_uri(s, _image_mime(s))

    def _auto(self):
        self.b_auto.setEnabled(False)
        self.b_auto.setText("Analyzing…")
        uri = self._uri()
        self._worker = _Worker(lambda: _caption_motion(uri), parent=self)

        def done(text):
            if text:
                self.prompt.setPlainText(text)
            self.b_auto.setEnabled(True)
            self.b_auto.setText("✨ Re-analyze")

        def fail(tb):
            self.b_auto.setEnabled(True)
            self.b_auto.setText("✨ Re-analyze")
            sys.stderr.write("[BYTEPLUS] motion auto-prompt failed:\n" + tb + "\n")

        self._worker.done.connect(done)
        self._worker.failed.connect(fail)
        self._worker.start()

    def _enhance(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            cmds.inViewMessage(amg="Type a motion first, then <hl>✦ Enhance</hl>.",
                               pos="midCenter", fade=True)
            return
        self.b_enhance.setEnabled(False)
        self.b_enhance.setText("Enhancing...")
        # TEXT-ONLY: improve the wording; never look at the image (that's what
        # '✨ Re-analyze' is for) so it can't override the user's motion intent.
        self._enh_worker = _Worker(lambda: _enhance_prompt(text), parent=self)

        def done(t):
            if t:
                self.prompt.setPlainText(t)          # Ctrl+Z restores the original
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")

        def fail(tb):
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")
            _error("Enhance failed:\n\n" + tb)

        self._enh_worker.done.connect(done)
        self._enh_worker.failed.connect(fail)
        self._enh_worker.start()

    def _guide(self):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("BYTEPLUS — How to write the motion")
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText("The image = the LOOK.  The motion comes from two places:")
        box.setInformativeText(
            "🎥  WITH playblast (checkbox ON)\n"
            "    The scene playblast drives the CAMERA and the main motion.\n"
            "    In the text, add only AMBIENT motion + mood:\n"
            "      • leaves sway, dust drifts, clouds move, people walk\n"
            "      • lighting / lens / pacing words are fine\n"
            "    AVOID camera words ('dolly', 'tracking', 'orbit', 'zoom') —\n"
            "    they compete with the playblast and can pull the result off it.\n\n"
            "✍️  WITHOUT playblast (checkbox OFF)\n"
            "    The TEXT is the motion — describe camera moves, subject action\n"
            "    and pacing freely.\n\n"
            "✦ Enhance improves your wording only (it doesn't look at the image\n"
            "    or playblast), so don't let it add camera moves when the\n"
            "    playblast is ON.")
        box.exec()

    def prompt_text(self):
        return self.prompt.toPlainText().strip()

    def wants_anim(self):
        return self.use_anim.isChecked()

    def duration_choice(self):
        """Chosen clip length in seconds (used when the playblast is OFF)."""
        return int(self.duration.currentText())

    def wants_audio(self):
        return self.cb_audio.isChecked()

    def image_refs(self):
        return list(self._img_refs)

    def video_refs(self):
        return list(self._vid_refs)

    def _refresh_refs(self):
        self.ref_list.clear()
        for r in self._img_refs:
            self.ref_list.addItem("{}  =  image · {}".format(
                r["label"], os.path.basename(r.get("path") or "")))
        for r in self._vid_refs:
            self.ref_list.addItem("{}  =  video · {}".format(
                r["label"], os.path.basename(r.get("path") or "")))

    def _remove_ref(self):
        row = self.ref_list.currentRow()
        if row < 0:
            return
        n_img = len(self._img_refs)
        if row < n_img:
            self._img_refs.pop(row)
        else:
            self._vid_refs.pop(row - n_img)
        self._refresh_refs()

    def _add_img_ref(self):
        if len(self._img_refs) >= 8:
            _error("Up to 8 extra image references (9 total with the main image).")
            return
        if not self._dream_items:
            _error("No Dream Gallery images to reference — generate some first.")
            return
        picked = _pick_gallery_image(self._dream_items, self)
        if not picked:
            return
        self._img_n += 1
        label = "@img{}".format(self._img_n)
        self._img_refs.append({"label": label, "url": picked.get("url"),
                               "path": picked.get("path")})
        self.prompt.insertPlainText(" " + label + " ")
        self._refresh_refs()

    def _add_vid_ref(self):
        if self._vid_refs:
            _error("v1 supports one extra reference video. Remove the current one "
                   "first (double-click it in the list).")
            return
        path = _pick_gallery_video(self._video_items, self)
        if not path:
            return
        self._vid_n += 1
        label = "@vid{}".format(self._vid_n)
        self._vid_refs.append({"label": label, "path": path})
        self.prompt.insertPlainText(" " + label + " ")
        self._refresh_refs()

    def _compose(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            cmds.inViewMessage(amg="Type a prompt with @tags first.",
                               pos="midCenter", fade=True)
            return
        self.b_compose.setEnabled(False)
        self.b_compose.setText("Composing...")
        img_refs = list(self._img_refs)
        vid_refs = list(self._vid_refs)
        has_pb = self.use_anim.isChecked()
        main = self._image_src
        self._cmp_worker = _Worker(
            lambda: _compose_ref_prompt(text, img_refs, vid_refs, has_pb, main),
            parent=self)

        def done(t):
            if t:
                self.prompt.setPlainText(t)
            self.b_compose.setEnabled(True)
            self.b_compose.setText("✦ Compose")

        def fail(tb):
            self.b_compose.setEnabled(True)
            self.b_compose.setText("✦ Compose")
            _error("Compose failed:\n\n" + tb)

        self._cmp_worker.done.connect(done)
        self._cmp_worker.failed.connect(fail)
        self._cmp_worker.start()


def animate_with_seedance(image_src: str, poster_path=None, dream_items=None,
                          video_items=None):
    """Dream -> Animate: feed a Seedream image (+ the scene's animation) to
    Seedance to generate a video. The motion prompt is auto-analyzed from the
    image, and the scene's animation is captured when present.

    `image_src` is the ORIGINAL Seedream platform URL when available -- we pass
    it through untouched so the face 'Trusted Outputs' chain stays valid (a
    re-uploaded copy would be rejected). `poster_path` is a local image used as
    the Video Gallery thumbnail."""
    if not _scene_ok_to_proceed():
        return
    has_anim = _has_animation()
    d = AnimateDialog(image_src, has_anim, dream_items=dream_items,
                      video_items=video_items)
    if not d.exec():
        return
    use_anim = d.wants_anim()
    audio = d.wants_audio()
    img_refs = d.image_refs()
    vid_refs = d.video_refs()
    extra_movies = [r.get("path") for r in vid_refs if r.get("path")]
    motion = d.prompt_text()
    # Only inject a generic motion description when there is genuinely NO motion
    # source (no scene animation AND no reference video) -- otherwise it would tell
    # Seedance to invent generic motion and drown out the reference video.
    if not motion and not use_anim and not extra_movies:
        motion = "subtle cinematic motion, gentle camera move"
    # (@tags are resolved later, in make_video, where the video numbering is known.)
    # Extra reference IMAGES: prefer each one's trusted platform URL (keeps the
    # face-exemption chain) while fresh, else its local file. 9 total incl. main.
    extra_imgs = []
    for r in img_refs:
        u = r.get("url")
        s = u if (u and _url_is_fresh(u)) else r.get("path")
        if s:
            extra_imgs.append(s)
    extra_imgs = extra_imgs[:8]
    image_sources = [image_src] + extra_imgs
    # The main image is a fresh trusted Seedream URL when it's an http link (see
    # _on_animate). Lets _seedance_generate retry a flaky face-exemption rejection.
    trusted_input = isinstance(image_src, str) and image_src.startswith("http")
    # REFERENCE-MEDIA mode: image = look, video = motion. Seedance's multimodal API
    # refers to each attachment by a NUMBERED label matching the content order
    # (Image 1 = the main image, Image 2.. = extras; Video 1 = the playblast, or the
    # first gallery clip when there's no playblast). See the Seedance r2v docs.
    if extra_imgs:
        look_tag = ("The main subject is Image 1 — keep its exact appearance, "
                    "materials, colours and identity. Use the other reference "
                    "images (Image 2, Image 3, …) as described in the text. ")
    else:
        look_tag = ("Animate the subject from Image 1, keeping its exact "
                    "appearance, materials, colours and style from Image 1; do "
                    "not restyle or change its look. ")
    prompt = look_tag + (("Action: " + motion) if motion else "")

    # Playblast ON -> clip length follows the scene animation; OFF -> the user's
    # choice from the dialog (Seedance 2.0: 4-15 s, verified).
    if use_anim:
        seconds = _anim_seconds()
        duration = max(4, min(15, int(round(seconds)) or 4))
    else:
        duration = d.duration_choice()
        seconds = duration

    # Reference videos (the playblast and/or an extra clip) need a public video
    # host (R2/TOS). If there isn't one, alert the user -- they'll be dropped.
    host = _motion_host_ready()
    if (use_anim or extra_movies) and not host:
        proceed = _msgbox(
            QtWidgets.QMessageBox.Warning, "BYTEPLUS - motion hosting not configured",
            "Reference-video hosting (Cloudflare R2 / TOS) is not set up, so the "
            "playblast / extra reference video can't be sent to Seedance.\n\n"
            "The video will still be generated, but the motion will be "
            "APPROXIMATE (from the text description only), not a faithful copy "
            "of your scene's animation, and any extra reference video is dropped."
            "\n\nFor faithful motion, use  BYTEPLUS > Set up motion hosting…  "
            "(Cloudflare R2 needs nothing to install), then animate again. "
            "Continue anyway?",
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        if proceed != QtWidgets.QMessageBox.Ok:
            return

    # Cost guard (only prompts if the estimate exceeds the threshold).
    has_video = bool(host) and (use_anim or bool(extra_movies))
    _tok, _usd = _est_video_cost(CONFIG.VIDEO_RESOLUTION, CONFIG.VIDEO_RATIO,
                                 duration, has_video)
    if not _confirm_cost(_usd, "Animate -> {} video, {}s.".format(
            CONFIG.VIDEO_RESOLUTION, duration)):
        return

    dlg = _progress("Preparing animation...")
    QtWidgets.QApplication.processEvents()
    try:
        movie = None
        motion_frames = []                           # ONLY for the text fallback
        capture_failed = False                       # wanted a playblast, couldn't get one
        if use_anim:
            # Prefer the VIDEO reference. Capture it first; only fall back to
            # sampling frames (for a text motion description) when there is no
            # video -- when the video IS attached, the frames aren't used, so we
            # don't waste time/disk sampling them.
            if host:
                _rng = _anim_range()                 # capture the SAME range as `duration`

                def _try_capture():
                    # Playblast capture is LOCAL and FREE -> retry a few times so a
                    # transient Maya/GPU glitch doesn't silently drop us to text.
                    for _att in range(4):
                        dlg.setLabelText("Capturing motion playblast (video){}...".format(
                            "" if _att == 0 else "  retry {}".format(_att)))
                        QtWidgets.QApplication.processEvents()
                        try:
                            cand = _playblast_movie(*_rng)
                        except Exception as e:
                            sys.stderr.write("[BYTEPLUS] playblast capture failed "
                                             "(attempt {}): {}\n".format(_att + 1, e))
                            continue
                        if _playblast_is_valid(cand, seconds):
                            return cand
                        sys.stderr.write("[BYTEPLUS] playblast looked invalid (attempt "
                                         "{}); retrying.\n".format(_att + 1))
                    return None

                movie = _try_capture()
                # You WANTED faithful motion but the capture kept failing. Don't
                # silently spend a paid generation on generic motion -- ask.
                while not movie:
                    dlg.hide()
                    choice = _msgbox(
                        QtWidgets.QMessageBox.Warning,
                        "BYTEPLUS - motion playblast capture failed",
                        "The scene's motion playblast could not be captured after "
                        "several tries, so Seedance would invent GENERIC motion "
                        "instead of following your animation.\n\n"
                        "Check that the time-slider range covers your animation and "
                        "that the active view is a normal 3D viewport, then Retry.\n\n"
                        "  • Retry  -- capture again\n"
                        "  • Ignore -- generate with generic motion anyway\n"
                        "  • Cancel -- stop (nothing generated or charged)",
                        QtWidgets.QMessageBox.Retry | QtWidgets.QMessageBox.Ignore
                        | QtWidgets.QMessageBox.Cancel)
                    if choice == QtWidgets.QMessageBox.Retry:
                        dlg.show()
                        movie = _try_capture()
                        continue
                    if choice == QtWidgets.QMessageBox.Cancel:
                        dlg.close()
                        return
                    capture_failed = True            # Ignore -> generic on purpose
                    break
                dlg.show()
            else:
                # Hosting isn't set up, so even a captured playblast can't be sent.
                # The user already OK'd the 'motion hosting not configured' warning.
                capture_failed = True
            if not movie:                            # text-only fallback path
                if capture_failed:
                    sys.stderr.write("[BYTEPLUS] motion: {} -> generating GENERIC "
                                     "motion.\n".format(
                                         "playblast capture failed" if host
                                         else "motion hosting (R2/TOS) not configured"))
                dlg.setLabelText("Sampling motion frames...")
                QtWidgets.QApplication.processEvents()
                for f in _frame_samples(min(6, CONFIG.MAX_IMAGE_REFS)):
                    motion_frames.append(_playblast_frame(f))
        elif not extra_movies:
            sys.stderr.write("[BYTEPLUS] motion: 'Use scene animation' is off (or the "
                             "scene has no animation) -> motion from the text prompt.\n")
    except Exception:
        dlg.close()
        _error("Could not prepare animation:\n\n" + traceback.format_exc())
        return

    # Prepare the SELECTED motion videos (gallery clips): validate/transcode each to
    # a Seedance-safe MP4 (like the playblast), then keep only those that fit
    # Seedance's limit (<=3 reference videos, <=15s total incl. the playblast). WARN
    # about any that are dropped instead of dropping them silently downstream. Needs
    # a video host (checked/warned above); without one nothing can be sent.
    ready_extras = []
    if extra_movies and host:
        dlg.setLabelText("Preparing reference video(s)...")
        QtWidgets.QApplication.processEvents()
        _vbudget = 15 - (int(duration) if movie else 0)
        _vslots = 3 - (1 if movie else 0)
        _dropped = []
        for mv in extra_movies:
            try:
                mv2 = _ensure_seedance_video(mv)
            except Exception as e:
                _dropped.append((mv, "not a Seedance-compatible video ({})".format(e)))
                continue
            mvdur = _video_duration(mv2) or 0
            if len(ready_extras) >= _vslots:
                _dropped.append((mv, "over Seedance's 3-reference-video limit"))
            elif mvdur > _vbudget + 0.1:
                _dropped.append((mv, "{:.1f}s won't fit the {:.0f}s left (15s total "
                                     "with the playblast)".format(mvdur, max(0, _vbudget))))
            else:
                ready_extras.append(mv2)
                _vbudget -= mvdur
        if _dropped:
            _lines = "\n".join("  • {} — {}".format(os.path.basename(str(_p)), _why)
                               for _p, _why in _dropped)
            dlg.hide()
            _msgbox(QtWidgets.QMessageBox.Warning,
                    "BYTEPLUS - some motion videos were not sent",
                    "These selected reference videos will NOT be sent to Seedance:"
                    "\n\n" + _lines + "\n\nSeedance allows at most 3 reference videos "
                    "totalling 15 seconds (including the scene playblast).",
                    QtWidgets.QMessageBox.Ok)
            dlg.show()

    if extra_movies:
        sys.stderr.write("[BYTEPLUS] reference videos: {} selected -> {} will be "
                         "sent to Seedance{}.\n".format(
                             len(extra_movies), len(ready_extras),
                             "" if host else " (motion hosting R2/TOS not configured)"))

    dlg.setLabelText("Submitting to Seedance (image + {})...".format(
        "motion video" if (movie or ready_extras) else "motion description"))
    QtWidgets.QApplication.processEvents()
    def failed(tb):
        dlg.close()
        if any(s in tb for s in ("SensitiveContent", "PrivacyInformation",
                                 "real person")):
            _error(
                "Seedance blocked this image: it detected a HUMAN FACE that is "
                "not a trusted input.\n\n"
                "Seedance 2.0 only accepts AI faces that are a FRESH Seedream "
                "output from this same account (the moderation-exemption / "
                "Trusted-Outputs path). Real human faces are never allowed.\n\n"
                "What works:\n"
                "  • Generate the face with  BYTEPLUS > Dream  and tick "
                "'Text-to-Image' (exempt for everyone), then Animate it — the "
                "plugin passes the trusted link automatically.\n"
                "  • Viewport-guided (image-to-image) faces work too once your "
                "account has KYC HIGH.\n"
                "  • The trusted link expires in ~24h — if this image is older, "
                "regenerate it and animate again.\n"
                "  • Real-person footage still needs a BytePlus contract "
                "(authorized real-person assets).")
        else:
            _error(tb)

    # poster for the Video Gallery: explicit poster, else a local source image
    poster = poster_path or (image_src if not str(image_src).startswith("http")
                             else None)

    def make_video(p):                               # re-runnable with a new prompt
        # Resolve @tags now that the video numbering is known (playblast = Video 1,
        # gallery clips follow). This matches the content order in _seedance_generate.
        p = _bind_refs(p, img_refs, vid_refs, vid_offset=(2 if movie else 1))
        n_vid = (1 if movie else 0) + len(ready_extras)
        final = p
        if n_vid:
            # One or more reference videos attached (playblast and/or gallery clips)
            # -> tell Seedance to FOLLOW their motion, by their numbered labels (the
            # role the API uses). Content order: playblast is Video 1, extras follow.
            labels = ["Video {}".format(i + 1) for i in range(n_vid)]
            if len(labels) == 1:
                vlist, verb = labels[0], "It provides"
            else:
                vlist = ", ".join(labels[:-1]) + " and " + labels[-1]
                verb = "They provide"
            final = ("Strictly follow the exact motion, movement path, camera work "
                     "and timing of {} throughout. {} ONLY the motion and camera, "
                     "not the look — keep the subject's exact appearance from "
                     "Image 1.  ".format(vlist, verb) + p)
        elif motion_frames:
            # No video at all -> text-only FALLBACK from sampled scene frames.
            try:
                desc = _describe_scene_motion(motion_frames)
                if desc:
                    final = "Motion to follow: " + desc + ".  " + p
            except Exception as e:
                sys.stderr.write("[BYTEPLUS] scene-motion describe skipped: "
                                 "{}\n".format(e))
        # No first_frame (can't mix with a video ref). require_motion_video makes a
        # failed playblast upload FAIL LOUDLY instead of silently degrading.
        return _seedance_generate(final, image_sources, movie, duration,
                                  require_motion_video=bool(movie),
                                  generate_audio=audio, extra_movies=ready_extras,
                                  fit_motion=True, trusted_input=trusted_input)

    worker = _Worker(lambda: make_video(prompt), parent=_main_window())
    worker.done.connect(lambda vb: (dlg.close(),
                        _add_video_result(vb, poster, make_video, prompt=prompt)))
    worker.failed.connect(failed)
    worker.start()
    animate_with_seedance._w = worker  # keep ref alive


# =============================================================================
# Feature 1 -- Render with Seedance 2.0
# =============================================================================
def render_with_seedance():
    """Render N keyframes with the CURRENT renderer (Arnold etc.) as references
    + a playblast for motion, then drive Seedance 2.0 to a 1080p video. N scales
    with the animation length (3 at <=5s up to 9 at >=15s).

    Architecture: ALL Maya operations (render, playblast) run synchronously on
    the MAIN thread -- driving cmds.render across threads crashes Maya. Only the
    network upload/submit/poll runs on a background worker.

    No prompt dialog: this feature is purely "render the scene as a video". The
    rendered keyframes carry the LOOK + lighting and the playblast carries the
    MOTION, so a fixed neutral prompt is used -- nothing for the artist to type."""
    if not _scene_ok_to_proceed():
        return
    # Render with Seedance is about FAITHFULLY rendering the scene's motion, not
    # approximating it -- so the playblast MUST be attachable. Require a motion
    # host (R2/TOS) UP FRONT, before spending an expensive Arnold render.
    if not _motion_host_ready():
        _error("Render with Seedance needs the playblast attached as the motion "
               "reference, which requires motion-video hosting (Cloudflare R2 or "
               "BytePlus TOS).\n\nSet it up in  BYTEPLUS > Settings > Storage & "
               "Hosting,  then try again.\n\n(Tip: use 'Animate with Seedance' if "
               "you only need approximate motion without hosting.)")
        return
    # Look comes from the rendered reference images; the motion clause is added in
    # make_video so it matches what's actually sent (video vs frames only).
    prompt = ("Photorealistic cinematic shot. Preserve the exact look, materials "
              "and lighting of the subject in the reference images.")

    seconds = _anim_seconds()
    n_refs = _ref_count(seconds, CONFIG.MAX_IMAGE_REFS)
    frames = _frame_samples(n_refs)
    duration = max(4, min(15, int(round(seconds)) or 4))
    renderer = cmds.getAttr("defaultRenderGlobals.currentRenderer")

    # Cost guard (Render always sends a playblast as the motion video).
    _tok, _usd = _est_video_cost(CONFIG.VIDEO_RESOLUTION, CONFIG.VIDEO_RATIO,
                                 duration, _motion_host_ready())
    if not _confirm_cost(_usd, "Render with Seedance -> {} video, {}s.".format(
            CONFIG.VIDEO_RESOLUTION, duration)):
        return

    # -- Phase 1: Maya-side rendering, ON THE MAIN THREAD (stable) -------------
    dlg = _progress("Preparing render...")
    QtWidgets.QApplication.processEvents()
    print("\n" + "=" * 60)
    print("BYTEPLUS Render with Seedance")
    print("  renderer  : {}   anim: {:.1f}s   ref frames: {} -> {}".format(
        renderer, seconds, n_refs, frames))
    try:
        img_dir = _scene_images_dir()
        mov_dir = _scene_movies_dir()
        print("  images dir: {}".format(img_dir))
        print("  movies dir: {}".format(mov_dir))
        ref_paths = []
        for i, f in enumerate(frames):
            dlg.setLabelText("STEP 1/2  Rendering frame {}/{} with '{}' "
                             "(scene frame {})...".format(i + 1, len(frames), renderer, f))
            QtWidgets.QApplication.processEvents()
            p = _render_frame(f, img_dir)
            print("  rendered  : frame {:>5} -> {}".format(f, p))
            ref_paths.append(p)
        dlg.setLabelText("STEP 1/2  Capturing motion playblast...")
        QtWidgets.QApplication.processEvents()
        # The playblast is MANDATORY here (Render = faithful motion, not approx).
        # If it can't be captured, stop -- don't fall back to frames-only.
        movie = _playblast_movie()
        print("  playblast : {}".format(movie))
    except Exception:
        dlg.close()
        _error("Render preparation failed (could not render frames or capture the "
               "playblast). Render with Seedance needs a valid playblast for "
               "faithful motion.\n\n" + traceback.format_exc())
        return

    # Confirm to the artist exactly what was rendered and where it lives.
    cmds.inViewMessage(
        amg="Rendered <hl>{}</hl> {} frame(s) -> {}".format(
            len(ref_paths), renderer, img_dir),
        pos="midCenterTop", fade=True, fadeStayTime=3000)

    # -- Phase 2: upload + submit + poll, ON A WORKER THREAD (network only) ----
    dlg.setLabelText("Uploading references and submitting to Seedance...")
    QtWidgets.QApplication.processEvents()

    poster = ref_paths[0] if ref_paths else None     # first Arnold frame = poster

    def make_video(p):                               # re-runnable with a new prompt
        # The playblast is mandatory and attached. Reference it DIRECTLY (the
        # API's reference_video role); require_motion_video makes a failed upload
        # FAIL LOUDLY (retry) instead of degrading -- Render must be faithful.
        final = ("Strictly follow the motion, movement path, camera work and "
                 "timing of the reference video; the reference video provides "
                 "ONLY the motion, not the look.  " + p)
        return _seedance_generate(final, ref_paths, movie, duration,
                                  require_motion_video=True, fit_motion=True)

    worker = _Worker(lambda: make_video(prompt), parent=_main_window())
    worker.done.connect(lambda vb: (dlg.close(),
                        _add_video_result(vb, poster, make_video, prompt=prompt)))
    worker.failed.connect(lambda tb: (dlg.close(), _error(tb)))
    worker.start()
    render_with_seedance._w = worker  # keep ref alive


# =============================================================================
# Feature 2 -- Dream with Seedreams 5.0
# =============================================================================
def _image_size():
    """Exact 'WxH' size for the configured Dream/Refine image aspect (falls back
    to descriptive '2K' if the aspect isn't in the table)."""
    return CONFIG.IMAGE_DIMS.get(CONFIG.IMAGE_RATIO, "2K")


def _seedream(prompt: str, ref_uris: list[str] | None = None, size: str = "2K",
              return_url: bool = False, model: str | None = None):
    """One synchronous Seedream image generation. `ref_uris` are reference-image
    URLs/data-URIs (already passed through _asset_uri).

    Returns image bytes by default. With return_url=True returns (bytes, url)
    where `url` is the original Seedream platform URL -- needed to keep the
    biometric trust chain intact when feeding the image to Seedance."""
    m = model or CONFIG.SEEDREAM_MODEL

    def _call(fmt):
        def _post(sz):
            body = {
                "model": m,
                "prompt": prompt,
                "size": sz,
                "response_format": fmt,
                "watermark": CONFIG.WATERMARK,   # False -> no "AI generated" stamp
            }
            if ref_uris:
                body["image"] = ref_uris
            return _request("POST", CONFIG.BASE_URL + CONFIG.IMAGE_GEN, body)
        try:
            return _post(size)
        except RuntimeError as e:
            # Self-healing: if an exact "WxH" size is rejected, fall back to the
            # descriptive "2K" (the previous behaviour) so generation never breaks.
            if size != "2K" and any(s in str(e) for s in
                                    ("size", "Size", "InvalidParameter", "resolution")):
                sys.stderr.write("[BYTEPLUS] size '{}' rejected; retrying with "
                                 "'2K'.\n".format(size))
                return _post("2K")
            raise

    if return_url:
        # Prefer a platform URL (keeps the face trust chain for Animate). But
        # URL responses get stricter output moderation -- if that rejects it,
        # fall back to bytes so Dream still succeeds (url unavailable).
        try:
            resp = _call("url")
        except RuntimeError as e:
            if "SensitiveContent" in str(e) or "OutputImage" in str(e):
                sys.stderr.write("[BYTEPLUS] URL response was moderated; "
                                 "falling back to bytes (Animate trust chain "
                                 "won't be available for this image).\n")
                resp = _call("b64_json")
            else:
                raise
    else:
        resp = _call("b64_json")

    _track("images", resp, m)
    item = resp["data"][0]
    url = item.get("url")
    data = base64.b64decode(item["b64_json"]) if item.get("b64_json") \
        else _get_bytes(url)
    return (data, url) if return_url else data


# Mode directives -- the two modalities differ only by this preamble (Seedream
# has no documented "reference strength" param, so modes are prompt-driven).
MODE_AROUND = (   # Mode 1: dream AROUND the reference
    "Use the attached reference image as the authoritative guide for the camera "
    "angle, framing, composition AND the subjects/content present. Keep that "
    "layout, viewpoint and the subjects' poses and placement. Realize it as a "
    "finished, photorealistic image. Scene direction:\n\n")
MODE_LAYOUT = (   # Mode 2: use the LAYOUT only
    "Use the attached reference image ONLY for the camera angle, framing and "
    "spatial layout (where things sit in the frame). Do NOT copy its content, "
    "materials or look -- freely reinterpret the scene as described below, "
    "keeping only that composition:\n\n")

# Two-image variants: when an Extra reference is supplied, image 1 (viewport) and
# image 2 (extra) get distinct roles so Seedream actually uses the extra image.
MODE_AROUND_EXTRA = (   # Mode 1 + extra: viewport = pose/framing, extra = look
    "Two reference images are attached. Reproduce the EXACT pose, body "
    "orientation, limb positions and placement of the figure in the FIRST image, "
    "and keep its camera angle, framing and composition. Render that figure with "
    "the design and appearance of the SECOND image -- its identity, colors, "
    "materials and details. In short: POSE, FRAMING and COMPOSITION come from "
    "image 1; the LOOK and CHARACTER come from image 2. Realize it as a finished, "
    "photorealistic image. Scene direction:\n\n")
MODE_LAYOUT_EXTRA = (   # Mode 2 + extra: extra IS the subject placed into the layout
    "Two reference images are attached. Use the FIRST image ONLY for the camera "
    "angle, framing and spatial layout (where things sit in the frame) -- do NOT "
    "copy its content or look. Use the SECOND image as the authoritative reference "
    "for the MAIN SUBJECT/CHARACTER: faithfully reproduce its identity, design, "
    "colors, materials and details, and place that subject into the first image's "
    "composition. Reinterpret the surrounding scene as described below:\n\n")

_REPLACE_TEMPLATE = ("Replace the mannequin(s)/placeholder figure(s) with "
                     "<describe what each becomes>. ")


class DreamDialog(QtWidgets.QDialog):
    """Collects the Dream intent: viewport ref, optional extra ref, mode, and a
    resizable word-wrapping prompt with an auto-prompt button."""

    # Optional camera controls -> phrases appended to the prompt (look only;
    # they do NOT change the canvas aspect, which is set by Image aspect ratio).
    _LENS = {
        "Lens: auto": "",
        "From Maya camera": "",            # special-cased in camera(): reads focalLength
        "Anamorphic": "anamorphic lens",
        "Fisheye": "fisheye lens, strong barrel distortion",
        "16mm ultra-wide": "16mm ultra-wide-angle lens",
        "24mm wide": "24mm wide-angle lens", "35mm": "35mm lens",
        "50mm": "50mm lens", "85mm portrait": "85mm portrait lens",
        "135mm telephoto": "135mm telephoto lens",
        "Macro": "macro lens, extreme close focus",
        "Tilt-shift": "tilt-shift lens, miniature look",
    }
    _SHOT = {
        "Shot: auto": "", "Wide establishing": "wide establishing shot",
        "Medium": "medium shot", "Close-up": "close-up shot",
        "Extreme close-up": "extreme close-up shot",
        "Over-the-shoulder": "over-the-shoulder shot",
        "Two-shot": "two-shot framing",
        "Low angle": "low-angle shot", "High angle": "high-angle shot",
        "Dutch angle": "dutch-angle tilted shot",
        "POV": "first-person POV shot",
        "Bird's-eye": "bird's-eye top-down view",
        "Aerial / top-down": "aerial top-down shot",
    }
    _LOOK = {
        "Look: auto": "", "Cinematic": "cinematic lighting, filmic color grade",
        "Golden hour": "warm golden-hour lighting",
        "Blue hour": "cool blue-hour twilight lighting",
        "Moody / low-key": "moody low-key lighting, dramatic shadows",
        "High-key bright": "bright high-key lighting",
        "Neon / cyberpunk": "neon cyberpunk lighting, vivid colored glow",
        "Rim / backlight": "strong rim backlighting, glowing edges",
        "Volumetric god-rays": "volumetric lighting, visible god rays",
        "Overcast soft": "soft overcast diffused lighting",
        "Teal & orange": "teal-and-orange color grade",
        "Noir B&W": "black-and-white film noir, high contrast",
        "Film grain": "subtle film grain",
        "Lens flare": "anamorphic lens flare",
        "Shallow DOF / bokeh": "shallow depth of field, creamy bokeh",
    }

    def camera(self):
        """Selected camera modifiers as a prompt suffix (or '')."""
        lens_key = self.cam_lens.currentText()
        if lens_key == "From Maya camera":
            fl = _maya_focal_length()
            lens = "{:.0f}mm lens".format(fl) if fl else ""
        else:
            lens = self._LENS.get(lens_key, "")
        parts = [lens,
                 self._SHOT.get(self.cam_shot.currentText(), ""),
                 self._LOOK.get(self.cam_look.currentText(), "")]
        parts = [p for p in parts if p]
        return (".  " + ", ".join(parts) + ".") if parts else ""

    def __init__(self, snapshot_path, parent=None, initial_prompt=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS - Dream with Seedream 5.0")
        self.setMinimumSize(580, 640)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._snap = snapshot_path
        self._extra = None
        self._cap_worker = None
        v = QtWidgets.QVBoxLayout(self)

        # --- reference thumbnails -------------------------------------------
        refs = QtWidgets.QHBoxLayout()
        vb = QtWidgets.QVBoxLayout()
        vb.addWidget(QtWidgets.QLabel("Viewport reference"))
        self.vp_thumb = QtWidgets.QLabel()
        self.vp_thumb.setFixedSize(240, 135)
        self.vp_thumb.setStyleSheet("background:#1d1d1d;")
        self.vp_thumb.setPixmap(QtGui.QPixmap(snapshot_path).scaled(
            240, 135, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        vb.addWidget(self.vp_thumb)
        refs.addLayout(vb)

        eb = QtWidgets.QVBoxLayout()
        ex_label = QtWidgets.QLabel("Extra reference (optional)")
        ex_tip = ("A second reference image used together with the viewport.\n"
                  "• 'Dream AROUND' mode: keeps the viewport figure's POSE, framing "
                  "and composition, and applies THIS image's LOOK (identity, "
                  "colors, materials) to it.\n"
                  "• 'Use the LAYOUT only' mode: THIS image becomes the main "
                  "subject in its own pose, placed into the viewport's composition.")
        ex_label.setToolTip(ex_tip)
        eb.addWidget(ex_label)
        self.ex_thumb = QtWidgets.QLabel("(none)")
        self.ex_thumb.setAlignment(QtCore.Qt.AlignCenter)
        self.ex_thumb.setFixedSize(240, 135)
        self.ex_thumb.setStyleSheet("background:#1d1d1d; color:#888;")
        self.ex_thumb.setToolTip(ex_tip)
        eb.addWidget(self.ex_thumb)
        erow = QtWidgets.QHBoxLayout()
        self._b_browse = QtWidgets.QPushButton("Browse...")
        self._b_browse.clicked.connect(self._browse)
        self._b_clear = QtWidgets.QPushButton("Clear")
        self._b_clear.clicked.connect(self._clear_extra)
        erow.addWidget(self._b_browse); erow.addWidget(self._b_clear)
        eb.addLayout(erow)
        refs.addLayout(eb)
        v.addLayout(refs)

        # --- Text-to-Image (face-safe) --------------------------------------
        self.cb_text_only = QtWidgets.QCheckBox(
            "Text-to-Image (ignore the viewport) — required for AI human faces / "
            "portraits")
        self.cb_text_only.setToolTip(
            "Generates purely from your text prompt, with NO viewport/extra "
            "reference. Seedance only accepts faces that come from a Seedream "
            "text-to-image output on this same account (the moderation-exemption "
            "path). Viewport-guided (image-to-image) faces need KYC HIGH. Real "
            "human faces are never allowed — only AI-generated people.")
        self.cb_text_only.toggled.connect(self._on_text_only)
        v.addWidget(self.cb_text_only)

        # --- mode ------------------------------------------------------------
        v.addWidget(QtWidgets.QLabel("<b>Mode</b>"))
        self.mode_around = QtWidgets.QRadioButton(
            "Dream AROUND the reference  (keep subjects + layout, just finish it)")
        self.mode_around.setChecked(True)
        self.mode_layout = QtWidgets.QRadioButton(
            "Use the LAYOUT only  (same composition, reinterpret the content)")
        v.addWidget(self.mode_around)
        v.addWidget(self.mode_layout)

        # --- prompt ----------------------------------------------------------
        ph = QtWidgets.QHBoxLayout()
        ph.addWidget(QtWidgets.QLabel("<b>Prompt</b>"))
        ph.addStretch(1)
        b_tpl = QtWidgets.QPushButton("Insert replace template")
        b_tpl.clicked.connect(self._insert_template)
        self.b_enhance = QtWidgets.QPushButton("✦ Enhance")
        self.b_enhance.setToolTip("Improve the scene/subject wording only — "
                                  "camera & look are set by the Camera dropdowns")
        self.b_enhance.clicked.connect(self._enhance)
        self.b_auto = QtWidgets.QPushButton("✨ Auto")
        self.b_auto.setToolTip("Write a prompt from scratch by analyzing the viewport")
        self.b_auto.clicked.connect(self._auto)
        ph.addWidget(b_tpl); ph.addWidget(self.b_enhance); ph.addWidget(self.b_auto)
        v.addLayout(ph)

        self.prompt = QtWidgets.QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Describe what you want (subject, lighting, lens, style). "
            "Use '✨ Auto' to draft it from the viewport.")
        v.addWidget(self.prompt, 1)
        _add_dictate_button(ph, self.prompt)     # prompt now exists -> safe
        if initial_prompt:                       # e.g. handed over from Seed Chat
            self.prompt.setPlainText(initial_prompt)

        # --- camera controls (optional, appended to the prompt) --------------
        cam = QtWidgets.QHBoxLayout()
        cam.addWidget(QtWidgets.QLabel("Camera:"))
        self.cam_lens = QtWidgets.QComboBox()
        self.cam_lens.addItems(list(self._LENS.keys()))
        self.cam_shot = QtWidgets.QComboBox()
        self.cam_shot.addItems(list(self._SHOT.keys()))
        self.cam_look = QtWidgets.QComboBox()
        self.cam_look.addItems(list(self._LOOK.keys()))
        for w in (self.cam_lens, self.cam_shot, self.cam_look):
            cam.addWidget(w, 1)
        v.addLayout(cam)

        tip = QtWidgets.QLabel("Tips: subject · composition · lighting · "
                               "lens · style  (<600 words)")
        tip.setStyleSheet("color:#888;")
        v.addWidget(tip)

        # --- variations: how many different images to generate at once --------
        varrow = QtWidgets.QHBoxLayout()
        varrow.addWidget(QtWidgets.QLabel("Variations:"))
        self.cb_variations = QtWidgets.QComboBox()
        for k in ("1", "2", "4", "6", "8"):
            self.cb_variations.addItem(k, int(k))
        self.cb_variations.setCurrentText("4")
        self.cb_variations.setToolTip("How many different images to generate at "
                                      "once. Each is billed separately. "
                                      "Regenerate still makes one at a time.")
        varrow.addWidget(self.cb_variations)
        varrow.addStretch(1)
        v.addLayout(varrow)

        if CONFIG.SHOW_COST:
            self.cost = QtWidgets.QLabel()
            self.cost.setStyleSheet("color:#2E8BE6; font-weight:bold;")
            v.addWidget(self.cost)

            def _upd_cost():
                nv = self.variations()
                self.cost.setText("{}  ({} image{})".format(
                    _fmt_cost(0, _est_image_cost(nv)), nv, "s" if nv > 1 else ""))
            self.cb_variations.currentIndexChanged.connect(_upd_cost)
            _upd_cost()

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Generate")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    # -- controls ------------------------------------------------------------
    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a reference image", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self._extra = path
            self.ex_thumb.setPixmap(QtGui.QPixmap(path).scaled(
                240, 135, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _clear_extra(self):
        self._extra = None
        self.ex_thumb.clear()
        self.ex_thumb.setText("(none)")

    def _on_text_only(self, on):
        # T2I ignores every reference, so grey out the reference/mode controls
        # and drop any extra reference the user had picked.
        for w in (self.mode_around, self.mode_layout, self._b_browse, self._b_clear):
            w.setEnabled(not on)
        if on:
            self._clear_extra()

    def _insert_template(self):
        self.prompt.insertPlainText(_REPLACE_TEMPLATE)
        self.prompt.setFocus()

    def _auto(self):
        self.b_auto.setEnabled(False)
        self.b_auto.setText("Analyzing...")
        uri = _data_uri(self._snap, "image/png")
        self._cap_worker = _Worker(lambda: _caption_viewport(uri), parent=self)

        def done(text):
            self.prompt.setPlainText(text)
            self.b_auto.setEnabled(True)
            self.b_auto.setText("✨ Auto")

        def fail(tb):
            self.b_auto.setEnabled(True)
            self.b_auto.setText("✨ Auto")
            _error("Auto-prompt failed:\n\n" + tb)

        self._cap_worker.done.connect(done)
        self._cap_worker.failed.connect(fail)
        self._cap_worker.start()

    def _enhance(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            cmds.inViewMessage(amg="Type a prompt first, then <hl>✦ Enhance</hl>.",
                               pos="midCenter", fade=True)
            return
        self.b_enhance.setEnabled(False)
        self.b_enhance.setText("Enhancing...")
        # SCENE/SUBJECT ONLY: improves the content wording, never camera/lighting/
        # look (those are owned by the Camera dropdowns) -> no conflict between
        # the enhanced text and the dropdown selections.
        self._enh_worker = _Worker(lambda: _enhance_scene(text), parent=self)

        def done(t):
            if t:
                self.prompt.setPlainText(t)          # Ctrl+Z restores the original
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")

        def fail(tb):
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")
            _error("Enhance failed:\n\n" + tb)

        self._enh_worker.done.connect(done)
        self._enh_worker.failed.connect(fail)
        self._enh_worker.start()

    # -- getters -------------------------------------------------------------
    def prompt_text(self):
        return self.prompt.toPlainText().strip()

    def directive(self, has_extra=False):
        layout_only = self.mode_layout.isChecked()
        if has_extra:                            # two images -> role-aware preamble
            return MODE_LAYOUT_EXTRA if layout_only else MODE_AROUND_EXTRA
        return MODE_LAYOUT if layout_only else MODE_AROUND

    def variations(self):
        return int(self.cb_variations.currentData() or 1)

    def text_only(self):
        return self.cb_text_only.isChecked()

    def extra_ref(self):
        return self._extra


class RefineDialog(QtWidgets.QDialog):
    """Edit-instruction dialog for Refine, with a text-only ✦ Enhance that
    sharpens the instruction (without turning it into a full scene prompt)."""

    def __init__(self, parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("Refine image")
        self.setMinimumSize(480, 280)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._worker = None
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel(
            "Describe the change to apply to this image\n"
            "(e.g. 'add visible dunes and mountains in the distance'):"))
        self.prompt = QtWidgets.QPlainTextEdit()
        v.addWidget(self.prompt, 1)
        hb = QtWidgets.QHBoxLayout()
        self.b_enhance = QtWidgets.QPushButton("✦ Enhance")
        self.b_enhance.setToolTip("Sharpen your edit instruction (text only — "
                                  "keeps it an instruction, won't restyle)")
        self.b_enhance.clicked.connect(self._enhance)
        hb.addWidget(self.b_enhance)
        _add_dictate_button(hb, self.prompt)
        hb.addStretch(1)
        v.addLayout(hb)
        if CONFIG.SHOW_COST:
            cost = QtWidgets.QLabel(_fmt_cost(0, _est_image_cost(1)) + "  (per image)")
            cost.setStyleSheet("color:#2E8BE6; font-weight:bold;")
            v.addWidget(cost)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Apply")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _enhance(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            cmds.inViewMessage(amg="Type an edit first, then <hl>✦ Enhance</hl>.",
                               pos="midCenter", fade=True)
            return
        self.b_enhance.setEnabled(False)
        self.b_enhance.setText("Enhancing...")
        self._worker = _Worker(lambda: _enhance_edit(text), parent=self)

        def done(t):
            if t:
                self.prompt.setPlainText(t)
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")

        def fail(tb):
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")
            _error("Enhance failed:\n\n" + tb)

        self._worker.done.connect(done)
        self._worker.failed.connect(fail)
        self._worker.start()

    def text(self):
        return self.prompt.toPlainText().strip()


class DreamGallery(QtWidgets.QDialog):
    """Holds every Dream result (this session + previous ones loaded from disk),
    with regenerate, save, and animate. Stays on top of Maya."""

    def __init__(self, regen, img_dir, parent=None, variations=1):
        super().__init__(parent or _main_window())
        self.setWindowTitle(_usage_title("BYTEPLUS - Dream Gallery"))
        self.setMinimumSize(760, 660)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._regen = regen           # callable -> {"bytes","path","url"}
        self._img_dir = img_dir
        self._variations = max(1, int(variations))   # initial-batch size
        self._items = []
        self._current = None
        self._worker = None
        self._batch_workers = []      # keep parallel-variation workers alive

        v = QtWidgets.QVBoxLayout(self)
        self.view = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self.view.setStyleSheet("background:#1d1d1d;")
        self.view.setMinimumHeight(380)
        v.addWidget(self.view, 1)
        self._ov = _overlay_button(self.view, self._prompt)   # floating Prompt button
        QtCore.QTimer.singleShot(0, lambda: _place_overlay(self.view, self._ov))

        self.strip = QtWidgets.QListWidget()
        self.strip.setViewMode(QtWidgets.QListView.IconMode)
        self.strip.setFlow(QtWidgets.QListView.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setFixedHeight(118)
        self.strip.setIconSize(QtCore.QSize(160, 90))
        self.strip.setMovement(QtWidgets.QListView.Static)
        self.strip.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.strip.itemClicked.connect(self._on_select)
        v.addWidget(self.strip)

        row = QtWidgets.QHBoxLayout()
        b_regen = QtWidgets.QPushButton("\U0001F504 Regenerate")
        b_regen.setToolTip("New variation of the same prompt")
        b_regen.clicked.connect(self.generate)
        self._b_regen = b_regen                      # kept so rebind() can toggle it
        if regen is None:                            # opened standalone (no Dream)
            b_regen.setEnabled(False)
            b_regen.setToolTip("Run 'Dream with Seedreams 5.0' to enable. "
                               "You can still Refine/Animate existing images.")
        b_refine = QtWidgets.QPushButton("✏ Refine")
        b_refine.setToolTip("Edit the selected image with a comment "
                            "(e.g. 'make it night', 'add a robot')")
        b_refine.clicked.connect(self._refine)
        b_import = QtWidgets.QPushButton("\U0001F4C2 Import")
        b_import.setToolTip("Bring in external image(s) to refine or animate")
        b_import.clicked.connect(self._import)
        b_save = QtWidgets.QPushButton("\U0001F4BE Save As...")
        b_save.clicked.connect(self._on_save)
        b_del = QtWidgets.QPushButton("\U0001F5D1 Delete")
        b_del.clicked.connect(self._delete)
        b_cmp = QtWidgets.QPushButton("⇄ Compare")
        b_cmp.setToolTip("Select two images (Ctrl/Shift-click) then Compare — or "
                         "compare the current one against another. Drag slider "
                         "(A/B wipe).")
        b_cmp.clicked.connect(self._compare)
        b_clear = QtWidgets.QPushButton("Clear all")
        b_clear.clicked.connect(self._clear_all)
        b_anim = QtWidgets.QPushButton("Animate with Seedance →")
        b_anim.clicked.connect(self._on_animate)
        b_close = QtWidgets.QPushButton("Close")
        b_close.clicked.connect(self.accept)
        for b in (b_regen, b_refine, b_import, b_save, b_cmp, b_del, b_clear, b_anim):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_close)
        v.addLayout(row)

        self._load_existing()

    def _load_existing(self):
        import glob
        hidden = _load_hidden()
        scene = _scene_tag()
        for f in sorted(glob.glob(os.path.join(self._img_dir, "*dream*.png"))):
            base = os.path.basename(f)
            # strip the scene prefix before checking tokens, so a scene whose
            # name contains 'ref'/'anim' can't be misclassified.
            tail = base[len(scene):] if base.startswith(scene) else base
            if "ref" in tail or "anim" in tail:
                continue                       # those are inputs, not results
            if f in hidden:
                continue                       # cleared earlier without disk delete
            try:
                with open(f, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            # Restore the trusted platform URL + the saved prompt from sidecars.
            self._add(data, f, _read_url_sidecar(f), select=False,
                      prompt=_read_prompt_sidecar(f))
        if self._items:
            self.strip.setCurrentRow(self.strip.count() - 1)
            self._show(self._items[-1])

    def rebind(self, regen, img_dir, variations=1):
        """Reuse this open gallery for a new Dream/open instead of spawning a new
        window: swap the generator + folder and reload the current scene."""
        self._regen = regen
        self._img_dir = img_dir
        self._variations = max(1, int(variations))
        self._b_regen.setEnabled(regen is not None)
        self.strip.clear()
        self._items = []
        self._current = None
        self.view.clear()
        self._load_existing()

    def _add(self, data, path, url, select=True, prompt=None, t2i=None):
        # t2i: True = trusted Text-to-Image output (a face in it is animatable);
        # False = refine/edit/import/viewport-guided (image-to-image -> a face needs
        # KYC HIGH, Seedance rejects it); None = unknown (loaded from disk).
        item = {"bytes": data, "path": path, "url": url, "prompt": prompt, "t2i": t2i}
        _write_url_sidecar(path, url)            # persist the trusted URL (if any)
        _write_prompt_sidecar(path, prompt)      # persist the prompt used (if any)
        self._items.append(item)
        pix = QtGui.QPixmap()
        pix.loadFromData(data)
        lw = QtWidgets.QListWidgetItem(QtGui.QIcon(pix), "")   # no filename label
        lw.setToolTip(os.path.basename(path))    # name on hover instead
        lw.setData(QtCore.Qt.UserRole, item)     # store the dict, not an index
        self.strip.addItem(lw)
        self.setWindowTitle(_usage_title("BYTEPLUS - Dream Gallery"))
        if select:
            self.strip.setCurrentItem(lw)
            self._show(item)

    def _show(self, item):
        self._current = item
        pix = QtGui.QPixmap()
        pix.loadFromData(item["bytes"])
        self.view.setPixmap(pix.scaled(900, 600, QtCore.Qt.KeepAspectRatio,
                                       QtCore.Qt.SmoothTransformation))

    def _on_select(self, lw):
        self._show(lw.data(QtCore.Qt.UserRole))

    def _delete(self):
        lw = self.strip.currentItem()
        if not lw:
            return
        item = lw.data(QtCore.Qt.UserRole)
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("BYTEPLUS - Delete image")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText("Remove '{}' from the gallery?".format(
            os.path.basename(item["path"])))
        cb = QtWidgets.QCheckBox("Also delete the file from disk")
        cb.setChecked(True)
        box.setCheckBox(cb)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        if box.exec() != QtWidgets.QMessageBox.Ok:
            return
        if cb.isChecked():
            for p in (item["path"], item["path"] + ".url", item["path"] + ".txt"):
                try:
                    os.remove(p)
                except OSError:
                    pass
        else:
            _hide_paths([item["path"]])          # keep it off the gallery on reopen
        if item in self._items:
            self._items.remove(item)
        self.strip.takeItem(self.strip.row(lw))
        nxt = self.strip.currentItem()
        if nxt:
            self._show(nxt.data(QtCore.Qt.UserRole))
        else:
            self.view.clear()
            self._current = None

    def _clear_all(self):
        if not self._items:
            return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("BYTEPLUS - Clear gallery")
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setText("Remove ALL {} images from the gallery?".format(len(self._items)))
        cb = QtWidgets.QCheckBox("Also delete the files from disk")
        cb.setChecked(False)                     # safer default for bulk delete
        box.setCheckBox(cb)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        if box.exec() != QtWidgets.QMessageBox.Ok:
            return
        if cb.isChecked():
            for it in self._items:
                for p in (it["path"], it["path"] + ".url", it["path"] + ".txt"):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        else:
            _hide_paths([it["path"] for it in self._items])   # stay cleared on reopen
        self._items = []
        self.strip.clear()
        self.view.clear()
        self._current = None

    def _run(self, fn, label="Dreaming with Seedream 5.0..."):
        """Run a generation callable -> {bytes,path,url} in a worker and append
        the result. Shared by Regenerate and Refine."""
        prog = _progress(label)

        def done(res):
            prog.close()
            self._add(res["bytes"], res["path"], res["url"],
                      prompt=res.get("prompt"), t2i=res.get("t2i"))

        def fail(tb):
            prog.close()
            _error(tb)

        self._worker = _Worker(fn, parent=self)
        self._worker.done.connect(done)
        self._worker.failed.connect(fail)
        self._worker.start()

    def generate(self):
        """Regenerate: a single fresh variation of the original Dream prompt."""
        if not self._regen:
            return
        self._run(self._regen)

    def generate_batch(self):
        """Initial Dream generation: produce self._variations DIFFERENT images in
        parallel (each an independent Seedream call). Regenerate stays single."""
        if not self._regen:
            return
        n = max(1, int(getattr(self, "_variations", 1)))
        if n <= 1:
            self._run(self._regen)
            return
        if not _confirm_cost(_est_image_cost(n),
                             "Dream -> {} image variations.".format(n)):
            return
        self._run_many(self._regen, n)

    def _run_many(self, fn, n, label="Dreaming with Seedream 5.0..."):
        """Run `fn` (-> {bytes,path,url}) n times in parallel, appending each
        result to the gallery as it finishes. One progress dialog tracks all n."""
        prog = _progress("{} (0/{})".format(label, n))
        self._batch_workers = []
        st = {"completed": 0, "failed": 0}

        def _tick():
            st["completed"] += 1
            try:
                prog.setLabelText("{} ({}/{})".format(label, st["completed"], n))
            except Exception:
                pass
            if st["completed"] >= n:
                prog.close()
                self._batch_workers = []
                if st["failed"] == n:
                    _error("All variations failed. See the Script Editor.")

        def _ok(res):
            try:
                self._add(res["bytes"], res["path"], res["url"],
                          prompt=res.get("prompt"), t2i=res.get("t2i"))
            finally:
                _tick()

        def _bad(tb):
            st["failed"] += 1
            sys.stderr.write("[BYTEPLUS] a Dream variation failed:\n" + tb + "\n")
            _tick()

        for _ in range(n):
            # All N variations share the batch's cancel token, so the single ✕ on
            # the HUD row cancels (discards) the whole batch at once.
            w = _Worker(fn, parent=self, cancel_event=prog.cancel)
            w.done.connect(_ok)
            w.failed.connect(_bad)
            self._batch_workers.append(w)
            w.start()

    def _refine(self):
        """Edit the SELECTED image with a free-text comment, as a new variation."""
        if not self._current:
            return
        d = RefineDialog(self)
        if not d.exec():
            return
        comment = d.text()
        if not comment:
            return
        # Refine is a normal Seedream image edit -- it does NOT need the trust
        # chain, so use the LOCAL file (the saved platform URL expires in ~24h and
        # would 403). Fall back to the URL only if there's no local file.
        ref = self._current.get("path") or self._current.get("url")
        img_dir = self._img_dir

        def fn():
            ref_uri = ref if (isinstance(ref, str) and ref.startswith("http")) \
                else _asset_uri(ref, _image_mime(ref))
            prompt = ("Edit the attached image. Keep the same composition, "
                      "subjects and overall style, and apply ONLY this change: "
                      + comment)
            data, url = _seedream(prompt, [ref_uri], size=_image_size(),
                                  return_url=True)
            if _cancel_requested():                  # discard, no orphan file
                raise _Cancelled()
            out = _unique_path(img_dir, "byteplus_dream")
            with open(out, "wb") as f:
                f.write(data)
            # t2i=False: Refine is an image-to-image edit -> the result is NOT a
            # trusted Text-to-Image output, so a face in it can't be animated
            # (Seedance needs KYC HIGH for image-to-image faces).
            return {"bytes": data, "path": out, "url": url,
                    "prompt": "Refine: " + comment, "t2i": False}

        self._run(fn, label="Refining image with Seedream 5.0...")

    def _on_save(self):
        if not self._current:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save As", "seedream_result.png", "PNG (*.png);;JPEG (*.jpg)")
        if path:
            with open(path, "wb") as f:
                f.write(self._current["bytes"])
            cmds.inViewMessage(amg="Saved <hl>{}</hl>".format(path),
                               pos="midCenter", fade=True)

    def _selected_items(self):
        """Selected strip items (their dicts), in row order."""
        out = []
        for i in range(self.strip.count()):
            lw = self.strip.item(i)
            if lw and lw.isSelected():
                out.append(lw.data(QtCore.Qt.UserRole))
        return out

    def _compare(self):
        """A/B wipe between two images. Uses two selected images if exactly two are
        selected; otherwise compares the current image against one you pick."""
        sel = self._selected_items()
        if len(sel) == 2:
            a, b = sel[0], sel[1]
        else:
            if not self._current:
                return
            others = [it for it in self._items if it is not self._current]
            if not others:
                _error("Select two images (Ctrl/Shift-click), or have a second "
                       "image in the gallery, to compare.")
                return
            picked = _pick_gallery_image(others, self, warn_trust=False)
            if not picked:
                return
            a, b = self._current, picked
        a_src = a.get("bytes") or a.get("path")
        b_src = b.get("bytes") or b.get("path")
        ABCompareDialog(a_src, b_src, "A", "B", parent=self).exec()

    def _on_animate(self):
        if not self._current:
            return
        # Prefer the platform URL (keeps the face trust chain) -- but ONLY while
        # it's still fresh; a pre-signed Seedream URL expires in ~24h and would
        # 403. Once stale, fall back to the local file. The local path is also
        # handed over as the Video Gallery poster.
        url = self._current.get("url")
        fresh = bool(url and _url_is_fresh(url))
        ref = url if fresh else self._current.get("path")
        # Diagnostic: a FACE only survives Seedance moderation when we send a FRESH
        # trusted Seedream platform URL. If this logs 'LOCAL FILE', the image wasn't
        # made with Dream > Text-to-Image, or is >24h old, or was imported -->
        # regenerate it (Dream > Text-to-Image) and animate within ~24h.
        t2i = self._current.get("t2i")
        sys.stderr.write("[BYTEPLUS] Animate source = {} (fresh trusted URL: {}, "
                         "T2I origin: {}).\n".format(
                             "platform URL" if fresh else "LOCAL FILE (re-uploaded)",
                             fresh, t2i))
        # Proactive face-trust warning. A face survives Seedance moderation ONLY as a
        # FRESH, trusted Text-to-Image Seedream output. Refined/edited/imported
        # (image-to-image) faces need KYC HIGH; a stale/re-uploaded URL loses trust.
        warn = None
        if t2i is False:
            warn = ("This image was refined / edited / imported (image-to-image), so "
                    "it is NOT a trusted Text-to-Image output.\n\nIf it contains a "
                    "HUMAN FACE, Seedance will REJECT it unless your BytePlus account "
                    "has KYC HIGH.\n\nTo animate a face, regenerate it with  "
                    "Dream ▸ Text-to-Image  (put your change in the prompt).\n\n"
                    "Objects and scenes without faces animate fine.\n\nContinue anyway?")
        elif not fresh:
            warn = ("This image has no fresh trusted Seedream link — it wasn't made "
                    "with Dream ▸ Text-to-Image, or it's over ~24h old, or it was "
                    "imported.\n\nIf it contains a HUMAN FACE, Seedance will REJECT "
                    "it. To animate a face: regenerate it with  Dream ▸ Text-to-Image"
                    "  and animate within ~24h.\n\nObjects and scenes without faces "
                    "animate fine.\n\nContinue anyway?")
        if warn and _msgbox(
                QtWidgets.QMessageBox.Warning, "BYTEPLUS - face may be rejected", warn,
                QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel
                ) != QtWidgets.QMessageBox.Ok:
            return
        vg = getattr(_video_gallery, "_inst", None)
        video_items = list(vg._items) if vg is not None else []
        animate_with_seedance(ref or url, poster_path=self._current.get("path"),
                              dream_items=list(self._items),
                              video_items=video_items)

    def _prompt(self):
        if self._current:
            _show_prompt(self, self._current.get("prompt"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "_ov", None):
            _place_overlay(self.view, self._ov)

    def _import(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Import image(s)", "", "Images (*.png *.jpg *.jpeg *.webp)")
        for p in paths:
            ext = os.path.splitext(p)[1].lower() or ".png"
            dst = _unique_path(self._img_dir, _scene_tag() + "_dream_import", ext=ext)
            try:
                with open(p, "rb") as src:
                    data = src.read()
                with open(dst, "wb") as out:
                    out.write(data)
            except OSError as e:
                _error("Could not import {}:\n{}".format(p, e))
                continue
            self._add(data, dst, None, select=True, t2i=False)  # imported -> not T2I-trusted


def dream_with_seedream(initial_prompt=None):
    """Snapshot the viewport, collect intent via DreamDialog, then open the
    persistent Dream Gallery (generate / regenerate / save / animate).

    `initial_prompt` pre-fills the prompt box (used by Seed Chat's 'Send to
    Dream'); the menu still calls this with no arguments."""
    import shutil
    if not _scene_ok_to_proceed():
        return
    snap = _viewport_snapshot()
    d = DreamDialog(snap, initial_prompt=initial_prompt)
    if not d.exec():
        return
    prompt = d.prompt_text()
    if not prompt:
        return
    text_only = d.text_only()                    # T2I: no viewport ref (face-safe)
    extra = None if text_only else d.extra_ref()
    directive = "" if text_only else d.directive(has_extra=bool(extra))
    n_variations = d.variations()                # how many to generate at once
    prompt = prompt + d.camera()                 # append optional camera modifiers
    img_dir = _scene_images_dir()                # images/byteplus/<scene>/
    scene = _scene_tag()

    def regen():
        # Text-to-Image: pure prompt, NO reference image -> the Seedream output is
        # a trusted input for Seedance (moderation-exemption path for AI faces).
        ref_uris = None
        if not text_only:
            # persist the exact reference we send, so the artist can inspect it
            ref_path = _unique_path(img_dir, scene + "_dream_ref")
            shutil.copyfile(snap, ref_path)
            ref_uris = [_asset_uri(ref_path, "image/png")]
            if extra:
                ref_uris.append(_asset_uri(extra, _image_mime(extra)))
        # return_url=True keeps the platform URL for trust-preserving Animate.
        # Text-to-Image (face-safe) uses Seedream 5.0 Lite so the AI face is a
        # TRUSTED input for Seedance (base 5.0 faces are rejected -- see CONFIG).
        data, url = _seedream(directive + prompt, ref_uris, size=_image_size(),
                              return_url=True,
                              model=(CONFIG.SEEDREAM_FACE_MODEL if text_only else None))
        if _cancel_requested():                  # cancelled during the call ->
            raise _Cancelled()                   # discard, don't write an orphan file
        out = _unique_path(img_dir, scene + "_dream")
        with open(out, "wb") as f:
            f.write(data)
        # t2i=text_only: a face-safe Text-to-Image output is a TRUSTED, animatable
        # Seedance input; a viewport-guided (image-to-image) output is not.
        return {"bytes": data, "path": out, "url": url, "prompt": prompt,
                "t2i": text_only}

    gallery = _dream_gallery(regen, img_dir, n_variations)
    gallery.show()
    gallery.raise_()
    gallery.generate_batch()                  # first generation (n variations)


def _dream_gallery(regen, img_dir, variations=1):
    """Return the single Dream Gallery, reusing the open one (reload it for this
    Dream/scene) instead of spawning a new window."""
    g = getattr(_dream_gallery, "_inst", None)
    if g is not None:
        try:
            g.objectName()                   # touch the C++ obj; raises if destroyed
        except Exception:
            g = None
    if g is None:
        g = DreamGallery(regen, img_dir, variations=variations)
        _dream_gallery._inst = g
    else:
        g.rebind(regen, img_dir, variations=variations)
    return g


def open_gallery():
    """Open the Dream Gallery standalone (loads previous images from the project).
    Regenerate is disabled here; Refine and Animate work on existing images."""
    gallery = _dream_gallery(None, _scene_images_dir())
    gallery.show()
    gallery.raise_()


# =============================================================================
# Feature 3 -- Generate Texture (-> OpenPBR shader)
# =============================================================================
class TextureDialog(QtWidgets.QDialog):
    """Prompt box for Generate Texture, with a ✦ Enhance helper (text-only)."""

    def __init__(self, target_label, parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS - Generate Texture")
        self.setMinimumSize(520, 320)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel(
            "Describe the texture for '{}':".format(target_label)))
        self.prompt = QtWidgets.QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "e.g. weathered hammered copper with green patina, seamless, PBR")
        v.addWidget(self.prompt, 1)
        hb = QtWidgets.QHBoxLayout()
        self.b_enhance = QtWidgets.QPushButton("✦ Enhance")
        self.b_enhance.setToolTip("Improve the wording of your material description "
                                  "(keeps your intent; text only)")
        self.b_enhance.clicked.connect(self._enhance)
        hb.addWidget(self.b_enhance)
        _add_dictate_button(hb, self.prompt)
        hb.addStretch(1)
        v.addLayout(hb)
        note = QtWidgets.QLabel(
            "Generates albedo + roughness + normal (+ metalness) and wires them "
            "into a new OpenPBR shader on the object.")
        note.setWordWrap(True); note.setStyleSheet("color:#888;")
        v.addWidget(note)
        if CONFIG.SHOW_COST:
            cost = QtWidgets.QLabel(_fmt_cost(0, _est_image_cost(4)) + "  (4 maps)")
            cost.setStyleSheet("color:#2E8BE6; font-weight:bold;")
            v.addWidget(cost)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Generate")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def text(self):
        return self.prompt.toPlainText().strip()

    def _enhance(self):
        t = self.prompt.toPlainText().strip()
        if not t:
            cmds.inViewMessage(amg="Type a material first, then <hl>✦ Enhance</hl>.",
                               pos="midCenter", fade=True)
            return
        self.b_enhance.setEnabled(False)
        self.b_enhance.setText("Enhancing...")
        self._w = _Worker(lambda: _enhance_texture(t), parent=self)

        def done(out):
            if out:
                self.prompt.setPlainText(out)        # Ctrl+Z restores the original
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")

        def fail(tb):
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")
            _error("Enhance failed:\n\n" + tb)

        self._w.done.connect(done)
        self._w.failed.connect(fail)
        self._w.start()


def generate_texture():
    """Generate a texture for the selected object and wire it into a new
    openPBRSurface shader."""
    sel = cmds.ls(selection=True, long=True)
    if not sel:
        _error("Select an object first.")
        return
    target = sel[0]

    d = TextureDialog(target.split('|')[-1])
    if not d.exec():
        return
    prompt = d.text()
    if not prompt:
        return
    dlg = _progress("Generating PBR map set (albedo / roughness / normal)...")

    # One folder per texture set: images/textures/<material>/<material>_<map>.png
    tex_dir = _texture_dir(target)
    stem = _safe_name(target)

    def _save_map(data: bytes, suffix: str) -> str:
        path = _unique_path(tex_dir, stem + "_" + suffix)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def gen():
        # 1) Albedo from the artist's description (flat, lighting-free so it reads
        #    as base color, not a lit render). Must finish first -- the other
        #    maps reference it for spatial alignment.
        albedo = _seedream(
            prompt + ", seamless tileable PBR base color albedo, flat even "
            "lighting, no cast shadows, no specular highlights, top-down")
        albedo_path = _save_map(albedo, "baseColor")
        albedo_ref = _asset_uri(albedo_path, "image/png")

        # 2) Roughness / normal / metalness generated *from the albedo as a
        #    reference image* so they stay aligned (Seedream reference-consistency).
        #    These are model approximations, not photometric captures. The three
        #    are independent of each other -> fire them concurrently.
        jobs = {
            "specularRoughness":
                "Grayscale roughness map of the exact same surface as the "
                "reference, perfectly aligned, white = rough, black = "
                "smooth/glossy, no color, seamless tileable",
            "normal":
                "Tangent-space normal map of the exact same surface as the "
                "reference, perfectly aligned, dominant blue-purple, encoding "
                "the surface bumps and grooves, seamless tileable",
            "baseMetalness":
                "Grayscale metalness map of the exact same surface as the "
                "reference, perfectly aligned, white = bare metal, black = "
                "non-metal / dielectric, no color, seamless tileable",
        }
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {k: pool.submit(_seedream, p, [albedo_ref])
                       for k, p in jobs.items()}
            results = {k: _save_map(f.result(), k) for k, f in futures.items()}

        results["baseColor"] = albedo_path
        results["_preview"] = albedo
        results["_dir"] = tex_dir
        _track("textures")                           # the 4 maps also count as images
        return results

    def ok_(maps):
        dlg.close()
        _build_openpbr(target, maps)
        cmds.inViewMessage(
            amg="PBR maps saved to <hl>{}</hl>".format(maps["_dir"]),
            pos="midCenter", fade=True)
        PreviewWindow(
            "PBR maps -> {} (albedo / roughness / metalness / normal)".format(
                target.split('|')[-1]),
            maps["_preview"], kind="image").show()

    worker = _Worker(gen, parent=_main_window())
    worker.done.connect(ok_)
    worker.failed.connect(lambda tb: (dlg.close(), _error(tb)))
    worker.start()
    generate_texture._w = worker


def _make_file_texture(tex_path: str, name: str, raw: bool = False) -> str:
    """Create a `file` node (+ its place2dTexture) pointing at tex_path.
    `raw=True` marks it as non-color data (roughness / normal)."""
    file_node = cmds.shadingNode("file", asTexture=True, isColorManaged=True,
                                 name=name)
    p2d = cmds.shadingNode("place2dTexture", asUtility=True, name=name + "_p2d")
    for a in ("coverage", "translateFrame", "rotateFrame", "mirrorU", "mirrorV",
              "stagger", "wrapU", "wrapV", "repeatUV", "offset", "rotateUV",
              "noiseUV", "vertexUvOne", "vertexUvTwo", "vertexUvThree",
              "vertexCameraOne"):
        cmds.connectAttr(p2d + "." + a, file_node + "." + a, force=True)
    cmds.connectAttr(p2d + ".outUV", file_node + ".uvCoord", force=True)
    cmds.connectAttr(p2d + ".outUvFilterSize", file_node + ".uvFilterSize", force=True)

    cmds.setAttr(file_node + ".fileTextureName", tex_path, type="string")
    if raw:  # roughness / normal carry data, not sRGB color
        cmds.setAttr(file_node + ".colorSpace", "Raw", type="string")
        cmds.setAttr(file_node + ".ignoreColorSpaceFileRules", True)
    return file_node


def _first_existing_attr(node: str, candidates) -> str | None:
    for a in candidates:
        if cmds.attributeQuery(a, node=node, exists=True):
            return a
    return None


def _build_openpbr(target: str, maps: dict):
    """Create an openPBRSurface shader, wire the full PBR map set (base color,
    roughness, tangent-space normal via bump2d), and assign it to `target`."""
    shader = cmds.shadingNode("openPBRSurface", asShader=True, name="byteplus_openPBR")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                   name=shader + "SG")
    cmds.connectAttr(shader + ".outColor", sg + ".surfaceShader", force=True)

    # --- base color ----------------------------------------------------------
    base = _make_file_texture(maps["baseColor"], "byteplus_albedo")
    cmds.connectAttr(base + ".outColor", shader + ".baseColor", force=True)

    # --- roughness (scalar from a grayscale map) -----------------------------
    rough_attr = _first_existing_attr(shader, ("specularRoughness", "roughness"))
    if rough_attr and maps.get("specularRoughness"):
        rfile = _make_file_texture(maps["specularRoughness"], "byteplus_rough", raw=True)
        cmds.connectAttr(rfile + ".outColorR", shader + "." + rough_attr, force=True)

    # --- metalness (scalar from a grayscale map) -----------------------------
    metal_attr = _first_existing_attr(shader, ("baseMetalness", "metalness"))
    if metal_attr and maps.get("baseMetalness"):
        mfile = _make_file_texture(maps["baseMetalness"], "byteplus_metal", raw=True)
        cmds.connectAttr(mfile + ".outColorR", shader + "." + metal_attr, force=True)

    # --- normal (tangent-space, via bump2d) ----------------------------------
    normal_attr = _first_existing_attr(shader, ("normalCamera", "geometryNormal"))
    if normal_attr and maps.get("normal"):
        nfile = _make_file_texture(maps["normal"], "byteplus_normal", raw=True)
        bump = cmds.shadingNode("bump2d", asUtility=True, name="byteplus_bump")
        cmds.setAttr(bump + ".bumpInterp", 1)          # 1 = Tangent Space Normals
        cmds.setAttr(bump + ".bumpDepth", CONFIG.BUMP_DEPTH)  # artist-adjustable depth
        cmds.connectAttr(nfile + ".outAlpha", bump + ".bumpValue", force=True)
        cmds.connectAttr(bump + ".outNormal", shader + "." + normal_attr, force=True)

    cmds.sets(target, edit=True, forceElement=sg)


# =============================================================================
# Settings dialog -- edit resolution / ratio / duration-driver / TOS / webhook
# =============================================================================
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS  -  Settings")
        try:
            avail = QtWidgets.QApplication.primaryScreen().availableGeometry()
            self.resize(540, min(740, int(avail.height() * 0.85)))
        except Exception:
            self.resize(540, 700)
        outer = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        outer.addWidget(tabs, 1)

        def _tab(title):
            page = QtWidgets.QWidget()
            f = QtWidgets.QFormLayout(page)
            f.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setWidget(page)
            tabs.addTab(scroll, title)
            return f

        form = _tab("API && Models")

        # --- API key ----------------------------------------------------------
        form.addRow(QtWidgets.QLabel("<b>BytePlus ModelArk API key</b>"))
        self.api_key = QtWidgets.QLineEdit(CONFIG.API_KEY)
        self.api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_key.setPlaceholderText("paste your ARK_API_KEY here")
        reveal = QtWidgets.QCheckBox("Show")
        reveal.toggled.connect(lambda on: self.api_key.setEchoMode(
            QtWidgets.QLineEdit.Normal if on else QtWidgets.QLineEdit.Password))
        krow = QtWidgets.QHBoxLayout()
        krow.addWidget(self.api_key, 1); krow.addWidget(reveal)
        kw = QtWidgets.QWidget(); kw.setLayout(krow)
        form.addRow("API key", kw)
        self.remember = QtWidgets.QCheckBox(
            "Remember on this machine (stored in plaintext in ~/.byteplus_maya.json)")
        self.remember.setChecked(CONFIG.REMEMBER_API_KEY)
        form.addRow("", self.remember)
        khint = QtWidgets.QLabel(
            "Leave blank to use the ARK_API_KEY environment variable instead. "
            "The key entered here takes precedence.")
        khint.setWordWrap(True); khint.setStyleSheet("color:#888;")
        form.addRow("", khint)

        # --- Models / endpoint ------------------------------------------------
        form.addRow(QtWidgets.QLabel("<b>Models &amp; endpoint</b>"))
        self.base_url = QtWidgets.QLineEdit(CONFIG.BASE_URL)
        form.addRow("Base URL", self.base_url)
        self.seedream_model = QtWidgets.QLineEdit(CONFIG.SEEDREAM_MODEL)
        self.seedream_model.setPlaceholderText("e.g. seedream model ID or ep-xxxx")
        form.addRow("Seedream (image) model", self.seedream_model)
        self.seedream_face_model = QtWidgets.QLineEdit(CONFIG.SEEDREAM_FACE_MODEL)
        self.seedream_face_model.setPlaceholderText(
            "Seedream 5.0 Lite -- required so AI faces (Text-to-Image) are animatable")
        form.addRow("Seedream face model (T2I)", self.seedream_face_model)
        self.seedance_model = QtWidgets.QLineEdit(CONFIG.SEEDANCE_MODEL)
        self.seedance_model.setPlaceholderText("e.g. seedance model ID or ep-xxxx")
        form.addRow("Seedance (video) model", self.seedance_model)
        self.llm_model = QtWidgets.QLineEdit(CONFIG.LLM_MODEL)
        self.llm_model.setPlaceholderText("multimodal LLM for auto-prompt")
        form.addRow("LLM model (auto-prompt)", self.llm_model)
        self.seed_chat_model = QtWidgets.QLineEdit(CONFIG.SEED_CHAT_MODEL)
        self.seed_chat_model.setPlaceholderText("Seed 2.0 model for the Seed Chat window")
        form.addRow("Seed Chat model", self.seed_chat_model)
        self.three_d_model = QtWidgets.QLineEdit(CONFIG.THREE_D_MODEL)
        self.three_d_model.setPlaceholderText("3D model ID / ep-... from your ModelArk console")
        form.addRow("3D model (Seed 3D)", self.three_d_model)
        mhint = QtWidgets.QLabel(
            "Copy the exact model ID (or inference endpoint 'ep-...') from your "
            "BytePlus ModelArk console. Test one with byteplus_maya.diagnose("
            "'the-id').")
        mhint.setWordWrap(True); mhint.setStyleSheet("color:#888;")
        form.addRow("", mhint)

        form = _tab("Generation")

        self.resolution = QtWidgets.QComboBox()
        self.resolution.addItems(["480p", "720p", "1080p", "4k"])
        self.resolution.setCurrentText(CONFIG.VIDEO_RESOLUTION)
        form.addRow("Video resolution", self.resolution)
        res_hint = QtWidgets.QLabel(
            "4k = 10-bit HDR-grade color, encoded in H.265 (HEVC). Only the base "
            "Seedance 2.0 model supports it (not Fast); some players may not play "
            "HEVC directly. Costs more per video.")
        res_hint.setWordWrap(True); res_hint.setStyleSheet("color:#888;")
        form.addRow("", res_hint)

        self.ratio = QtWidgets.QComboBox()
        self.ratio.addItems(["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"])
        self.ratio.setCurrentText(CONFIG.VIDEO_RATIO)
        form.addRow("Video aspect ratio", self.ratio)

        self.image_ratio = QtWidgets.QComboBox()
        self.image_ratio.addItems(["16:9", "4:3", "1:1", "3:4", "9:16", "21:9"])
        self.image_ratio.setCurrentText(CONFIG.IMAGE_RATIO)
        self.image_ratio.setToolTip("Fixes the aspect of Dream / Refine images "
                                    "(exact pixels) so it's consistent, instead of "
                                    "letting Seedream infer it from the content.")
        form.addRow("Image aspect ratio", self.image_ratio)

        self.refs = QtWidgets.QSpinBox()
        self.refs.setRange(1, 9)                      # Seedance image-ref cap
        self.refs.setValue(CONFIG.MAX_IMAGE_REFS)
        form.addRow("Max reference frames", self.refs)

        self.ref_w = QtWidgets.QSpinBox(); self.ref_w.setRange(64, 4096)
        self.ref_w.setValue(CONFIG.REF_WIDTH)
        self.ref_h = QtWidgets.QSpinBox(); self.ref_h.setRange(64, 4096)
        self.ref_h.setValue(CONFIG.REF_HEIGHT)
        wh = QtWidgets.QHBoxLayout()
        wh.addWidget(self.ref_w); wh.addWidget(QtWidgets.QLabel("x")); wh.addWidget(self.ref_h)
        whw = QtWidgets.QWidget(); whw.setLayout(wh)
        form.addRow("Reference render size", whw)

        self.bump_depth = QtWidgets.QDoubleSpinBox()
        self.bump_depth.setRange(0.0, 5.0)
        self.bump_depth.setSingleStep(0.1)
        self.bump_depth.setValue(CONFIG.BUMP_DEPTH)
        self.bump_depth.setToolTip("Default bump2d depth for generated normal "
                                   "maps (adjustable per-material in Hypershade)")
        form.addRow("Texture bump depth", self.bump_depth)

        self.color_manage = QtWidgets.QCheckBox(
            "Apply color management (OCIO view transform / LUTs) to rendered refs")
        self.color_manage.setChecked(CONFIG.COLOR_MANAGE)
        self.color_manage.setToolTip("Makes Seedance reference frames match the "
                                     "artist's viewport. Untick to save the raw buffer.")
        form.addRow("", self.color_manage)

        form.addRow(QtWidgets.QLabel("<b>Cost estimate</b>"))
        self.show_cost = QtWidgets.QCheckBox(
            "Show approximate cost (tokens / USD) before generating")
        self.show_cost.setChecked(CONFIG.SHOW_COST)
        form.addRow("", self.show_cost)
        self.cost_confirm = QtWidgets.QDoubleSpinBox()
        self.cost_confirm.setRange(0.0, 1000.0)
        self.cost_confirm.setSingleStep(0.5)
        self.cost_confirm.setPrefix("$ ")
        self.cost_confirm.setValue(float(CONFIG.COST_CONFIRM_USD))
        self.cost_confirm.setToolTip("Ask for confirmation before generating when "
                                     "the estimate exceeds this. 0 = always confirm.")
        form.addRow("Confirm above", self.cost_confirm)
        chint = QtWidgets.QLabel(
            "Estimates are approximate (BytePlus billing is the source of truth). "
            "Images are cheap; mainly guards expensive 4K videos.")
        chint.setWordWrap(True); chint.setStyleSheet("color:#888;")
        form.addRow("", chint)

        form = _tab("Storage && Hosting")
        form.addRow(QtWidgets.QLabel("<b>Network</b>"))
        self.ssl_verify = QtWidgets.QCheckBox(
            "Verify SSL certificates (untick only if Maya's Python lacks a CA bundle)")
        self.ssl_verify.setChecked(CONFIG.SSL_VERIFY)
        form.addRow("", self.ssl_verify)

        form.addRow(QtWidgets.QLabel("<b>Object storage (TOS)</b> "
                                     "&mdash; needed for playblast motion"))
        self.use_tos = QtWidgets.QCheckBox("Use TOS (upload refs / motion video)")
        self.use_tos.setChecked(CONFIG.USE_TOS)
        form.addRow("", self.use_tos)
        self.tos_ak = QtWidgets.QLineEdit(CONFIG.TOS_AK)
        self.tos_ak.setEchoMode(QtWidgets.QLineEdit.Password)
        self.tos_ak.setPlaceholderText("TOS Access Key")
        form.addRow("TOS Access Key", self.tos_ak)
        self.tos_sk = QtWidgets.QLineEdit(CONFIG.TOS_SK)
        self.tos_sk.setEchoMode(QtWidgets.QLineEdit.Password)
        self.tos_sk.setPlaceholderText("TOS Secret Key")
        tos_reveal = QtWidgets.QCheckBox("Show")
        tos_reveal.toggled.connect(lambda on: (
            self.tos_ak.setEchoMode(QtWidgets.QLineEdit.Normal if on
                                    else QtWidgets.QLineEdit.Password),
            self.tos_sk.setEchoMode(QtWidgets.QLineEdit.Normal if on
                                    else QtWidgets.QLineEdit.Password)))
        skrow = QtWidgets.QHBoxLayout()
        skrow.addWidget(self.tos_sk, 1); skrow.addWidget(tos_reveal)
        skw = QtWidgets.QWidget(); skw.setLayout(skrow)
        form.addRow("TOS Secret Key", skw)
        self.bucket = QtWidgets.QLineEdit(CONFIG.TOS_BUCKET)
        self.bucket.setPlaceholderText("your bucket name")
        form.addRow("TOS bucket", self.bucket)
        self.endpoint = QtWidgets.QLineEdit(CONFIG.TOS_ENDPOINT)
        form.addRow("TOS endpoint", self.endpoint)
        self.region = QtWidgets.QLineEdit(CONFIG.TOS_REGION)
        form.addRow("TOS region", self.region)
        hint = QtWidgets.QLabel(
            "Keys saved with 'Remember' (above), in plaintext. Needs the `tos` "
            "SDK (pip install tos). Leave keys blank to use ${} / ${} env vars."
            .format(CONFIG.TOS_AK_ENV, CONFIG.TOS_SK_ENV))
        hint.setWordWrap(True); hint.setStyleSheet("color:#888;")
        form.addRow("", hint)

        # --- Cloudflare R2 (private motion-video host, no SDK) ----------------
        form.addRow(QtWidgets.QLabel("<b>Motion video hosting (Cloudflare R2)</b>"))
        self.motion_host = QtWidgets.QComboBox()
        self.motion_host.addItems(["off", "r2"])
        self.motion_host.setCurrentText(CONFIG.MOTION_HOST)
        form.addRow("Motion host", self.motion_host)
        self.r2_account = QtWidgets.QLineEdit(CONFIG.R2_ACCOUNT_ID)
        self.r2_account.setPlaceholderText("R2 account ID")
        form.addRow("R2 account ID", self.r2_account)
        self.r2_ak = QtWidgets.QLineEdit(CONFIG.R2_ACCESS_KEY)
        self.r2_ak.setEchoMode(QtWidgets.QLineEdit.Password)
        self.r2_ak.setPlaceholderText("R2 Access Key ID")
        form.addRow("R2 Access Key", self.r2_ak)
        self.r2_sk = QtWidgets.QLineEdit(CONFIG.R2_SECRET_KEY)
        self.r2_sk.setEchoMode(QtWidgets.QLineEdit.Password)
        self.r2_sk.setPlaceholderText("R2 Secret Access Key")
        r2_reveal = QtWidgets.QCheckBox("Show")
        r2_reveal.toggled.connect(lambda on: (
            self.r2_ak.setEchoMode(QtWidgets.QLineEdit.Normal if on
                                   else QtWidgets.QLineEdit.Password),
            self.r2_sk.setEchoMode(QtWidgets.QLineEdit.Normal if on
                                   else QtWidgets.QLineEdit.Password)))
        r2row = QtWidgets.QHBoxLayout()
        r2row.addWidget(self.r2_sk, 1); r2row.addWidget(r2_reveal)
        r2w = QtWidgets.QWidget(); r2w.setLayout(r2row)
        form.addRow("R2 Secret Key", r2w)
        self.r2_bucket = QtWidgets.QLineEdit(CONFIG.R2_BUCKET)
        self.r2_bucket.setPlaceholderText("your R2 bucket name")
        form.addRow("R2 bucket", self.r2_bucket)
        r2hint = QtWidgets.QLabel(
            "Private + no SDK needed. The playblast is uploaded as a time-limited "
            "private URL and DELETED when the job finishes. Off by default. Test "
            "with BYTEPLUS > Diagnostics > Test R2 hosting.")
        r2hint.setWordWrap(True); r2hint.setStyleSheet("color:#888;")
        form.addRow("", r2hint)

        form = _tab("Analytics && Webhook")
        form.addRow(QtWidgets.QLabel("<b>Usage analytics</b>"))

        # Privacy disclosure (always shown). The telemetry BACKEND (PostHog
        # host/key/bucket/callback) is configured at build time in code and is
        # intentionally NOT exposed in the UI -- customers never see it.
        pnote = QtWidgets.QLabel(
            "BYTEPLUS sends <b>usage data</b> (features used, models and token "
            "counts) to help us improve the product. It never sends your prompts, "
            "scenes, images, videos or API keys. If you fill in the optional "
            "details below, your name / email / company are included so usage can "
            "be attributed to you. See <b>About</b> for the full notice.")
        pnote.setWordWrap(True)
        form.addRow("", pnote)

        # Developer mode is the ONE control we expose to everyone: it just shows
        # the Diagnostics menu (developers / partners). No backend data here.
        self.debug = QtWidgets.QCheckBox("Show the Diagnostics menu (developers / partners)")
        self.debug.setChecked(bool(CONFIG.DEBUG))
        form.addRow("Developer mode", self.debug)
        if _debug_on():
            devhint = QtWidgets.QLabel(
                "Telemetry is always on; the analytics backend is configured at "
                "build time and is not shown here.")
            devhint.setWordWrap(True); devhint.setStyleSheet("color:#888;")
            form.addRow("", devhint)

        form.addRow(QtWidgets.QLabel("<b>Your details (optional)</b>"))
        self.user_email = QtWidgets.QLineEdit(CONFIG.USER_EMAIL)
        self.user_email.setPlaceholderText("you@studio.com")
        form.addRow("Email", self.user_email)
        self.user_name = QtWidgets.QLineEdit(CONFIG.USER_NAME)
        form.addRow("Name", self.user_name)
        self.user_role = QtWidgets.QLineEdit(CONFIG.USER_ROLE)
        self.user_role.setPlaceholderText("e.g. Lighting TD")
        form.addRow("Role", self.user_role)
        self.user_company = QtWidgets.QLineEdit(CONFIG.USER_COMPANY)
        self.user_company.setPlaceholderText("your studio / company")
        form.addRow("Company", self.user_company)
        ihint = QtWidgets.QLabel(
            "Optional — links your usage to you/your studio in our analytics so "
            "we can support you better. Leave blank to stay anonymous. Clear any "
            "field and Save to remove it.")
        ihint.setWordWrap(True); ihint.setStyleSheet("color:#888;")
        form.addRow("", ihint)

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)                          # fixed below the tabs

    def _apply(self):
        CONFIG.API_KEY = self.api_key.text().strip()
        CONFIG.REMEMBER_API_KEY = self.remember.isChecked()
        CONFIG.BASE_URL = self.base_url.text().strip().rstrip("/")
        CONFIG.SEEDREAM_MODEL = self.seedream_model.text().strip()
        CONFIG.SEEDREAM_FACE_MODEL = self.seedream_face_model.text().strip()
        CONFIG.SEEDANCE_MODEL = self.seedance_model.text().strip()
        CONFIG.LLM_MODEL = self.llm_model.text().strip()
        CONFIG.SEED_CHAT_MODEL = self.seed_chat_model.text().strip()
        CONFIG.THREE_D_MODEL = self.three_d_model.text().strip()
        CONFIG.VIDEO_RESOLUTION = self.resolution.currentText()
        CONFIG.VIDEO_RATIO = self.ratio.currentText()
        CONFIG.IMAGE_RATIO = self.image_ratio.currentText()
        CONFIG.MAX_IMAGE_REFS = self.refs.value()
        CONFIG.REF_WIDTH = self.ref_w.value()
        CONFIG.REF_HEIGHT = self.ref_h.value()
        CONFIG.BUMP_DEPTH = self.bump_depth.value()
        CONFIG.COLOR_MANAGE = self.color_manage.isChecked()
        CONFIG.SHOW_COST = self.show_cost.isChecked()
        CONFIG.COST_CONFIRM_USD = self.cost_confirm.value()
        CONFIG.SSL_VERIFY = self.ssl_verify.isChecked()
        CONFIG.USE_TOS = self.use_tos.isChecked()
        CONFIG.TOS_AK = self.tos_ak.text().strip()
        CONFIG.TOS_SK = self.tos_sk.text().strip()
        CONFIG.TOS_BUCKET = self.bucket.text().strip()
        CONFIG.TOS_ENDPOINT = self.endpoint.text().strip()
        CONFIG.TOS_REGION = self.region.text().strip()
        CONFIG.MOTION_HOST = self.motion_host.currentText()
        CONFIG.R2_ACCOUNT_ID = self.r2_account.text().strip()
        CONFIG.R2_ACCESS_KEY = self.r2_ak.text().strip()
        CONFIG.R2_SECRET_KEY = self.r2_sk.text().strip()
        CONFIG.R2_BUCKET = self.r2_bucket.text().strip()
        # Telemetry is always on (CONFIG.TELEMETRY) and the analytics backend
        # (PostHog host/key/bucket/callback) is a build-time constant -- not
        # exposed in the UI. The only analytics control we save is Developer mode.
        debug_was = bool(CONFIG.DEBUG)
        CONFIG.DEBUG = self.debug.isChecked()
        debug_changed = bool(CONFIG.DEBUG) != debug_was
        # Identity (optional) — always editable; re-send to PostHog if changed.
        new_id = (self.user_email.text().strip(), self.user_name.text().strip(),
                  self.user_role.text().strip(), self.user_company.text().strip())
        old_id = (CONFIG.USER_EMAIL, CONFIG.USER_NAME, CONFIG.USER_ROLE,
                  CONFIG.USER_COMPANY)
        (CONFIG.USER_EMAIL, CONFIG.USER_NAME, CONFIG.USER_ROLE,
         CONFIG.USER_COMPANY) = new_id
        if CONFIG.TELEMETRY:
            _install_id()                            # ensure an id exists
            _telemetry_start()
            if new_id != old_id and any(new_id):
                _posthog_identify()
        _save_prefs()
        self.accept()
        if debug_changed:                            # show/hide the Diagnostics menu now
            maya.utils.executeDeferred(install)


def _style_tp_item(item_name):
    """Recolor the 'Technology Preview' menu entry BytePlus-blue. Best-effort:
    cmds can't color a menu item, so we reach the underlying QAction and swap in
    a styled QLabel. If anything fails, the plain entry stays (no breakage)."""
    try:
        ptr = omui.MQtUtil.findMenuItem(item_name)
        if not ptr:
            return
        QAction = getattr(QtGui, "QAction", None) or QtWidgets.QAction
        act = wrapInstance(int(ptr), QAction)
        menu = act.parentWidget()
        if menu is None:
            return
        label = QtWidgets.QLabel("✨  Technology Preview")
        label.setStyleSheet(
            "color:#2F88FF; font-weight:bold; padding:3px 24px;")  # BytePlus blue
        wa = QtWidgets.QWidgetAction(menu)
        wa.setDefaultWidget(label)
        menu.insertAction(act, wa)
        menu.removeAction(act)
    except Exception:
        pass


def open_settings():
    SettingsDialog().exec()


class MotionHostWizard(QtWidgets.QDialog):
    """Guided setup for the playblast motion-video host. Lets the client pick a
    backend (Cloudflare R2 - no install, recommended; or BytePlus TOS - same
    vendor, needs the 'tos' package), paste keys with step-by-step help, TEST the
    connection (upload -> fetch -> delete), and Save & enable it."""

    def __init__(self, parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS - Motion video hosting setup")
        self.setMinimumWidth(580)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._worker = None
        v = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            "<b>Faithful motion needs somewhere to put the playblast</b> that "
            "Seedance can read. Pick a host, paste your keys, then press "
            "<b>Test connection</b>. Without a host, Animate still works but the "
            "motion is approximate (from the text description only).")
        intro.setWordWrap(True)
        v.addWidget(intro)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Host:"))
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("Cloudflare R2  (recommended - nothing to install)", "r2")
        self.kind.addItem("BytePlus TOS  (same vendor - needs the 'tos' package)", "tos")
        row.addWidget(self.kind, 1)
        v.addLayout(row)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self._r2_page())
        self.stack.addWidget(self._tos_page())
        v.addWidget(self.stack)
        self.kind.currentIndexChanged.connect(self.stack.setCurrentIndex)
        idx = 1 if (CONFIG.USE_TOS and CONFIG.MOTION_HOST != "r2") else 0
        self.kind.setCurrentIndex(idx)
        self.stack.setCurrentIndex(idx)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        bar = QtWidgets.QHBoxLayout()
        self.b_test = QtWidgets.QPushButton("Test connection")
        self.b_test.clicked.connect(self._test)
        self.b_save = QtWidgets.QPushButton("Save && enable")
        self.b_save.clicked.connect(self._save)
        b_close = QtWidgets.QPushButton("Close")
        b_close.clicked.connect(self.reject)
        bar.addWidget(self.b_test)
        bar.addStretch(1)
        bar.addWidget(self.b_save)
        bar.addWidget(b_close)
        v.addLayout(bar)

    def _r2_page(self):
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        steps = QtWidgets.QLabel(
            "<b>Get Cloudflare R2 keys</b> (the free tier is plenty):<br>"
            "1. dash.cloudflare.com &rarr; R2 &rarr; <i>Create bucket</i> (any name).<br>"
            "2. R2 &rarr; <i>Manage R2 API Tokens</i> &rarr; <i>Create API token</i> "
            "with <b>Object Read &amp; Write</b>.<br>"
            "3. Copy the <b>Access Key ID</b>, <b>Secret Access Key</b>, and your "
            "<b>Account ID</b> (shown at the top of the R2 page).")
        steps.setWordWrap(True)
        steps.setStyleSheet("color:#bbb;")
        f.addRow(steps)
        self.r2_account = QtWidgets.QLineEdit(CONFIG.R2_ACCOUNT_ID)
        self.r2_account.setPlaceholderText("R2 account ID")
        f.addRow("Account ID", self.r2_account)
        self.r2_ak = QtWidgets.QLineEdit(CONFIG.R2_ACCESS_KEY)
        self.r2_ak.setEchoMode(QtWidgets.QLineEdit.Password)
        f.addRow("Access Key ID", self.r2_ak)
        self.r2_sk = QtWidgets.QLineEdit(CONFIG.R2_SECRET_KEY)
        self.r2_sk.setEchoMode(QtWidgets.QLineEdit.Password)
        f.addRow("Secret Access Key", self.r2_sk)
        self.r2_bucket = QtWidgets.QLineEdit(CONFIG.R2_BUCKET)
        self.r2_bucket.setPlaceholderText("your R2 bucket name")
        f.addRow("Bucket", self.r2_bucket)
        note = QtWidgets.QLabel(
            "No SDK needed. The playblast is uploaded as a private, time-limited "
            "URL and deleted automatically when the job finishes.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;")
        f.addRow(note)
        return w

    def _tos_page(self):
        w = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(w)
        steps = QtWidgets.QLabel(
            "<b>BytePlus TOS</b> (same account as your API key):<br>"
            "1. console.byteplus.com &rarr; TOS &rarr; create a bucket.<br>"
            "2. Create an Access Key / Secret Key (IAM).<br>"
            "<b>Requires the 'tos' package</b> in Maya's Python. In a terminal:<br>"
            "<tt>\"&lt;Maya&gt;\\bin\\mayapy.exe\" -m pip install tos</tt><br>"
            "If unsure, use R2 instead - it needs nothing.")
        steps.setWordWrap(True)
        steps.setStyleSheet("color:#bbb;")
        f.addRow(steps)
        self.tos_ak = QtWidgets.QLineEdit(CONFIG.TOS_AK)
        self.tos_ak.setEchoMode(QtWidgets.QLineEdit.Password)
        f.addRow("Access Key", self.tos_ak)
        self.tos_sk = QtWidgets.QLineEdit(CONFIG.TOS_SK)
        self.tos_sk.setEchoMode(QtWidgets.QLineEdit.Password)
        f.addRow("Secret Key", self.tos_sk)
        self.tos_bucket = QtWidgets.QLineEdit(CONFIG.TOS_BUCKET)
        self.tos_bucket.setPlaceholderText("your bucket name")
        f.addRow("Bucket", self.tos_bucket)
        self.tos_endpoint = QtWidgets.QLineEdit(CONFIG.TOS_ENDPOINT)
        f.addRow("Endpoint", self.tos_endpoint)
        self.tos_region = QtWidgets.QLineEdit(CONFIG.TOS_REGION)
        f.addRow("Region", self.tos_region)
        return w

    def _apply_to_config(self):
        kind = self.kind.currentData()
        if kind == "r2":
            CONFIG.R2_ACCOUNT_ID = self.r2_account.text().strip()
            CONFIG.R2_ACCESS_KEY = self.r2_ak.text().strip()
            CONFIG.R2_SECRET_KEY = self.r2_sk.text().strip()
            CONFIG.R2_BUCKET = self.r2_bucket.text().strip()
        else:
            CONFIG.TOS_AK = self.tos_ak.text().strip()
            CONFIG.TOS_SK = self.tos_sk.text().strip()
            CONFIG.TOS_BUCKET = self.tos_bucket.text().strip()
            CONFIG.TOS_ENDPOINT = self.tos_endpoint.text().strip() or CONFIG.TOS_ENDPOINT
            CONFIG.TOS_REGION = self.tos_region.text().strip() or CONFIG.TOS_REGION
        return kind

    def _busy(self, on, msg=""):
        self.b_test.setEnabled(not on)
        self.b_save.setEnabled(not on)
        if msg:
            self.status.setText(msg)

    def _test(self):
        kind = self._apply_to_config()
        if kind == "r2" and not (CONFIG.R2_ACCOUNT_ID and CONFIG.R2_ACCESS_KEY
                                 and CONFIG.R2_SECRET_KEY and CONFIG.R2_BUCKET):
            self.status.setText("<span style='color:#e66'>Fill in all four R2 "
                                "fields first.</span>")
            return
        if kind == "tos":
            try:
                import tos  # noqa: F401
            except Exception:
                self.status.setText("<span style='color:#e66'>The 'tos' package "
                    "isn't installed (see the steps above), so TOS can't be "
                    "tested. Use R2, or install the package.</span>")
                return
            if not (CONFIG.TOS_AK and CONFIG.TOS_SK and CONFIG.TOS_BUCKET):
                self.status.setText("<span style='color:#e66'>Fill in Access Key, "
                                    "Secret Key and Bucket first.</span>")
                return
        self._busy(True, "Testing... uploading a tiny file, fetching it back, "
                         "deleting it.")
        self._worker = _Worker(lambda: _motion_host_selftest(kind), parent=self)
        self._worker.done.connect(self._test_ok)
        self._worker.failed.connect(self._test_fail)
        self._worker.start()

    def _test_ok(self, _):
        self._busy(False)
        self.status.setText("<span style='color:#6c6'>&#10003; Success - upload, "
                            "fetch and delete all worked. Press <b>Save &amp; "
                            "enable</b>.</span>")

    def _test_fail(self, tb):
        self._busy(False)
        last = (str(tb).strip().splitlines() or ["error"])[-1]
        self.status.setText("<span style='color:#e66'>&#10007; Test failed: {}"
                            "</span>".format(last))

    def _save(self):
        kind = self._apply_to_config()
        if kind == "r2":
            CONFIG.MOTION_HOST = "r2"
        else:
            CONFIG.USE_TOS = True
        CONFIG.REMEMBER_API_KEY = True               # persist the keys to prefs
        _save_prefs()
        cmds.inViewMessage(
            amg="BYTEPLUS: motion hosting saved ({}). Keys stored in your prefs."
                .format(kind), pos="midCenter", fade=True)
        self.accept()


def setup_hosting():
    """BYTEPLUS > Set up motion hosting -- the guided R2/TOS wizard."""
    MotionHostWizard().exec()


def show_usage():
    """Show cumulative + token usage with a per-project breakdown
    (BYTEPLUS > Usage...)."""
    u = usage_snapshot()
    dlg = QtWidgets.QDialog(_main_window())
    dlg.setWindowTitle("BYTEPLUS - Usage")
    dlg.setMinimumSize(560, 440)
    dlg.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
    v = QtWidgets.QVBoxLayout(dlg)

    # --- view selector: Global / Per-project / Both (persisted client choice) --
    selrow = QtWidgets.QHBoxLayout()
    selrow.addWidget(QtWidgets.QLabel("View:"))
    rb_global = QtWidgets.QRadioButton("Global")
    rb_project = QtWidgets.QRadioButton("Per-project")
    rb_both = QtWidgets.QRadioButton("Both")
    grp = QtWidgets.QButtonGroup(dlg)
    for rb in (rb_global, rb_project, rb_both):
        grp.addButton(rb)
        selrow.addWidget(rb)
    selrow.addStretch(1)
    v.addLayout(selrow)
    {"global": rb_global, "project": rb_project}.get(
        CONFIG.USAGE_VIEW, rb_both).setChecked(True)

    # --- global totals section ---------------------------------------------
    g_head = QtWidgets.QLabel("<b>Totals on this machine</b>")
    v.addWidget(g_head)
    summary = ("Image generations (incl. texture maps):  {images}\n"
               "Texture sets:                             {textures}\n"
               "Videos generated:                         {videos}\n"
               "Auto-prompt LLM calls:                    {llm}\n"
               "Tokens  in {tokens_in:,}  ·  out {tokens_out:,}  ·  "
               "total {tokens_total:,}").format(**u)
    lbl = QtWidgets.QLabel(summary)
    lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    v.addWidget(lbl)

    # --- per-project section ----------------------------------------------
    p_head = QtWidgets.QLabel("<b>By project (Maya scene)</b>")
    v.addWidget(p_head)
    projects = u.get("projects") or {}
    rows = sorted(projects.items(),
                  key=lambda kv: kv[1].get("tokens_total", 0), reverse=True)
    tbl = QtWidgets.QTableWidget(len(rows), 5)
    tbl.setHorizontalHeaderLabels(["Project", "Imgs", "Vids", "Tex", "Tokens"])
    tbl.verticalHeader().setVisible(False)
    tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    tbl.horizontalHeader().setSectionResizeMode(
        0, QtWidgets.QHeaderView.Stretch)
    for r, (name, pb) in enumerate(rows):
        vals = [name,
                str(pb.get("images", 0)), str(pb.get("videos", 0)),
                str(pb.get("textures", 0)),
                "{:,}".format(pb.get("tokens_total", 0))]
        for c, text in enumerate(vals):
            it = QtWidgets.QTableWidgetItem(text)
            if c >= 1:
                it.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            tbl.setItem(r, c, it)
    v.addWidget(tbl, 1)
    p_empty = QtWidgets.QLabel(
        "<i>No per-project data yet — generate something to populate this.</i>")
    p_empty.setVisible(not rows)
    v.addWidget(p_empty)

    if _debug_on():
        v.addWidget(QtWidgets.QLabel("Telemetry: always on ({})    ·    "
                                     "Stored at: {}".format(
                                         CONFIG.TELEMETRY_BACKEND,
                                         CONFIG.USAGE_PATH)))

    def _apply_view():
        if rb_global.isChecked():
            mode = "global"
        elif rb_project.isChecked():
            mode = "project"
        else:
            mode = "both"
        show_g = mode in ("global", "both")
        show_p = mode in ("project", "both")
        g_head.setVisible(show_g); lbl.setVisible(show_g)
        p_head.setVisible(show_p); tbl.setVisible(show_p)
        p_empty.setVisible(show_p and not rows)
        if mode != CONFIG.USAGE_VIEW:                # remember the client's choice
            CONFIG.USAGE_VIEW = mode
            _save_prefs()

    for rb in (rb_global, rb_project, rb_both):
        rb.toggled.connect(_apply_view)
    _apply_view()

    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
    bb.rejected.connect(dlg.reject)
    bb.accepted.connect(dlg.accept)
    v.addWidget(bb)
    dlg.exec()


_NOTICE_TEXT = """BYTEPLUS for Maya — Notice & Disclaimer

Technology Preview — developed by John Paul Giancarlo on behalf of ByteDance.

1. AS-IS, AT YOUR OWN RISK
This software is a Technology Preview, provided "AS IS" and "AS AVAILABLE",
WITHOUT WARRANTIES OF ANY KIND, express or implied (including merchantability,
fitness for a particular purpose, and non-infringement). You use it at your own
risk. It may be incomplete, change, or stop working at any time.

2. NO LIABILITY
To the maximum extent permitted by law, the authors and ByteDance are NOT liable
for any direct, indirect, incidental, or consequential damages, or any loss of
data, profits, or goodwill, arising from use of the software.

3. YOUR BYTEPLUS USAGE IS YOURS
The software calls BytePlus ModelArk APIs (Seedream, Seedance, and the Seed LLM)
using YOUR OWN API key. You are responsible for your keys and for all
usage, tokens, and charges incurred under them. Those services are governed by
BytePlus's own terms; generated content is subject to their content and biometric
policies.

4. THIRD-PARTY SOFTWARE
Runs inside Autodesk Maya, under Autodesk's separate license. Other brand names,
product names, and trademarks belong to their respective owners.

5. ANONYMOUS USAGE DATA
To improve the software, it sends ANONYMOUS usage analytics (features used, model
ids, token counts). It does NOT send your prompts, scenes, images, videos, or API
keys. You may optionally provide your details (editable in Settings) and you may
stay anonymous.

Questions: john.giancarlo@bytedance.com"""


def show_about():
    dlg = QtWidgets.QDialog(_main_window())
    dlg.setWindowTitle("About BYTEPLUS for Maya")
    dlg.setMinimumSize(620, 560)
    v = QtWidgets.QVBoxLayout(dlg)

    title = QtWidgets.QLabel("BYTEPLUS for Maya")
    title.setAlignment(QtCore.Qt.AlignCenter)
    title.setStyleSheet("font-size:16px; font-weight:bold;")
    v.addWidget(title)

    ver = QtWidgets.QLabel(CONFIG.VERSION)
    ver.setAlignment(QtCore.Qt.AlignCenter)
    ver.setStyleSheet("color:#4d8bff;")           # BytePlus blue
    v.addWidget(ver)

    # Version / credits block (like Arnold's grey panel).
    info = QtWidgets.QTextEdit(readOnly=True)
    info.setFixedHeight(120)
    info.setPlainText(
        "Technology preview developed by John Paul Giancarlo on behalf of "
        "ByteDance.\n\n"
        "Models in use:\n"
        "  • Seedream (image):  {sd}\n"
        "  • Seedance (video):  {sv}\n"
        "  • LLM (auto-prompt): {llm}".format(
            sd=CONFIG.SEEDREAM_MODEL, sv=CONFIG.SEEDANCE_MODEL, llm=CONFIG.LLM_MODEL))
    v.addWidget(info)

    v.addWidget(QtWidgets.QLabel("Notice & Disclaimer"))
    eula = QtWidgets.QTextEdit(readOnly=True)
    eula.setPlainText(_NOTICE_TEXT)
    eula.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
    v.addWidget(eula, 1)

    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
    bb.accepted.connect(dlg.accept)
    v.addWidget(bb)
    dlg.exec()


def report_bug():
    """Collect a short report and open the user's email client (temporary)."""
    desc, ok = QtWidgets.QInputDialog.getMultiLineText(
        _main_window(), "Report a Bug",
        "Describe the problem (steps, what you expected, what happened):", "")
    if not ok:
        return
    import platform
    u = usage_snapshot()
    body = (
        "BYTEPLUS for Maya - bug report\n"
        "--------------------------------\n"
        "Version: {ver}\n"
        "Maya: {maya}\n"
        "OS: {os}\n"
        "Usage: {img} images / {vid} videos / {llm} llm calls\n\n"
        "Description:\n{desc}\n").format(
        ver=CONFIG.VERSION, maya=cmds.about(version=True), os=platform.platform(),
        img=u["images"], vid=u["videos"], llm=u["llm"], desc=desc)
    subject = "BYTEPLUS for Maya bug report ({})".format(CONFIG.VERSION)
    mailto = "mailto:{}?subject={}&body={}".format(
        CONFIG.BUG_EMAIL, urllib.parse.quote(subject), urllib.parse.quote(body))
    QtGui.QDesktopServices.openUrl(QtCore.QUrl(mailto, QtCore.QUrl.TolerantMode))


# =============================================================================
# Seed Chat -- multimodal assistant (BytePlus Seed 2.0) inside Maya
# -----------------------------------------------------------------------------
# A multi-turn chat window: creative + technical help for the artist, prompt
# writing/repair for Seedream/Seedance, image description, and a grounded
# "Model Genius" knowledge base about the BytePlus ModelArk platform. It reuses
# the existing transport (_request), the QThread worker (_Worker), the viewport
# grab (_viewport_snapshot) and the image encoders (_data_uri/_image_mime).
# The _chat() helper is deliberately generic so the future in-Maya assistant
# (tool-calling agent) can build on it.
# =============================================================================

def _chat(messages, model=None, system=None):
    """Low-level multi-turn chat call against ModelArk /chat/completions.

    `messages` is a list of {"role", "content"} dicts where content is either a
    plain string or a list of multimodal parts ({"type":"text",...} /
    {"type":"image_url","image_url":{"url":...}}). If `system` is given it is
    prepended as a system message. Returns the assistant reply text.

    NETWORK ONLY -- blocking; call from a _Worker, never the Maya UI thread. This
    is the single shared chat wrapper the Seed Chat window and (later) the in-Maya
    assistant both build on."""
    model = model or CONFIG.SEED_CHAT_MODEL
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    body = {"model": model, "messages": msgs}
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, model)
    return (resp["choices"][0]["message"]["content"] or "").strip()


# Distilled "Model Genius" system prompt. Grounded in the bundled
# byteplus-models-genius skill references -- keep every fact here CORRECT and
# never let the model invent model IDs, params, endpoints, prices or limits.
_SEED_CHAT_SYSTEM = (
    "You are Seed Chat, an assistant embedded in the 'BYTEPLUS for Maya' plugin, "
    "powered by BytePlus Seed 2.0. You help a 3D artist working in Autodesk Maya. "
    "You can: (1) answer technical questions about the BytePlus ModelArk platform "
    "and its models (act as 'Model Genius'); (2) write and repair image/video "
    "prompts; (3) describe or critique images the user attaches; (4) give creative "
    "and technical direction for their Maya renders.\n\n"
    "GROUNDED FACTS (BytePlus ModelArk, region ap-southeast-1, base URL "
    "https://ark.ap-southeast.bytepluses.com/api/v3):\n"
    "- IMAGE = Seedream (flagship 'seedream-5-0-260128', plus -lite, "
    "'seedream-4-5-251128', 'seedream-4-0-250828'). Sync endpoint "
    "/images/generations. Up to 14 reference images; prompts in ENGLISH under 600 "
    "words; sizes 2K/3K/4K or exact WxH pixels; watermark defaults TRUE.\n"
    "- VIDEO = Seedance 2.0 ('dreamina-seedance-2-0-260128' base, plus -fast and "
    "-mini-260615). Async /contents/generations/tasks. 480p/720p/1080p/4k (1080p & "
    "4k = base model only), 4-15 s, 24 fps, up to 9 reference images. Prompt "
    "formula: Subject + Action details + Scene/Environment + Lighting & Color + "
    "Camera movement + Visual style + Quality; quantify motion (speed/inertia). "
    "Watermark defaults FALSE.\n"
    "- 3D = Hyper3d-Rodin-Gen2 (text->3D and image->3D) and Hitem3d-2.0 "
    "(image->3D only). Async, same tasks endpoint; outputs glb/obj/fbx/usdz with "
    "optional PBR materials.\n"
    "- LLM / agent = Seed 2.0 (this chat): 256K context, multimodal understanding, "
    "native tool calling.\n"
    "- COMPLIANCE: real human faces are NEVER allowed as references. AI-generated "
    "people are only allowed via the Seedream text-to-image 'Trusted Output' path "
    "on the same account.\n\n"
    "The plugin's BYTEPLUS menu already offers: Render with Seedance, Dream with "
    "Seedream, Dream/Video galleries, Generate Texture, and Settings. When the user "
    "wants an image, offer to hand an optimized prompt to 'Dream'.\n\n"
    "STYLE: be concise and practical. Reply in the user's language (they may write "
    "Spanish), BUT any prompt you produce for Seedream/Seedance must be in ENGLISH. "
    "If you are unsure of an exact ID, parameter, price or limit, say so rather "
    "than guessing. Never fabricate.")


class _ChatInput(QtWidgets.QPlainTextEdit):
    """Multi-line input that sends on Enter (Shift+Enter inserts a newline)."""

    def __init__(self, on_send, parent=None):
        super().__init__(parent)
        self._on_send = on_send
        self.setPlaceholderText(
            "Ask anything, or type an idea and hit '✨ Prompt Doctor'. "
            "Enter = send, Shift+Enter = new line.")

    def keyPressEvent(self, e):
        if e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and \
                not (e.modifiers() & QtCore.Qt.ShiftModifier):
            self._on_send()
            return
        super().keyPressEvent(e)


class SeedChatDialog(QtWidgets.QDialog):
    """Multi-turn multimodal chat with BytePlus Seed 2.0 (CONFIG.SEED_CHAT_MODEL).
    Persistent singleton so the conversation survives closing the window."""

    def __init__(self, parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS - Seed Chat")
        self.setMinimumSize(560, 680)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._history = []            # API messages (no system); grows per turn
        self._attachments = []        # local image paths for the NEXT user turn
        self._last_assistant = ""     # last reply text, for "Send to Dream"
        self._busy = False            # a chat request is in flight
        self._workers = []            # keep QThread refs alive

        v = QtWidgets.QVBoxLayout(self)

        # -- target selector (drives Prompt Doctor) --------------------------
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Mode:"))
        self.target = QtWidgets.QComboBox()
        self.target.addItems(["\U0001F4AC Chat",
                              "\U0001F5BC Image prompt (Seedream)",
                              "\U0001F3AC Video prompt (Seedance)"])
        self.target.setToolTip("Chat = free conversation / Model Genius. The image "
                               "and video modes tune the '✨ Prompt Doctor' button.")
        top.addWidget(self.target)
        top.addStretch(1)
        b_clear = QtWidgets.QPushButton("Clear chat")
        b_clear.clicked.connect(self._clear_chat)
        top.addWidget(b_clear)
        v.addLayout(top)

        # -- conversation view -----------------------------------------------
        self.view = QtWidgets.QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setStyleSheet("QTextBrowser{background:#1d1d1d;color:#dddddd;}")
        v.addWidget(self.view, 1)
        self._say("assistant",
                  "Hi \U0001F44B I'm Seed Chat (Seed 2.0). Ask me about BytePlus "
                  "models, attach an image to describe it, or type an idea and hit "
                  "✨ Prompt Doctor to turn it into an optimized prompt.")

        # -- attachments row -------------------------------------------------
        att = QtWidgets.QHBoxLayout()
        b_img = QtWidgets.QPushButton("\U0001F4CE Image")
        b_img.setToolTip("Attach reference image(s) for the next message")
        b_img.clicked.connect(self._attach_image)
        b_vp = QtWidgets.QPushButton("\U0001F5BC Viewport")
        b_vp.setToolTip("Attach a grab of the current Maya viewport")
        b_vp.clicked.connect(self._attach_viewport)
        self.att_label = QtWidgets.QLabel("no attachments")
        self.att_label.setStyleSheet("color:#888;")
        b_att_clear = QtWidgets.QPushButton("✕")
        b_att_clear.setFixedWidth(28)
        b_att_clear.setToolTip("Clear attachments")
        b_att_clear.clicked.connect(self._clear_attachments)
        att.addWidget(b_img); att.addWidget(b_vp)
        att.addWidget(self.att_label, 1); att.addWidget(b_att_clear)
        v.addLayout(att)

        # -- input -----------------------------------------------------------
        self.input = _ChatInput(self._send)
        self.input.setFixedHeight(90)
        v.addWidget(self.input)

        # -- action buttons --------------------------------------------------
        actions = QtWidgets.QHBoxLayout()
        self.b_doctor = QtWidgets.QPushButton("✨ Prompt Doctor")
        self.b_doctor.setToolTip("Rewrite your text into an optimized ENGLISH "
                                 "prompt for the selected target")
        self.b_doctor.clicked.connect(self._prompt_doctor)
        self.b_describe = QtWidgets.QPushButton("\U0001F50E Describe image")
        self.b_describe.setToolTip("Describe the attached image + suggest a prompt")
        self.b_describe.clicked.connect(self._describe_image)
        self.b_dream = QtWidgets.QPushButton("→ Dream")
        self.b_dream.setToolTip("Open 'Dream with Seedream' with the last reply "
                                "as the prompt")
        self.b_dream.setEnabled(False)
        self.b_dream.clicked.connect(self._send_to_dream)
        self.b_seed3d = QtWidgets.QPushButton("→ Seed 3D")
        self.b_seed3d.setToolTip("Open 'Seed 3D' with the last reply as the prompt")
        self.b_seed3d.setEnabled(False)
        self.b_seed3d.clicked.connect(self._send_to_seed3d)
        _add_dictate_button(actions, self.input)
        actions.addWidget(self.b_doctor); actions.addWidget(self.b_describe)
        actions.addStretch(1)
        actions.addWidget(self.b_dream); actions.addWidget(self.b_seed3d)
        v.addLayout(actions)

        # -- send row --------------------------------------------------------
        srow = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color:#2E8BE6;")
        srow.addWidget(self.status, 1)
        self.b_send = QtWidgets.QPushButton("Send")
        self.b_send.setDefault(True)
        self.b_send.clicked.connect(lambda: self._send())
        srow.addWidget(self.b_send)
        v.addLayout(srow)

    # -- transcript ----------------------------------------------------------
    @staticmethod
    def _esc(t):
        return (t.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace("\n", "<br>"))

    def _say(self, role, text):
        who, col = ("You", "#8ac6ff") if role == "user" else ("Seed", "#7ee081")
        self.view.append(
            "<p style='margin:6px 0'><b style='color:{}'>{}:</b> {}</p>".format(
                col, who, self._esc(text)))
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # -- attachments ---------------------------------------------------------
    def _attach_image(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Attach reference image(s)", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        self._attachments.extend(paths)
        self._refresh_attachments()

    def _attach_viewport(self):
        try:
            self._attachments.append(_viewport_snapshot())
        except Exception as e:
            _error("Could not grab the viewport:\n{}".format(e))
            return
        self._refresh_attachments()

    def _clear_attachments(self):
        self._attachments = []
        self._refresh_attachments()

    def _refresh_attachments(self):
        n = len(self._attachments)
        self.att_label.setText("no attachments" if not n else
                               "{} image{} attached".format(n, "s" if n > 1 else ""))
        self.att_label.setStyleSheet("color:#888;" if not n else "color:#7ee081;")

    # -- sending -------------------------------------------------------------
    def _set_busy(self, busy):
        self._busy = busy
        for w in (self.b_send, self.b_doctor, self.b_describe, self.input,
                  self.target):
            w.setEnabled(not busy)
        self.status.setText("Seed is typing…" if busy else "")

    def _build_user_content(self, text):
        if not self._attachments:
            return text
        parts = [{"type": "text", "text": text}]
        for p in self._attachments:
            try:
                uri = _data_uri(p, _image_mime(p))
            except Exception:
                continue
            parts.append({"type": "image_url", "image_url": {"url": uri}})
        return parts

    def _send(self, prefix=""):
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if prefix:
            text = (prefix + text) if text else prefix
        if not text and not self._attachments:
            return
        n_att = len(self._attachments)
        content = self._build_user_content(text)
        shown = text if not n_att else "{}  [\U0001F4CE {} image{}]".format(
            text, n_att, "s" if n_att > 1 else "")
        self._say("user", shown or "[image]")
        self._history.append({"role": "user", "content": content})
        self.input.clear()
        self._clear_attachments()
        hist = list(self._history)
        self._set_busy(True)
        w = _Worker(lambda: _chat(hist, system=_SEED_CHAT_SYSTEM), parent=self)
        w.done.connect(self._on_reply)
        w.failed.connect(self._on_fail)
        self._workers.append(w)
        w.start()

    def _on_reply(self, reply):
        self._set_busy(False)
        reply = reply or "(empty reply)"
        self._history.append({"role": "assistant", "content": reply})
        self._last_assistant = reply
        self.b_dream.setEnabled(True)
        self.b_seed3d.setEnabled(True)
        self._say("assistant", reply)

    def _on_fail(self, tb):
        self._set_busy(False)
        _error(tb)

    # -- quick actions -------------------------------------------------------
    def _prompt_doctor(self):
        if not self.input.toPlainText().strip():
            _error("Type your idea in the box first, then hit Prompt Doctor.")
            return
        if "Video" in self.target.currentText():
            prefix = ("Act as Prompt Doctor. Rewrite the following idea into ONE "
                      "optimized ENGLISH prompt for the Seedance video model, using "
                      "the formula Subject + Action details + Scene + Lighting & "
                      "Color + Camera movement + Visual style + Quality, quantifying "
                      "the motion. Output ONLY the prompt.\n\n")
        else:
            prefix = ("Act as Prompt Doctor. Rewrite the following idea into ONE "
                      "optimized ENGLISH prompt for the Seedream image model: state "
                      "subject, composition, lighting, lens and style, under 150 "
                      "words, in simple direct language. Output ONLY the prompt.\n\n")
        self._send(prefix=prefix)

    def _describe_image(self):
        if not self._attachments:
            _error("Attach an image first (\U0001F4CE Image or \U0001F5BC Viewport).")
            return
        self._send(prefix=("Describe this image in detail (subject, composition, "
                           "lighting, style), then suggest ONE optimized ENGLISH "
                           "prompt to recreate or improve it.\n\n"))

    def _send_to_dream(self):
        prompt = (self._last_assistant or "").strip()
        if not prompt:
            return
        try:
            dream_with_seedream(initial_prompt=prompt)
        except Exception:
            _error(traceback.format_exc())

    def _send_to_seed3d(self):
        prompt = (self._last_assistant or "").strip()
        if not prompt:
            return
        try:
            open_seed_3d(initial_prompt=prompt)
        except Exception:
            _error(traceback.format_exc())

    def _clear_chat(self):
        self._history = []
        self._last_assistant = ""
        self.b_dream.setEnabled(False)
        self.b_seed3d.setEnabled(False)
        self.view.clear()
        self._say("assistant", "Chat cleared. What would you like to do?")


def _seed_chat_window():
    """Return the single Seed Chat window, rebuilding it if the underlying C++
    object was destroyed (robust singleton, same pattern as the Dream gallery)."""
    w = getattr(_seed_chat_window, "_inst", None)
    if w is not None:
        try:
            w.objectName()                   # touch the C++ obj; raises if destroyed
        except Exception:
            w = None
    if w is None:
        w = SeedChatDialog()
        _seed_chat_window._inst = w
    return w


def open_seed_chat():
    """Open the Seed Chat window (BYTEPLUS menu entry)."""
    w = _seed_chat_window()
    w.show()
    w.raise_()


# =============================================================================
# Seed 3D -- text-to-3D asset generation (BytePlus 3D) imported into the scene
# -----------------------------------------------------------------------------
# Clones the async task pattern used for Seedance video (create -> poll -> download
# via CONFIG.THREE_D_TASKS, the same /contents/generations/tasks endpoint), then
# imports the downloaded mesh into the current Maya scene on the MAIN thread. v1 is
# Text->3D (CONFIG.THREE_D_MODEL). Image->3D + asset breakdown is a later phase.
#
# The 3D model ID must be set from your ModelArk console in Settings > 3D model --
# the documented IDs 404'd on this account until the model is activated there.
# =============================================================================

# fmt key -> (maya plugin to load, cmds.file import "type"). Missing = not natively
# importable by Maya (glb/gltf/stl) -- we still download it but can't import.
_3D_IMPORT = {
    "usdz": ("mayaUsdPlugin", "USD Import"),
    "usd":  ("mayaUsdPlugin", "USD Import"),
    "fbx":  ("fbxmaya", "FBX"),
    "obj":  ("objExport", "OBJ"),
}


def _scene_models_dir() -> str:
    """data/byteplus3d/<scene>/ -- generated 3D assets, grouped per Maya scene."""
    return _project_subdir("data", "data",
                           os.path.join("byteplus3d", _scene_tag()))


def _find_model_url(obj):
    """Recursively dig a 3D-model file URL out of an arbitrary task result. Robust
    to whichever key/nesting the 3D API uses (file_url / model_url / url ...)."""
    exts = (".glb", ".gltf", ".obj", ".fbx", ".stl", ".usdz", ".usd", ".zip")
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("http") and (any(e in s.lower() for e in exts)
                                     or "model" in s.lower()):
            return s
        return None
    if isinstance(obj, dict):
        for k in ("file_url", "fileUrl", "model_url", "modelUrl", "url"):
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        for v in obj.values():
            f = _find_model_url(v)
            if f:
                return f
    if isinstance(obj, (list, tuple)):
        for v in obj:
            f = _find_model_url(v)
            if f:
                return f
    return None


def _extract_3d_archive(out: str, fmt: str) -> str:
    """A 3D file_url is usually a ZIP / usdz holding the model layer PLUS a
    textures/ folder. Maya resolves the material's RELATIVE texture paths only when
    those files exist ON DISK next to the model layer -- importing the .usdz
    directly leaves the textures inside the archive (unresolved -> grey shader). So
    extract next to the saved file and import the real model layer. Falls back to
    `out` if it isn't an archive or extraction fails."""
    import zipfile
    try:
        if not zipfile.is_zipfile(out):
            return out
        extract_dir = os.path.splitext(out)[0] + "_files"
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(out) as z:
            z.extractall(extract_dir)
        pref = {
            "usdz": (".usdc", ".usda", ".usd"),
            "usd":  (".usdc", ".usda", ".usd"),
            "fbx":  (".fbx",),
            "obj":  (".obj",),
        }.get(fmt.lower(), (".usdc", ".usda", ".usd", ".fbx", ".obj", ".glb", ".gltf"))
        cands = []
        for root, _dirs, files in os.walk(extract_dir):
            for f in files:
                if f.lower().endswith(pref):
                    cands.append(os.path.join(root, f))
        if cands:
            cands.sort(key=lambda p: (p.count(os.sep), len(p)))   # shallowest first
            sys.stderr.write("[BYTEPLUS] 3D archive extracted -> importing {}\n"
                             .format(cands[0]))
            return cands[0]
    except Exception as e:
        sys.stderr.write("[BYTEPLUS] 3D archive extract failed ({}); importing the "
                         "downloaded file as-is.\n".format(e))
    return out


def _seed3d_generate(prompt, fmt="usdz", material="PBR", mesh_mode="Quad",
                     quality="", hd=False, images=None) -> bytes:
    """Submit a text->3D or image->3D job and poll until done; return the model-file
    bytes. NETWORK ONLY -- call from a _Worker, never the Maya UI thread.

    `images` (0-5 local paths or http URLs) switches on Image->3D: each is attached
    as an image_url part (local files -> base64, http URLs pass through). Output
    params are appended to the text as `--flags` (the API's loose-validation form)."""
    text = prompt.strip()
    text += " --material {} --mesh_mode {} --fileformat {}".format(
        material, mesh_mode, fmt)
    if quality:
        text += " --subdivisionlevel {}".format(quality)
    if hd:
        text += " --addons HighPack --hd_texture true"

    content = [{"type": "text", "text": text}]
    for src in (images or [])[:5]:                # Image->3D accepts 1-5 images
        uri = src if (isinstance(src, str) and src.startswith("http")) \
            else _data_uri(src, _image_mime(src))
        content.append({"type": "image_url", "image_url": {"url": uri}})
    body = {"model": CONFIG.THREE_D_MODEL, "content": content}
    if CONFIG.CALLBACK_URL:
        body["callback_url"] = CONFIG.CALLBACK_URL

    sys.stderr.write("[BYTEPLUS] Seed 3D request -> model={} fmt={} material={} "
                     "mesh={} hd={} images={}\n".format(
                         CONFIG.THREE_D_MODEL, fmt, material, mesh_mode, hd,
                         len(images or [])))
    created = _request("POST", CONFIG.BASE_URL + CONFIG.THREE_D_TASKS, body)
    tid = created.get("id") or created.get("task_id")
    if not tid:
        raise RuntimeError("No task id in 3D response: " + json.dumps(created))

    url = "{}{}/{}".format(CONFIG.BASE_URL, CONFIG.THREE_D_TASKS, tid)
    while True:                                       # 3D generation is async
        time.sleep(CONFIG.POLL_SECONDS)
        if _cancel_requested():                       # user hit the HUD's ✕
            try:
                _request("DELETE", url)               # abort -> frees compute
                sys.stderr.write("[BYTEPLUS] Seed 3D task {} cancelled.\n".format(tid))
            except Exception as ce:
                sys.stderr.write("[BYTEPLUS] 3D cancel: could not abort {} -> "
                                 "{}\n".format(tid, ce))
            raise _Cancelled()
        st = _request("GET", url)
        status = (st.get("status") or st.get("state") or "").lower()
        if status in ("succeeded", "success", "done", "completed"):
            model_url = _find_model_url(st)
            if not model_url:
                raise RuntimeError("3D task succeeded but no model URL found. Raw "
                                   "response:\n" + json.dumps(st, indent=2))
            _track("models", st, CONFIG.THREE_D_MODEL)
            sys.stderr.write("[BYTEPLUS] Seed 3D done -> {}\n".format(model_url))
            return _get_bytes(model_url)
        if status in ("failed", "error", "cancelled", "canceled", "expired"):
            raise RuntimeError("3D task failed: " + json.dumps(st, indent=2))


def _save_and_import_3d(data: bytes, fmt: str, prompt: str):
    """MAIN THREAD: write the downloaded model under the current project, import it
    into the scene, then frame it. Wrapped in ONE undo chunk so the whole import is
    a single Ctrl+Z."""
    ext = "." + fmt.lower().lstrip(".")
    out = _unique_path(_scene_models_dir(), _scene_tag() + "_seed3d", ext=ext)
    with open(out, "wb") as f:
        f.write(data)
    try:                                              # prompt sidecar for reference
        with open(os.path.splitext(out)[0] + ".txt", "w", encoding="utf-8") as f:
            f.write(prompt.strip() + "\n")
    except Exception:
        pass

    plugin, ftype = _3D_IMPORT.get(fmt.lower(), (None, None))
    if not ftype:
        _msgbox(QtWidgets.QMessageBox.Information, "BYTEPLUS - 3D downloaded",
                "The 3D asset was saved to:\n\n{}\n\nMaya can't import '{}' "
                "natively, so it wasn't added to the scene. Use USD, FBX or OBJ "
                "for automatic import.".format(out, fmt),
                QtWidgets.QMessageBox.Ok)
        return

    if plugin:
        try:
            if not cmds.pluginInfo(plugin, q=True, loaded=True):
                cmds.loadPlugin(plugin, quiet=True)
        except Exception as e:
            _error("Could not load the '{}' plugin needed to import {}:\n{}\n\n"
                   "The asset is saved at:\n{}".format(plugin, fmt, e, out))
            return

    # usdz/zip -> extract so the material's relative texture paths resolve on disk.
    import_path = _extract_3d_archive(out, fmt)
    ns = _safe_name(_scene_tag() + "_seed3d")
    cmds.undoInfo(openChunk=True)
    try:
        new = cmds.file(import_path.replace(os.sep, "/"), i=True, type=ftype,
                        ignoreVersion=True, mergeNamespacesOnClash=False,
                        namespace=ns, returnNewNodes=True,
                        preserveReferences=True) or []
    except Exception:
        _error("The 3D asset downloaded OK and is saved at:\n{}\n\nbut Maya could "
               "not import it as {}:\n\n{}".format(out, fmt, traceback.format_exc()))
        return
    finally:
        cmds.undoInfo(closeChunk=True)

    try:
        xforms = cmds.ls(new, type="transform") or new
        if xforms:
            cmds.select(xforms, replace=True)
            cmds.viewFit()
    except Exception:
        pass
    cmds.inViewMessage(amg="BYTEPLUS: 3D asset imported ({} node{}).".format(
        len(new), "s" if len(new) != 1 else ""), pos="midCenter", fade=True)


_ENHANCE_3D_SYSTEM = (
    "You improve prompts for a text-to-3D asset generator (Hyper3D). Rewrite the "
    "user's idea into ONE concise ENGLISH prompt describing a SINGLE 3D object: its "
    "form, key shapes, materials/surface and style, with a useful level of detail. "
    "Keep it under 60 words. Do NOT mention camera, lighting or scene/background -- "
    "it's a standalone asset, not a photo. Preserve the user's subject and intent. "
    "Output ONLY the improved prompt, no preamble or quotes.")


def _enhance_3d_prompt(text: str) -> str:
    """Improve the wording of a text-to-3D prompt with Seed 2.0. TEXT-ONLY, network
    only -- call from a _Worker."""
    return _chat([{"role": "user", "content": "Improve this 3D asset prompt:\n" + text}],
                 system=_ENHANCE_3D_SYSTEM)


class Seed3DDialog(QtWidgets.QDialog):
    """Collects a Text->3D or Image->3D request (prompt/image + output params)."""

    def __init__(self, parent=None, initial_prompt=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS - Seed 3D")
        self.setMinimumSize(560, 560)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._images = []                     # local paths / http URLs for Image->3D
        self._enh_worker = None
        v = QtWidgets.QVBoxLayout(self)

        # -- mode ------------------------------------------------------------
        mrow = QtWidgets.QHBoxLayout()
        mrow.addWidget(QtWidgets.QLabel("Mode:"))
        self.mode_text = QtWidgets.QRadioButton("Text → 3D")
        self.mode_text.setChecked(True)
        self.mode_image = QtWidgets.QRadioButton("Image → 3D")
        self.mode_text.toggled.connect(self._sync_mode)
        mrow.addWidget(self.mode_text); mrow.addWidget(self.mode_image)
        mrow.addStretch(1)
        v.addLayout(mrow)

        # -- image source (Image->3D only) -----------------------------------
        self.img_row = QtWidgets.QWidget()
        ih = QtWidgets.QHBoxLayout(self.img_row)
        ih.setContentsMargins(0, 0, 0, 0)
        self.thumb = QtWidgets.QLabel("(no image)")
        self.thumb.setFixedSize(160, 120)
        self.thumb.setAlignment(QtCore.Qt.AlignCenter)
        self.thumb.setStyleSheet("background:#1d1d1d; color:#888;")
        ih.addWidget(self.thumb)
        ibtns = QtWidgets.QVBoxLayout()
        b_browse = QtWidgets.QPushButton("Browse…")
        b_browse.clicked.connect(self._browse_image)
        b_gallery = QtWidgets.QPushButton("From gallery")
        b_gallery.clicked.connect(self._from_gallery)
        b_clr = QtWidgets.QPushButton("Clear")
        b_clr.clicked.connect(self._clear_images)
        for b in (b_browse, b_gallery, b_clr):
            ibtns.addWidget(b)
        ibtns.addStretch(1)
        ih.addLayout(ibtns); ih.addStretch(1)
        v.addWidget(self.img_row)

        lrow = QtWidgets.QHBoxLayout()
        self.lbl = QtWidgets.QLabel("<b>Describe the 3D asset to generate</b>")
        lrow.addWidget(self.lbl); lrow.addStretch(1)
        self.b_enhance = QtWidgets.QPushButton("✦ Enhance")
        self.b_enhance.setToolTip("Improve the wording of your 3D prompt with Seed 2.0 "
                                  "(keeps your subject and intent)")
        self.b_enhance.clicked.connect(self._enhance)
        lrow.addWidget(self.b_enhance)
        v.addLayout(lrow)
        self.prompt = QtWidgets.QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "e.g. a stylized wooden treasure chest with iron bands, game-ready")
        if initial_prompt:
            self.prompt.setPlainText(initial_prompt)
        v.addWidget(self.prompt, 1)

        form = QtWidgets.QFormLayout()
        self.material = QtWidgets.QComboBox()
        self.material.addItems(["PBR", "Shaded", "None"])
        self.material.setCurrentText(CONFIG.THREE_D_MATERIAL)
        self.material.setToolTip("PBR = base-color+metallic+normal+roughness maps; "
                                 "Shaded = base color with baked light; None = white mesh")
        form.addRow("Material", self.material)
        self.mesh = QtWidgets.QComboBox()
        self.mesh.addItems(["Quad", "Raw"])
        self.mesh.setToolTip("Quad = clean quad topology; Raw = triangle mesh")
        form.addRow("Mesh", self.mesh)
        self.fmt = QtWidgets.QComboBox()
        self.fmt.addItems(["usdz", "fbx", "obj"])
        self.fmt.setCurrentText(CONFIG.THREE_D_FORMAT)
        self.fmt.setToolTip("File format to request and import (Maya imports USD via "
                            "mayaUsdPlugin, FBX via fbxmaya, OBJ built-in)")
        form.addRow("Import format", self.fmt)
        self.quality = QtWidgets.QComboBox()
        self.quality.addItems(["(default)", "high", "medium", "low"])
        self.quality.setToolTip("Polygon-detail preset (subdivision level)")
        form.addRow("Detail", self.quality)
        self.hd = QtWidgets.QCheckBox("4K textures (HighPack)")
        form.addRow("", self.hd)
        v.addLayout(form)

        hint = QtWidgets.QLabel(
            "If generation fails with 'NotFound', set your real 3D model ID in "
            "BYTEPLUS > Settings > 3D model (the shipped default is a placeholder).")
        hint.setWordWrap(True); hint.setStyleSheet("color:#888;")
        v.addWidget(hint)

        if CONFIG.SHOW_COST:
            cost = QtWidgets.QLabel(_fmt_cost(0, CONFIG.COST_3D_USD) + "  (per model)")
            cost.setStyleSheet("color:#2E8BE6; font-weight:bold;")
            v.addWidget(cost)

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Generate")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._sync_mode()                     # hide the image row in Text mode

    def prompt_text(self):
        return self.prompt.toPlainText().strip()

    def _enhance(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            cmds.inViewMessage(amg="Type a prompt first, then <hl>✦ Enhance</hl>.",
                               pos="midCenter", fade=True)
            return
        self.b_enhance.setEnabled(False)
        self.b_enhance.setText("Enhancing…")
        self._enh_worker = _Worker(lambda: _enhance_3d_prompt(text), parent=self)

        def done(t):
            if t:
                self.prompt.setPlainText(t)          # Ctrl+Z restores the original
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")

        def fail(tb):                                # NB: no _msgbox from a modal dialog
            self.b_enhance.setEnabled(True)
            self.b_enhance.setText("✦ Enhance")
            cmds.inViewMessage(amg="Enhance failed (see Script Editor).",
                               pos="midCenter", fade=True)
            sys.stderr.write("[BYTEPLUS] 3D enhance failed:\n" + tb + "\n")

        self._enh_worker.done.connect(done)
        self._enh_worker.failed.connect(fail)
        self._enh_worker.start()

    def _sync_mode(self, *_):
        img = self.mode_image.isChecked()
        self.img_row.setVisible(img)
        if img:
            self.lbl.setText("<b>Optional guidance</b>  (the image drives the shape)")
            self.prompt.setPlaceholderText(
                "Optional: extra guidance, e.g. 'clean topology, symmetrical, game-ready'")
        else:
            self.lbl.setText("<b>Describe the 3D asset to generate</b>")
            self.prompt.setPlaceholderText(
                "e.g. a stylized wooden treasure chest with iron bands, game-ready")

    def _browse_image(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Choose reference image(s) for Image → 3D", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if paths:
            self._images = paths[:5]
            self._refresh_img()

    def _from_gallery(self):
        # Open the generated-images folder in a standard file dialog. Robust: works
        # whether or not the gallery window is open, and -- unlike _msgbox / a custom
        # modal picker -- a QFileDialog is safe to open from inside this modal dialog
        # (re-showing an always-on-top modal via _msgbox freezes Maya).
        try:
            start = _scene_images_dir()
        except Exception:
            start = ""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Pick generated image(s) for Image → 3D", start,
            "Images (*.png *.jpg *.jpeg *.webp)")
        if paths:
            self._images = paths[:5]
            self._refresh_img()

    def _clear_images(self):
        self._images = []
        self._refresh_img()

    def _refresh_img(self, data=None):
        if self._images and self._images[0]:
            pm = QtGui.QPixmap()
            if data:
                pm.loadFromData(data)
            elif not str(self._images[0]).startswith("http"):
                pm = QtGui.QPixmap(self._images[0])
            if not pm.isNull():
                self.thumb.setPixmap(pm.scaled(
                    160, 120, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            else:
                self.thumb.setText("image set")
            self.thumb.setToolTip("{} image(s)".format(len(self._images)))
        else:
            self.thumb.clear()
            self.thumb.setText("(no image)")

    def params(self):
        q = self.quality.currentText()
        return {
            "mode": "image" if self.mode_image.isChecked() else "text",
            "images": list(self._images),
            "material": self.material.currentText(),
            "mesh_mode": self.mesh.currentText(),
            "fmt": self.fmt.currentText(),
            "quality": "" if q.startswith("(") else q,
            "hd": self.hd.isChecked(),
        }


def open_seed_3d(initial_prompt=None):
    """Open Seed 3D (Text->3D or Image->3D): collect intent, then generate +
    import async. `initial_prompt` pre-fills the prompt (used by Seed Chat)."""
    if not _scene_ok_to_proceed():
        return
    d = Seed3DDialog(initial_prompt=initial_prompt)
    if not d.exec():
        return
    p = d.params()
    prompt = d.prompt_text()
    images = p.get("images") or []
    if p["mode"] == "image":
        if not images:
            _error("Image → 3D needs at least one image. Use  Browse…  or  "
                   "From gallery.")
            return
    elif not prompt:
        return
    fmt = p["fmt"]

    dlg = _progress("Generating 3D asset (this can take a minute)...")
    worker = _Worker(
        lambda: _seed3d_generate(prompt, fmt=fmt, material=p["material"],
                                 mesh_mode=p["mesh_mode"], quality=p["quality"],
                                 hd=p["hd"], images=images),
        parent=_main_window())
    worker.done.connect(lambda data: (dlg.close(),
                                      _save_and_import_3d(data, fmt, prompt or "image-to-3d")))
    worker.failed.connect(lambda tb: (dlg.close(), _error(tb)))
    worker.start()
    open_seed_3d._w = worker                          # keep the QThread referenced


# =============================================================================
# Seed Assistant -- in-Maya automation agent (BytePlus Seed 2.0 + tool calling)
# -----------------------------------------------------------------------------
# A chat window where Seed 2.0 can INSPECT and MODIFY the Maya scene through two
# tools: get_scene_info (read-only, auto-runs) and run_maya_python (executes
# Python -- the user REVIEWS/EDITS/APPROVES every block, and it runs inside one
# undo chunk). The tool-calling loop alternates a background API call (_Worker)
# with main-thread tool execution until the model returns a final answer.
# Reuses _chat's transport idea via _chat_with_tools; see also [Seed Chat].
# =============================================================================

def _chat_with_tools(messages, tools, system=None, model=None):
    """One tool-enabled chat round. Returns the raw assistant message dict (which
    may carry `tool_calls`). NETWORK ONLY -- call from a _Worker."""
    model = model or CONFIG.SEED_CHAT_MODEL
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    body = {"model": model, "messages": msgs, "tools": tools, "tool_choice": "auto"}
    resp = _request("POST", CONFIG.BASE_URL + CONFIG.CHAT_COMPLETIONS, body)
    _track("llm", resp, model)
    return resp["choices"][0]["message"]


_AGENT_TOOLS = [
    {"type": "function", "function": {
        "name": "get_scene_info",
        "description": "Return a JSON snapshot of the current Maya scene: current "
                       "selection, object counts by type, frame range, current "
                       "frame, renderer, up-axis, linear unit and scene file name. "
                       "Read-only and runs automatically. Call it to understand the "
                       "scene before acting.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "run_maya_python",
        "description": "Execute Python code inside Maya (maya.cmds is available as "
                       "`cmds`, maya.mel as `mel`). Use for ALL scene changes and "
                       "for any query get_scene_info does not cover. The user "
                       "reviews, may edit, and approves the code before it runs, "
                       "and it runs inside a single undo step. print() any values "
                       "you need returned to you.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Python code to run in Maya."}},
            "required": ["code"]}}},
]

_AGENT_SYSTEM = (
    "You are Seed Assistant, an automation agent embedded in Autodesk Maya (this "
    "is Maya 2027), powered by BytePlus Seed 2.0. You help the artist inspect and "
    "modify their Maya scene through two tools:\n"
    "- get_scene_info(): read-only JSON snapshot (selection, counts, frame range, "
    "renderer, units). Runs automatically. Call it to understand scene state first.\n"
    "- run_maya_python(code): executes Python in Maya (maya.cmds as `cmds`, maya.mel "
    "as `mel`). The USER reviews/edits/approves every block before it runs, inside a "
    "single undo step.\n\n"
    "Guidelines:\n"
    "- Inspect first (get_scene_info) when the task depends on scene state.\n"
    "- Write minimal, focused, correct maya.cmds code; prefer cmds over mel. print() "
    "any value you need to read back (the printed output is returned to you).\n"
    "- Do ONE coherent step per run_maya_python call so the user can review it; "
    "you'll see the result and can continue.\n"
    "- Never assume node names -- query them; handle empty selections gracefully.\n"
    "- If the user SKIPS a code block, don't silently retry it; ask what they'd "
    "prefer.\n"
    "- Clearly state anything destructive (deleting nodes, file operations) BEFORE "
    "proposing the code.\n"
    "- Briefly say what you're about to do before proposing code, and give a short "
    "summary when done. Reply in the user's language (they may write Spanish).")


def _tool_scene_info():
    """MAIN THREAD: a compact, read-only snapshot of the scene as a JSON string."""
    info = {}
    try:
        sel = cmds.ls(selection=True) or []
        info["selection"] = sel[:50]
        info["selected_count"] = len(sel)
        info["current_frame"] = cmds.currentTime(q=True)
        try:
            info["frame_range"] = [cmds.playbackOptions(q=True, min=True),
                                   cmds.playbackOptions(q=True, max=True)]
        except Exception:
            pass
        info["scene"] = cmds.file(q=True, sceneName=True) or "(unsaved)"
        try:
            info["up_axis"] = cmds.upAxis(q=True, axis=True)
        except Exception:
            pass
        try:
            info["linear_unit"] = cmds.currentUnit(q=True, linear=True)
        except Exception:
            pass
        try:
            info["renderer"] = cmds.getAttr("defaultRenderGlobals.currentRenderer")
        except Exception:
            pass
        counts = {}
        for label, kw in (("mesh", {"type": "mesh"}), ("camera", {"type": "camera"}),
                          ("joint", {"type": "joint"}),
                          ("nurbsCurve", {"type": "nurbsCurve"}),
                          ("light", {"lights": True})):
            try:
                counts[label] = len(cmds.ls(**kw) or [])
            except Exception:
                pass
        info["counts"] = counts
        info["total_transforms"] = len(cmds.ls(type="transform") or [])
    except Exception as e:
        info["error"] = str(e)
    return json.dumps(info)


class _CodeApprovalDialog(QtWidgets.QDialog):
    """Shows the Python the assistant wants to run. The user can edit it, then Run
    or Skip, and optionally trust the rest of the session (auto-run)."""

    def __init__(self, code, parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS - Seed Assistant wants to run code")
        self.setMinimumSize(660, 470)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel(
            "<b>The assistant proposes running this Python in Maya.</b><br>"
            "Review or edit it, then Run or Skip. It runs inside a single undo step "
            "(Ctrl+Z reverts it)."))
        self.edit = QtWidgets.QPlainTextEdit()
        self.edit.setPlainText(code)
        mono = QtGui.QFont("Consolas"); mono.setStyleHint(QtGui.QFont.Monospace)
        self.edit.setFont(mono)
        v.addWidget(self.edit, 1)
        self.trust = QtWidgets.QCheckBox(
            "Don't ask again this session -- auto-run the assistant's code")
        v.addWidget(self.trust)
        bb = QtWidgets.QDialogButtonBox()
        bb.addButton("Run", QtWidgets.QDialogButtonBox.AcceptRole)
        bb.addButton("Skip", QtWidgets.QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def result_code(self):
        return self.edit.toPlainText()

    def trust_session(self):
        return self.trust.isChecked()


class SeedAssistantDialog(QtWidgets.QDialog):
    """In-Maya automation agent: multi-turn chat with Seed 2.0 that can inspect and
    (with per-block approval) modify the scene via tool calls. Singleton."""

    _MAX_ROUNDS = 8                       # tool-call rounds per user turn (runaway guard)

    def __init__(self, parent=None):
        super().__init__(parent or _main_window())
        self.setWindowTitle("BYTEPLUS - Seed Assistant")
        self.setMinimumSize(600, 700)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self._history = []
        self._busy = False
        self._trust_session = False
        self._workers = []

        v = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel(
            "<b>Seed Assistant</b> — automates Maya. It runs code only after you approve it."))
        top.addStretch(1)
        b_clear = QtWidgets.QPushButton("Clear")
        b_clear.clicked.connect(self._clear_chat)
        top.addWidget(b_clear)
        v.addLayout(top)

        self.view = QtWidgets.QTextBrowser()
        self.view.setStyleSheet("QTextBrowser{background:#1d1d1d;color:#dddddd;}")
        v.addWidget(self.view, 1)
        self._say("assistant",
                  "Hi \U0001F44B I can inspect and modify your Maya scene. Tell me "
                  "what to do (e.g. \"select all lights\", \"rename selected to "
                  "prop_### \", \"lay out these on a grid\"). I'll propose code and "
                  "you approve it before it runs.")

        self.input = _ChatInput(self._send)
        self.input.setFixedHeight(84)
        v.addWidget(self.input)

        srow = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color:#2E8BE6;")
        srow.addWidget(self.status, 1)
        self.b_send = QtWidgets.QPushButton("Send")
        self.b_send.setDefault(True)
        self.b_send.clicked.connect(lambda: self._send())
        srow.addWidget(self.b_send)
        v.addLayout(srow)

    # -- transcript ----------------------------------------------------------
    @staticmethod
    def _esc(t):
        return (t.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace("\n", "<br>"))

    def _say(self, role, text):
        esc = self._esc(text)
        if role == "code":
            html = ("<pre style='background:#111;color:#cfe6ff;padding:6px;"
                    "border-left:3px solid #2E8BE6;white-space:pre-wrap'>{}</pre>"
                    .format(esc))
        else:
            who, col = {"user": ("You", "#8ac6ff"),
                        "assistant": ("Seed", "#7ee081"),
                        "tool": ("tool", "#c8a24a")}.get(role, ("Seed", "#7ee081"))
            html = ("<p style='margin:6px 0'><b style='color:{}'>{}:</b> {}</p>"
                    .format(col, who, esc))
        self.view.append(html)
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # -- tools (MAIN THREAD) -------------------------------------------------
    def _exec_tool(self, name, args):
        if name == "get_scene_info":
            return _tool_scene_info()
        if name == "run_maya_python":
            return self._run_python(args.get("code", "") if isinstance(args, dict) else "")
        return "Unknown tool: {}".format(name)

    def _run_python(self, code):
        if not (code or "").strip():
            return "No code was provided."
        if not self._trust_session:
            d = _CodeApprovalDialog(code, self)
            if not d.exec():
                self._say("tool", "⏭ You skipped this code.")
                return ("The user SKIPPED running this code. Do not retry it; ask "
                        "them what they'd prefer instead.")
            code = d.result_code()
            if d.trust_session():
                self._trust_session = True
                self._say("tool", "Auto-run enabled for this session.")
        self._say("code", code)
        import io as _io
        import contextlib as _ctx
        buf = _io.StringIO()
        g = {"cmds": cmds, "mel": mel}
        cmds.undoInfo(openChunk=True)
        try:
            with _ctx.redirect_stdout(buf), _ctx.redirect_stderr(buf):
                exec(code, g)                        # noqa: S102 -- user-approved
            out = buf.getvalue().strip()
            res = "Ran OK." + ("\nOutput:\n" + out if out else " (no printed output)")
        except Exception:
            res = "ERROR while running the code:\n" + traceback.format_exc()
            out = buf.getvalue().strip()
            if out:
                res += "\nOutput before the error:\n" + out
        finally:
            cmds.undoInfo(closeChunk=True)
        self._say("tool", res[:1800])
        return res

    # -- agent loop ----------------------------------------------------------
    def _set_busy(self, busy):
        self._busy = busy
        for w in (self.b_send, self.input):
            w.setEnabled(not busy)
        self.status.setText("Seed is working…" if busy else "")

    def _send(self):
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self._say("user", text)
        self._history.append({"role": "user", "content": text})
        self.input.clear()
        self._agent_step(self._MAX_ROUNDS)

    def _agent_step(self, rounds_left):
        hist = list(self._history)
        self._set_busy(True)
        w = _Worker(lambda: _chat_with_tools(hist, _AGENT_TOOLS,
                                             system=_AGENT_SYSTEM), parent=self)
        w.done.connect(lambda msg: self._on_agent_msg(msg, rounds_left))
        w.failed.connect(self._on_fail)
        self._workers.append(w)
        w.start()

    def _on_agent_msg(self, msg, rounds_left):
        content = msg.get("content") if isinstance(msg, dict) else None
        tool_calls = (msg.get("tool_calls") if isinstance(msg, dict) else None) or []
        am = {"role": "assistant", "content": content}
        if tool_calls:
            am["tool_calls"] = tool_calls
        self._history.append(am)
        if content:
            self._say("assistant", content)
        if not tool_calls:
            self._set_busy(False)               # final answer
            return
        if rounds_left <= 0:
            self._say("assistant", "(Stopped: reached the tool-call limit for this "
                                   "turn. Ask me to continue if needed.)")
            self._set_busy(False)
            return
        for tc in tool_calls:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            if name != "run_maya_python":
                self._say("tool", "→ {}()".format(name))
            try:
                result = self._exec_tool(name, args)
            except Exception:
                result = "Tool crashed:\n" + traceback.format_exc()
            self._history.append({"role": "tool", "tool_call_id": tc.get("id"),
                                  "content": result})
        self._agent_step(rounds_left - 1)

    def _on_fail(self, tb):
        self._set_busy(False)
        _error(tb)

    def _clear_chat(self):
        if self._busy:
            return
        self._history = []
        self.view.clear()
        self._say("assistant", "Cleared. What should I do in the scene?")


def _seed_assistant_window():
    """Robust singleton for the Seed Assistant window (rebuilds if destroyed)."""
    w = getattr(_seed_assistant_window, "_inst", None)
    if w is not None:
        try:
            w.objectName()
        except Exception:
            w = None
    if w is None:
        w = SeedAssistantDialog()
        _seed_assistant_window._inst = w
    return w


def open_seed_assistant():
    """Open the Seed Assistant window (BYTEPLUS menu entry)."""
    w = _seed_assistant_window()
    w.show()
    w.raise_()


# =============================================================================
# Menu construction
# =============================================================================
def _safe(fn):
    """Wrap a menu callback so exceptions surface in a dialog, not silently."""
    def wrapped(*_):
        try:
            fn()
        except Exception:
            _error(traceback.format_exc())
    return wrapped


def install():
    """Build (or rebuild) the BYTEPLUS menu on Maya's main window."""
    _load_prefs()
    _load_usage()
    if cmds.menu(CONFIG.MENU_NAME, exists=True):
        cmds.deleteUI(CONFIG.MENU_NAME)
    gmw = mel.eval("$tmp = $gMainWindow")
    cmds.menu(CONFIG.MENU_NAME, label=CONFIG.MENU_LABEL, parent=gmw, tearOff=True)

    # Small native Maya icons next to each item (icons ship with Maya, so there
    # is nothing extra to distribute; a missing name just shows no icon).
    cmds.menuItem(label="Render with Seedance 2.0", parent=CONFIG.MENU_NAME,
                  image="render.png",
                  annotation="Render up to 9 refs + playblast -> 1080p video",
                  command=_safe(render_with_seedance))
    cmds.menuItem(label="Dream with Seedreams 5.0", parent=CONFIG.MENU_NAME,
                  image="out_imagePlane.png",
                  annotation="Viewport snapshot + prompt -> generated image",
                  command=_safe(dream_with_seedream))
    cmds.menuItem(label="Open Dream Gallery", parent=CONFIG.MENU_NAME,
                  image="fileOpen.png",
                  annotation="Browse / refine / animate previously generated images",
                  command=_safe(open_gallery))
    cmds.menuItem(label="Open Video Gallery", parent=CONFIG.MENU_NAME,
                  image="playblast.png",
                  annotation="Browse / regenerate / open generated videos",
                  command=_safe(open_video_gallery))
    cmds.menuItem(divider=True, parent=CONFIG.MENU_NAME)
    cmds.menuItem(label="Seed Chat", parent=CONFIG.MENU_NAME,
                  image="commandButton.png",
                  annotation="Chat with Seed 2.0: prompt help, describe images, "
                             "ask Model Genius",
                  command=_safe(open_seed_chat))
    cmds.menuItem(label="Seed 3D", parent=CONFIG.MENU_NAME,
                  image="polyCube.png",
                  annotation="Generate a 3D asset from text or an image and import it",
                  command=_safe(open_seed_3d))
    cmds.menuItem(label="Seed Assistant", parent=CONFIG.MENU_NAME,
                  image="commandButton.png",
                  annotation="Agent that inspects/automates your Maya scene "
                             "(runs code only after you approve it)",
                  command=_safe(open_seed_assistant))
    cmds.menuItem(divider=True, parent=CONFIG.MENU_NAME)
    cmds.menuItem(label="Generate Texture", parent=CONFIG.MENU_NAME,
                  image="out_file.png",
                  annotation="Prompt -> texture wired into a new OpenPBR shader",
                  command=_safe(generate_texture))
    cmds.menuItem(divider=True, parent=CONFIG.MENU_NAME)
    cmds.menuItem(label="Settings...", parent=CONFIG.MENU_NAME,
                  image="advancedSettings.png",
                  annotation="Resolution, ratio, ref count, TOS, webhook",
                  command=_safe(open_settings))
    cmds.menuItem(label="Set up motion hosting...", parent=CONFIG.MENU_NAME,
                  image="menuIconWindow.png",
                  annotation="Guided setup + test for the playblast video host "
                             "(Cloudflare R2 / BytePlus TOS)",
                  command=_safe(setup_hosting))
    cmds.menuItem(label="Usage...", parent=CONFIG.MENU_NAME,
                  image="menuIconWindow.png",
                  annotation="Images / videos / tokens used on this machine",
                  command=_safe(show_usage))
    cmds.menuItem(label="Report a Bug...", parent=CONFIG.MENU_NAME,
                  image="help.png",
                  annotation="Email a bug report to the developer",
                  command=_safe(report_bug))
    cmds.menuItem(label="About", parent=CONFIG.MENU_NAME,
                  image="help.png",
                  command=_safe(show_about))

    # Diagnostics submenu -- developer/partner only. Hidden in client builds
    # (DEBUG off). Devs flip CONFIG.DEBUG in Settings or set BYTEPLUS_DEBUG=1.
    if _debug_on():
        diag = cmds.menuItem(label="Diagnostics", parent=CONFIG.MENU_NAME,
                             subMenu=True, tearOff=True)
        cmds.menuItem(label="Test Seedream (image)", parent=diag,
                      annotation="POST /images/generations with the saved model",
                      command=_safe(diagnose))
        cmds.menuItem(label="Test LLM (auto-prompt)", parent=diag,
                      annotation="Validate the multimodal LLM used for auto-prompt",
                      command=_safe(diagnose_llm))
        cmds.menuItem(label="Test Seedance model (video)", parent=diag,
                      annotation="Create a tiny Seedance task to validate the model ID",
                      command=_safe(diagnose_video))
        cmds.menuItem(label="Test image refs (9x)", parent=diag,
                      annotation="Validate the multi-image reference payload",
                      command=_safe(diagnose_images))
        cmds.menuItem(label="Test motion playblast + TOS", parent=diag,
                      annotation="Playblast -> TOS URL -> Seedance video reference",
                      command=_safe(diagnose_video_movie))
        cmds.menuItem(label="Test R2 hosting", parent=diag,
                      annotation="Upload/presign/fetch/delete a test file on R2",
                      command=_safe(diagnose_r2))
        cmds.menuItem(label="Test telemetry", parent=diag,
                      annotation="Send one test event to PostHog / R2",
                      command=_safe(diagnose_telemetry))

    cmds.menuItem(divider=True, parent=CONFIG.MENU_NAME)
    tp = cmds.menuItem(label="Technology Preview", parent=CONFIG.MENU_NAME,
                       enable=False)
    _style_tp_item(tp)                               # paint it BytePlus-blue

    # First-run, consent-based identity prompt (deferred so the menu shows first).
    maya.utils.executeDeferred(_maybe_identify)
    return CONFIG.MENU_NAME


def uninstall():
    if cmds.menu(CONFIG.MENU_NAME, exists=True):
        cmds.deleteUI(CONFIG.MENU_NAME)


# =============================================================================
# Optional: load as a real Maya plug-in (Plug-in Manager)
# =============================================================================
def initializePlugin(plugin):
    install()


def uninitializePlugin(plugin):
    uninstall()


if __name__ == "__main__":
    install()
