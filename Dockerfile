FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer-cached separately from source)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY tcbot/ ./tcbot/
RUN uv sync --frozen --no-dev

# Verify hiredis C extension is present
RUN uv run --frozen python -c "import hiredis; print('hiredis C extension verified')"

EXPOSE 5000

CMD ["uv", "run", "--frozen", "python", "-m", "tcbot"]
