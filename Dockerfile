FROM python:3.12-slim

# uv (gestore dipendenze & runtime)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_FROZEN=1

# 1) dipendenze (layer cachato): installa solo le deps, non il progetto
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra web --no-install-project

# 2) codice + schema, poi installa il progetto
COPY conquisterco ./conquisterco
COPY schema.sql ./
RUN uv sync --frozen --extra web

# dati e media su volume /data (persistono fuori dall'immagine)
ENV CONQUISTERCO_DB=/data/conquisterco.db \
    CONQUISTERCO_MEDIA=/data/media
RUN mkdir -p /data/media

EXPOSE 8077
# --no-sync: usa l'ambiente già costruito (con l'extra web), senza ri-sincronizzare
CMD ["uv", "run", "--no-sync", "uvicorn", "conquisterco.app.main:app", \
     "--host", "0.0.0.0", "--port", "8077"]
