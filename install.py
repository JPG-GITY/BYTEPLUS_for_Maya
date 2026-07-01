"""BYTEPLUS for Maya -- drag-and-drop installer.

HOW TO INSTALL (any OS -- Windows, macOS, Linux):
    1. Unzip this folder somewhere.
    2. Open Maya.
    3. Drag THIS file (install.py) from your file browser into the Maya
       viewport (the 3D area).
    4. Done -- the BYTEPLUS menu appears and will load automatically every time
       you start Maya.

What it does: copies `byteplus_maya.py` into Maya's user scripts folder, sets it
to auto-load on startup (userSetup.py), and builds the menu immediately. No admin
rights, no environment variables, nothing to configure by hand.
"""

import os
import shutil
import sys

import maya.cmds as cmds
import maya.utils


# The block we write into userSetup.py so the menu loads on every Maya start.
_AUTOLOAD = """
# >>> BYTEPLUS for Maya (auto-load) >>>
def _byteplus_install():
    try:
        import byteplus_maya
        byteplus_maya.install()
    except Exception:
        import sys, traceback
        sys.stderr.write("[BYTEPLUS] startup install failed:\\n"
                         + traceback.format_exc())

try:
    import maya.utils
    maya.utils.executeDeferred(_byteplus_install)
except Exception:
    pass
# <<< BYTEPLUS for Maya (auto-load) <<<
"""

_MARKER = "BYTEPLUS for Maya (auto-load)"


def _source_dir():
    """Folder this installer is sitting in (where byteplus_maya.py lives)."""
    try:
        return os.path.dirname(os.path.realpath(__file__))
    except NameError:                                    # __file__ not set
        return os.getcwd()


def _install():
    src_dir = _source_dir()
    plugin_src = os.path.join(src_dir, "byteplus_maya.py")
    if not os.path.exists(plugin_src):
        cmds.confirmDialog(
            title="BYTEPLUS -- install failed",
            message="Could not find 'byteplus_maya.py' next to install.py.\n\n"
                    "Keep both files together in the unzipped folder and drag "
                    "install.py into Maya again.",
            button=["OK"])
        return

    # Maya's per-version user scripts dir -- already on Maya's Python path, so
    # `import byteplus_maya` works with no sys.path edits. Cross-platform.
    scripts_dir = cmds.internalVar(userScriptDir=True)
    if not os.path.isdir(scripts_dir):
        os.makedirs(scripts_dir)

    # 1. Copy the plugin in.
    plugin_dst = os.path.join(scripts_dir, "byteplus_maya.py")
    shutil.copyfile(plugin_src, plugin_dst)

    # 2. Add the auto-load block to userSetup.py (create or append; idempotent).
    usersetup = os.path.join(scripts_dir, "userSetup.py")
    existing = ""
    if os.path.exists(usersetup):
        with open(usersetup, "r") as f:
            existing = f.read()
    if _MARKER not in existing:
        with open(usersetup, "a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(_AUTOLOAD)

    # 3. Build the menu now so the user sees it without restarting.
    if scripts_dir not in sys.path:
        sys.path.append(scripts_dir)
    for mod in ("byteplus_maya",):
        if mod in sys.modules:
            del sys.modules[mod]                         # pick up the fresh copy
    import byteplus_maya
    byteplus_maya.install()

    cmds.confirmDialog(
        title="BYTEPLUS -- installed",
        message="BYTEPLUS for Maya is installed.\n\n"
                "  - The BYTEPLUS menu is in the main menu bar now.\n"
                "  - It will load automatically every time you start Maya.\n\n"
                "Next: open BYTEPLUS > Settings... and paste your API key.",
        button=["Great"])


def onMayaDroppedPythonFile(*args):
    """Maya calls this when the file is dragged into the viewport."""
    try:
        _install()
    except Exception:
        import traceback
        cmds.confirmDialog(
            title="BYTEPLUS -- install error",
            message="Install failed:\n\n" + traceback.format_exc(),
            button=["OK"])


# If someone runs it from the Script Editor instead of dragging, install too.
if __name__ == "__main__":
    _install()
