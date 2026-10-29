# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ARG UID=1000
ARG GID=1000

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        tmux \
        git \
        ripgrep \
        jq \
        curl \
        ca-certificates \
        libsecret-1-0 \
        build-essential \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN groupadd -g ${GID} cloude \
 && useradd -u ${UID} -g ${GID} -m -s /bin/bash cloude

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src/                 /app/src/
COPY client/              /app/client/
COPY config.example.json  /app/config.example.json
COPY setup_auth.py        /app/setup_auth.py
COPY setup.sh             /app/setup.sh

RUN chown -R cloude:cloude /app

USER cloude

ENV TERM=xterm-256color \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CLOUDECODE_BIND_HOST=0.0.0.0

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["python3", "-m", "src.main"]
