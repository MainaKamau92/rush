# Versions and dependency hashes are fixed; rebuild intentionally to upgrade.
FROM python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace

FROM base AS dependencies
COPY requirements/runtime.txt /tmp/runtime.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/runtime.txt

FROM dependencies AS build
COPY requirements/build.txt /tmp/build.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/build.txt
COPY . .
RUN pip wheel --no-build-isolation --no-deps --wheel-dir /dist .

FROM dependencies AS dev
RUN apt-get update && apt-get install --no-install-recommends -y git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements/development.txt /tmp/dev.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/dev.txt
COPY . .
RUN pip install --no-build-isolation --no-deps -e . \
    && git config --system --add safe.directory /workspace
CMD ["pytest", "--cov", "--cov-report=term-missing", "--cov-report=xml", "--cov-report=json"]

FROM dependencies AS runtime
COPY --from=build /dist /dist
RUN pip install --no-deps /dist/*.whl && rm -rf /dist \
    && useradd --uid 10001 --create-home rush \
    && mkdir -p /state && chown rush:rush /state
USER rush
ENV RUSH_STATE_DIR=/state RUSH_ENVIRONMENT=production
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
