# Patches to port to the Windows master (`byteplus_maya.py`)

Applied to the **Mac install** (v2.01) on 2026-07-27 and verified with Maya's own
Python 3.13.9. The master source lives on the Windows machine, so the next build
loses these unless they are ported.

Backup of the pre-patch Mac file:
`~/Library/Preferences/Autodesk/maya/modules/BYTEPLUS/scripts/byteplus_maya.py.bak-20260727-094343`

---

## 1. Corporate-VPN SSL failure (macOS only) — CRITICAL

Full write-up: **SSL_CORPORATE_CA_FIX.md** (same folder).

**Symptom:** `Network error -- couldn't reach BytePlus (A failure in the SSL library
occurred (_ssl.c:1032))` while the browser and curl work.

**Cause:** the corporate VPN (SealSuite SWG) re-signs TLS with its own CA. macOS puts
that CA in the **keychain**, but Maya's Python verifies against **certifi**, which
lacks it. Windows Python already reads the OS store, so this is macOS-only.

**Fix:** `_ssl_context()` merges the keychain CAs, so it works with verification ON.
See SSL_CORPORATE_CA_FIX.md for the exact code block (two new helpers
`_os_trust_ca_pem()` / `_add_os_trust()` plus the rewritten `_ssl_context()`).

**Expect colleagues on the same VPN to hit this.** Without the fix their only option
is Settings > untick "Verify SSL certificates".

---

## 2. Empty-gallery hint — says WHERE it looked

**Why:** the galleries read from `<maya project>/movies|images/byteplus/<scene>/`.
When a project is copied from another machine and Maya's **Set Project** points at a
different folder (e.g. a nested `assets` project), the gallery is simply empty and it
looks like the plugin lost the files. This shows the path and the active project.

### 2a. `_ZoomView` — add `show_text()` (Dream gallery preview is a QGraphicsView)

In `set_pixmap()` and `clear()`, add `self._hide_msg()` as the first line, then add:

```python
    def _hide_msg(self):
        it = getattr(self, "_msg", None)
        if it is not None:
            it.setVisible(False)

    def show_text(self, msg):
        """Render a centred message instead of an image (empty-gallery hint)."""
        self._item.setPixmap(QtGui.QPixmap())
        self._has = False
        it = getattr(self, "_msg", None)
        if it is None:
            it = self._scene.addText("")
            it.setDefaultTextColor(QtGui.QColor("#9a9a9a"))
            self._msg = it
        it.setPlainText(msg or "")
        it.setVisible(bool(msg))
        self.resetTransform()
        self._zoom = 0
        self._scene.setSceneRect(it.boundingRect())
        self.centerOn(it)
```

### 2b. The shared helper (put it just above `class VideoGallery`)

```python
def _empty_gallery_hint(folder: str, kind: str) -> str:
    """Message for an empty gallery. Says WHERE we looked and which project is
    active, so a wrong Maya 'Set Project' -- very common when a project is copied
    from another machine, and the folder is per-project -- is obvious instead of
    looking like the plugin lost the files."""
    try:
        proj = cmds.workspace(q=True, fullName=True) or "(none)"
    except Exception:
        proj = "(none)"
    return ("No {k} for this scene yet.\n\n"
            "Looked in:\n{f}\n\n"
            "Current project:\n{p}\n\n"
            "If your {k} are somewhere else, pick the right project with "
            "File > Set Project…, then reopen this gallery.".format(
                k=kind, f=folder, p=proj))
```

### 2c. Wire it into both galleries

`VideoGallery._load_existing()` — after the `if self._items:` block:

```python
        if self._items:
            self.strip.setCurrentRow(self.strip.count() - 1)
            self._show(self._items[-1])
        else:                              # nothing found -> say where we looked
            self.view.setText(_empty_gallery_hint(self._mov_dir, "videos"))
        self._retrofit_thumbnails()
```

`DreamGallery._load_existing()` — same idea, but the view is a `_ZoomView`:

```python
        if self._items:
            self.strip.setCurrentRow(self.strip.count() - 1)
            self._show(self._items[-1])
        else:                              # nothing found -> say where we looked
            self.view.show_text(_empty_gallery_hint(self._img_dir, "images"))
```

### Sample output

```
No videos for this scene yet.

Looked in:
/Users/…/projects/default/assets/movies/byteplus/Human_TST-Seedance-DANCE

Current project:
/Users/…/projects/default/assets

If your videos are somewhere else, pick the right project with
File > Set Project…, then reopen this gallery.
```

---

## Verification performed
| Check | Result |
|---|---|
| `ast.parse` with Maya 2027 Python 3.13.9 | OK (13,951 lines) |
| TLS handshake with `SSL_VERIFY=True` | FAIL before → **OK (TLS 1.3)** after |
| Real HTTPS POST to the API | **HTTP 401** (reached it; only the key was missing) |
| `_empty_gallery_hint()` rendered | Correct path + project shown |
