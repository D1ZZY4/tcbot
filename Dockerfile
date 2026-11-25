FROM python:3.14-slim@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b

# * libstdc++6 provides the runtime the greenlet extension links
# * against. greenlet comes with sqlalchemy[asyncio], so the async
# * engine cannot start without it.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

WORKDIR /app

# * `uv run` re-syncs the environment before executing. Without this, every
# * verification step and the runtime command re-add the dev group that the
# * syncs above deliberately exclude, shipping developer tooling to production.
ENV UV_NO_DEV=1

# Install dependencies first (layer-cached separately from source)
# * The observability extra ships the Prometheus endpoint and the Sentry
# * client. Both are optional in the code, but the image is the primary
# * deployment path, so the advertised surfaces must actually exist.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra observability

# Copy source and install the project itself
# * i18n/ is mandatory at runtime: the TOML catalog loads from the
# * project root on first t() call, so an image without it fails every
# * handler with I18nError.
# * alembic/ and alembic.ini are mandatory too: the bot applies the
# * schema migrations at startup, so an image without them cannot open
# * the database.
COPY tcbot/ ./tcbot/
COPY i18n/ ./i18n/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
RUN uv sync --frozen --no-dev --extra observability

# Verify the C extensions the runtime imports are present
RUN uv run --frozen -- python -c "import hiredis; print('hiredis C extension verified')"
RUN uv run --frozen -- python -c "import greenlet; print('greenlet C extension verified')"

ARG PORT=5000
EXPOSE ${PORT}
ENV PORT=${PORT}

# * The bot only needs its virtualenv and read-only catalog files at runtime.
RUN useradd --system --create-home --uid 10001 tcbot \
    && chown -R tcbot:tcbot /app
USER tcbot

CMD ["uv", "run", "--frozen", "--extra", "observability", "python", "-m", "tcbot"]
