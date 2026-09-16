FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLUGIN_DEPENDENCIES_DIR=/app/.plugin-deps \
    PYTHONPATH=/app/.plugin-deps:/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Only framework files are copied. Plugins are supplied through /app/plugins.
COPY bot.py sync_commands.py docker_entrypoint.py ./
COPY qqbot_app/ ./qqbot_app/

RUN mkdir -p /app/plugins /app/.plugin-deps \
    && test -z "$(find /app/plugins -mindepth 1 -print -quit)"

ENTRYPOINT ["python", "docker_entrypoint.py"]
CMD ["python", "bot.py"]
