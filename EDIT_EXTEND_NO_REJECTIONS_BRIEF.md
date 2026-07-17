# Seedance 2.0 — Edit Video & Extend WITHOUT face rejections (integration brief)

**Hand this to the other Claude.** It is framework-agnostic (Maya / Blender / Houdini /
standalone) — it's about the BytePlus Seedance API mechanics, not the DCC.

If Edit-video or Extend keeps getting a face rejection (`SensitiveContent`,
`InputImageSensitiveContentDetected.PrivacyInformation`, "real person", biometric),
you are almost certainly **breaking the trusted-output chain**. Read the ROOT CAUSE,
then run the CODE-REVIEW CHECKLIST — the bug is one of those 3 lines.

---

## ROOT CAUSE (read this first)

Seedance's moderation rejects **real human faces** as input references. An **AI-generated**
face is only *exempt* when the input you send is **byte/URL-identical to a fresh Seedance /
Seedream OUTPUT from the same account, passed through UNTOUCHED**.

The exemption is **stripped** the instant you do ANY of these to that output:
1. **Re-host it** — download the clip/frame and upload it to *your own* storage (R2 / TOS /
   S3 / a signed URL). The new URL ≠ Seedance's output URL → treated as an external face → **rejected**.
2. **Re-encode / transcode it** — ffmpeg re-mux, resize, change container/codec. Different bytes → trust lost.
3. **Self-extract a frame** — grabbing the "last frame" yourself with ffmpeg produces an
   *untrusted* image. Even if visually identical, it is not Seedance's signed output → **rejected**.

So the #1 reason your app loops: **for Edit/Extend you are re-uploading the local file or
self-extracting a frame**, instead of reusing the ORIGINAL URLs Seedance already gave you.

---

## THE 5 GOLDEN RULES

1. **At generation time, request and SAVE the trusted URLs.** In the create-video request set
   `return_last_frame: true`. In the result, Seedance returns:
   - `content.video_url` — the clip's own trusted URL (valid ~24 h)
   - `content.last_frame_url` — a watermark-free trusted PNG of the last frame (valid ~24 h)

   Save BOTH next to your local file (a sidecar JSON: `{ "url": ..., "ts": <epoch> }`).
   Without this you have nothing trusted to reuse later — this is the usual missing piece.

2. **Reuse the ORIGINAL URL — never a re-hosted copy.**
   - **Edit video** (video-to-video): send the saved `video_url` as the `reference_video`.
   - **Extend**: send the saved `last_frame_url` as the `first_frame`.

3. **Pass-through, don't touch.** Any input that is already an `http(s)://` URL or an
   `asset://<id>` MUST be sent to the API **unchanged**. Never download→re-upload it, never
   re-encode it, never base64 a re-hosted copy. (Local file paths are the ONLY thing you may
   upload — and a local file with a face has no exemption.)

4. **24 h expiry → use the permanent asset library.** Those trusted URLs die in ~24 h. After
   that, re-hosting fails the face again. The permanent fix is the **Private Trusted Asset
   Library** (a.k.a. digital characters): upload the character once via `CreateAsset` → get a
   permanent `asset://<id>` that Seedance trusts forever. Pass `asset://<id>` through untouched.

5. **Never hardcode "HUMAN FACE" in your error.** Moderation false-positives happen (mirrors,
   reflections, a bathroom clip with no faces). Surface the REAL API error code/message.
   And **do NOT auto-retry a face rejection** — it is deterministic within a session (if the
   exemption isn't honored, every retry fails identically and wastes attempts). Only retry
   TRANSIENT (network/DNS/timeout) errors.

---

## STEP-BY-STEP — EDIT VIDEO (video-to-video)

Goal: transform a clip while keeping its subject/motion/camera, no face rejection.

1. Look up the clip's saved `video_url` (from rule 1). Check it's **fresh** (`now - ts < 24h`).
2. **If fresh** → build a multimodal request:
   ```
   content = [
     { "type":"text", "text": "<edit prompt: keep motion & camera, change only X>" },
     { "type":"video_url", "role":"reference_video", "video_url": { "url": <saved video_url> } }
   ]
   ```
   Send `video_url` **as-is** — no download, no re-upload, no transcode. The face stays trusted.
3. **If NOT fresh (or you never saved it)** → you have no trusted source. Options:
   - Re-generate the clip (new trusted URL), or
   - Accept that a clip WITH a face can't be edited (re-hosting will reject it). Clips WITHOUT
     faces (environments, objects, stylized) edit fine even when re-hosted.
4. The API returns a **silent** edit; re-mux the original clip's audio back if you want sound
   (that's a local ffmpeg step on the RESULT, it doesn't affect trust).
5. Also save the EDITED result's `video_url` so the edit can itself be edited (chain within 24 h).

---

## STEP-BY-STEP — EXTEND (continue past the length cap)

Goal: continue a clip; the new clip starts from the previous clip's last frame.

1. Look up the clip's saved `last_frame_url` (Seedance's OWN trusted PNG — NOT a self-extracted
   frame). Check freshness (< 24 h).
2. **If fresh** → mode-1 (first_frame):
   ```
   content = [
     { "type":"text", "text": "<what happens next>" },
     { "type":"image_url", "role":"first_frame", "image_url": { "url": <saved last_frame_url> } }
   ]
   ```
   Pass `last_frame_url` **as-is**. Because it's Seedance's own trusted output, the face is exempt.
3. **If you self-extract the last frame with ffmpeg → it WILL be rejected** if it contains a
   face. That is the trap. Only do local extraction for NO-FACE clips (and warn the user).
4. Save the new clip's own `video_url` / `last_frame_url` so it can be extended again (B→C).

---

## ADDING REFERENCE IMAGES (to lock a character's identity/look)

Useful when the face isn't visible in the frame and the model "invents" the look.

**CRITICAL — Seedance 2.0 has 3 MUTUALLY-EXCLUSIVE content modes; you cannot mix them:**
- Mode 1: `first_frame` (one image).
- Mode 2: `first_frame` + `last_frame` (two images).
- Mode 3: **multimodal** — 1–9 `reference_image` (+ ≤3 `reference_video`, ≤3 `reference_audio`).

Consequences:
- **Edit video** already uses `reference_video` → it's mode 3 → you CAN add `reference_image`.
  Add the character reference(s) as extra `reference_image` items. In the prompt, say
  "lock the character's identity/face/wardrobe to the reference image(s); keep the video's
  motion & camera."
- **Extend** uses `first_frame` → mode 1 → you **cannot** add `reference_image` in the same call.
  To add a character reference, **switch to mode 3**: put the trusted last frame as
  `reference_image` #1 and the character ref(s) as #2+, and describe it in text:
  "Continue seamlessly from Image 1 (the previous shot's final frame) as the start; keep the
  character consistent with the other reference image(s)." (Approximate start, but it works.)

**Reference-image trust rule (same chain):** a `reference_image` that contains a FACE must ALSO
be trusted — a fresh Seedream output URL or an `asset://<id>`. A face from a **local file** is
rejected. So for a face reference, use a fresh gallery URL or (best) a permanent `asset://`.

Reference-image / reference-video payload shapes:
```
{ "type":"image_url", "role":"reference_image", "image_url": { "url": <trusted url / asset://> } }
{ "type":"video_url", "role":"reference_video", "video_url": { "url": <trusted url> } }
```

---

## CODE-REVIEW CHECKLIST (find the bug — it's one of these)

Grep the Edit/Extend code paths and answer each:

- [ ] **Do you request `return_last_frame: true` and SAVE `content.video_url` +
      `content.last_frame_url` at generation time?** If not → you have nothing trusted to reuse.
      (This is the most common missing piece — fix it first.)
- [ ] **Edit video:** do you send the SAVED `video_url` as `reference_video`, or do you
      **upload the local .mp4** to your storage? If you upload → that's the rejection. Reuse the URL.
- [ ] **Extend:** do you send the SAVED `last_frame_url` as `first_frame`, or do you
      **ffmpeg-extract the last frame** yourself? Self-extract → rejection. Reuse the URL.
- [ ] **Do you re-encode/transcode** the clip before sending (resize, re-mux, codec change)?
      Any of these strips trust. Send the original URL untouched.
- [ ] **Does your "resolve input" helper ALWAYS download+re-upload?** It must PASS THROUGH any
      value that already starts with `http`/`https`/`asset://` UNCHANGED. Only local paths get uploaded.
- [ ] **Reference images:** are face refs trusted (fresh URL / `asset://`), or local files? Local
      face → rejected.
- [ ] **Mode check:** are you accidentally sending `first_frame` + `reference_image` together?
      That's an invalid mode and can fail or be ignored.
- [ ] **Freshness:** is the URL within ~24 h? If not, re-hosting will reject the face — use `asset://`.
- [ ] **Error handling:** do you hardcode "HUMAN FACE", or surface the real code? Do you retry a
      face rejection (waste) instead of only retrying network errors?

**The single most likely fix:** stop re-uploading / re-extracting for Edit & Extend; instead
save `video_url` + `last_frame_url` at generation and reuse them **verbatim** as
`reference_video` / `first_frame`. For anything older than 24 h or a persistent character, use a
permanent `asset://` from the trusted asset library.

---

### One-line mental model
> Seedance trusts **its own fresh outputs, passed back untouched.** The moment your code
> re-hosts, re-encodes, or self-extracts, the face becomes "a stranger" and gets blocked.
