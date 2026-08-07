# Seedance 2.5 in BYTEPLUS for Maya — status & plan

Model: `dreamina-seedance-2-5-260628` · **verified live on this account** (present in
`GET /api/v3/models`, and test submissions were accepted).

---

## Phase 1 — DONE (capability layer, already in the Mac install)

2.5 is **not** a drop-in for 2.0, so the plugin is now *model-aware*. All of this sits
inside `_seedance_generate`, which means **all 8 call sites** (Animate, Render, Edit,
Extend, batch queue…) are safe without touching any of them.

| Added | Where |
|---|---|
| `SEEDANCE_MODEL_25` + `SEEDANCE_CAPS` (per-model envelope) | CONFIG |
| `COST_VIDEO_RATES_25` = 480p/720p `(10.7, 6.4)` USD/M tokens | CONFIG |
| `COST_DIMS_25` — 2.5's 480p is 854×480, not 2.0's 864×496 | CONFIG |
| `_seedance_caps()` / `_is_seedance_25()` / `_fit_resolution()` / `_fit_duration()` | helpers |
| `_est_video_cost(..., model)` — per-model rates + dims | helpers |
| `output_format` param → `body["output_format"]` (mov, 2.5 only) | `_seedance_generate` |

Verified with Maya's own Python:

```
1080p / 4k  →  2.5 steps down to 720p (instead of failing the job)
45 s        →  2.0: 15 s   2.5: 30 s        -1 passes through (model picks)
ep-xxxxx    →  falls back to the conservative 2.0 envelope
720p 30 s with playblast, 2.5 → 1,296,000 tokens ≈ $8.29
```

**Live-API facts confirmed by test submission (not assumed):**
- `duration: 30` + `720p` → **accepted**.
- `1080p` → **rejected synchronously**: `InvalidParameter — the parameter resolution
  specified in the request is not valid for model dreamina-seedance-2-5 in t2v`.
- `ratio: adaptive` + `duration: -1` + `output_format: mov` → **accepted**.
- `DELETE` on a 2.5 task returns **409 Conflict** — 2.5 starts too fast to abort, so
  the plugin's create-then-abort diagnostic pattern does **not** work here.

---

## Phase 2 — the opportunities, ranked for THIS plugin

### 1. Base-mesh rendering — the one that matters ⭐

2.5 adds a first-class **base-mesh (white-model) reference** task: feed an untextured
blockmesh video, and the model renders on top of it while following its motion, camera
and blocking.

**A Maya playblast IS a white-model video.** This plugin already:
- playblasts the viewport, and
- runs `_isolate_polys()` first — which strips everything except polymeshes.

The 2.5 guide's hard requirement for fine-grained meshes is *"no trajectory lines,
coordinate lines or camera cones — they leak into the output"*. The plugin already
produces exactly that clean mesh. We were accidentally doing it right.

This is the documented fix for the motion-fidelity problem we chased for weeks: 2.0's
`reference_video` extracts *temporal dynamics* (a guide), whereas 2.5's base-mesh path
is built to carry structure frame by frame. Prompt shape the guide prescribes:

> "Refer to the camera movement and action of Video 1… map the man in grey in Image 1
> to the red mesh in Video 1."

**Work:** a dedicated prompt builder for the playblast path + naming the mesh↔reference
mapping. Mostly prompt engineering, little plumbing.

### 2. Native edit / extend — VideoPilot retirement ✅ DONE

**The code was already clean.** A six-agent sweep of the 14,122-line plugin found
**zero** occurrences of "pilot" (verified five ways, including byte-level and
normalised whole-file scans). The v2.01 built on Windows had already removed it, and
**Edit video already runs on the native Seedance path**:

```
"✎ Edit video" button L4549 → _regen L4999 → VideoEditDialog L4401
    → _seedance_edit_wrap L5715 → _seedance_edit L5740 → _seedance_generate  (ark /api/v3)
```

What was left was **stale documentation** still advertising a retired feature — now
cleaned: `NOTICE.md`, `USER_GUIDE.md` (root), `build_brief.js` (which still called
Edit video *"coming soon … currently greyed out"*), `build_deck.js`,
`POSTHOG_DASHBOARD.md`.

⚠️ **Do NOT delete these look-alikes** — a name-based sweep would break the build:
`_ssl_context` (L572) is the plugin's only SSL context builder, carries the macOS
keychain fix and every HTTP request; `VideoEditDialog`, the Edit/Extend buttons,
`MOTION_HOST` (Cloudflare R2, not a VideoPilot host), and the `Action`-keyed signed
API at L1535 (Trusted Asset Library) are all native features.

Remaining 2.5 work on this path:

The Edit-video feature fought VideoPilot for weeks: separate host, expired TLS cert,
503/404 flapping, a ModelArk oncall. 2.5 has **editing and extension as native task
types on the same `ark` endpoint with the same API key**. No second host, no cert
workaround, no oncall.

⚠️ **Locked parameters** — get these wrong and you get an *asynchronous*
`InvalidParameter.TaskTypeConstraint` after queueing:

| Task | `ratio` | `duration` |
|---|---|---|
| Video editing | must be `adaptive` | must be `-1` |
| Video extension | must be `adaptive` | free (4–30) |
| First / first+last frame | must be `adaptive` | free (4–30) |

Task type is inferred from `content.role` **plus prompt wording** — "add/remove/replace"
⇒ edit; "extend/continue" ⇒ extension. So the UI must send `adaptive`/`-1` on those
paths, and the existing `_seedance_edit_wrap()` phrasing needs auditing against it.
Also: input video ≤ 20 s for good edits, and **mov in / mov out**.

### 3. 30-second single take

`max(4, min(15, …))` appears at **7 sites** (lines ~1033, 4370, 4950, 6001, 6069, 6448,
6727). They are now redundant for 2.5 — `_fit_duration()` handles the window centrally —
but they still visually cap the UI at 15 s. Make the spinboxes/labels read the model's
window so a Maya shot longer than 15 s can render as one take.

### 4. Timestamps — 2.0 ignored them, 2.5 obeys them

2.5 responds to **integer-second** timestamps (`[0-10s] … [10-20s]`) on a **continuous**
timeline. Maya knows the scene's timing, so the plugin could emit a real shot list from
camera cuts / time markers instead of prose. This is the biggest storytelling upgrade.

### 5. Keyframe reference

"Render with Seedance" already renders 3–9 Arnold frames as references. 2.5's **keyframe
reference** ("Take Image 1 to Image N in sequence as keyframes") aligns the output
*relatively strictly* to them — those Arnold frames stop being loose style hints and
become actual keyframes. `MAX_IMAGE_REFS` can go 9 → 30 for 2.5.

### 6. Smaller wins

- Audio references (up to 10) + native 10-language generation.
- `mov` output for colour fidelity into Nuke/Resolve.
- Multi-view entity reference is now supported (2.0 discouraged it).

---

## Landmines to respect

| Risk | Mitigation |
|---|---|
| **No 1080p/4K in 2.5** | Handled: steps down to 720p + logs. But 4K users must stay on 2.0 — keep both models selectable, don't replace `SEEDANCE_MODEL`. |
| **Locked ratio/duration** | Edit/extend/first-frame paths must send `adaptive` (+ `-1` for edit). Error is async, so it burns queue time. |
| **Resource pack** | 2.5 requires a purchased Seedance 2.0–2.5 resource pack to activate. Fine on this account; **client builds must fail with a clear message**, not a raw API error. |
| **Cost** | 2.5 ≈ 1.5× 2.0 at the same res (10.7 vs 7.0 USD/M no-video). A 30 s 720p take with playblast ≈ **$8.29**. The cost confirm threshold matters more now. |
| **No abort** | `DELETE` → 409 once running. The HUD's cancel can stop polling but **cannot stop billing** for 2.5. Worth saying so in the UI. |
| Pricing provenance | The 2.5 unit prices come from an internally-marked table. Cross-check against the published pricing page before shipping them in a customer build. |

---

## Suggested order

1. **Base-mesh prompt mode** for the playblast path (biggest quality win, low risk).
2. **Model selector** in Settings (2.0 / 2.5 / fast / mini) + UI that reads
   `_seedance_caps()` so resolution and duration controls reflect the chosen model.
3. **Switch Edit/Extend to native 2.5** with locked-parameter handling; retire VideoPilot.
4. **Timestamped shot lists** from the Maya timeline.
5. Keyframe reference + `MAX_IMAGE_REFS` 30 for 2.5.
