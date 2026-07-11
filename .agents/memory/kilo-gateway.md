---
name: Kilo AI Gateway API shape and model IDs
description: Confirmed via docs research — API compatibility and model identifiers for the Kilo AI Gateway used by ai_moderation's ai_client.py
---

- Kilo AI Gateway (`https://api.kilo.ai/api/gateway`) is **OpenAI-compatible** (chat-completions request/response shape) — not Anthropic's Messages API. Build `ai_client.py` against the OpenAI request shape.
- Free text model: `nvidia/nemotron-3-ultra-550b-a55b:free` (NVIDIA Nemotron 3 Ultra, 550B total / 55B active MoE params).
- Vision-capable model: `stepfun-ai/step-3.7-flash` (StepFun Step 3.7 Flash) — native multimodal, supports both image and video input, used only for profile pictures / in-chat media, never for text-only calls.
- Models are addressed by a single `provider/model` string in the request body; switching models is a config change (`AI_MODEL` / `AI_VISION_MODEL`), not a code change.

**Why:** avoids re-researching gateway compatibility and re-guessing model IDs on a future session; the API key (`KILO_API_KEY`) itself lives in Replit Secrets, never in `config.env.example` or this file.

**How to apply:** when implementing or debugging `ai_client.py`, assume this shape/these IDs are correct as of 2026-07-11; re-verify against Kilo/StepFun docs only if requests start failing, since gateway model catalogs change over time.
