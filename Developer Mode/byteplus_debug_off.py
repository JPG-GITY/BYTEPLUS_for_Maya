"""BYTEPLUS — DEV MODE OFF.  Shelf button: hides Diagnostics + telemetry config
(client view). Persists across restarts and rebuilds the menu immediately."""
import byteplus_maya
byteplus_maya.CONFIG.DEBUG = False
byteplus_maya._save_prefs()        # persist so it survives Maya restarts
byteplus_maya.install()            # rebuild the menu -> Diagnostics hidden
print("[BYTEPLUS] DEV MODE OFF — client view (Diagnostics + telemetry config "
      "hidden). Re-open Settings to confirm.")
