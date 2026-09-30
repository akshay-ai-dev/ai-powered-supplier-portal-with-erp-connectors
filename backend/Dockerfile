# API container: FastAPI, connector core, mock adapters, MCP server, AI, notifications.
# Dev image: the repo is bind-mounted at /repo, so code changes reload without a rebuild.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

# Keep the virtualenv outside the bind-mounted source folder.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /repo/backend
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
