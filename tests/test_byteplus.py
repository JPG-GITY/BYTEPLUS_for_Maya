"""Offline test harness for byteplus_maya.py — run it from the repo root:

    python tests/test_byteplus.py

Stubs Maya + PySide so the REAL plugin module imports outside Maya, then exercises
the logic with the network mocked. No Maya, no BytePlus calls, no cost.

Covers: trusted-URL Edit/Extend (face exemption), reference images, network
hardening (friendly errors, resilient polling, no double-charge) and the in-flight
task journal + auto-recovery.
"""
import sys, types, os, json, time, tempfile, io, socket
import urllib.request as _ur, urllib.error as _ue
from unittest.mock import MagicMock

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- stub maya ---
maya = types.ModuleType("maya"); sys.modules["maya"] = maya
for sub in ["cmds", "mel", "OpenMayaUI", "utils"]:
    mm = MagicMock(); sys.modules["maya." + sub] = mm; setattr(maya, sub, mm)

# ----------------------------------------------------------- fake Qt / shiboken
class _AnyMeta(type):
    def __getattr__(cls, name): return _mkclass(name)
    def __call__(cls, *a, **k): return _AnyObj()

def _mkclass(name="Any"): return _AnyMeta(name, (), {})

class _AnyObj:
    def __init__(self, *a, **k): pass
    def __call__(self, *a, **k):
        if len(a) == 1 and callable(a[0]) and not k: return a[0]
        return _AnyObj()
    def __getattr__(self, n): return _AnyObj()

class _FakeQtMod(types.ModuleType):
    def __getattr__(self, name): return _mkclass(name)

pyside6 = types.ModuleType("PySide6"); sys.modules["PySide6"] = pyside6
for sub in ["QtWidgets", "QtCore", "QtGui"]:
    fm = _FakeQtMod("PySide6." + sub); sys.modules["PySide6." + sub] = fm
    setattr(pyside6, sub, fm)
shib = types.ModuleType("shiboken6"); shib.wrapInstance = lambda *a, **k: _AnyObj()
sys.modules["shiboken6"] = shib

# --------------------------------------------------------------- import module
sys.path.insert(0, SRC_DIR)
import byteplus_maya as bm
print("imported byteplus_maya OK  (VERSION = %s)" % bm.CONFIG.VERSION)

# capture originals BEFORE any mocking
ORIG_OPEN, ORIG_REQUEST = bm._open, bm._request
ORIG_GET_BYTES, ORIG_GEN = bm._get_bytes, bm._seedance_generate

FAILS = []
def check(name, cond):
    print(("  PASS " if cond else "  FAIL ") + name)
    if not cond: FAILS.append(name)

tmp = tempfile.mkdtemp()

# =========================================================== 1. srcurl sidecar
print("\n[1] _read_srcurl_sidecar")
vid = os.path.join(tmp, "clip_video_1.mp4"); open(vid, "wb").write(b"x")
json.dump({"url": "https://seedance.cdn/orig.mp4", "ts": int(time.time())},
          open(vid + ".srcurl.json", "w"))
check("fresh sidecar returns url",
      bm._read_srcurl_sidecar(vid) == "https://seedance.cdn/orig.mp4")
json.dump({"url": "https://seedance.cdn/orig.mp4", "ts": 0},
          open(vid + ".srcurl.json", "w"))
check("stale (>24h) sidecar returns None", bm._read_srcurl_sidecar(vid) is None)
os.remove(vid + ".srcurl.json")
check("missing sidecar returns None", bm._read_srcurl_sidecar(vid) is None)
open(vid + ".srcurl.json", "w").write("{not json")
check("malformed sidecar returns None (no crash)", bm._read_srcurl_sidecar(vid) is None)

# ================================ 2 & 3. _seedance_generate movie handling ====
print("\n[2/3] _seedance_generate movie: http passthrough vs local re-host")
posted = {}
def fake_request(method, url, body=None):
    if method == "POST":
        posted["body"] = body; return {"id": "task1"}
    if method == "GET":
        return {"status": "succeeded",
                "content": {"video_url": "https://seedance.cdn/out.mp4",
                            "last_frame_url": "https://seedance.cdn/last.png"},
                "resolution": "1080p", "duration": 5}
    return {}
host_calls = []
def fake_host(path):
    host_calls.append(path); return ("https://r2.hosted/clip.mp4", lambda: None)
bm._request = fake_request
bm._get_bytes = lambda u: b"FAKE"
bm._cancel_requested = lambda: False
bm._track = lambda *a, **k: None
bm._host_video = fake_host
bm.time.sleep = lambda *a, **k: None
bm.CONFIG.POLL_SECONDS = 0
bm.CONFIG.TASKS_PATH = os.path.join(tmp, "tasks.json")

def ref_video_url(body):
    for it in body.get("content", []):
        if it.get("role") == "reference_video":
            return it["video_url"]["url"]
    return None

host_calls.clear(); posted.clear(); meta = {}
out = bm._seedance_generate("edit night", [], "https://trusted.seedance/orig.mp4",
                            5, require_motion_video=True, out_meta=meta)
check("http movie: _host_video NOT called (no re-host)", host_calls == [])
check("http movie: reference_video url == the trusted url",
      ref_video_url(posted["body"]) == "https://trusted.seedance/orig.mp4")
check("http movie: returns the video bytes", out == b"FAKE")
check("http movie: out_meta['video_url'] captured",
      meta.get("video_url") == "https://seedance.cdn/out.mp4")

host_calls.clear(); posted.clear()
out = bm._seedance_generate("edit", [], "/local/clip.mp4", 5, require_motion_video=True)
check("local movie: _host_video called once", host_calls == ["/local/clip.mp4"])
check("local movie: reference_video url == the hosted url",
      ref_video_url(posted["body"]) == "https://r2.hosted/clip.mp4")

# =============================== 4 & 5. _seedance_edit source routing ==========
print("\n[4/5] _seedance_edit: trusted URL vs local re-encode")
gen_args = {}
def fake_generate(prompt, imgs, movie, duration, **kw):
    gen_args.clear(); gen_args.update(dict(prompt=prompt, imgs=imgs, movie=movie,
                                           duration=duration, kw=kw))
    return b"EDITED"
ensure_calls = []
bm._seedance_generate = fake_generate
bm._ensure_seedance_video = lambda p: (ensure_calls.append(p) or p)
bm._mux_audio_from = lambda out, path: out

ensure_calls.clear(); em = {}
r = bm._seedance_edit("/gallery/clip.mp4", "make it night", 5,
                      source_url="https://trusted/orig.mp4", out_meta=em)
check("edit+url: _seedance_generate got the trusted url as movie",
      gen_args.get("movie") == "https://trusted/orig.mp4")
check("edit+url: trusted_input=True passed", gen_args["kw"].get("trusted_input") is True)
check("edit+url: out_meta threaded through", gen_args["kw"].get("out_meta") is em)
check("edit+url: _ensure_seedance_video NOT called (no re-encode)", ensure_calls == [])
check("edit+url: returns edited bytes", r == b"EDITED")

ensure_calls.clear()
real_clip = os.path.join(tmp, "gallery_clip.mp4"); open(real_clip, "wb").write(b"vid")
r = bm._seedance_edit(real_clip, "make it night", 5)
check("edit local: _ensure_seedance_video WAS called", len(ensure_calls) == 1)
check("edit local: movie passed is a local temp copy (not a url)",
      isinstance(gen_args.get("movie"), str) and not gen_args["movie"].startswith("http"))
check("edit local: returns edited bytes", r == b"EDITED")

# ============================ 6. network errors wrapped as _NetworkError =======
print("\n[6] _open/_request: connection error -> friendly _NetworkError; HTTP kept")
bm._request, bm._open = ORIG_REQUEST, ORIG_OPEN
bm._api_key = lambda: "test"
_saved_urlopen = _ur.urlopen
def _dns_fail(*a, **k):
    raise _ue.URLError(socket.gaierror(11001, "getaddrinfo failed"))
_ur.urlopen = _dns_fail
try:
    bm._request("GET", "https://ark.example/x")
    check("dns error -> raises", False)
except bm._NetworkError as e:
    check("dns error -> _NetworkError", True)
    check("dns error -> friendly message", "Check your internet" in str(e))
except Exception as e:
    check("dns error -> _NetworkError (got %s)" % type(e).__name__, False)

def _http_fail(*a, **k):
    raise _ue.HTTPError("https://ark.example/x", 400, "Bad Request", {},
                        io.BytesIO(b'{"error":"bad detail"}'))
_ur.urlopen = _http_fail
try:
    bm._request("POST", "https://ark.example/x", {"a": 1})
    check("http error -> raises", False)
except bm._NetworkError:
    check("http error must NOT be _NetworkError", False)
except RuntimeError as e:
    check("http error -> RuntimeError (not network)", True)
    check("http error -> server body preserved", "bad detail" in str(e))
_ur.urlopen = _saved_urlopen

# ======================= 7. polling rides out blips (same task, no re-submit) ==
print("\n[7] poll rides out network blips (same task, no re-submit)")
bm._seedance_generate = ORIG_GEN
bm._get_bytes = lambda u: b"FAKE"
bm._track = lambda *a, **k: None
bm._cancel_requested = lambda: False
bm.time.sleep = lambda *a, **k: None
calls = {"POST": 0, "GET": 0}
def req7(method, url, body=None):
    if method == "POST": calls["POST"] += 1; return {"id": "t7"}
    if method == "GET":
        calls["GET"] += 1
        if calls["GET"] <= 3:
            raise bm._NetworkError("Network error -- blip")
        return {"status": "succeeded", "content": {"video_url": "https://cdn/o.mp4"}}
    return {}
bm._request = req7
out = bm._seedance_generate("p", [], None, 5)
check("poll blips then ok -> returns bytes", out == b"FAKE")
check("poll blips -> POST called ONCE (no re-submit)", calls["POST"] == 1)
check("poll blips -> GET retried (3 blips + 1 ok = 4)", calls["GET"] == 4)

# ================================= 8. poll give-up -> no re-submit, clean error =
print("\n[8] poll give-up -> _NetworkError, NO re-submit (no double charge)")
saved_retries = bm._POLL_NET_RETRIES
bm._POLL_NET_RETRIES = 2
c2 = {"POST": 0, "GET": 0}
def req8(method, url, body=None):
    if method == "POST": c2["POST"] += 1; return {"id": "t8"}
    if method == "GET": c2["GET"] += 1; raise bm._NetworkError("Network error -- down")
    return {}
bm._request = req8
try:
    bm._seedance_generate("p", [], None, 5)
    check("give-up -> raises", False)
except bm._NetworkError:
    check("give-up -> raises _NetworkError", True)
except Exception as e:
    check("give-up -> _NetworkError (got %s)" % type(e).__name__, False)
check("give-up -> POST called ONCE (no double charge)", c2["POST"] == 1)
check("give-up -> GET tried retries+1 times (3)", c2["GET"] == 3)
bm._POLL_NET_RETRIES = saved_retries

# ===================================== 9. _get_bytes retries a download blip ===
print("\n[9] _get_bytes retries a transient download blip")
bm._get_bytes = ORIG_GET_BYTES
bm.time.sleep = lambda *a, **k: None
class FakeResp:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b"IMG"
st9 = {"n": 0}
def open9(u):
    st9["n"] += 1
    if st9["n"] <= 2: raise bm._NetworkError("blip")
    return FakeResp()
bm._open = open9
check("_get_bytes returns after retrying blips", bm._get_bytes("https://x") == b"IMG")
check("_get_bytes tried 3 times (2 blips + 1 ok)", st9["n"] == 3)

# ============================== 10. _error collapses a network traceback =======
print("\n[10] _error collapses a raw network traceback to the clean line")
captured = {}
bm._msgbox = lambda icon, title, text, *a, **k: captured.update(text=text)
fake_tb = ("Traceback (most recent call last):\n"
           "  File \"byteplus_maya.py\", line 4931, in _run\n"
           "    st = _request(\"GET\", url)\n"
           "byteplus_maya._NetworkError: Network error -- couldn't reach BytePlus "
           "([Errno 11001] getaddrinfo failed). Check your internet / VPN / DNS and "
           "try again.\n")
bm._error(fake_tb)
check("_error shows only the clean network line (no 'Traceback')",
      "Traceback" not in captured.get("text", "")
      and captured.get("text", "").startswith("Network error --"))
captured.clear()
bm._error("Some other failure:\n\ndetails here")
check("_error leaves non-network messages untouched",
      captured.get("text") == "Some other failure:\n\ndetails here")

# =========================== 11. _seedance_edit forwards ref_imgs ==============
print("\n[11] _seedance_edit forwards ref_imgs as reference_image")
rec = {}
def gen_rec(prompt, imgs, movie, duration, **kw):
    rec.clear(); rec.update(prompt=prompt, imgs=imgs, movie=movie, kw=kw)
    return b"OUT"
bm._seedance_generate = gen_rec
bm._mux_audio_from = lambda out, path: out
bm._seedance_edit("/clip.mp4", "make her match", 5,
                  ref_imgs=["asset://char1", "https://gal/fresh.png"],
                  source_url="https://trusted/clip.mp4")
check("edit refs (url branch): imgs are the refs",
      rec["imgs"] == ["asset://char1", "https://gal/fresh.png"])
check("edit refs (url branch): movie is the trusted clip url",
      rec["movie"] == "https://trusted/clip.mp4")
bm._ensure_seedance_video = lambda p: p
real2 = os.path.join(tmp, "c2.mp4"); open(real2, "wb").write(b"v")
bm._seedance_edit(real2, "x", 5, ref_imgs=["asset://c"])
check("edit refs (local branch): imgs forwarded", rec["imgs"] == ["asset://c"])
check("edit refs (local branch): movie is a local path (re-hosted)",
      isinstance(rec["movie"], str) and not rec["movie"].startswith("http"))

# ================================= 12. _seedance_edit_wrap(with_refs) ===========
print("\n[12] _seedance_edit_wrap(with_refs)")
w1 = bm._seedance_edit_wrap("add rain", with_refs=True)
w0 = bm._seedance_edit_wrap("add rain", with_refs=False)
check("with_refs locks identity to the reference IMAGE(S)",
      "reference IMAGE" in w1 and "add rain" in w1)
check("without refs keeps the video-lock wording",
      "reference video exactly" in w0 and "add rain" in w0)

# ================================= 13. _extend_multimodal (mode-3) =============
print("\n[13] _extend_multimodal assembly (mode-3 for Extend)")
imgs13, text13 = bm._extend_multimodal("https://last.png",
                                       ["asset://c1", "https://ref.png"], "she runs off")
check("extend mode-3: Image 1 is the trusted last frame", imgs13[0] == "https://last.png")
check("extend mode-3: refs follow as Image 2+",
      imgs13[1:] == ["asset://c1", "https://ref.png"])
check("extend mode-3: prompt describes Image 1 as the start + user text",
      text13.startswith("Continue seamlessly from Image 1") and "she runs off" in text13)

# ============ 14. mode-3 payload: reference_video + N reference_image ==========
print("\n[14] _seedance_generate mode-3 payload: reference_video + N reference_image")
bm._seedance_generate = ORIG_GEN
posted2 = {}
def req14(method, url, body=None):
    if method == "POST": posted2["body"] = body; return {"id": "t14"}
    if method == "GET":
        return {"status": "succeeded", "content": {"video_url": "https://cdn/o.mp4"}}
    return {}
bm._request = req14
bm._get_bytes = lambda u: b"FAKE"
bm._host_video = lambda p: ("https://r2/hosted.mp4", lambda: None)
bm._cancel_requested = lambda: False
bm._track = lambda *a, **k: None
bm.time.sleep = lambda *a, **k: None
bm._seedance_generate("edit", ["asset://c", "https://ref.png"], "/local/clip.mp4", 5,
                      require_motion_video=True)
content = posted2["body"]["content"]
roles = [it.get("role") for it in content if it.get("type") in ("image_url", "video_url")]
check("mode-3 payload: exactly 1 reference_video", roles.count("reference_video") == 1)
check("mode-3 payload: exactly 2 reference_image", roles.count("reference_image") == 2)
img_urls = [it["image_url"]["url"] for it in content if it.get("role") == "reference_image"]
check("mode-3 payload: trusted refs passed through untouched",
      img_urls == ["asset://c", "https://ref.png"])

# ================== 15. task journal: add / drop / survive a dead poll =========
print("\n[15] task journal (a billed job must never be lost)")
bm.CONFIG.TASKS_PATH = os.path.join(tmp, "tasks.json")
bm._tasks_save([])
bm._ACTIVE_MOV_DIR = os.path.join(tmp, "movies_projA")
bm._task_journal_add("t-1", "a prompt", "seedance", bm._ACTIVE_MOV_DIR)
j = bm._tasks_load()
check("journal: entry written with its mov_dir",
      len(j) == 1 and j[0]["task_id"] == "t-1" and j[0]["mov_dir"] == bm._ACTIVE_MOV_DIR)
bm._task_journal_add("t-1", "a prompt", "seedance", bm._ACTIVE_MOV_DIR)
check("journal: re-adding the same id does not duplicate", len(bm._tasks_load()) == 1)
bm._task_journal_drop("t-1")
check("journal: drop removes it", bm._tasks_load() == [])

def req_ok(method, url, body=None):
    if method == "POST": return {"id": "t-ok"}
    if method == "GET":
        return {"status": "succeeded", "content": {"video_url": "https://cdn/o.mp4"}}
    return {}
bm._request = req_ok
bm._seedance_generate("p", [], None, 5)
check("journal: cleared after a successful download", bm._tasks_load() == [])

def req_fail(method, url, body=None):
    if method == "POST": return {"id": "t-bad"}
    if method == "GET": return {"status": "failed"}
    return {}
bm._request = req_fail
try:
    bm._seedance_generate("p", [], None, 5)
except RuntimeError:
    pass
check("journal: cleared when the task itself failed", bm._tasks_load() == [])

saved_r = bm._POLL_NET_RETRIES; bm._POLL_NET_RETRIES = 1
def req_dead(method, url, body=None):
    if method == "POST": return {"id": "t-lost"}
    if method == "GET": raise bm._NetworkError("Network error -- pc slept")
    return {}
bm._request = req_dead
try:
    bm._seedance_generate("p", [], None, 5)
except bm._NetworkError:
    pass
bm._POLL_NET_RETRIES = saved_r
left = bm._tasks_load()
check("journal: SURVIVES a dead poll (billed clip stays recoverable)",
      len(left) == 1 and left[0]["task_id"] == "t-lost")

# ============================ 16. _recover_scan decision table =================
print("\n[16] _recover_scan: recover / keep / drop")
def scan_with(status_resp, ts=None, raise_exc=None):
    bm._tasks_save([{"task_id": "t-x", "ts": ts if ts is not None else int(time.time()),
                     "prompt": "p", "model": "m", "mov_dir": "/movies/A"}])
    def rq(method, url, body=None):
        if raise_exc: raise raise_exc
        return status_resp
    bm._request = rq
    bm._get_bytes = lambda u: b"VID"
    return bm._recover_scan()

out, drop = scan_with({"status": "succeeded",
                       "content": {"video_url": "https://cdn/r.mp4",
                                   "last_frame_url": "https://cdn/l.png"}})
check("scan: succeeded -> recovered payload + drop",
      len(out) == 1 and out[0]["bytes"] == b"VID" and drop == ["t-x"])
check("scan: recovered keeps its OWN mov_dir + trusted urls",
      out[0]["mov_dir"] == "/movies/A"
      and out[0]["video_url"] == "https://cdn/r.mp4"
      and out[0]["last_frame_url"] == "https://cdn/l.png")

out, drop = scan_with({"status": "running"})
check("scan: still running -> keep (no drop, no save)", out == [] and drop == [])

out, drop = scan_with({"status": "failed"})
check("scan: failed -> drop, nothing saved", out == [] and drop == ["t-x"])

out, drop = scan_with({"status": "succeeded"}, ts=0)
check("scan: >48h old -> drop without calling the API", out == [] and drop == ["t-x"])

out, drop = scan_with(None, raise_exc=bm._NetworkError("offline"))
check("scan: offline -> KEEP (retry next load)", out == [] and drop == [])

out, drop = scan_with(None, raise_exc=RuntimeError("HTTP 401 unauthorized"))
check("scan: auth error -> KEEP (never lose a paid clip)", out == [] and drop == [])

out, drop = scan_with(None, raise_exc=RuntimeError("HTTP 404 NotFound"))
check("scan: task really gone (404) -> drop", out == [] and drop == ["t-x"])

# ============================= 17. playblast cache (reuse last) ================
print("\n[17] playblast cache (don't re-capture an unchanged scene)")
check("_fmt_age seconds", bm._fmt_age(45) == "45s ago")
check("_fmt_age minutes", bm._fmt_age(600) == "10 min ago")
check("_fmt_age hours", bm._fmt_age(7200) == "2h ago")

pb = os.path.join(tmp, "pb.mp4"); open(pb, "wb").write(b"movie")
bm._playblast_key = lambda s, e: ("scene", int(s), int(e), "camA")
bm._anim_range = lambda: (1, 100)
bm._PB_CACHE.clear()
check("no cache -> _playblast_cached() is None", bm._playblast_cached() is None)

bm._PB_CACHE[("scene", 1, 100, "camA")] = {"path": pb, "ts": time.time() - 120}
hit = bm._playblast_cached()
check("cache hit -> (path, age)", bool(hit) and hit[0] == pb and 115 < hit[1] < 125)

captured = {"n": 0}
bm.cmds.playblast = lambda **k: captured.__setitem__("n", captured["n"] + 1)
got = bm._playblast_movie(1, 100, reuse=True)
check("reuse=True -> returns the cached mp4 and does NOT re-capture",
      got == pb and captured["n"] == 0)

os.remove(pb)
check("cache pointing at a deleted file -> None (re-captures)",
      bm._playblast_cached() is None)

# --- survives a reload: rebuild the cache from the .pbmeta.json on disk ---------
pbdir = os.path.join(tmp, "pbdir"); os.makedirs(pbdir, exist_ok=True)
bm._project_movies_dir = lambda: pbdir
bm._scene_tag = lambda: "scene"
bm._active_camera = lambda: "camA"
bm._playblast_key = lambda s, e: (bm._scene_tag(), int(s), int(e), bm._active_camera())

def _make_pb(name, scene, start, end, cam, age):
    p = os.path.join(pbdir, name); open(p, "wb").write(b"movie")
    json.dump({"scene": scene, "start": start, "end": end, "camera": cam,
               "ts": int(time.time() - age)}, open(p + ".pbmeta.json", "w"))
    return p

bm._PB_CACHE.clear()
_old = _make_pb("byteplus_playblast_1.mp4", "scene", 1, 100, "camA", 7200)
hit = bm._playblast_cached()
check("empty memory -> finds a stamped playblast on disk (survives hard_reload)",
      bool(hit) and hit[0] == _old)
check("disk hit reports its real age (~2h)", bool(hit) and 7100 < hit[1] < 7300)
check("old hit would be offered UNTICKED", hit[1] > bm._PB_AUTOTICK_SECS)

bm._PB_CACHE.clear()
_new = _make_pb("byteplus_playblast_2.mp4", "scene", 1, 100, "camA", 60)
hit = bm._playblast_cached()
check("newest matching playblast wins", bool(hit) and hit[0] == _new)
check("fresh hit would be offered TICKED", hit[1] <= bm._PB_AUTOTICK_SECS)

bm._PB_CACHE.clear()
_make_pb("byteplus_playblast_3.mp4", "OTHER_SCENE", 1, 100, "camA", 10)
hit = bm._playblast_cached()
check("a playblast from another scene is never offered", bool(hit) and hit[0] == _new)

bm._PB_CACHE.clear()
bm._anim_range = lambda: (1, 250)                # different range -> different key
check("a different frame range doesn't match", bm._playblast_cached() is None)
bm._anim_range = lambda: (1, 100)

bm._PB_CACHE.clear()
_unstamped = os.path.join(pbdir, "byteplus_playblast_old.mp4")
open(_unstamped, "wb").write(b"movie")           # pre-sidecar file, no .pbmeta.json
hit = bm._playblast_cached()
check("unstamped legacy playblast is skipped (we can't know what it is)",
      bool(hit) and hit[0] == _new)

# ======================================================================= summary
print("\n" + ("=" * 52))
print("RESULT:", "ALL PASS" if not FAILS else "FAILURES -> " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
