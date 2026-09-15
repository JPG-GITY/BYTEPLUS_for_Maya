"""Install-layout smoke test for a BUILT client zip. Run it with mayapy, not plain python.

    <mayapy> -s -B tests/test_install_layout.py build/BYTEPLUS_for_Maya_2.02_macOS.zip
    <mayapy> -s -B tests/test_install_layout.py build/BYTEPLUS_for_Maya_2.02_Windows.zip

    macOS mayapy  : /Applications/Autodesk/maya2027/Maya.app/Contents/bin/mayapy
    Windows mayapy: "C:\\Program Files\\Autodesk\\Maya2027\\bin\\mayapy.exe"

1. Extracts the zip into a temp dir, restoring the zip's unix permissions the way unzip/Finder do.
2. Points MAYA_APP_DIR at a second temp dir, starts maya.standalone, and runs the zip's own
   install.py `_install()`, so the real copy / userSetup.py / Maya.env logic runs. Only the two
   UI steps are stubbed: cmds.confirmDialog, and byteplus_maya.install(). Building the menu
   needs Maya's main window and schedules first-run network calls.
3. Asserts that <MAYA_APP_DIR>/modules/BYTEPLUS.mod and BYTEPLUS/{scripts,lib,bin} landed.
4. Points HOME at a temp dir and removes the user site-packages from sys.path, then imports the
   INSTALLED byteplus_maya and checks CONFIG.VERSION, _import_tos() (skipped if the helper is
   absent) and _ffmpeg_exe() (the bundled binary, when the zip matches the host platform).

No BytePlus or other network calls. Your real prefs (~/.byteplus_maya*.json) are never read.
Exit code: 0 = no FAIL (SKIPs allowed), 1 = at least one FAIL, 2 = usage/setup error.

  --no-standalone  use MagicMock stand-ins for maya.* instead of maya.standalone (no licence)
  --keep           keep the temp dirs and print where they are
"""
import argparse
import importlib.abc
import importlib.util
import os
import shutil
import site
import stat
import sys
import tempfile
import warnings
import zipfile

COUNTS = {"PASS": 0, "FAIL": 0, "SKIP": 0}
JUNK = ("__pycache__", ".DS_Store", "Thumbs.db")
JUNK_SUFFIX = (".pyc", ".pyo", ".so", ".pyd", ".dylib", ".orig")


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    COUNTS[tag] += 1
    print("  %s %s%s" % (tag, name, "" if cond or detail == "" else "  -- %s" % (detail,)))
    return bool(cond)


def skip(name, why):
    COUNTS["SKIP"] += 1
    print("  SKIP %s  -- %s" % (name, why))


def same_path(a, b):
    return bool(a and b) and (os.path.normcase(os.path.realpath(a))
                              == os.path.normcase(os.path.realpath(b)))


def under(path, folder):
    p = os.path.normcase(os.path.realpath(path))
    f = os.path.normcase(os.path.realpath(folder))
    return p == f or p.startswith(f + os.sep)


def extract(zip_path, dest):
    with zipfile.ZipFile(zip_path) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit("corrupt zip entry: %s" % bad)
        z.extractall(dest)
        if os.name != "nt":
            for zi in z.infolist():
                mode = (zi.external_attr >> 16) & 0o777
                p = os.path.join(dest, *zi.filename.split("/"))
                if mode and os.path.isfile(p):
                    os.chmod(p, mode)
        return sorted({n.split("/", 1)[0] for n in z.namelist()}), z.namelist()


def start_maya(use_standalone):
    if use_standalone:
        import maya.standalone
        maya.standalone.initialize(name="python")
        import maya.cmds as cmds
        return cmds, maya.standalone
    import types
    from unittest.mock import MagicMock
    maya = types.ModuleType("maya")
    sys.modules["maya"] = maya
    for sub in ("cmds", "mel", "utils", "OpenMaya", "OpenMayaUI"):
        mm = MagicMock()
        sys.modules["maya." + sub] = mm
        setattr(maya, sub, mm)
    maya.cmds.about.side_effect = lambda **k: "2027" if k.get("version") else ""
    return maya.cmds, None


class StubPluginFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves a stand-in `byteplus_maya` while install.py runs, so its final
    `byteplus_maya.install()` (menu building) is recorded instead of executed."""

    def __init__(self):
        self.calls = 0

    def find_spec(self, fullname, path, target=None):
        if fullname == "byteplus_maya":
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        def install():
            self.calls += 1
            return "BYTEPLUS_MENU"
        module.install = install


def strip_user_site():
    """Drop per-user site-packages (pip --user installs) from sys.path. Call before
    changing HOME, because site.getusersitepackages() is derived from it."""
    user = set()
    try:
        user.add(os.path.normcase(os.path.realpath(site.getusersitepackages())))
    except Exception:
        pass
    markers = (os.sep + os.path.join("Library", "Python") + os.sep,
               os.sep + os.path.join(".local", "lib") + os.sep,
               os.path.join("AppData", "Roaming", "Python"))
    keep, removed = [], []
    for p in sys.path:
        rp = os.path.normcase(os.path.realpath(p)) if p else ""
        if p and (rp in user or any(os.path.normcase(m) in rp for m in markers)):
            removed.append(p)
        else:
            keep.append(p)
    sys.path[:] = keep
    return removed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install a built BYTEPLUS zip into a temp "
                                             "MAYA_APP_DIR and check the result.")
    ap.add_argument("zip")
    ap.add_argument("--no-standalone", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    if not os.path.isfile(args.zip):
        print("no such zip: %s" % args.zip)
        return 2

    tmp = tempfile.mkdtemp(prefix="byteplus_layout_")
    unzipped, app, home = (os.path.join(tmp, d) for d in ("unzipped", "maya_app", "home"))
    for d in (unzipped, app, home):
        os.makedirs(d)
    os.environ["MAYA_APP_DIR"] = app
    os.environ.pop("BYTEPLUS_FFMPEG", None)
    host = "win" if os.name == "nt" else "mac" if sys.platform == "darwin" else "linux"
    standalone = None
    try:
        print("zip : %s\ntemp: %s\nhost: %s, python %s"
              % (os.path.abspath(args.zip), tmp, host, sys.version.split()[0]))

        # ------------------------------------------------------------ 1. the zip --
        print("\n[1] zip layout")
        tops, names = extract(args.zip, unzipped)
        if not check("single top folder BYTEPLUS_for_Maya_<v>", len(tops) == 1
                     and tops[0].startswith("BYTEPLUS_for_Maya_"), tops):
            return 1
        pkg = os.path.join(unzipped, tops[0])
        ver = tops[0][len("BYTEPLUS_for_Maya_"):]
        base = os.path.basename(args.zip)
        plat = ("win" if "_Windows" in base else "mac" if "_macOS" in base
                else "win" if os.path.isdir(os.path.join(pkg, "BYTEPLUS", "bin", "win")) else "mac")
        other = "mac" if plat == "win" else "win"
        exe = "ffmpeg.exe" if plat == "win" else "ffmpeg"
        print("  version %s, platform zip: %s" % (ver, plat))
        for rel in ("install.py", "BYTEPLUS.mod", "README.txt", "NOTICE.md", "WHATS_NEW.md",
                    "USER_GUIDE.md", "USER_GUIDE.html", "USER_GUIDE.docx",
                    "BYTEPLUS/scripts/byteplus_maya.py", "BYTEPLUS/lib/tos/__init__.py",
                    "BYTEPLUS/bin/%s/%s" % (plat, exe)):
            if rel.startswith("BYTEPLUS/bin/") and plat == "mac":   # 2.02+: no ffmpeg on macOS
                check("macOS zip ships no BYTEPLUS/bin/ (ffmpeg comes from the user)",
                      not any("/BYTEPLUS/bin/" in n for n in names))
                continue
            check("zip has %s" % rel, os.path.isfile(os.path.join(pkg, *rel.split("/"))))
        check("zip has no bin/%s" % other,
              not any("/BYTEPLUS/bin/%s/" % other in n for n in names))
        junk = [n for n in names if any(part in JUNK or part.startswith("._")
                                        or part.endswith(JUNK_SUFFIX) for part in n.split("/"))]
        check("zip has no bytecode / compiled / OS junk", not junk, junk[:5])

        # ------------------------------------------------------- 2. install.py --
        print("\n[2] install.py into MAYA_APP_DIR=%s" % app)
        cmds, standalone = start_maya(not args.no_standalone)
        inst_path = os.path.join(pkg, "install.py")
        spec = importlib.util.spec_from_file_location("byteplus_zip_installer", inst_path)
        inst = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(inst)            # __name__ != "__main__": nothing runs yet
        if not check("install.py defines _install()", callable(getattr(inst, "_install", None))):
            return 1
        orig_dialog = getattr(cmds, "confirmDialog", None)
        cmds.confirmDialog = lambda *a, **k: "Great"
        finder = StubPluginFinder()
        sys.meta_path.insert(0, finder)
        try:
            inst._install()
            check("_install() completed", True)
        except Exception as e:
            check("_install() completed", False, repr(e))
            return 1
        finally:
            sys.meta_path.remove(finder)
            sys.modules.pop("byteplus_maya", None)
            if orig_dialog is not None:
                cmds.confirmDialog = orig_dialog

        modules = os.path.join(app, "modules")
        mdir = os.path.join(modules, "BYTEPLUS")
        mod = os.path.join(modules, "BYTEPLUS.mod")
        scripts, lib = os.path.join(mdir, "scripts"), os.path.join(mdir, "lib")
        check("modules/BYTEPLUS.mod installed", os.path.isfile(mod))
        first = open(mod, encoding="utf-8").read().splitlines()[0].split() if os.path.isfile(mod) else []
        check("BYTEPLUS.mod declares %s" % ver, first[:3] == ["+", "BYTEPLUS", ver], first)
        for sub in ("scripts", "lib") + (("bin",) if plat == "win" else ()):
            check("modules/BYTEPLUS/%s/ installed" % sub, os.path.isdir(os.path.join(mdir, sub)))
        check("scripts/byteplus_maya.py installed", os.path.isfile(os.path.join(scripts, "byteplus_maya.py")))
        check("lib/tos/__init__.py installed", os.path.isfile(os.path.join(lib, "tos", "__init__.py")))
        bundled = os.path.join(mdir, "bin", plat, exe)
        if plat == "win":
            check("bin/%s/%s installed" % (plat, exe), os.path.isfile(bundled))
        else:                                         # macOS 2.02+: ffmpeg comes from the user
            check("macOS package ships no bundled ffmpeg", not os.path.exists(bundled))
        if plat == "mac" and os.name != "nt" and os.path.isfile(bundled):
            check("bin/mac/ffmpeg keeps its exec bit", os.stat(bundled).st_mode & stat.S_IXUSR)
        maya_ver = str(cmds.about(version=True))
        us = os.path.join(app, maya_ver, "scripts", "userSetup.py")
        env = os.path.join(app, maya_ver, "Maya.env")
        check("userSetup.py has the auto-load block",
              os.path.isfile(us) and getattr(inst, "MARK_A", "#") in open(us, encoding="utf-8").read())
        check("Maya.env sets MAYA_DISABLE_ADP",
              os.path.isfile(env) and "MAYA_DISABLE_ADP" in open(env, encoding="utf-8").read())
        check("installer called byteplus_maya.install() once", finder.calls == 1, finder.calls)
        check("installed scripts dir is on sys.path", any(same_path(p, scripts) for p in sys.path))
        pre_junk = [os.path.join(b, n) for b, ds, fs in os.walk(mdir) for n in ds + fs
                    if n in JUNK or n.endswith(JUNK_SUFFIX)]
        check("installed module has no bytecode / compiled files (before import)", not pre_junk,
              pre_junk[:5])

        # ------------------------------------------------ 3. the installed plugin --
        print("\n[3] import the installed plugin (HOME=%s, no user site)" % home)
        removed = strip_user_site()
        if removed:
            print("  (removed from sys.path: %s)" % ", ".join(removed))
        os.environ["HOME"] = home
        os.environ["USERPROFILE"] = home
        sys.path[:] = [p for p in sys.path if same_path(p, scripts) or not
                       os.path.normcase(os.path.normpath(p or ".")).endswith(
                           os.path.normcase(os.path.join("BYTEPLUS", "scripts")))]
        if not any(same_path(p, scripts) for p in sys.path):
            sys.path.insert(0, scripts)
        sys.modules.pop("byteplus_maya", None)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import byteplus_maya as bm
        check("byteplus_maya imported from the installed scripts dir",
              same_path(bm.__file__, os.path.join(scripts, "byteplus_maya.py")), bm.__file__)
        version = getattr(getattr(bm, "CONFIG", None), "VERSION", "")
        check("CONFIG.VERSION starts with %s" % ver, version.split()[:1] == [ver], version)
        prefs = getattr(bm.CONFIG, "PREFS_PATH", None)
        if prefs:
            check("CONFIG.PREFS_PATH is under the temp HOME", under(prefs, home), prefs)

        if not callable(getattr(bm, "_import_tos", None)):
            skip("_import_tos() returns tos from the installed lib",
                 "byteplus_maya has no _import_tos() yet (the lead is adding it)")
        else:
            outside = importlib.util.find_spec("tos") if "tos" not in sys.modules else None
            if outside is not None and not under(outside.origin, lib):
                check("no tos importable outside the bundle", False,
                      "%s (run mayapy with -s / without a pip-installed tos)" % outside.origin)
            else:
                t = bm._import_tos()
                check("_import_tos() returns tos from the installed lib",
                      under(t.__file__, lib), t.__file__)
                idx = [k for k, p in enumerate(sys.path) if same_path(p, lib)]
                std = [k for k, p in enumerate(sys.path) if same_path(p, os.path.dirname(os.__file__))]
                check("lib is appended after the standard library, not prepended",
                      idx and std and idx[0] > std[0], (idx, std))
                try:
                    c = t.TosClientV2("AKTPexample", "example-secret",
                                      "tos-ap-southeast-1.bytepluses.com", "ap-southeast-1",
                                      security_token="example-token")
                    url = c.pre_signed_url(t.HttpMethodType.Http_Method_Get, "example-bucket",
                                           "maya/layout-test.txt", expires=60).signed_url
                    check("bundled tos signs a pre-signed URL offline (dummy creds + token)",
                          "X-Tos-Signature=" in url and "X-Tos-Security-Token=example-token" in url)
                except Exception as e:
                    check("bundled tos signs a pre-signed URL offline (dummy creds + token)", False, repr(e))

        if not callable(getattr(bm, "_ffmpeg_exe", None)):
            check("byteplus_maya has _ffmpeg_exe()", False)
        elif host != plat:
            skip("_ffmpeg_exe() on the %s package" % plat,
                 "zip is for %s, this host is %s" % (plat, host))
        else:
            got = bm._ffmpeg_exe()
            if plat == "win":
                check("_ffmpeg_exe() resolves to the bundled bin/%s/%s" % (plat, exe),
                      same_path(got, bundled), got)
            else:
                check("_ffmpeg_exe() on macOS uses a user-installed ffmpeg (or None), never the module",
                      got is None or not os.path.abspath(str(got)).startswith(os.path.abspath(mdir)), got)
                if got:
                    check("resolved ffmpeg is executable", os.access(got, os.X_OK), got)
        return 0 if COUNTS["FAIL"] == 0 else 1
    finally:
        print("\nRESULT: %(PASS)d PASS, %(FAIL)d FAIL, %(SKIP)d SKIP" % COUNTS)
        print("RESULT: ALL PASS" if COUNTS["FAIL"] == 0 else "RESULT: FAILURES")
        if standalone is not None:
            try:
                standalone.uninitialize()
            except Exception:
                pass
        if args.keep:
            print("kept: %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.exit(code)
