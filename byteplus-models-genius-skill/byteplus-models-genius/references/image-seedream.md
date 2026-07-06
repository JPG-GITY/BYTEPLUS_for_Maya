# Dola Seedream Image Generation

## Contents
1. Model lineup & endpoint
2. Resolution & sizing paradigms
3. Batch / sequential image generation
4. Output & format controls
5. Payload constraints (hard limits)
6. Multi-image blending & spatial reasoning
7. SSE streaming
8. Parameter support matrix
9. Image prompt engineering

---

## 1. Model lineup & endpoint

`POST https://ark.ap-southeast.bytepluses.com/api/v3/images/generations`. All image models are rated **500 Max IPM** (images per minute).

| Model ID | Notes |
|---|---|
| `seedream-5-0-260128` | Current flagship. Enhanced reference consistency, professional-grade quality. |
| `seedream-5-0-lite-260128` | Lite flagship — the endpoint also accepts it under the `seedream-5-0-260128` family. **Only Seedream model also available in `eu-west-1`.** Adds `output_format` and `optimize_prompt_options`. |
| `seedream-4-5-251128` | Prior gen. |
| `seedream-4-0-250828` | Prior gen; supports `fast` prompt-optimize mode. |
| `seededit-3-0-i2i` / `seedream-3-0-t2i` | Legacy edit / text-to-image; the only two that support `seed` and `guidance_scale`. Slated for deprecation (see enterprise-ops.md). |

Strengths: reference consistency, complex spatial reasoning, professional stylistic transfer.

## 2. Resolution & sizing paradigms

Two **mutually exclusive** ways to set output dimensions via `size`:

1. **Descriptive resolution** — a modifier string; the model infers aspect ratio from the prompt:
   - `seedream-5-0-lite`: `2K`, `3K`, `4K`
   - `seedream-4-5`: `2K`, `4K`
   - `seedream-4-0`: `1K`, `2K`, `4K`
2. **Exact pixel-mapping** — e.g. `"2048x2048"` (default). Both total-pixel range **and** aspect ratio must hold simultaneously:
   - 5.0-lite / 4.5: total pixels **[2560×1440 = 3,686,400 , 4096×4096 = 16,777,216]**, aspect **[1/16, 16]**.
   - 4.0: total pixels **[1280×720 = 921,600 , 16,777,216]**, aspect **[1/16, 16]**.
   - Example valid `3750x1250` (pixels 4.69M in range, ratio 3 in range); invalid `1500x1500` (pixels 2.25M below the 3.68M floor even though ratio is fine).

## 3. Batch / sequential image generation

Set `sequential_image_generation`:
- `disabled` (default) — one image.
- `auto` — the model decides whether to return several thematically related images (comic storyboards, brand kits, seasonal sets). Governed by `sequential_image_generation_options.max_images` (`[1,15]`, default 15).

**Hard cap:** *input reference images + generated images ≤ 15*. So multi-image blending and large batches trade off against each other. Works from text, a single image, or multiple references.

## 4. Output & format controls

- `response_format`: `url` (download link, **valid 24 h** — save immediately) or `b64_json` (inline Base64).
- `output_format`: `png` or `jpeg` — **only `seedream-5-0-lite`**; 4.5/4.0 are jpeg-only, no custom setting.
- `watermark`: **default `true`** for images (adds an "AI generated" mark bottom-right) — note this is the *opposite* default of Seedance video, where watermark defaults to `false`.
- `optimize_prompt_options.mode`: `standard` (5.0-lite/4.5 only support standard) or `fast` (4.0 — faster, slightly lower quality).

## 5. Payload constraints (hard limits)

- Reference images: public URLs or Base64 as `data:image/<format>;base64,<encoding>`.
- Single image ≤ **30 MB**.
- Total pixel count ≤ **36,000,000 pixels** (width × height product, not per-dimension maximums); each side > 14 px.
- Total request body ≤ **64 MB** — embedding multiple high-res Base64 images risks **HTTP 413 Payload Too Large**.
- Up to **14 reference images** per request.
- Formats: jpeg, png (5.0-lite/4.5/4.0 also webp, bmp, tiff, gif, heic, heif). Aspect [1/16, 16] for 5.0/4.5/4.0; [1/3, 3] for seededit.
- Best practice: store images in object storage (BytePlus TOS) and pass pre-signed URLs in the `image` array — lower latency, no buffer overruns.

## 6. Multi-image blending & spatial reasoning

Seedream 4.0–5.0 ingest up to **14 reference images** in a single inference pass. Capabilities:

- **Subject replacement / spatial insertion**: segment subject from Image A, map into the environment of Image B with accurate contact shadows and matched depth-of-field.
- **Composite editing / attribute transfer**: human model in one image + garment in another → garment drapes accurately over the model's proportions and pose.
- **Sequential character coherence**: feed character reference sheets to generate new poses/scenarios while locking facial and anatomical identity.

## 7. SSE streaming

Seedream 5.0-lite, 4.5, and 4.0 support **Server-Sent Events** via `stream: true`. The server pushes `image_generation.partial_succeeded` / `image_generation.partial_failed` the moment each image finishes, with an `image_index` plus the final `url` or `b64_json`, and a closing `image_generation.completed`. Works for both single and batch generation — frontends can populate the UI progressively.

## 8. Parameter support matrix

| Parameter | 5.0-lite | 4.5 | 4.0 | seededit-3-0-i2i / 3-0-t2i |
|---|---|---|---|---|
| `size` descriptive | 2K/3K/4K | 2K/4K | 1K/2K/4K | pixel only |
| `sequential_image_generation` | ✅ | ✅ | ✅ | ❌ |
| `stream` | ✅ | ✅ | ✅ | ❌ |
| `output_format` (png/jpeg) | ✅ | ❌ (jpeg) | ❌ (jpeg) | ❌ |
| `optimize_prompt_options.mode` | standard | standard | standard/fast | — |
| `seed` | ❌ | ❌ | ❌ | ✅ |
| `guidance_scale` | ❌ | ❌ | ❌ | ✅ (t2i 2.5 / i2i 5.5) |
| `watermark` (default true) | ✅ | ✅ | ✅ | ✅ |

Billing: `usage.generated_images` counts **only successfully generated** images (failures aren't billed); `usage.output_tokens ≈ sum(w*h)/256`. In a batch, a content-filter rejection skips to the next image; an internal 500 halts the remaining generations.

## 9. Image prompt engineering

- Keep prompts **under 600 English words** — beyond that, attention scatters and fine details are dropped in favor of heavily weighted elements.
- Use simple, direct language. Concise accurate prompts beat meandering AI-generated descriptive paragraphs.
- For sequential/batch sets, describe the scenes in order and reference `Image 1`, `Image 2`… when supplying multiple inputs so the mapping is unambiguous.
