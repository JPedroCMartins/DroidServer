# Painel (Host) do DroidServer em container.
# Uso: docker compose up -d --build  (ver docker-compose.yml)
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DROID_DATA_DIR=/data \
    DROID_LOG_DIR=/logs

WORKDIR /app

# Dependências primeiro (camada reaproveitada enquanto o uv.lock não muda).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY main.py ./
COPY app ./app

# Usuário sem privilégios; /data guarda nodes.json (tokens) e secret_key.
RUN useradd --system --uid 10001 droid \
    && mkdir -p /data /logs \
    && chown droid /data /logs
USER droid

EXPOSE 5050
CMD ["python", "main.py"]
