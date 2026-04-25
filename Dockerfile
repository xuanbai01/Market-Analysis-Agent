FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies (keep pins in sync with pyproject.toml).
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        fastapi==0.115.0 \
        uvicorn[standard]==0.30.6 \
        SQLAlchemy==2.0.35 \
        asyncpg==0.29.0 \
        alembic==1.13.2 \
        pydantic==2.9.2 \
        pydantic-settings==2.6.1 \
        python-dotenv==1.0.1 \
        httpx==0.27.2 \
        yfinance==1.3.0 \
        anthropic==0.97.0

# Copy the app code + migrations.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

EXPOSE 8000

# Apply any pending migrations before starting the API. Keeps
# `docker compose up` a single-command dev loop; in prod, run
# `alembic upgrade head` as a separate pre-deploy step.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
