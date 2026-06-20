# Vadana Extractor — Telegram bot image.
# Build & run:  docker compose up -d --build   (reads bot/.env)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ffmpeg + ffprobe drive the whiteboard → video and audio reconstruction
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# dependencies first, so this layer is cached unless requirements change
COPY requirements.txt ./
COPY bot/requirements.txt ./bot/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r bot/requirements.txt

# then the application code
COPY vadana ./vadana
COPY bot ./bot
COPY cli ./cli

# run unprivileged; cache/ holds the Telegram file-id store — mount it as a volume
RUN useradd -m -u 10001 app \
 && mkdir -p cache bot_work logs \
 && chown -R app /app
USER app

# every setting comes from the environment (BOT_TOKEN required) — see the README
CMD ["python", "-m", "bot.bot"]
