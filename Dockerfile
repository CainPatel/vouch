FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "certifi>=2024.8.30" \
    "fastapi>=0.115.0" \
    "google-genai>=2.30.1" \
    "httpx>=0.27.0" \
    "python-dotenv>=1.0.1" \
    "segno>=1.6.1" \
    "uvicorn[standard]>=0.32.0" \
    "websockets>=13.0"

COPY server ./server
COPY static ./static

EXPOSE 8080

CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
