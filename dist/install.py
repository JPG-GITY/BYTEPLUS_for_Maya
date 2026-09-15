"""
BYTEPLUS for Maya - Installer
=============================
HOW TO INSTALL:  unzip this package, then DRAG THIS FILE (install.py) into the
Maya viewport. That's it.

This installer will:
  - copy the BYTEPLUS module into your Maya 'modules' folder,
  - enable the BYTEPLUS menu to auto-load on every Maya start,
  - disable Autodesk ADP (prevents a known Windows crash during generation),
  - load BYTEPLUS now so you can use it immediately.

Re-dragging the file upgrades an existing install in place.
Works on Maya 2025 or newer (Windows / macOS).  Uninstall steps are in README.txt.
"""

import os
import sys
import shutil


MARK_A = "# >>> BYTEPLUS for Maya (auto-load) >>>"

AUTOLOAD_BLOCK = r'''# >>> BYTEPLUS for Maya (auto-load) >>>
def _byteplus_install():
    try:
        import byteplus_maya
        byteplus_maya.install()
    except Exception:
        import sys, traceback
        sys.stderr.write("[BYTEPLUS] startup install failed:\n" + traceback.format_exc())
try:
    import maya.utils
    maya.utils.executeDeferred(_byteplus_install)
except Exception:
    pass
# <<< BYTEPLUS for Maya (auto-load) <<<
'''


def _this_dir():
    """Folder that contains this install.py (the unzipped package root)."""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        import inspect
        return os.path.dirname(os.path.abspath(inspect.getsourcefile(lambda: 0)))


def _maya_app_dir():
    d = os.environ.get("MAYA_APP_DIR")
    if not d:
        d = os.path.join(os.path.expanduser("~"), "Documents", "maya")
    return d


def _append_block(path, marker, block):
    """Idempotently append `block` to a text file (skip if `marker` present)."""
    cur = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            cur = f.read()
    if marker in cur:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        if cur and not cur.endswith("\n"):
            f.write("\n")
        f.write("\n" + block)
    return True


def _install():
    import maya.cmds as cmds

    src = _this_dir()
    src_folder = os.path.join(src, "BYTEPLUS")
    src_mod = os.path.join(src, "BYTEPLUS.mod")
    if not os.path.isdir(src_folder) or not os.path.isfile(src_mod):
        raise RuntimeError(
            "Could not find 'BYTEPLUS' and 'BYTEPLUS.mod' next to install.py.\n"
            "Please UNZIP the whole package first, then drag install.py from the "
            "unzipped folder.")

    app = _maya_app_dir()
    modules = os.path.join(app, "modules")
    os.makedirs(modules, exist_ok=True)

    dst_folder = os.path.join(modules, "BYTEPLUS")
    dst_mod = os.path.join(modules, "BYTEPLUS.mod")
    if os.path.isdir(dst_folder):
        shutil.rmtree(dst_folder)
    shutil.copytree(src_folder, dst_folder)
    shutil.copyfile(src_mod, dst_mod)

    # Make it importable in THIS running session (the .mod PYTHONPATH only takes
    # effect on the next launch).
    scripts = os.path.join(dst_folder, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)

    ver = cmds.about(version=True)              # e.g. "2027"
    enabled = _append_block(
        os.path.join(app, ver, "scripts", "userSetup.py"), MARK_A, AUTOLOAD_BLOCK)
    adp = _append_block(
        os.path.join(app, ver, "Maya.env"), "MAYA_DISABLE_ADP", "MAYA_DISABLE_ADP=1\n")

    # Load right now.
    sys.modules.pop("byteplus_maya", None)
    import byteplus_maya
    byteplus_maya.install()

    msg = ("BYTEPLUS is installed and loaded.\n\n"
           "* Find the BYTEPLUS menu in the main menu bar.\n"
           "* First time: open  BYTEPLUS > Settings  and paste your BytePlus "
           "API key.\n")
    if adp:
        msg += ("\nA crash-prevention setting (MAYA_DISABLE_ADP) was added - "
                "please RESTART Maya once to apply it.")
    cmds.confirmDialog(title="BYTEPLUS installed", message=msg, button=["Great"])
    sys.stderr.write("[BYTEPLUS] install OK -> {}\n".format(dst_folder))


def onMayaDroppedPythonFile(*args):
    """Entry point Maya calls when this file is dropped into the viewport."""
    try:
        _install()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            import maya.cmds as cmds
            cmds.confirmDialog(title="BYTEPLUS install failed", message=tb,
                               button=["OK"])
        except Exception:
            sys.stderr.write(tb)


# Allow running directly (exec) too, not only drag-and-drop.
if __name__ == "__main__":
    try:
        _install()
    except Exception:
        import traceback
        sys.stderr.write(traceback.format_exc())
