FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install dependencies (match what you installed in your venv)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        fastapi==0.115.0 \
        uvicorn[standard]==0.30.6 \
        SQLAlchemy==2.0.35 \
        asyncpg==0.29.0 \
        pydantic==2.9.2 \
        pydantic-settings==2.6.1 \
        python-dotenv==1.0.1 \
        httpx==0.27.2

# Copy the app code
COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
