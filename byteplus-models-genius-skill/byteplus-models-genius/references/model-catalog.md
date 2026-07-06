# ModelArk Full Model Catalog (client-shareable)

Complete list of models on BytePlus ModelArk, grouped by capability. All IDs are date-suffixed — **always pin the exact ID**. Every model runs in `ap-southeast-1`; only `seed-2-0` models and `seedream-5-0-lite` also run in `eu-west-1` (video/3D/embedding are AP-Southeast-only). Base URLs: `ap-southeast-1` → `https://ark.ap-southeast.bytepluses.com/api/v3`, `eu-west-1` → `https://ark.eu-west.bytepluses.com/api/v3`.

> Pricing is **not** included per-model here yet — see enterprise-ops.md / the Billing page. Where a price is grounded it is noted (3D, Seedance 2.0). LLM / image / embedding per-token prices are marked *(pricing: see Billing)* until the billing tables are supplied.

The three banner ("flagship") models: **Dola Seed 2.0** (agentic LLM), **Dola Seedream 5.0** (image), **Dreamina Seedance 2.0** (video).

---

## 1. Deep reasoning & text generation (LLMs)

APIs: Chat API (`/chat/completions`) and Responses API (`/responses`). Full parameter detail in llm-and-responses-api.md.

| Model ID | Key capabilities | Context / Max Input | Max Output (incl CoT) | RPM / TPM |
|---|---|---|---|---|
| `seed-2-0-pro-260328` | Deep reasoning, text, multimodal understanding, **tool calling**, visual grounding, MCP | 256K / 224K | 128K (def 4K) | 30K / 1.5M |
| `seed-2-0-lite-260428` | + **audio understanding** | 256K / 256K | 128K | 30K / 1.5M |
| `seed-2-0-mini-260428` | + **audio understanding** | 256K / 256K | 128K | 30K / 1.5M |
| `seed-2-0-lite-260228` | + structured output | 256K / 256K | 128K | 30K / 1.5M |
| `seed-2-0-mini-260215` | + structured output, visual grounding | 256K / 256K | 128K | 30K / 1.5M |
| `seed-2-0-code-preview-260328` | dedicated **code** model | 256K / 256K | 128K | 30K / 1.5M |
| `seed-1-8-251228` | multimodal + structured output | 256K / 224K | 64K (CoT 32K) | 30K / 1.5M |
| `glm-5-2-260617` | text, function calling; **`xhigh`/`max` effort** | **1024K** / 1024K | 128K | **0.5K** / 1000K |
| `glm-4-7-251222` | text, function calling | 256K / 224K | 128K | 15K / 1.5M |
| `deepseek-v4-pro-260425` | text, function calling | **1024K** / 1024K | **384K** | 15K / 1.5M |
| `deepseek-v4-flash-260425` | text, function calling (cheaper) | **1024K** / 1024K | **384K** | 15K / 1.5M |
| `deepseek-v3-2-251201` | text, function calling, structured output | 128K / 128K | 32K | 15K / 1.5M |
| `gpt-oss-120b-250805` | text, function calling | 128K / 96K | 64K (CoT 32K) | 15K / 800K |
| `seed-1-6-250915` | image+video understanding, structured output | 256K / 224K | 32K | 15K / 800K |
| `seed-1-6-250615` | + visual grounding | 256K / 224K | 32K | 15K / 800K |
| `seed-1-6-flash-250715` | + visual grounding (see structured-output caveat) | 256K / 224K | 32K | 15K / 800K |
| `seed-1-6-flash-250615` | image+video understanding | 256K / 224K | 32K | 15K / 800K |

*(pricing: see Billing)*

## 2. Visual understanding (image / video / document)

Same Chat/Responses endpoints, multimodal input. Models: `seed-2-0` family (pro/lite/mini all versions), `seed-1-8-251228`, `seed-1-6-250915/250615`, `seed-1-6-flash-250715/250615`. Visual grounding on `seed-2-0-pro`, `seed-2-0-mini-260215`, `seed-1-8`, `seed-1-6-250615`, `seed-1-6-flash`. Detail control via `detail` (low/high/xhigh) or `image_pixel_limit`; video via `fps` (0.2–5). See llm-and-responses-api.md §11.

## 3. Audio understanding

Only **`seed-2-0-lite-260428`** and **`seed-2-0-mini-260428`**. ASR (19 languages + Chinese dialects), speech translation (15 pairs), diarization, caption, embedded-in-video audio. ~6.25 tokens/sec of audio. 256K context, 30K RPM / 1.5M TPM.

## 3b. Audio generation (Seed Audio — TTS / voice synthesis)

API: `POST https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create` (**different host** — `voice.*`, not `ark.*`). Auth: `X-Api-Key` (new console) or `X-Api-App-Id` + `X-Api-Access-Key` (legacy). Full detail in audio-generation.md.

| Model ID | Modes | Output | Limits |
|---|---|---|---|
| `seed-audio-1.0` | text-only · audio-reference (`@Audio1..3`, incl. voice clone via `speaker`) · image-reference | Base64 audio (wav/mp3/pcm/ogg_opus), up to **120 s** | `text_prompt` ≤2048 chars; ≤3 audio refs (≤30 s / ≤10 MB each); 1 image ref (≤10 MB); audio & image refs can't mix |

Billed on `original_duration` (capped 120 s) — per-second price *(pricing: see Billing)*.

## 4. Video generation (Seedance)

API: `POST /api/v3/contents/generations/tasks` (async). Full detail in video-seedance.md.

| Model ID | Resolutions | Duration | Audio-visual sync | Flex (offline) |
|---|---|---|---|---|
| `dreamina-seedance-2-0-260128` | 480p/720p/1080p/**4k** | 4–15 s | ✅ | ❌ online-only |
| `dreamina-seedance-2-0-fast-260128` | 480p/720p | 4–15 s | ✅ | ❌ |
| `dreamina-seedance-2-0-mini-260615` | 480p/720p | 4–15 s | ✅ | ❌ |
| `seedance-1-5-pro-251215` | 480p/720p/1080p | 4–12 s | ✅ | ✅ (TPD 500B) |
| `seedance-1-0-pro-250528` | 480p/720p/1080p | 2–12 s | — | ✅ |
| `seedance-1-0-pro-fast-251015` | 480p/720p/1080p | 2–12 s | — | ✅ |

24 FPS, `.mp4`. Rate: enterprise 600 RPM / 10 concurrency (4k: 15 / 1); individual 180 / 3. Pricing (Seedance 2.0 base, USD/1M tokens, no-video/with-video): 480p&720p 7.0/4.3 · 1080p 7.7/4.7 · 4k 4.0/2.4 — see video-seedance.md §11.

## 5. Image generation (Seedream)

API: `POST /api/v3/images/generations` (**synchronous**). Full detail in image-seedream.md. Rate: **500 IPM** all models.

| Model ID | Resolutions | Notes |
|---|---|---|
| `seedream-5-0-260128` (+ `seedream-5-0-lite-260128`) | 2K/3K/4K | flagship; lite adds `output_format`, also in `eu-west-1` |
| `seedream-4-5-251128` | 2K/4K | jpeg only |
| `seedream-4-0-250828` | 1K/2K/4K | supports `fast` prompt-optimize |
| `seededit-3-0-i2i` / `seedream-3-0-t2i` | pixel-only | legacy; only ones with `seed`/`guidance_scale`; being deprecated |

*(pricing: see Billing)*

## 6. 3D generation

API: `POST /api/v3/contents/generations/tasks` (async). Full detail in 3d-generation.md.

| Model ID | Input | Output tiers | Polygon range | RPM / concurrency | Free quota |
|---|---|---|---|---|---|
| `Hyper3d-Rodin-Gen2` (console `hyper3d-gen2`) | Text→3D, Image→3D | White / Textured / PBR / Textured+PBR | tri [500, 1,000,000] · quad [1,000, 200,000] | 60 / 3 | 150K tokens |
| `Hitem3d-2.0` (console `hitem3d-2-0`) | Image→3D | Std White/Textured · High-Precision White/Textured | [100,000, 2,000,000] | 600 / 30 | 500K tokens |

Formats: glb, obj, stl, fbx, usdz. **Pricing (grounded): $0.0133 / 1K output tokens; each model = fixed 30,000 tokens ≈ $0.399/model.**

## 7. Multimodal embedding

API: `POST /api/v3/embeddings/multimodal`. Full detail in multimodal-embedding.md.

| Model ID | Modalities | Context | Max vector dim | RPM / TPM |
|---|---|---|---|---|
| `skylark-embedding-vision-251215` | video + image + text (zh/en) | 128K | 2048 | 1.2K / 1200K |
| `skylark-embedding-vision-250615` | video + image + text (zh/en) | 128K | 2048 | 1.2K / 1200K |

`dimensions` selectable 1024 or 2048; optional sparse embeddings (text-only). **Pricing (grounded):** text **$0.000125 / 1K tokens**, image **$0.000325 / 1K tokens** (Skylark-embedding-vision rates as billed in Knowledge Base — see enterprise-ops.md §7).

---

## Quick "which model" guidance for clients

- **Agentic app / tool-calling orchestrator** → `seed-2-0-pro-260328`.
- **High-throughput classification / extraction** → `seed-2-0-lite-260428` (30K RPM / 1.5M TPM), `reasoning.effort: minimal`.
- **Million-token context** → `glm-5-2-260617` or `deepseek-v4-*-260425` (1024K).
- **Coding in IDE** → Coding Plan + `seed-2-0-code-preview-260328` (correct base URL, see llm-and-responses-api.md §4).
- **Marketing image / product shots** → `seedream-5-0-260128`; batch sets via `sequential_image_generation: auto`.
- **Talking-head / ad video with sound** → `dreamina-seedance-2-0-260128` (4k) or `-fast`/`-mini` for cost.
- **Game/asset 3D** → `Hyper3d-Rodin-Gen2` (text or image, PBR) or `Hitem3d-2.0` (high-precision from image).
- **Semantic search / RAG over mixed media** → `skylark-embedding-vision-251215`.
- **Text-to-speech / voiceover / audiobook / voice cloning** → `seed-audio-1.0` (⚠️ `voice.ap-southeast-1.bytepluses.com` host, `X-Api-Key` auth) — see audio-generation.md.
