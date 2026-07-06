# Dreamina Seedance 2.0 Video Generation & VideoPilot

## Contents
1. Models & specs
2. Resolution, 4K & 10-bit encoding
3. Parameter support matrix & input methods
4. Multimodal reference injection
5. Async task lifecycle
6. Frame math & video extension
7. Biometric compliance — "Trusted Outputs"
8. Video prompt engineering (the Advanced Formula)
9. Draft mode (Seedance 1.5 Pro only)
10. VideoPilot editing API
11. Pricing quick reference

---

## 1. Models & specs

Endpoint (AP Southeast only — video is **not** available in `eu-west-1`):
`POST https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks`

| Spec | Seedance 2.0 | Seedance 2.0 Fast | Seedance 2.0 Mini |
|---|---|---|---|
| Model ID | `dreamina-seedance-2-0-260128` | `dreamina-seedance-2-0-fast-260128` | `dreamina-seedance-2-0-mini-260615` |
| Resolutions | 480p, 720p, 1080p, **4k** | 480p, 720p | 480p, 720p |
| Default resolution | 720p | 720p | 720p |
| Aspect ratios | 21:9, 16:9, 4:3, 1:1, 3:4, 9:16, adaptive | same | same |
| Default ratio | adaptive | adaptive | adaptive |
| Duration | 4–15 s, or `-1` (auto) | 4–15 s, or `-1` | 4–15 s, or `-1` |
| Inference mode | online only | online only | online only |

- **Only the base `dreamina-seedance-2-0-260128` supports 1080p and 4k.** Fast and Mini top out at 720p.
- Mini reached API access on **June 22, 2026** (UTC+8); during the June 15–22 trial it was Playground-only with concurrency capped at 1.
- Note on naming: billing/pricing/resource-pack docs use the `dreamina-`-prefixed IDs above; the console and Elements/Digital-Character library URLs sometimes use the un-prefixed form `seedance-2-0-260128`. Both refer to the same model. (Seedance 1.5 Pro is `seedance-1-5-pro-251215`.)
- Prompt languages: all models support English; **Seedance 2.0 series additionally supports Japanese, Indonesian, Spanish, and Portuguese.** Recommended prompt length under ~1000 words.

## 2. Resolution, 4K & 10-bit encoding

Set via the **`resolution`** string. Valid values: `480p`, `720p`, `1080p` (not Fast/Mini), `4k` (base 2.0 only). Default `720p`.

**The 10-bit upgrade is implicit in `4k` — there is no separate bit-depth / HDR / pixel-format parameter.** Selecting `"resolution": "4k"` on `dreamina-seedance-2-0-260128` automatically yields:
- **10-bit encoding** (vs standard 8-bit), preserving richer color gradations and smoother tonal transitions — suitable for professional video production and HDR content.
- **H.265 (HEVC) codec.** Some players/browsers cannot play it directly — plan a decode/transcode path for previews.

4k pixel dimensions by aspect ratio (Seedance 2.0 series only):

| Aspect ratio | 4k (W×H) |
|---|---|
| 16:9 | 3840×2160 |
| 4:3 | 3326×2494 |
| 1:1 | 2880×2880 |
| 3:4 | 2494×3326 |
| 9:16 | 2160×3840 |
| 21:9 | 4398×1886 |

Video **reference inputs** also accept up to 4k (480p/720p/1080p/4k), frame rate [24, 60], each ≤200 MB, ≤3 clips totalling ≤15 s, total pixels per ref in [640×640=409600, 3326×2494=8295044]. Containers: MP4/MOV; video H.264/H.265, audio AAC/MP3.

## 3. Parameter support matrix & input methods

Two ways to pass `resolution`/`ratio`/`duration`/`frames`/`seed`/`camera_fixed`/`watermark`:
- **New (recommended)** — fields directly in the request body; **strict validation** (bad value → error). Write values in full (`"resolution": "720p"`), no abbreviations.
- **Legacy** — appended to the prompt text; **loose validation** (bad value → silently defaulted): `--rs 720p --rt 16:9 --dur 5 --seed 11 --cf false --wm true` (or full `--resolution/--ratio/--duration/--camerafixed/--watermark`).

Support matrix (Seedance 2.0 base unless noted):

| Parameter | 2.0 | Notes |
|---|---|---|
| `resolution` (+`4k`) | ✅ | 4k = base 2.0 only; 1080p not on Fast/Mini |
| `ratio` (`adaptive` default) | ✅ | actual ratio returned by Retrieve API |
| `duration` (`[4,15]` or `-1`) | ✅ | `-1` = model picks length within range |
| `frames` | ❌ | unsupported on 2.0 **and** 1.5 Pro; use `duration`. (Formula where supported: frames = 25+4n, range [29,289].) |
| `seed` | ❌ | unsupported on 2.0 |
| `camera_fixed` | ❌ | unsupported on 2.0 (and reference-to-image scenarios) |
| `generate_audio` (default `true`) | ✅ | output is **always mono**; put dialogue in double quotes to optimize |
| `draft` | ❌ | **1.5 Pro only** (see §9) |
| `service_tier=flex` | ❌ | 2.0 is **online-only**; no offline / 50%-price tier |
| `priority` (`0–9`, default `0`) | ✅ | **2.0 only**; reorders the queue within one Endpoint, FIFO within same priority; doesn't preempt running tasks; not available in flex |
| `safety_identifier` | ✅ | ≤64-char hashed end-user ID for usage-policy abuse detection |
| `return_last_frame` (default `false`) | ✅ | watermark-free PNG, same dims as video |
| `execution_expires_after` | ✅ | default 172800 s (48 h), range [3600, 259200]; on timeout → `expired` |
| `watermark` (default `false`) | ✅ | `true` → "AI Generated" bottom-right |
| `callback_url` | ✅ | POST mirrors the Retrieve response on state change |

Image inputs: formats .jpeg/.png/.webp/.bmp/.tiff/.gif (2.0 & 1.5 Pro also .heic/.heif); aspect ratio (0.4, 2.5); 300–6000 px per side; single image <30 MB; **request body ≤64 MB** (don't Base64 large files); 1–9 reference images for 2.0 multimodal. URL, Base64, or `asset://<ASSET_ID>` (digital characters) accepted.

## 4. Multimodal reference injection

A single `content[]` payload combines text + image + video + audio:
- **Image references (0–9)**: lock character identity, environment composition, style. `role: reference_image`.
- **Video reference (0–3, ≤15 s total)**: temporal dynamics — camera kinematics (pan/tilt/zoom/orbit), motion cadence, pacing. `role: reference_video`. Seedance 2.0 only.
- **Audio (0–3, ≤15 s total) + `generate_audio: true`**: synced vocals, SFX, score. Seedance 2.0 only. Formats wav/mp3, each ≤15 MB. **Audio cannot be sent alone** — at least one image or video reference is required.

**Three mutually exclusive modes — cannot be mixed in one request:**
1. **First frame**: one `image_url`, `role: first_frame` (or left blank). All models.
2. **First + last frames**: two `image_url`s, `role: first_frame` and `last_frame` (required). Seedance 2.0 / 1.5 Pro / 1.0 Pro. Frames may be identical; mismatched ratios → first frame wins, last is center-cropped.
3. **Multimodal reference**: 1–9 `reference_image` (+ optional video/audio). Seedance 2.0 only.

This is the root of the `first_frame`/`reference_image` exclusivity: a single call can't carry both roles. To approximate "first/last frame + references," stay in mode 3 and name the reference images as first/last **in the prompt text**. For a guaranteed exact first/last frame, use mode 2 with explicit roles. (Also supported: `draft_task` content type for sample-based generation — 1.5 Pro only.)

## 5. Async task lifecycle

1. **Create**: `POST .../contents/generations/tasks` → returns `id` (task ID, stored 7 days from `created_at`).
2. **Retrieve**: `GET .../contents/generations/tasks/{id}` → `status` ∈ `queued → running → succeeded/failed`, plus `cancelled` (only from `queued`) and `expired`.
3. **Webhooks**: `callback_url` receives a POST mirroring the Retrieve response on state change; retried 3× if no 5-second delivery ack.
4. **Output**: `content.video_url` valid **24 h** — download immediately (this is the CDN-expiry behavior); `content.last_frame_url` also 24 h.
5. **Usage**: `usage.completion_tokens` = billable tokens; for video `total_tokens = completion_tokens` (input tokens always 0). Response also echoes `resolution`, `ratio`, `duration`/`frames`, `framespersecond`, `generate_audio`, `priority`, `safety_identifier`, `service_tier`.

## 6. Frame math & video extension

- Output base rate **24 FPS**; `frames` is unsupported on 2.0 (use `duration`). Reference videos may be 24–60 FPS.
- `return_last_frame: true` → final frame as a watermark-free PNG, dimensions matching the video.
- **Extension pattern**: feed video A's `last_frame_url` as video B's first frame to daisy-chain past the 15 s cap.

## 7. Biometric compliance — "Trusted Outputs"

Seedance 2.0 **categorically rejects** reference images/videos containing unverified real human faces. A face asset is accepted only if it originates from a trusted platform output generated **within the preceding 30 days**, on the same account:
- Face-containing videos generated by Seedance 2.0 series
- Last-frame images derived from Seedance 2.0 outputs
- Face-containing images from Dola Seedream 5.0 Lite

Trust is **nullified** by altering file metadata, third-party compression, or cross-account asset transfer → task fails. Alternatives provided: preset digital characters (`asset://<ASSET_ID>`) and authorized real-person assets via enterprise contract. Restriction applies to **real human faces only** — stylized 3D/cartoon characters are unaffected.

## 8. Video prompt engineering — the Advanced Formula

The engine decouples a **spatial layer** (what's in frame) from a **temporal layer** (how it changes). Address both.

**Formula**: Precise Subject + Action Details + Scene/Environment + Lighting & Color Tone + Camera Movement + Visual Style + Image Quality + Constraints.

Key heuristics:
- **Subject tagging**: `Define the woman wearing a red dress in <Image_1> as <Subject_1>`, then use `<Subject_1>` rigorously. Failure → subject mutation mid-timeline.
- **Quantify kinematics**: abstract verbs hallucinate. Specify vector/speed/inertia ("slowly raise a hand", "use the inertia of turning to naturally raise a hand"). Slow coherent transitions suppress burst-dynamic failures.
- **Externalize emotion somatically**: not "anger" but "both fists clenched, jawline tense, chest heaving, eyes sharp as knives".
- **Functional typography**: accurate in-scene text (slogans, synced subtitles, tracking speech bubbles) via text + positioning templates.

## 9. Draft mode — **Seedance 1.5 Pro only**

⚠️ Draft mode is **no longer a Seedance 2.0 feature** in the current API. `draft: true` and the `draft_task` / sample-task content type are supported **only by `seedance-1-5-pro-251215`**. On 1.5 Pro: draft renders at 480p (other resolutions error), no last-frame return, no offline inference; the final render reuses `model`, `content.text`, `content.image_url`, `generate_audio`, `seed`, `ratio`, `duration`, `camera_fixed` keyed by the returned `draft_task_id`.

For Seedance 2.0 cost-efficient iteration, substitute: prototype at 480p/720p (and/or use Mini/Fast), lock the prompt, then re-render at 1080p/4k on the base model.

## 10. VideoPilot editing API

Iterative editing suite, parallel to core generation:
- **`ImitateAndGenerateVideo`**: `RefVideoUrl` + edit instructions. `TimeBudget` (1/2/3) allocates compute (higher = better quality, more latency). `ImitationSetting` toggles 'imitative' vs 'creative'.
- **`RegenerateVideoSegmentFromFeedback`**: isolate a `SegmentId`, give targeted `FeedbackMessage` → re-renders only that slice.
- **`ListSegmentVersions`**: temporal version control — review/hot-swap historical segment versions.
- **`ExtractKeyFramesAndPlot`**: analyzes existing videos, extracts keyframes, auto-builds prompt libraries to reproduce styles.

Roadmap: native video splitting and precise keyframe insertion are scheduled additions.

## 11. Pricing quick reference (Seedance 2.0 base, online)

Unit price (USD per 1M tokens) — input without video / with video:
- 480p & 720p: **7.0 / 4.3**
- 1080p: **7.7 / 4.7**
- **4k: 4.0 / 2.4** — lower unit price, but ~4× the pixels of 1080p → higher net cost per video.

Per-video estimate, 5 s, 16:9, no video input: 480p $0.35 · 720p $0.76 · 1080p $1.87 · **4k $3.89**. With video input, 4k runs **$4.20–9.33** depending on input length (2–4 s → low, 15 s → high). Fast/Mini do not support 1080p or 4k.

Token estimate = `(input_video_dur + output_video_dur) × W × H × fps / 1024`. When input includes video, 2.0/Fast enforce a resolution-/ratio-/duration-dependent **minimum token consumption**. Resource packs (prepaid, 90-day) deduct online-inference tokens; base 2.0 requires a minimum of 7× 1M-token packs. Actual cost = the `completion_tokens` returned after the call.
