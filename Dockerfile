FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv

WORKDIR /app

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
COPY tcbot/ ./tcbot/
COPY i18n/ ./i18n/
RUN uv sync --frozen --no-dev --extra observability

# Verify hiredis C extension is present
RUN uv run --frozen -- python -c "import hiredis; print('hiredis C extension verified')"

ARG PORT=5000
EXPOSE 5000
ENV PORT=5000

CMD ["uv", "run", "--frozen", "python", "-m", "tcbot"]
