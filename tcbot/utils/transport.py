# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Shared Telegram transport tuning for every runtime entry point."""

from __future__ import annotations

# * HTTP timeout values for the PTB ApplicationBuilder (seconds).
# * Raised for Replit: first getMe() response can take >15s on this network.
HTTP_READ_TIMEOUT: int = 60
HTTP_WRITE_TIMEOUT: int = 30
HTTP_CONNECT_TIMEOUT: int = 30
HTTP_POOL_TIMEOUT: int = 15

# * Connection pool size for the underlying httpx client (API calls).
# * Not used for update fetching in webhook mode; still needed for send/edit/etc.
# * Sized above the fan_out cap (10): one full fan-out plus concurrent
# * handler traffic must never queue on pool exhaustion.
API_POOL_SIZE: int = 16
