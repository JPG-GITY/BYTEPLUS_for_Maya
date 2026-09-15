#!/usr/bin/env python3
"""Build and verify the BYTEPLUS for Maya client zips (Windows + macOS).

    python3 tools/package.py --stage <dir>       # python3 >= 3.10 or mayapy; stdlib only

Inputs (read only -- this script never modifies dist/ or the plugin):
  byteplus_maya.py              repo root; CONFIG.VERSION "2.02 (Technology Preview)" -> 2.02
  dist/                         install.py, BYTEPLUS.mod, README.txt, NOTICE.md, WHATS_NEW.md,
                                USER_GUIDE.md/.html/.docx, images/, BYTEPLUS/scripts/byteplus_maya.py,
                                BYTEPLUS/lib/ (vendored TOS SDK), BYTEPLUS/bin/win/LICENSE*.txt
  <stage>/bin/win/ffmpeg.exe    untracked; sha256 pinned below
  (macOS ships no ffmpeg: the only static build was x86_64 and does not run on Apple
   Silicon without Rosetta; the plugin finds a Homebrew/MacPorts ffmpeg instead)
                                (--stage defaults to $BYTEPLUS_STAGE, else <repo>/build/stage)

Outputs (build/ is gitignored):
  build/BYTEPLUS_for_Maya_<v>_Windows.zip   plugin + docs + lib + bin/win only
  build/BYTEPLUS_for_Maya_<v>_macOS.zip     plugin + docs + lib (no bin/)
  build/SHA256SUMS.txt

Every gate runs before anything is written; any failure exits 1 and writes nothing.
Zips are deterministic for a given zlib: sorted entries, fixed timestamp and permissions,
deflate. Build on macOS or Linux (the macOS exec-bit gate needs POSIX permissions).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import shutil
import stat
import sys
import zipfile

ROOT_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WIN_FFMPEG_SHA256 = "6ef145b645c393dd1e4d0f987558d54699c6bc3fef788b1aa7bbe12e2c3ec112"
ZIP_DATE_TIME = (2026, 9, 15, 0, 0, 0)

TOP_FILES = ("install.py", "BYTEPLUS.mod", "README.txt", "NOTICE.md", "WHATS_NEW.md",
             "USER_GUIDE.md", "USER_GUIDE.html", "USER_GUIDE.docx")

# platform -> (bin sub-folder, ((file, source), ...)); source "stage" = <stage>/bin/<sub>,
# "dist" = dist/BYTEPLUS/bin/<sub>
BINS = {
    "Windows": ("win", (("ffmpeg.exe", "stage"),
                        ("LICENSE-ffmpeg.txt", "dist"),
                        ("LICENSE.txt", "dist"))),
    "macOS": ("mac", ()),                          # no bundled ffmpeg on macOS
}
EXECUTABLES = ("ffmpeg", "ffmpeg.exe")

JUNK_PATTERNS = ("__pycache__", "*.pyc", "*.pyo", ".DS_Store", "._*", "Thumbs.db",
                 "*.bak*", "*DAMAGED*", "*.orig", "*.so", "*.pyd", "*.dylib")

# CONFIG fields that must ship with an empty default ("" or None).
SECRET_FIELDS = ("API_KEY", "AUDIO_API_KEY", "TOS_AK", "TOS_SK", "TOS_SESSION_TOKEN",
                 "TOS_BUCKET", "R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET",
                 "ASSET_AK", "ASSET_SK", "ASSET_SESSION_TOKEN", "AUTO_TRUST_GROUP_ID",
                 "CALLBACK_URL", "INSTALL_ID", "TELEMETRY_BUCKET", "CUSTOMER_ID",
                 "USER_EMAIL", "USER_NAME")
KEY_LITERAL_RE = re.compile(r"AK(?:LT|TP)[A-Za-z0-9+/=_-]{16,}")   # BytePlus AK / STS AK
MACHO_MAGIC = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_nocr(path):
    with open(path, "rb") as f:
        return f.read().replace(b"\r", b"")


def is_junk(name):
    return any(fnmatch.fnmatchcase(name, p) for p in JUNK_PATTERNS)


def find_junk(top):
    bad = []
    if os.path.isdir(top):
        for base, dirs, files in os.walk(top):
            bad += [os.path.join(base, n) for n in dirs + files if is_junk(n)]
    return bad


def walk_files(top, arc_prefix):
    out = []
    for base, dirs, files in os.walk(top):
        dirs.sort()
        for f in sorted(files):
            full = os.path.join(base, f)
            out.append((arc_prefix + os.path.relpath(full, top).replace(os.sep, "/"), full))
    return out


def config_body(src):
    """Body of `class CONFIG:` -- up to the next top-level (column 0, non-comment) line."""
    m = re.search(r"^class CONFIG\b[^\n]*:\n(.*?)(?=^[^\s#])", src, re.M | re.S)
    return m.group(1) if m else None


def image_refs(md_text):
    refs = re.findall(r"!\[[^\]]*\]\(\s*<?([^)>\s]+)", md_text)
    refs += re.findall(r"<img\b[^>]*\bsrc=[\"']([^\"']+)", md_text)
    return sorted(set(refs))


class Gates:
    def __init__(self):
        self.failed = []

    def __call__(self, ok, label, detail=""):
        print("  [%s] %s%s" % ("ok" if ok else "FAIL", label,
                               "" if ok or not detail else "\n         " + detail))
        if not ok:
            self.failed.append(label)
        return ok


def write_zip(path, entries):
    """entries: sorted [(arcname, source_path)]. Deterministic ZipInfo for every file."""
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for arc, src in entries:
            zi = zipfile.ZipInfo(arc, date_time=ZIP_DATE_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 3                              # unix: permissions are honoured
            mode = 0o755 if os.path.basename(arc) in EXECUTABLES else 0o644
            zi.external_attr = (stat.S_IFREG | mode) << 16
            zi.file_size = os.path.getsize(src)
            with open(src, "rb") as fi, z.open(zi, "w") as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
    os.replace(tmp, path)


def verify_zip(path, entries, top, sub, plugin_nocr, gate):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        gate(z.testzip() is None, "%s: zip integrity (testzip)" % os.path.basename(path))
        gate(names == [a for a, _ in entries], "%s: entries match the planned list" % sub)
        junk = [n for n in names if any(is_junk(part) for part in n.split("/"))]
        gate(not junk, "%s: no junk entries" % sub, ", ".join(junk[:10]))
        wrong = [n for n in names if "/BYTEPLUS/bin/" in n
                 and not n.startswith("%s/BYTEPLUS/bin/%s/" % (top, sub))]
        gate(not wrong, "%s: only bin/%s is present" % (sub, sub), ", ".join(wrong))
        bad_modes = []
        for i in infos:
            want = 0o755 if os.path.basename(i.filename) in EXECUTABLES else 0o644
            if (i.external_attr >> 16) & 0o777 != want or i.date_time != ZIP_DATE_TIME:
                bad_modes.append(i.filename)
        gate(not bad_modes, "%s: fixed permissions + timestamp" % sub, ", ".join(bad_modes[:10]))
        shipped = z.read("%s/BYTEPLUS/scripts/byteplus_maya.py" % top).replace(b"\r", b"")
        gate(shipped == plugin_nocr, "%s: shipped plugin == repo-root byteplus_maya.py" % sub)
        return len(names)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build + verify the BYTEPLUS for Maya zips.")
    ap.add_argument("--stage", default=os.environ.get("BYTEPLUS_STAGE"),
                    help="folder with bin/win/ffmpeg.exe and bin/mac/* "
                         "(default: $BYTEPLUS_STAGE, else <root>/build/stage)")
    ap.add_argument("--root", default=ROOT_DEFAULT,
                    help="repo root (default: the repo this script lives in)")
    ap.add_argument("--out", default=None, help="output folder (default: <root>/build)")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    dist = os.path.join(root, "dist")
    out_dir = os.path.abspath(args.out or os.path.join(root, "build"))
    stage = os.path.abspath(args.stage or os.path.join(root, "build", "stage"))
    live = os.path.join(root, "byteplus_maya.py")
    dist_plugin = os.path.join(dist, "BYTEPLUS", "scripts", "byteplus_maya.py")
    gate = Gates()

    print("BYTEPLUS for Maya packager  (python %s)" % sys.version.split()[0])
    print("  root : %s\n  stage: %s\n  out  : %s" % (root, stage, out_dir))
    if sys.version_info < (3, 10):
        print("needs Python 3.10+"); return 1
    if not os.path.isfile(live):
        print("missing %s" % live); return 1

    # ---- version --------------------------------------------------------------
    plugin_nocr = read_nocr(live)
    src = plugin_nocr.decode("utf-8")
    body = config_body(src)
    vm = body and re.search(r"^    VERSION\s*=\s*([\"'])(.+?)\1", body, re.M)
    if not vm:
        print("  [FAIL] could not find CONFIG.VERSION in byteplus_maya.py"); return 1
    ver = vm.group(2).split()[0]
    top = "BYTEPLUS_for_Maya_%s" % ver
    print("version: %s   (CONFIG.VERSION = %r)" % (ver, vm.group(2)))
    print("GATES")
    gate(bool(re.fullmatch(r"\d+\.\d+", ver)), "version looks like X.YY", ver)

    # ---- plugin ---------------------------------------------------------------
    try:
        compile(src, live, "exec")
        gate(True, "plugin compiles")
    except SyntaxError as e:
        gate(False, "plugin compiles", str(e))
    gate(os.path.isfile(dist_plugin) and read_nocr(dist_plugin) == plugin_nocr,
         "dist/BYTEPLUS/scripts/byteplus_maya.py == byteplus_maya.py (ignoring CR)",
         "copy the root plugin into dist/BYTEPLUS/scripts/ (keep its line endings)")

    # ---- module file ----------------------------------------------------------
    mod_path = os.path.join(dist, "BYTEPLUS.mod")
    mod_tokens = []
    if os.path.isfile(mod_path):
        lines = read_nocr(mod_path).decode("utf-8").splitlines()
        mod_tokens = lines[0].split() if lines else []
    gate(len(mod_tokens) >= 3 and mod_tokens[:2] == ["+", "BYTEPLUS"] and mod_tokens[2] == ver,
         "BYTEPLUS.mod declares version %s" % ver, "first line: %r" % " ".join(mod_tokens))

    # ---- required files ---------------------------------------------------------
    missing = [f for f in TOP_FILES if not os.path.isfile(os.path.join(dist, f))]
    gate(not missing, "dist/ has %s" % ", ".join(TOP_FILES), "missing: " + ", ".join(missing))
    gate(os.path.isfile(os.path.join(dist, "BYTEPLUS", "lib", "tos", "__init__.py")),
         "dist/BYTEPLUS/lib has the vendored tos SDK")
    gate(os.path.isdir(os.path.join(dist, "images")), "dist/images exists")

    # ---- guide images -----------------------------------------------------------
    guide = os.path.join(dist, "USER_GUIDE.md")
    if os.path.isfile(guide):
        guide_text = open(guide, encoding="utf-8").read()
        images_dir = os.path.join(dist, "images") + os.sep
        bad = []
        for ref in image_refs(guide_text):
            p = os.path.normpath(os.path.join(dist, ref.replace("%20", " ")))
            if not (p.startswith(images_dir) and os.path.isfile(p)):
                bad.append(ref)
        gate(not bad, "every image referenced by dist/USER_GUIDE.md is in dist/images",
             "missing: " + ", ".join(bad))
        tp = set(re.findall(r"Technology Preview v?(\d+\.\d+)", guide_text))
        if tp - {ver}:
            print("  [warn] USER_GUIDE.md mentions Technology Preview %s (building %s)"
                  % (", ".join(sorted(tp)), ver))

    # ---- junk -------------------------------------------------------------------
    junk = find_junk(dist)
    for sub in ("win", "mac"):
        junk += find_junk(os.path.join(stage, "bin", sub))
    gate(not junk, "no __pycache__/.pyc/.DS_Store/._*/Thumbs.db/*.bak*/*DAMAGED*/*.orig/"
                   "*.so/*.pyd/*.dylib in dist/ or the stage",
         "\n         ".join(os.path.relpath(j, root) for j in junk[:20]))

    # ---- secrets ------------------------------------------------------------------
    non_empty = []
    for name in SECRET_FIELDS:
        for rhs in re.findall(r"^    %s\s*(?::[^=\n]*)?=\s*(.*)$" % name, body or "", re.M):
            if not re.fullmatch(r"(?:\"\"|''|None)\s*(?:#.*)?", rhs.strip()):
                non_empty.append("CONFIG." + name)
    assigned = sorted(set(re.findall(r"\bCONFIG\.(%s)\s*=\s*[rRuU]?([\"'])(?!\2)"
                                     % "|".join(SECRET_FIELDS), src)))
    non_empty += ["CONFIG.%s = <literal>" % a for a, _ in assigned]
    gate(not non_empty, "credential/identity CONFIG defaults are empty",
         "non-empty: " + ", ".join(non_empty))   # names only; never print the values
    key_hits = ["byteplus_maya.py:%d" % (src.count("\n", 0, m.start()) + 1)
                for m in KEY_LITERAL_RE.finditer(src)]
    for f in ("install.py", "README.txt", "NOTICE.md", "WHATS_NEW.md", "USER_GUIDE.md"):
        p = os.path.join(dist, f)
        if os.path.isfile(p):
            t = read_nocr(p).decode("utf-8", "replace")
            key_hits += ["%s:%d" % (f, t.count("\n", 0, m.start()) + 1)
                         for m in KEY_LITERAL_RE.finditer(t)]
    gate(not key_hits, "no AKLT/AKTP access-key literals", "at: " + ", ".join(key_hits))

    # ---- binaries -----------------------------------------------------------------
    sources = {}
    for plat, (sub, files) in BINS.items():
        sources.setdefault(plat, [])
        for fname, origin in files:
            base = os.path.join(stage, "bin", sub) if origin == "stage" \
                else os.path.join(dist, "BYTEPLUS", "bin", sub)
            p = os.path.join(base, fname)
            if gate(os.path.isfile(p), "%s: %s present" % (plat, os.path.relpath(p, root)
                                                          if p.startswith(root) else p)):
                sources.setdefault(plat, []).append(
                    ("%s/BYTEPLUS/bin/%s/%s" % (top, sub, fname), p))
    win_exe = os.path.join(stage, "bin", "win", "ffmpeg.exe")
    if os.path.isfile(win_exe):
        digest = sha256_file(win_exe)
        gate(digest == WIN_FFMPEG_SHA256, "Windows: ffmpeg.exe sha256 is the pinned LGPL build",
             "got %s" % digest)

    if gate.failed:
        print("\nBUILD FAILED (%d gate%s) -- nothing written:" %
              (len(gate.failed), "" if len(gate.failed) == 1 else "s"))
        for f in gate.failed:
            print("  - " + f)
        return 1

    # ---- entries ------------------------------------------------------------------
    common = [("%s/%s" % (top, f), os.path.join(dist, f)) for f in TOP_FILES]
    common += walk_files(os.path.join(dist, "images"), "%s/images/" % top)
    common.append(("%s/BYTEPLUS/scripts/byteplus_maya.py" % top, dist_plugin))
    common += walk_files(os.path.join(dist, "BYTEPLUS", "lib"), "%s/BYTEPLUS/lib/" % top)
    extra = sorted(set(os.listdir(os.path.join(dist, "BYTEPLUS", "scripts"))) - {"byteplus_maya.py"})
    if extra:
        print("  [warn] not shipped (unexpected in dist/BYTEPLUS/scripts): " + ", ".join(extra))

    os.makedirs(out_dir, exist_ok=True)
    sums = []
    print("BUILD")
    for plat, (sub, _files) in BINS.items():
        entries = sorted(common + sources[plat])
        name = "BYTEPLUS_for_Maya_%s_%s.zip" % (ver, plat)
        path = os.path.join(out_dir, name)
        write_zip(path, entries)
        n = verify_zip(path, entries, top, sub, plugin_nocr, gate)
        digest = sha256_file(path)
        sums.append("%s  %s\n" % (digest, name))
        print("  %s: %d entries, %.1f MB (%d bytes)\n    sha256 %s"
              % (name, n, os.path.getsize(path) / 1e6, os.path.getsize(path), digest))
    if gate.failed:
        print("\nVERIFY FAILED: " + ", ".join(gate.failed))
        return 1
    with open(os.path.join(out_dir, "SHA256SUMS.txt"), "w", newline="\n") as f:
        f.writelines(sums)
    print("wrote %s\nDONE" % os.path.join(out_dir, "SHA256SUMS.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
