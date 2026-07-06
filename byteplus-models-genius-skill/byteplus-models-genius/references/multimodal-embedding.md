# Multimodal Embedding (Skylark Embedding Vision)

## Contents
1. Models & specs
2. Endpoint & input structure
3. Output-control parameters
4. Response shape
5. Input limits
6. Architectural notes

---

## 1. Models & specs

| Model ID | Modalities | Context | Max vector dim | RPM / TPM |
|---|---|---|---|---|
| `skylark-embedding-vision-251215` | video + image + text (Chinese & English) | 128K | 2048 | 1.2K / 1200K |
| `skylark-embedding-vision-250615` | video + image + text (Chinese & English) | 128K | 2048 | 1.2K / 1200K |

Both vectorize **mixed video/image/text as a single combined vector** — one call in, one embedding out (not one-per-item). AP-Southeast-only.

**Pricing (grounded, Skylark-embedding-vision token rates):** text input **$0.000125 / 1K tokens**, image input **$0.000325 / 1K tokens**. (These are the rates billed in the Knowledge Base; confirm the standalone `/embeddings/multimodal` line item matches on the Billing page. Video frames bill as `image_tokens`.)

## 2. Endpoint & input structure

`POST https://ark.ap-southeast.bytepluses.com/api/v3/embeddings/multimodal`

`input[]` is a list mixing content types; the whole list is embedded as **one** vector:
- Text: `{"type":"text","text":"..."}`
- Image: `{"type":"image_url","image_url":{"url":"<URL or data:image/...;base64,...>"}}`
- Video: `{"type":"video_url","video_url":{"url":"<URL or Base64>"}}`

```json
{
  "model": "skylark-embedding-vision-251215",
  "input": [
    {"type": "text", "text": "a red sports car at sunset"},
    {"type": "image_url", "image_url": {"url": "https://.../car.jpg"}}
  ]
}
```

`skylark-embedding-vision-250615` and later accept **unlimited** mixed text/image/video items. (The older `-250328` build only allowed 3 combos: 1 text, 1 image, or 1 image + 1 text.)

## 3. Output-control parameters

| Parameter | Values (default) | Effect |
|---|---|---|
| `dimensions` | `1024` or `2048` (default 2048) | Output vector dimension. Supported on `-250615` and later. |
| `encoding_format` | `float` (default) / `base64` | Return floats or Base64-packed vector. |
| `instructions` | string | Inference prompt; if omitted a modality-based default is generated. |
| `sparse_embedding` | `{"type":"disabled"}` (default) / `{"type":"enabled"}` | **Text-only.** `enabled` also returns a sparse vector alongside the dense one (for hybrid dense+sparse retrieval). |

## 4. Response shape

- `id`, `model`, `created`, `object: "list"`
- `data.embedding` — the dense `float[]`
- `data.sparse_embedding` — array of `{"index":dim, "value":non-zero}` (only when `sparse_embedding.type = "enabled"`; only non-zero elements)
- `data.object: "embedding"`
- `usage.prompt_tokens`, `usage.total_tokens`, and `usage.prompt_tokens_details.{text_tokens, image_tokens}` (image/video frames count as `image_tokens`; a few preset `text_tokens` are added when you send image/video).

## 5. Input limits

- **Text**: UTF-8, ≤100,000 bytes each; ≤8,000 tokens per text (model limit). For best quality keep total ≤4,096 tokens or ≤4 texts.
- **Image**: jpeg, png, webp, bmp, tiff, ico, dib, icns, sgi, jpeg2000. Aspect ratio [1/100, 100]; total pixels ≤ **36,000,000** (width×height product). For tiff/sgi/icns/jpeg2000 the file metadata must match the actual format or parsing fails.
- **Video**: mp4, avi, mov (lowercase); single file ≤ **50 MB**; Base64 supported. **Audio inside video is not embedded** (visual + text only).

## 6. Architectural notes

- One request → one vector for a **whole multimodal document** — ideal for cross-modal retrieval (search images/videos with a text query, or vice versa) in a single index.
- Pick `dimensions: 1024` to halve vector-store footprint and speed ANN search when 2048 is overkill; `2048` for maximum fidelity.
- Enable `sparse_embedding` (text-only) to run **hybrid retrieval** (dense semantic + sparse lexical) — better exact-keyword recall on top of semantic match.
- Respect **128K context** and the ≤4-texts / ≤4,096-token quality guidance: batching too much heterogeneous content into one vector dilutes it — embed at the granularity you'll retrieve.
