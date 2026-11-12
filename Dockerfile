# --- Etapa 1: compilar dependencias (pyswisseph no publica wheels) ---
FROM python:3.13-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# --- Etapa 2: imagen final, sin compiladores y sin root ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EPHEM_DATA_DIR=/data
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin ephem
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* && rm -rf /wheels
WORKDIR /srv
COPY app ./app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--no-server-header", "--no-access-log"]
