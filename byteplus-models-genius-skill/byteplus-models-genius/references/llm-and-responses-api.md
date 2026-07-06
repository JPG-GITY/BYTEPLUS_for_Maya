# Dola Seed 2.0 LLMs & the Responses API

## Contents
1. Model taxonomy & the full LLM catalog
2. Deep reasoning control parameters
3. Reasoning summary & encrypted thinking
4. Coding plan & IDE integration
5. Chat API vs Responses API (stateful architecture)
6. Context caching
7. Context editing & window truncation
8. MCP tool use
9. Structured outputs
10. Prefill-based response
11. Multimodal understanding (image / video / audio / document)

---

## 1. Model taxonomy & the full LLM catalog

**Dola Seed 2.0** is the flagship general-purpose agentic LLM series — built for complex reasoning and long-chain, multi-step task execution. All Seed 2.0 variants carry a **256K context window** and are rated **30K RPM / 1.5M TPM** (the highest tier in the catalog).

Key Seed 2.0 IDs (note the date-suffixed versioning — always pin an exact ID):

- `seed-2-0-pro-260328` — flagship agentic node. Deep Reasoning + Text Gen + Multi-modal Understanding + **Tool Calling** (adds Visual Grounding in the vision path).
- `seed-2-0-lite-260428` / `seed-2-0-mini-260428` — latest Lite/Mini; Deep Reasoning + Text Gen + Multi-modal + Function Calling. **These two are the only models that also do Audio Understanding.**
- `seed-2-0-lite-260228` / `seed-2-0-mini-260215` — prior Lite/Mini; add **Structured Output**.
- `seed-2-0-code-preview-260328` — dedicated code model (Deep Reasoning + Text Gen + Multi-modal + Function Calling). *This is the correct code ID — there is no `dola-seed-2.0-code` / `bytedance-seed-code`.*

Seed 2.0 default output is 4K tokens; Max Output incl. CoT is **128K**, Max CoT **128K**.

### Full catalog (all `ap-southeast-1`; context/limits in tokens)

| Model ID | Context | Max Input | Max Output (incl CoT) | RPM / TPM | Notes |
|---|---|---|---|---|---|
| `seed-2-0-pro-260328` | 256K | 224K* | 128K | 30K / 1.5M | Tool Calling, Visual Grounding, MCP |
| `seed-2-0-lite-260428` | 256K | 256K | 128K | 30K / 1.5M | + Audio Understanding |
| `seed-2-0-mini-260428` | 256K | 256K | 128K | 30K / 1.5M | + Audio Understanding |
| `seed-2-0-lite-260228` | 256K | 256K | 128K | 30K / 1.5M | + Structured Output |
| `seed-2-0-mini-260215` | 256K | 256K | 128K | 30K / 1.5M | + Structured Output, Visual Grounding |
| `seed-2-0-code-preview-260328` | 256K | 256K | 128K | 30K / 1.5M | code model |
| `seed-1-8-251228` | 256K | 224K | 64K | 30K / 1.5M | Multi-modal + Structured Output; Max CoT 32K |
| `glm-5-2-260617` | **1024K** | 1024K | 128K | **0.5K** / 1000K | very low RPM — batch, not high-QPS. Supports `xhigh`/`max` effort |
| `glm-4-7-251222` | 256K | 224K | 128K | 15K / 1.5M | text + function calling |
| `deepseek-v4-pro-260425` | **1024K** | 1024K | **384K** | 15K / 1.5M | huge output ceiling |
| `deepseek-v4-flash-260425` | **1024K** | 1024K | **384K** | 15K / 1.5M | cheaper flash tier |
| `deepseek-v3-2-251201` | 128K | 128K | 32K | 15K / 1.5M | + Structured Output |
| `gpt-oss-120b-250805` | 128K | 96K | 64K | 15K / **800K** | Max CoT 32K |
| `seed-1-6-250915` | 256K | 224K | 32K | 15K / 800K | Image+Video Understanding, Structured Output |
| `seed-1-6-250615` | 256K | 224K | 32K | 15K / 800K | + Visual Grounding |
| `seed-1-6-flash-250715` | 256K | 224K | 32K | 15K / 800K | + Visual Grounding (see §9 caveat) |
| `seed-1-6-flash-250615` | 256K | 224K | 32K | 15K / 800K | Image+Video Understanding |

\*Pro's Max Input shows 256K in some tables and 224K in the Text-Generation table — treat 224K as the safe planning number.

**Regions:** every listed model runs in `ap-southeast-1`; **only `seed-2-0` models and `seedream-5-0-lite` are also in `eu-west-1`.** Match the base URL to the region (see enterprise-ops.md).

## 2. Deep reasoning control parameters

Native, programmatic Chain-of-Thought control (no "think step by step" prompt hacks needed):

| Parameter | Valid values | Effect |
|---|---|---|
| `thinking.type` | `enabled`, `disabled`, `auto` | `enabled` = always reason first (default on Seed 2.0). `disabled` = immediate direct output, drastically lower TTFT for simple tasks. `auto` = model decides per-request; skips reasoning on easy questions. |
| `reasoning.effort` | `minimal`, `low`, `medium` (default), `high`, `xhigh`, `max` | CoT compute budget. `minimal` turns reasoning **off** (answers directly). `low` favors speed, `medium` balances, `high` forces exhaustive analysis. `xhigh` / `max` are **only honored by `glm-5-2-260617`** — ignored elsewhere. |
| `max_output_tokens` (Responses) / `max_completion_tokens` (Chat) | integer | Caps CoT + answer combined; overrides the legacy 4K `max_tokens`. Can't be set together with `max_tokens` (errors). |

Interaction: with `thinking.type=disabled`, `reasoning.effort` only accepts `minimal` (any of low/medium/high errors). `glm-5-2` defaults to `max`; if you pass `minimal` it turns reasoning off, `low`/`medium`→treated as `high`, `xhigh`→`max`.

Cost-efficiency multiplexing: route intent-classification through `minimal`, then invoke `seed-2-0-pro-260328` at `high` for hard troubleshooting.

## 3. Reasoning summary & encrypted thinking

Supported by `seed-2-0-lite-260428` / `seed-2-0-mini-260428` / `seed-2-0-pro-260328`:

- **Reasoning summary is on by default** — the API returns a *summary* of the chain-of-thought rather than the raw CoT. `usage.output_tokens_details.reasoning_tokens` still bills the raw CoT length. Expect higher inter-packet latency; raise your request timeout.
- **Encrypted CoT**: add `"include": ["reasoning.encrypted_content"]` to get `encrypted_content` back. To carry thinking across tool-call turns, either pass `previous_response_id` (recommended) or send `encrypted_content` back verbatim — any tampering breaks restoration.

## 4. Coding plan & IDE integration

The ModelArk Coding Plan integrates code models into Claude Code, TRAE, Cursor, Roo Code, Cline, OpenCode.

Base URLs (critical — the wrong one bypasses Coding Plan quotas and incurs standard, potentially higher, API charges):
- Anthropic-protocol tools: `https://ark.ap-southeast.bytepluses.com/api/coding`
- OpenAI-compatible tools: `https://ark.ap-southeast.bytepluses.com/api/coding/v3`
- Standard data plane (NOT for coding plan): `/api/v3`

Model choices in tool config include `seed-2-0-code-preview-260328`, `glm-5-2`, `glm-4-7`, `deepseek-v3-2`, `gpt-oss`, or an `Auto` mode that picks the optimal model per scenario. Coding Plan is a subscription (Lite / Pro tiers); the wrong base URL silently drops out of the plan.

## 5. Chat API vs Responses API

- **Chat API** (`/chat/completions`): stateless. Client resends the full `messages` history every request → payload grows with session depth.
- **Responses API** (`/responses`): stateful, server-side context storage **enabled by default** (`store: true`). Returns a Response object with a unique ID; subsequent requests pass `previous_response_id` instead of history. Simplifies client code, cuts network overhead, avoids context truncation.
  - **Storage lifecycle**: kept **3 days** by default, max 7 days via `expire_at`. Up to 1000 stored items per chain; delete items to prune the window. CoT is not stored; `store` is currently free.
  - **`instructions` field** supplements the system prompt for one turn — but **disables caching**: a request with `instructions` neither writes nor hits the cache.

Only the Responses API supports MCP tools and (on 250615+ models) context caching. New models 250615+ support the Responses API by default.

## 6. Context caching (Responses API)

Governed by the `caching` object, e.g. `caching={"type": "enabled", "prefix": True}`. Two modes; some models also have implicit cache.

**Prefix caching**: a large fixed prefix (e.g., a policy document in the system prompt) is prefilled once and stored; later requests skip the prefill phase → ~80% cheaper cached-input tokens and faster responses. **Requires ≥256 tokens** to create (else errors); can't be created with `stream:true`.

**Session caching**: the Responses API auto-stores conversation context; pass `previous_response_id` to reuse cached input across turns.

**Billing**: cached input is billed at the discounted rate; newly added (uncached) context bills as normal input; a per-natural-hour **storage fee** applies to session caches (any fraction of an hour rounds up). `usage.prompt_tokens_details.cached_tokens` reports the hit. Delete a mid-chain response and subsequent turns recompute (and re-bill) that content.

## 7. Context editing & window truncation

`context_management.edits` (beta) on `seed-2-0-pro-260328` / `seed-2-0-lite-260228` / `seed-2-0-mini-260215` / `seed-2-0-code-preview-260328` / `seed-1-8-251228`:

- `clear_thinking` — drops older CoT; `keep` controls how many recent thinking turns survive (`{"type":"thinking_turns","value":N}` or `"all"`).
- `clear_tool_uses` — drops old tool-call content once a `trigger` (`tool_uses` count) fires; `keep`, `exclude_tools`, and `clear_tool_input` refine it.
- Combined: list `clear_thinking` **before** `clear_tool_uses`.

Window truncation without context editing: use the Responses **delete** API to prune specific responses from the stored chain.

## 8. MCP tool use (Responses API)

Chat API supports only classic Function Calling (model emits JSON schema; client executes locally). The Responses API natively integrates the **Model Context Protocol (MCP)**.

```json
"tools": [
  {
    "type": "mcp",
    "server_label": "enterprise_wiki",
    "server_url": "https://mcp.internal.enterprise.com/mcp",
    "require_approval": "never",
    "headers": {"Authorization": "Bearer <token>"}
  }
]
```

Requires header `extra_headers={"ark-beta-mcp": "true"}`. Function-calling schema (Responses form) is flat: `{"type":"function","name":...,"description":...,"parameters":{...}}` — note this differs from the Chat API, which nests everything under a `"function"` object.

## 9. Structured outputs

Responses API — define the schema under **`text.format`** (flat, not nested under `json_schema`):

```json
"text": {
  "format": {
    "type": "json_schema",
    "name": "math_reasoning",
    "strict": true,
    "schema": { "type": "object", "properties": { ... }, "required": [...], "additionalProperties": false }
  }
}
```

`json_object` mode (valid JSON, no schema enforcement): `"text": {"format": {"type": "json_object"}}`. Chat API uses `response_format` instead. `json_schema` is the recommended, strict-mode-capable successor to `json_object`.

Supported (beta): `seed-2-0-lite-260228`, `seed-2-0-mini-260215`, `seed-1-8-251228`, `deepseek-v3-2-251201`, and the `seed-1-6` family. **Caveat:** the structured-output tutorial states `seed-1-6-flash-250715` does **not** support structured output despite appearing in the capability table — verify before relying on it.

## 10. Prefill-based response

Guide the model to continue from preset assistant text: set the last `input` message `role:"assistant"` with `"partial": true`. The model continues from that content.

Supported: `seed-2-0-pro-260328`, `seed-2-0-lite-260228`, `seed-2-0-mini-260215`, `seed-2-0-code-preview-260328`, `seed-1-8-251228`. Not compatible with structured output; discouraged with built-in tools; prefix/session caching works (with prefill, the assistant `content` seeds the continuation).

## 11. Multimodal understanding

Seed 2.0 models accept **images, video, PDF documents**; `seed-2-0-lite-260428` / `seed-2-0-mini-260428` additionally do **audio**. Same Responses/Chat endpoints; input via file path (Files API, ≤512 MB, recommended), Base64 (≤10 MB image / ≤50 MB audio; body ≤64 MB), or URL (≤10 MB image / ≤50 MB audio-video).

- **Image detail**: `detail` (`low`/`high`/`xhigh`) or the higher-priority `image_pixel_limit` (`{min_pixels,max_pixels}`) controls tokens/precision. Seed 2.0 default `detail` = `high`, fixed 1280 tokens/image; image tokens ≈ `w*h/1764`.
- **Video**: `fps` (0.2–5, default 1) sets frame-sampling density; each sampled frame is prefixed with a `[<t> second]` timestamp so the model reasons about timing. Max 80K tokens per video.
- **Audio**: ~6.25 tokens/second; embedded audio tracks in video are auto-extracted (ASR, translation, diarization, caption). 19 ASR languages / 15 AST language pairs.
