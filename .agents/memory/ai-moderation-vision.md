---
name: AI moderation vision model (StepFun) design decisions
description: How profile-picture/nickname and in-chat media moderation is scoped in PRD.md Bagian 23 — check before building vision_scan.py or extending context_builder.py for media
---

## Decisions (confirmed with user, not to be re-litigated)

- **Provider/model**: Kilo AI Gateway is OpenAI-compatible (chat-completions shape, not Anthropic Messages API). Vision model is StepFun `stepfun-ai/step-3.7-flash` (native multimodal, supports both image and video), used through the same gateway/base URL as the text model.
- **Separate model, not a replacement**: text moderation keeps using the text model (`AI_MODEL`, Nemotron free tier) for all messages. The vision model (`AI_VISION_MODEL`) is only invoked when a message/profile actually carries an image or video — never for text-only traffic.
- **Profile picture / nickname check**: periodic scheduled job (every 24h, not on join/on-change/real-time) scans all members of `ai_moderation_enabled` groups. User explicitly chose periodic over per-event to keep cost predictable.
- **Dedup requirement (my addition, user said "up to you")**: cache each user's last-checked `photo.*_file_unique_id` in Redis (~25h TTL) and skip the vision call entirely if the profile photo hasn't changed since the last scan — without this, every 24h scan re-analyzes every member's unchanged photo.
- **In-chat media**: photos/videos sent in messages ARE analyzed by vision too (not just captions) — user explicitly confirmed this, it was not a default assumption.
- **Cost/size guard (my addition)**: videos over 20MB or 60s skip vision analysis and fall back to text/caption-only evaluation, to avoid disproportionate token cost and requests that would exceed the 15s AI timeout.
- **Rate limiting**: vision calls share the same cooldown/global-hourly-cap limiter as text calls (Bagian 14) — no separate budget for vision.
- **Failure handling**: any vision call failure (timeout, unsupported format, API error) falls back to text/caption-only evaluation; it never blocks the overall message evaluation.

**Why:** the original PRD only marked `nickname-pfp` as "Tidak — butuh inspeksi visual" (human-only). The user later decided a vision-capable model makes it AI-enforceable after all, which required a genuinely new architecture section rather than a one-line edit.

**How to apply:** before writing `vision_scan.py`, `context_builder.py` media handling, or `ai_client.py` vision request formatting, read PRD.md Bagian 23 in full — it has the confirmed config keys (`AI_VISION_MODEL`, `AI_PFP_SCAN_INTERVAL_HOURS`, `AI_VISION_MAX_VIDEO_MB/SECONDS`) and the two still-open verification items (Telegram API throttling for per-member `get_chat` scans; exact image/video request format on Kilo's gateway for StepFun — do not assume it's byte-identical to OpenAI's `image_url` content-part without checking Kilo/StepFun docs directly at implementation time).
