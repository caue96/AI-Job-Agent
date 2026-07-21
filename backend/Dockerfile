FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic ./alembic
COPY alembic.ini ./

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /app/data/cv_uploads /app/data/cv_exports \
    && chown -R app:app /app/data
USER app

EXPOSE 8000
