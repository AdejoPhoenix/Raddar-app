FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Install deps first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app ./app
COPY static ./static
COPY scripts ./scripts
COPY alembic ./alembic
COPY alembic.ini ./

EXPOSE 8000
# Honor $PORT when the platform injects one (Render/Fly), default 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
