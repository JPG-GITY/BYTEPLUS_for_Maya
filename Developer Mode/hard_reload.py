# ============================================================================
# BYTEPLUS - Hard reload (re-read byteplus_maya.py from disk, NO Maya restart)
# ----------------------------------------------------------------------------
# Paste into the Maya Script Editor (Python tab) and run, or make a shelf button:
#   Script Editor -> paste -> select all -> middle-mouse-drag to a shelf.
# Run it after copying a new byteplus_maya.py into the module's scripts/ folder.
# ============================================================================
import sys
import maya.cmds as cmds

_MOD = "byteplus_maya"

# 1) Close any open BYTEPLUS windows (galleries / dialogs) so old Qt objects from
#    the previous module instance don't linger as orphans.
try:
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    for _w in QtWidgets.QApplication.topLevelWidgets():
        try:
            if (_w.windowTitle() or "").startswith("BYTEPLUS"):
                _w.close()
                _w.deleteLater()
        except Exception:
            pass
except Exception as _e:
    print("[BYTEPLUS reload] window cleanup skipped:", _e)

# 2) Remove the menu (install() rebuilds it, but delete first for a clean slate).
try:
    if cmds.menu("byteplusMenu", exists=True):
        cmds.deleteUI("byteplusMenu")
except Exception as _e:
    print("[BYTEPLUS reload] menu delete skipped:", _e)

# 3) Purge the cached module so the .py is RE-READ (re-compiled) from disk.
for _name in [_m for _m in list(sys.modules)
              if _m == _MOD or _m.startswith(_MOD + ".")]:
    del sys.modules[_name]

# 4) Fresh import + rebuild the menu.
import byteplus_maya
byteplus_maya.install()

# 5) Confirm which file / version actually loaded.
print("[BYTEPLUS reload] OK ->", byteplus_maya.__file__)
print("[BYTEPLUS reload] version:", byteplus_maya.CONFIG.VERSION)
