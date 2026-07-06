# Audio Generation (Seed Audio 1.0 — TTS / voice synthesis)

Text-to-speech / audio synthesis on BytePlus. **This is audio *generation* (TTS), not the audio *understanding*/ASR that `seed-2-0-lite/mini` do** — different capability, different endpoint, different host.

## Contents
1. Model & activation
2. Endpoint & host (⚠️ not the `ark.*` host)
3. Authentication (two mutually-exclusive modes)
4. Request body & generation modes
5. Reference rules & limits
6. Audio configuration
7. Response shape & billing
8. Examples
9. Constraints & gotchas

---

## 1. Model & activation

- **Model ID:** `seed-audio-1.0` (currently the only supported model).
- **Activate:** BytePlus console → Voice → `https://console.byteplus.com/voice/new/setting/activate?projectName=default` → find **"Seed-Audio 1.0"** → activate → collect API key.

## 2. Endpoint & host

| Item | Value |
|---|---|
| Protocol | HTTPS |
| Method | POST |
| URL | `https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create` |
| Content-Type | `application/json` |
| Output limit | up to **120 seconds** of generated audio per request |

⚠️ **Host gotcha:** Seed Audio uses the **`voice.ap-southeast-1.bytepluses.com`** host, NOT the `ark.ap-southeast.bytepluses.com` host the LLM/image/video/3D/embedding APIs use. Don't reuse the ARK base URL here.

## 3. Authentication (choose ONE mode per request)

**⭐ Recommended — new console API key (single header):**

| Header | Required | Description |
|---|---|---|
| `X-Api-Key` | Yes | API Key from the Volcengine Speech console |
| `X-Api-Request-Id` | No | Client-side trace ID (internal TraceID or UUID) for troubleshooting |

**Legacy console — App ID + Access Key (two headers):**

| Header | Required | Description |
|---|---|---|
| `X-Api-App-Id` | Yes | Application ID from the legacy console |
| `X-Api-Access-Key` | Yes | Access key from the legacy console |
| `X-Api-Request-Id` | No | Client-side trace ID |

Use only one mode per request — do not mix.

## 4. Request body & generation modes

| Field | Type | Required | Description |
|---|---|---|---|
| `model` | string | Yes | `seed-audio-1.0` |
| `text_prompt` | string | Yes | Prompt / text to synthesize. **Max 2048 characters.** |
| `references` | array | No | Reference resources. **Omit for text-only generation.** |
| `audio_config` | object | No | Output audio configuration (see §6) |
| `watermark` | object | No | Watermark config; an **empty object `{}` is accepted**. |

**Three generation modes:**
- **Text-only** — omit `references`. Audio is generated purely from `text_prompt`.
- **Audio-reference** — provide audio via `speaker`, `audio_data`, or `audio_url`. Refer to reference items *by order* in `text_prompt` using **`@Audio1`, `@Audio2`, `@Audio3`**.
- **Image-reference** — provide one image via `image_data` or `image_url`. `text_prompt` contains only the text to synthesize.

## 5. Reference rules & limits

Each reference item picks exactly one source field:

| Field | Meaning | Mutual exclusion |
|---|---|---|
| `speaker` | Voice ID — a supported Doubao TTS voice or a voice-clone voice ID | one of `speaker` / `audio_data` / `audio_url` |
| `audio_data` | Base64-encoded reference audio | one of `speaker` / `audio_data` / `audio_url` |
| `audio_url` | URL of a remote reference audio file | one of `speaker` / `audio_data` / `audio_url` |
| `image_data` | Base64-encoded reference image | one of `image_data` / `image_url`; **cannot mix with audio refs** |
| `image_url` | URL of a remote reference image | one of `image_data` / `image_url`; **cannot mix with audio refs** |

**Limits:**
- Audio references: **up to 3** per request. Each audio file **≤ 30 s and ≤ 10 MB**. Formats: `wav`, `mp3`, `pcm`, `ogg_opus`.
- Image references: **only 1** per request. **≤ 10 MB**. Formats: `jpeg`, `png`, `webp`.
- **Image references cannot be mixed with audio references** in the same request.

## 6. Audio configuration (`audio_config`)

| Field | Type | Default | Allowed values / range |
|---|---|---|---|
| `format` | string | `wav` | `wav`, `mp3`, `pcm`, `ogg_opus` |
| `sample_rate` | int | `24000` | 8000, 16000, 24000, 32000, 44100, 48000 |
| `speech_rate` | int | `0` | −50 to 100 (100 = 2.0× speed; −50 = 0.5× speed) |
| `loudness_rate` | int | `0` | −50 to 100 (100 = 2.0× volume; −50 = 0.5× volume) |
| `pitch_rate` | int | `0` | −12 to 12 |

## 7. Response shape & billing

**Response headers:** `X-Tt-Logid` — server-side LogID; provide it when reporting/troubleshooting.

**Response body:**

| Field | Type | Description |
|---|---|---|
| `code` | int | Status code (see official error-code doc) |
| `message` | string | Status details |
| `audio` | string | Generated audio, **Base64-encoded** |
| `duration` | float | Duration after speed/post-processing, seconds |
| `original_duration` | float | Original model output duration (s) — **used for billing, capped at 120 s** |
| `url` | string | Temporary audio URL — **valid for 2 hours** per the official doc |

> **Billing basis:** billed on `original_duration` (capped at 120 s), i.e. per second of generated audio. Per-second price was NOT in the supplied doc — see Billing / request the rate.

## 8. Examples

**Minimal (text-only) cURL:**
```bash
curl --request POST \
  --url 'https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create' \
  --max-time 120 \
  --header 'Content-Type: application/json' \
  --header 'X-Api-Key: your_api_key' \
  --data-raw '{
    "model": "seed-audio-1.0",
    "text_prompt": "Generate a short suspense radio drama in a late-night convenience store.",
    "audio_config": {"format": "mp3", "sample_rate": 48000, "pitch_rate": 0, "speech_rate": 0, "loudness_rate": 0},
    "watermark": {}
  }'
```

**Audio-reference (note the `@Audio1` mention aligned with the first reference):**
```json
{
  "model": "seed-audio-1.0",
  "text_prompt": "Use @Audio1 as the narrator voice and read the following line naturally: Welcome to the store.",
  "references": [{"audio_url": "https://example.com/reference.mp3"}],
  "audio_config": {"format": "wav", "sample_rate": 24000, "speech_rate": 0, "loudness_rate": 0, "pitch_rate": 0},
  "watermark": {}
}
```

**Image-reference:**
```json
{
  "model": "seed-audio-1.0",
  "text_prompt": "Read this scene description in a restrained suspense style.",
  "references": [{"image_url": "https://example.com/reference.png"}],
  "audio_config": {"format": "wav", "sample_rate": 24000, "speech_rate": 0, "loudness_rate": 0, "pitch_rate": 0},
  "watermark": {}
}
```

**Python (decode Base64 → file):**
```python
import base64, requests
url = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create"
headers = {"Content-Type": "application/json", "X-Api-Key": "your_api_key"}
payload = {
    "model": "seed-audio-1.0",
    "text_prompt": "Generate a short suspense radio drama in a late-night convenience store.",
    "audio_config": {"format": "wav", "sample_rate": 24000, "speech_rate": 0, "loudness_rate": 0, "pitch_rate": 0},
    "watermark": {},
}
resp = requests.post(url, headers=headers, json=payload, timeout=120)
resp.raise_for_status()
data = resp.json()
if "audio" in data:
    with open("output.wav", "wb") as f:
        f.write(base64.b64decode(data["audio"]))
```

## 9. Constraints & gotchas

- **Wrong host** — must use `voice.ap-southeast-1.bytepluses.com`, not the ARK host.
- **≤ 2048 characters** in `text_prompt`; for long scripts/audiobooks, split into chunks and stitch outputs.
- **`@AudioN` ordering** must match the order of items in `references` — mis-ordering swaps voices.
- **Never mix** image references with audio references in one request.
- The returned `url` is **temporary (2 h)** — persist the Base64-decoded audio if you need long-term storage.
- **Voiceprint safety:** if the API returns a sensitive voiceprint / voice-clone error, simplify the voice description and avoid references to real or distinctive real-person voices.
- **Never hard-code API keys**; log request/response metadata for troubleshooting but **redact auth headers**.
- Set client timeout to ~120 s (matches the max output length).
