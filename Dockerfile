# Money Radar v2 — always-on service image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RADAR_HOME=/app

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml ./
RUN mkdir radar && touch radar/__init__.py \
    && pip install . \
    && pip uninstall -y money-radar \
    && rm -rf radar build *.egg-info

COPY radar ./radar
# Defaults baked in; docker-compose mounts your edited copies over them.
COPY config.yaml profile.yaml goals.yaml ./

RUN useradd --uid 1000 --create-home radar \
    && mkdir -p /app/data \
    && chown radar:radar /app/data
USER radar

HEALTHCHECK --interval=2m --timeout=20s --start-period=2m --retries=3 \
    CMD ["python", "-m", "radar", "health"]

CMD ["python", "-m", "radar", "run"]
