# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Short-name adapter over the immutable Configs dataclass."""

from __future__ import annotations

from .models import Configs


# ! Property names in _CfgAdapter are imported by every module; rename with caution.
class _CfgAdapter:
    """Thin adapter that exposes Configs fields with the short canonical names used by all modules."""

    def __init__(self, c: Configs) -> None:
        self._c = c

    @property
    def bot_token(self) -> str:
        """Telegram bot token from BOT_TOKEN."""
        return self._c.bot_token

    @property
    def initial_owner_id(self) -> int:
        """Telegram user ID of the initial Founder seeded on first startup."""
        return self._c.owner_id

    @property
    def community_name(self) -> str:
        """Display name for the community used in bot messages and logs."""
        return self._c.community_name

    @property
    def mongodb_uri(self) -> str:
        """MongoDB connection string from MONGODB_URI."""
        return self._c.mongodb_uri

    @property
    def db_name(self) -> str:
        """MongoDB database name (defaults to 'tcbot')."""
        return self._c.db_name

    @property
    def prefixes(self) -> list[str]:
        """List of command prefix characters (e.g. ['/', '!', '.'])."""
        return list(self._c.prefixes)

    @property
    def port(self) -> int:
        """Flask health-check / webhook server port as int; falls back to 5000 for invalid values."""
        return self._c.port_int

    @property
    def main_group(self) -> int:
        """Main community group chat ID, or 0 when unset."""
        return self._c.main_group_id

    @property
    def main_channel(self) -> int:
        """Announcement channel chat ID, or 0 when unset."""
        return self._c.main_channel_id

    @property
    def exec_group(self) -> int:
        """Staff/exec group chat ID, or 0 when unset."""
        return self._c.extend_group_id

    def is_primary_group(self, chat_id: int | None) -> bool:
        """Return True for the main/exec groups (never disconnect).

        Single source of truth for primary-group membership; every guard
        across connect, disconnect, maintenance, greeting, and workflow
        modules must use this instead of inline tuple checks.
        """
        if chat_id is None or chat_id <= 0:
            return False
        return chat_id in (self.main_group, self.exec_group)

    @property
    def logs(self) -> tuple[int, int | None]:
        """Moderation log destination as (chat_id, thread_id)."""
        return self._c.logs_tuple

    @property
    def logs_errors(self) -> tuple[int, int | None]:
        """Error report destination as (chat_id, thread_id)."""
        return self._c.logs_errors_id

    @property
    def proofs(self) -> tuple[int, int | None]:
        """Ban proof destination as (chat_id, thread_id)."""
        return self._c.proofs_id

    @property
    def appeals(self) -> tuple[int, int | None]:
        """Appeal record destination as (chat_id, thread_id)."""
        return self._c.appeals_id

    @property
    def appeal_log_handle(self) -> str:
        """Public log handle shown to users in appeal instructions."""
        return self._c.appeal_log_handle

    @property
    def appeal_discussion_topic(self) -> int:
        """Thread ID inside MAIN_GROUP where appeal review cards are posted."""
        return self._c.appeal_discussion_topic

    @property
    def album_debounce(self) -> int:
        """Album grouping window in seconds for multi-photo ban proofs."""
        return self._c.album_debounce_seconds

    @property
    def log_level(self) -> int:
        """Logging verbosity level as a stdlib logging int constant."""
        return self._c.log_level

    @property
    def modules_load(self) -> list[str]:
        """Optional allowlist of module names to load; empty means load all."""
        return self._c.modules_load

    @property
    def modules_no_load(self) -> list[str]:
        """Optional denylist of module names to skip during loading."""
        return self._c.modules_no_load

    @property
    def redis_url(self) -> str | None:
        """Redis connection URL from REDIS_URL (None when not configured)."""
        return self._c.redis_url

    @property
    def warn_expiry_days(self) -> int:
        """Days after which warn_counts expire; 0 = disabled."""
        return self._c.warn_expiry_days

    @property
    def sync_interval_hours(self) -> int:
        """Hours between scheduled enforcement-sync sweeps; 0 = disabled."""
        return self._c.sync_interval_hours

    @property
    def fed_warn_limit(self) -> int:
        """Federation-wide warn threshold that triggers an auto-ban (0 = disabled).

        When a user accumulates this many warnings across all federation groups
        combined (summed by ``federation_warn_count``), they are automatically
        federation-banned, even if no single group has reached the per-group
        warn threshold.  Set to 0 to disable cross-group enforcement and rely
        solely on the per-group threshold.
        """
        return self._c.fed_warn_limit

    @property
    def warn_limit(self) -> int:
        """Per-group warning threshold that triggers an automatic ban.

        When a user's warn count in a single group reaches or exceeds this
        value, they are automatically federation-banned and their warns in that
        group are cleared.  ``>=`` is deliberate: after a total enforcement
        failure the count still equals the limit and the next warn must re-fire
        the auto-ban (a ``==`` trigger would wedge permanently at limit+1).
        Duplicate bans are prevented by the already-banned guard and by
        deactivate_all_active_bans on unban.  Minimum 1; defaults to 3.
        """
        return self._c.warn_limit

    @property
    def webhook_url(self) -> str:
        """Public base URL for the webhook endpoint (empty string = polling fallback).

        Set by WEBHOOK_URL env var, or auto-detected from REPLIT_DEV_DOMAIN on Replit.
        An empty value means no public URL is available; the bot falls back to
        long-polling, which is only acceptable for local development.
        """
        return self._c.webhook_url

    @property
    def webhook_secret(self) -> str:
        """Secret token sent by Telegram in the X-Telegram-Bot-Api-Secret-Token header.

        Set by WEBHOOK_SECRET env var, or generated via secrets.token_hex(32) at startup.
        A generated token changes every restart, but set_webhook() is always called with
        the current token, so Telegram stays in sync.
        """
        return self._c.webhook_secret

    @property
    def webhook_secret_explicit(self) -> str:
        """Explicit WEBHOOK_SECRET from env (empty string when not configured).

        Unlike :meth:`webhook_secret` this never falls back to a generated
        token, so serverless receivers (which cannot re-register the webhook
        on every cold start) can fail closed when no secret is configured.
        """
        return self._c.webhook_secret_explicit

    @property
    def cron_secret(self) -> str:
        """Bearer token protecting the serverless cron endpoint (empty = not configured).

        Compared against the ``Authorization: Bearer <token>`` header that
        Vercel Cron sends when CRON_SECRET is set on the project. An empty
        value makes /api/cron refuse every request (fail closed); always set
        it in production.
        """
        return self._c.cron_secret

    @property
    def is_webhook_mode(self) -> bool:
        """True when a public webhook URL is available; False for polling fallback."""
        return bool(self._c.webhook_url)

    @property
    def community_channel_url(self) -> str:
        """Public URL of the main community channel (built-in default when env is empty)."""
        return self._c.community_channel_url

    @property
    def community_group_url(self) -> str:
        """Public URL of the main community discussion group (built-in default when env is empty)."""
        return self._c.community_group_url

    @property
    def community_logs_url(self) -> str:
        """Public URL of the logs channel (built-in default when env is empty)."""
        return self._c.community_logs_url

    @property
    def community_exec_url(self) -> str:
        """Public URL or invite link of the exec/staff group (built-in default when env is empty)."""
        return self._c.community_exec_url

    @property
    def community_travel_url(self) -> str:
        """Public URL or invite link of the TRAVEL community (built-in default when env is empty)."""
        return self._c.community_travel_url

    @property
    def mtproto_enabled(self) -> bool:
        """True when API_ID + API_HASH are set (MTProto lookups available)."""
        return self._c.api_id > 0 and bool(self._c.api_hash)

    @property
    def api_id(self) -> int:
        """Telegram API ID for MTProto, or 0 when not configured."""
        return self._c.api_id

    @property
    def api_hash(self) -> str:
        """Telegram API hash for MTProto (empty when not configured)."""
        return self._c.api_hash

    @property
    def mtproto_session(self) -> str:
        """Namespace for the shared MTProto session in MongoDB."""
        return self._c.mtproto_session
