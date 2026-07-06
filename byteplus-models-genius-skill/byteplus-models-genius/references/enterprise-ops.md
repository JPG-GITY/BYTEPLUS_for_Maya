# Enterprise Operations: Regions, IAM, Rate Limits, Billing, Deprecation

## Contents
1. Regions & base URLs
2. Authentication & IAM
3. Rate limits
4. Service tiers (default vs flex)
5. AI Savings Plans
6. Billing cycle (near real-time vs hourly)
7. Grounded prices (embedding & Knowledge Base)
8. Model deprecation lifecycle

---

## 1. Regions & base URLs

Two regions, and **you must match the base URL to the region** or the call fails / hits the wrong quota:

| Region | Base URL |
|---|---|
| `ap-southeast-1` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `eu-west-1` | `https://ark.eu-west.bytepluses.com/api/v3` |

- **Every model in the Model list runs in `ap-southeast-1`.**
- **`eu-west-1` is restricted**: only `seed-2-0` models and `seedream-5-0-lite` are available there. Everything else (video/Seedance, other image models, most legacy LLMs) is AP-Southeast-only — notably **all Seedance video generation is AP-Southeast-only**.
- Coding Plan uses separate paths off the AP-Southeast host: `/api/coding` (Anthropic-protocol) and `/api/coding/v3` (OpenAI-compatible). See llm-and-responses-api.md.

## 2. Authentication & IAM

Two security classes of API:

1. **Data-plane** (`/chat/completions`, `/responses`, `/images/generations`, `/contents/generations/tasks`): simple API Key auth via Bearer header — `Authorization: Bearer $ARK_API_KEY` — minimizing handshake latency.
2. **Control-plane** (resource allocation, endpoint creation, telemetry): Access Key/Secret Key signature auth; supports IP whitelists and departmental resource groups.

Cost & security segmentation:
- Billing telemetry segments **by API Key** — provision unique keys per microservice/staging env/app to track token consumption without multiple master accounts.
- **Sub-Accounts** with restrictive policy templates — e.g. `ArkReadOnlyAccess` gives analysts dashboard/telemetry visibility but blocks destructive `DELETE` calls and endpoint changes.

## 3. Rate limits

All published limits are **theoretical maxima, not guarantees** — real ceilings depend on platform load and invocation method. Bursty ramps can trip protection even below the nominal cap; ramp traffic gradually.

| Domain | RPM / concurrency | TPM |
|---|---|---|
| Seed 2.0 LLMs (Lite/Mini/Pro) | 30K RPM | 1.5M TPM |
| `glm-4-7`, `deepseek-v4-*`, `deepseek-v3-2`, `gpt-oss-120b` | 15K RPM | 800K–1.5M TPM |
| `glm-5-2-260617` | **0.5K RPM** (very low) | 1000K TPM |
| Seed 1.6 family | 15K RPM | 800K TPM |
| Image (Seedream, all) | — | **500 IPM** (images/min) |
| Seedance video — enterprise-verified | 600 RPM / 10 concurrency (non-4k) | 4k: 15 RPM / 1 concurrency |
| Seedance video — individual | 180 RPM / 3 concurrency (non-4k) | 4k: 15 RPM / 1 concurrency |

## 4. Service tiers

`service_tier` parameter:
- **`default`**: standard online inference, queue-prioritized for minimal latency. Required for real-time user-facing apps.
- **`flex`**: offline/batch inference during off-peak periods. Higher TTFT, but **50% discount**. Best for bulk asset generation, longitudinal analytics, overnight rendering.
- **Caveat**: Seedance 2.0 mandates online inference — `flex` is NOT supported for it (widely used in text and legacy image/video models). Seedance 1.5 Pro and 1.0 Pro *do* support `flex` (TPD-quota'd).

## 5. AI Savings Plans

- Up to **42% discount** for committed usage terms.
- Cover broad categories: most LLMs (Dola-Seed-2.0, Skylark-pro) and multimedia models (Dola-Seedream-5.0-lite, ByteDance-Seedance-1.5-pro).
- Unified management in Billing Center; rolling credits — up to **20% of unused monthly commitment rolls over** to the next billing period.
- **Seedance 2.0 resource packs** are a separate, prepaid mechanism (90-day validity, per-model): base 2.0 requires a minimum of 7× 1M-token packs; Fast/Mini have their own minimums. Packs deduct online-inference tokens before pay-as-you-go kicks in.

## 6. Billing cycle (near real-time vs hourly)

BytePlus is migrating most model-service billing from **hourly** to **near real-time** billing (rolled out in batches **Mar 6 – Mar 31, 2026, UTC+8**; service is unaffected during migration). Billing time is whatever the system actually records.

| | Hourly (legacy) | Near real-time (upgraded) |
|---|---|---|
| Bill cadence | one bill per hour | one bill **per 5-minute** cycle |
| Bill latency | ~1–2 h after the cycle ends | ~5–10 min after the cycle ends |
| Example | 16:00–17:00 bill issued 18:00–19:00 | 16:00–16:05 bill issued 16:10–16:15 |

Per billing item:

| Service / item | Billing method | Cycle |
|---|---|---|
| Online inference — input, output, **cache hit** | pay-as-you-go / token | **near real-time** |
| Online inference — **cache storage** | pay-as-you-go / token | **hourly** |
| Model unit | see Model Unit billing | see Model Unit billing |
| Batch inference — input, output, cache hit | pay-as-you-go / token | **near real-time** |
| Fine-tuning | paid by **compute** | **hourly** |

So: cache *hits* bill near-real-time, but cache *storage* and fine-tuning stay hourly.

## 7. Grounded prices (embedding & Knowledge Base)

These per-item prices ARE grounded (from the Billing docs). Core LLM chat, Seedream image, and Seedance 1.x/1.0 per-token prices were **not** in the supplied docs — leave those as "see Billing" until provided. Seedance 2.0 pricing lives in video-seedance.md; 3D pricing in 3d-generation.md.

**Skylark Embedding Vision (per input tokens):**
- text → **$0.000125 / 1K tokens**
- image → **$0.000325 / 1K tokens**

(These are the Skylark-embedding-vision text/image token rates as billed in the Knowledge Base; confirm they match the standalone `/embeddings/multimodal` line item on the Billing page.)

**Knowledge Base (RAG product — pay-as-you-go, hourly compute):** ModelArk also offers a managed Knowledge Base / RAG service (not a "model," so not in the catalog). Grounded price list:

| Item | Measure | Unit price |
|---|---|---|
| `standard_compute_knowledge` (Standard) | per Knowledge Base | **$0.0416 / hour** |
| `compute_knowledge` (Pro) | per CU (`max(CPU cores, mem/8GB)`) | **$0.25 / hour** |
| `rerank_knowledge` | input tokens | **$0.00004 / 1K** |
| `parser_basic_knowledge` | doc pages | **$10 / 1K pages** |
| `text_embedding_knowledge` | input tokens | **$0.00015 / 1K** |
| `text_embedding_multifunctional_knowledge` (dense+sparse) | input tokens | **$0.00015 / 1K** |
| `Skylark-embedding-vision-text_knowledge` | input tokens | **$0.000125 / 1K** |
| `Skylark-embedding-vision-image_knowledge` | input tokens | **$0.000325 / 1K** |
| VLM/LLM used inside KB | — | "Follow Ark" (standard model pricing) |

KB gotchas: uploading documents **immediately reserves compute and starts hourly billing**; deleting documents does **not** free the resources — you must delete the whole Knowledge Base to stop charges. Compute autoscales with data volume; multiple vector-model combos bill separately.

## 8. Model deprecation lifecycle

BytePlus maintains a Deprecation Timetable in structured stages:
1. **First Notification**
2. **Deprecation Date** — no new endpoints can be created
3. **Deactivation Date** — API stops responding

Example (March 2026 cycle): `seedream-3-0-t2i` and `seedance-1-0-lite` phased out.

**Automated Replacement** may silently route deprecated-model calls to a successor (e.g. `seedream-3-0` → `seedream-5-0-lite`). Convenient but risky: capabilities, parameter requirements, and pricing differ across versions — run evaluation testing before the Deactivation Date to avoid production outages. Always pin exact date-suffixed model IDs so a version rollover never surprises you.
