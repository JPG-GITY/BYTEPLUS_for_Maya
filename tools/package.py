"""Build the distributable zip from dist/ with the CURRENT plugin code, then verify it.

    python tools/build_guide.py     # regenerate the guide first (md -> docx/html + sync)
    python tools/package.py         # then build + verify the zip

The version comes from CONFIG.VERSION in byteplus_maya.py -- bump it there (and in
dist/BYTEPLUS.mod) and this script follows.
"""
import os, re, sys, shutil, zipfile, py_compile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
LIVE = os.path.join(ROOT, "byteplus_maya.py")
DIST_PLUGIN = os.path.join(DIST, "BYTEPLUS", "scripts", "byteplus_maya.py")

src_text = open(LIVE, encoding="utf-8").read()
m = re.search(r'^\s{4}VERSION\s*=\s*"([^"]+)"', src_text, re.M)
if not m:
    print("could not find CONFIG.VERSION in byteplus_maya.py"); sys.exit(1)
VER = m.group(1).split()[0]                       # "2.0" from '2.0' / '2.0 (Preview)'
ZIP = os.path.join(ROOT, "BYTEPLUS_for_Maya_%s.zip" % VER)
TOP = "BYTEPLUS_for_Maya_%s" % VER
print("packaging version:", VER)

py_compile.compile(LIVE, doraise=True)
shutil.copyfile(LIVE, DIST_PLUGIN)
print("synced live plugin -> dist (%d bytes)" % os.path.getsize(DIST_PLUGIN))

for base, dirs, files in os.walk(DIST):
    for d in list(dirs):
        if d == "__pycache__":
            shutil.rmtree(os.path.join(base, d), ignore_errors=True); dirs.remove(d)
    for f in files:
        if f.endswith(".pyc"):
            os.remove(os.path.join(base, f))

SHIP = ["install.py", "BYTEPLUS.mod", "README.txt",
        "USER_GUIDE.docx", "USER_GUIDE.html", "USER_GUIDE.md"]
missing = [f for f in SHIP if not os.path.exists(os.path.join(DIST, f))]
if missing:
    print("MISSING in dist:", missing); sys.exit(1)

if os.path.exists(ZIP):
    os.remove(ZIP)
n = 0
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
    for f in SHIP:
        z.write(os.path.join(DIST, f), "%s/%s" % (TOP, f)); n += 1
    for sub in ("images", "BYTEPLUS"):
        for base, dirs, files in os.walk(os.path.join(DIST, sub)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(base, f)
                rel = os.path.relpath(full, DIST).replace("\\", "/")
                z.write(full, "%s/%s" % (TOP, rel)); n += 1
print("wrote %s (%d files, %.1f MB)" % (ZIP, n, os.path.getsize(ZIP) / 1e6))

with zipfile.ZipFile(ZIP) as z:
    names = z.namelist()
    pyc = [x for x in names if x.endswith(".pyc") or "__pycache__" in x]
    imgs = sum(1 for x in names if "/images/" in x and not x.endswith("/"))
    src = z.read("%s/BYTEPLUS/scripts/byteplus_maya.py" % TOP).decode("utf-8", "replace")
    testok = z.testzip() is None
mod_line = open(os.path.join(DIST, "BYTEPLUS.mod")).read().splitlines()[0]
FEATURES = ("_seedance_edit", "_read_srcurl_sidecar", "_RefImagesWidget",
            "_extend_multimodal", "_NetworkError", "_task_journal_add",
            "_recover_scan", "_auto_register_asset", "open_seed_audio",
            "open_video_gen", "open_dialogue_scene")
missing_feats = [f for f in FEATURES if f not in src]

print("VERIFY:")
print("  entries       :", len(names))
print("  pyc/pycache   :", len(pyc), "(must be 0)")
print("  images        :", imgs)
print("  integrity     :", "OK" if testok else "BAD")
print("  VERSION in zip:", VER in src)
print("  mod           :", mod_line)
for f in FEATURES:
    print("  has %-22s: %s" % (f, f in src))
ok = (not pyc and testok and not missing_feats and VER in mod_line)
print("DONE" if ok else "FAIL -> missing: %s" % (missing_feats or "version/mod mismatch"))
sys.exit(0 if ok else 1)
