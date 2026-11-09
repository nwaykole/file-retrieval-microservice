# ---- build stage: resolve deps into a venv ----
# distroless python3-debian12 ships Python 3.11, so build against the same minor version.
FROM python:3.11-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
RUN python -m venv /venv
COPY pyproject.toml ./
COPY src ./src
RUN /venv/bin/pip install ".[gcp]"

# ---- runtime: distroless, non-root, no shell, no package manager ----
FROM gcr.io/distroless/python3-debian12:nonroot
COPY --from=build /venv /venv
COPY --from=build /src/src /app
ENV PYTHONPATH="/app:/venv/lib/python3.11/site-packages" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
EXPOSE 8080
# 2 workers per pod with ~1 vCPU; scale horizontally rather than vertically.
ENTRYPOINT ["/usr/bin/python3", "-m", "uvicorn", "file_service.main:create_app", "--factory", \
            "--host", "0.0.0.0", "--port", "8080", "--workers", "2", \
            "--timeout-graceful-shutdown", "20", "--no-server-header", "--proxy-headers"]
