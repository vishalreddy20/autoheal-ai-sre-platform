FROM python:3.11-slim AS base
WORKDIR /app

RUN addgroup --system app && adduser --system --group app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

FROM base AS final
COPY . .
USER app
EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:8002/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002", \
     "--workers", "2"]
