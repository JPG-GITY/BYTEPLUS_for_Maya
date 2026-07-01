"""BYTEPLUS — DEV MODE ON.  Shelf button: shows Diagnostics + telemetry config.
Persists across restarts and rebuilds the menu immediately."""
import byteplus_maya
byteplus_maya.CONFIG.DEBUG = True
byteplus_maya._save_prefs()        # persist so it survives Maya restarts
byteplus_maya.install()            # rebuild the menu -> Diagnostics appears
print("[BYTEPLUS] DEV MODE ON  — Diagnostics + telemetry config visible. "
      "Re-open Settings to see the telemetry plumbing.")
