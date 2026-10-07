# Stage 1: instala las dependencias de producción en un virtualenv (para la plataforma destino,
# porque asyncpg y greenlet traen binarios compilados).
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY main.py alembic.ini ./
COPY --chmod=755 entrypoint.sh ./
COPY alembic ./alembic
COPY src ./src

# Stage 2: runtime sin privilegios.
FROM python:3.14-slim
RUN useradd --system --no-create-home app
WORKDIR /app
COPY --from=build --chown=root:root /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=2)" || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000"]
