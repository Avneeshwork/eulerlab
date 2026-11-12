# EulerLab: the Python side (API, scheduler, dead-man switch) in one image (ADR-164).
#
# One image, several services: docker-compose.yml starts it four times with a
# different command each. The repository is bind-mounted at /app at run time,
# so the agents' commits (pre-registered cards, research notes) land in the
# operator's checkout, not in a container layer that vanishes. The virtualenv
# therefore lives outside /app, in /opt/venv, where the mount cannot hide it.
#
# Data lives wherever EULERLAB_DATA_DIR points (default /data, a named volume).

FROM python:3.12-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    EULERLAB_DATA_DIR=/data \
    TZ=Asia/Kolkata

# make and git: the jobs are Makefile targets, and the research autopilot and
# the engineering agent commit to the repository.
RUN apt-get update \
    && apt-get install -y --no-install-recommends make git curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

# Dependencies first, so a code change does not re-resolve them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra web --extra angel --extra db --extra dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra web --extra angel --extra db --extra dev

RUN mkdir -p /data && git config --global --add safe.directory /app

ENV PATH="/opt/venv/bin:${PATH}"

# `make health` exits 1 when anything is red, so it is the health check as is.
HEALTHCHECK --interval=60s --timeout=20s --start-period=60s --retries=3 \
    CMD ["python", "-m", "eulerlab.health"]

CMD ["uvicorn", "eulerlab.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
