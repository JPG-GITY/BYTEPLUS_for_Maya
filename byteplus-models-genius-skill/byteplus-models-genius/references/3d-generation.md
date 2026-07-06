# 3D Generation (Hyper3D Rodin & Hitem3D)

## Contents
1. Models & specs
2. Endpoint & async lifecycle
3. Input methods (text / image)
4. Output-control parameters
5. Pricing
6. Constraints

---

## 1. Models & specs

Both are AP-Southeast-only, async, and share the generation-task endpoint.

| Spec | `Hyper3d-Rodin-Gen2` (console `hyper3d-gen2`) | `Hitem3d-2.0` (console `hitem3d-2-0`) |
|---|---|---|
| Input | **Text→3D and Image→3D** | **Image→3D only** |
| Output tiers | White model · Textured model · PBR material model · Textured + PBR | Standard White · Standard Textured · High-Precision White · High-Precision Textured |
| Polygon count | triangular mesh **[500, 1,000,000]** · quad mesh **[1,000, 200,000]** | **[100,000, 2,000,000]** |
| Resolution | — | 1536 / 1536pro |
| File formats | glb, obj, stl, fbx, usdz | glb, obj, stl, fbx, usdz |
| Rate limit | 60 RPM / 3 concurrency | 600 RPM / 30 concurrency |
| Free quota | 150K tokens | 500K tokens |

Regional availability is restricted to a published country list (AU, KH, EG, HK, ID, IN, JP, KW, MY, PH, QA, SA, SG, ZA, KR, TW, TH, TR, VN, etc.) — verify the current list in the docs before promising availability.

## 2. Endpoint & async lifecycle

Same pattern as video generation:

1. **Create**: `POST https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks` with `model` + `content[]` → returns `id` (kept **7 days** from `created_at`).
2. **Retrieve**: `GET .../contents/generations/tasks/{id}` → `status` ∈ `queued → running → succeeded/failed`, plus `cancelled` (queued-only) / `expired`.
3. **Output**: `content.file_url` (the 3D model file) — valid **24 h**, download immediately.
4. **List / Delete**: same `contents/generations/tasks` list & delete endpoints as video (7-day history).
5. **Webhook**: `callback_url` mirrors the Retrieve payload on state change.
6. **Usage**: `usage.completion_tokens` (= billable); `total_tokens = completion_tokens` (input tokens 0).

```bash
curl https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks \
  -H "Authorization: Bearer $ARK_API_KEY" -H "Content-Type: application/json" \
  -d '{ "model": "Hyper3d-Rodin-Gen2",
        "content": [ {"type":"text","text":"a quadruped mech robot, orange armor --material PBR --mesh_mode Quad --fileformat glb"} ] }'
```

## 3. Input methods (text / image)

`content[]` accepts text and/or image parts:
- **Text→3D** (Hyper3D only): `{"type":"text","text":"<prompt> --<params>"}`. English only, ≤400 chars (truncated beyond).
- **Image→3D**: `{"type":"image_url","image_url":{"url":"..."}}` — **1–5 images**, URL or Base64 (`data:image/<fmt>;base64,...`). Optional text + params.
- `seed`: integer `[0, 65535]` for reproducibility control (same request + different seed → different output; same seed ≈ similar, not identical).

Image requirements: jpg / jpeg / png; single image < 4096×4096 px; < 30 MB; 1–5 images.

## 4. Output-control parameters

Passed either directly in the body or appended to the text prompt as `--<param> <value>`:

| Parameter | Values (default) | Effect |
|---|---|---|
| `material` | `PBR` (default) / `Shaded` / `All` / `None` | PBR = base-color+metallic+normal+roughness maps; Shaded = base color + baked lighting; None = white mesh |
| `mesh_mode` | `Quad` (default) / `Raw` | Quad mesh vs triangle mesh |
| `quality_override` | Raw [500, 1,000,000] def 500000 · Quad [1,000, 200,000] def 18000 | Explicit polygon count; **overrides `subdivisionlevel`**. Recommend ≥150,000 |
| `subdivisionlevel` | Raw: high 500k / medium 150k / low 20k · Quad: high 50k / medium 18k (def) / low 8k | Preset polygon tier |
| `addons` | `HighPack` | Upgrades textures to **4K** (default 2K) |
| `fileformat` | `glb` (default) / obj / usdz / fbx / stl | Output file format |
| `hd_texture` | `false` (default) / `true` | HD texture |
| `use_original_alpha` | `false` (default) / `true` | Preserve transparent regions of the input image |
| `bbox_condition` | `[x, y, z]` | Bounding-box dimensions; usually leave unset (model decides) |
| `TAPose` | `false` (default) / `true` | Enforce standard T/A-pose binding for humanoids |

## 5. Pricing

**Grounded:** the 3D generation API charges **$0.0133 USD per 1K output tokens**, and each generated 3D model consumes a **fixed 30,000 tokens ≈ $0.399 per model**. Free quota per model (150K tokens Hyper3D / 500K Hitem3D) covers roughly 5 / 16 models before billing. Confirm any model-specific differences on the Billing page.

## 6. Constraints

- Output `file_url` expires in **24 h** — persist to your own storage immediately.
- Task records retained **7 days**; poll Retrieve or use `callback_url`.
- Hitem3D is **image-only** — no text-to-3D.
- Regional availability is a fixed country list; don't promise a region without checking.
