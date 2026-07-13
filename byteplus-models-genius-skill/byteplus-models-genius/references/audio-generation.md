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
| `text_prompt` | string | Yes | Prompt / text to synthesize. **Max 3000 characters.** |
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
- **≤ 3000 characters** in `text_prompt`; for long scripts/audiobooks, split into chunks and stitch outputs.
- **`@AudioN` ordering** must match the order of items in `references` — mis-ordering swaps voices.
- **Never mix** image references with audio references in one request.
- The returned `url` is **temporary (2 h)** — persist the Base64-decoded audio if you need long-term storage.
- **Voiceprint safety:** if the API returns a sensitive voiceprint / voice-clone error, simplify the voice description and avoid references to real or distinctive real-person voices.
- **Never hard-code API keys**; log request/response metadata for troubleshooting but **redact auth headers**.
- Set client timeout to ~120 s (matches the max output length).

---

## 10. T2A & TA2A — prompt-driven audio + multi-role conversation (Audio 1.0's killer features)

Beyond plain TTS and voice cloning, Audio 1.0 adds two **prompt-driven** modes no normal TTS has — the reason to use it for **audiobooks, video dubbing and games**.

| Mode | You pass | You get |
|---|---|---|
| **T2A** (Text-prompt → Audio) | a rich `text_prompt` describing voices + environment + background music + SFX + the lines — **no references** | the model generates **voice(s) + music + sound effects together**, in one shot |
| **TA2A** (Text-prompt + Audio → Audio) | the same rich prompt **plus up to 3 reference clips** (≤30 s each) for voice identity/emotion | same, but specific characters use the **referenced voices** |

**Multi-role conversation in ONE prompt.** Write the whole script inline with a short voice description before each character's line; the model performs **all roles** with distinct voices and accurate emotion — no need to synthesize each line separately. This is what makes it ideal for dialogue/dubbing.

### T2A prompt structure (include all five)
1. **Environment** — weather / location / context ("after-school hallway, distant footsteps, locker clacks, reverb").
2. **Background music / SFX** — genre + instruments + ambient sounds ("gentle jazz piano, brushed drums, accordion").
3. **Character action / appearance** — (waving hands, playing soccer…).
4. **Character voice** — gender / age / accent / emotion / tone / speed ("teenage male, American accent, bright, cocky").
5. **The lines** — what each character says.

> **Language rule:** keep the **prompt language == script language**. Prompt-driven generation (T2A/TA2A) currently supports **English & Chinese** (more languages by end of July 2026). The preset **TTS2.0 `speaker` voices** (see the voicelist) cover many more languages (ES/MX, FR, DE, JA, KR, ID, PT…) — use `speaker` for those.

### TA2A — binding a reference clip to a character
Tag which reference each character uses with either **`@Audio1` / `@Audio2` / `@Audio3`** (in upload order) or the **`<<TGT_SPK1>>` / `<<TGT_SPK2>>` / `<<TGT_SPK3>>`** token inside the line, e.g. *"Marcus (smooth confident broadcaster, the actor is `<<TGT_SPK1>>`) says: …"*. Reference clips can be **uploaded per request OR pulled from the asset library** (`asset://…` audio assets).

### Example — short multi-role T2A (voice + SFX in one prompt)
> School bell "ring-a-ling" fading, after-school hallway with distant chatter and locker "clack". **Jake** (teenage male, American accent, bright, cocky) says playfully: "Hey, Emma—you free Saturday? My treat, that new amusement park!" A backpack zipper "zzzip." **Emma** (teenage female, sweet soft airy, shy) lowers her voice, flustered: "Uh… I still haven't finished my homework." Jake coaxes: "You can do it Sunday~ it's just half a day!" … Ends with both footsteps fading away.

## 11. Ideal use cases
- **Audiobook** — T2A/TA2A generate narration + character voices + SFX, no human recording (~1/10 the cost).
- **Video dubbing** — describe the voice OR upload a **character image** (image-reference) to derive the voice; generate voice + SFX + music together. Pairs with Seedance `reference_audio` (`asset://`).
- **Gaming** — character lines and environmental SFX for immersive scenes.
- **Pricing:** $0.15/min of generated audio (billed per second).
