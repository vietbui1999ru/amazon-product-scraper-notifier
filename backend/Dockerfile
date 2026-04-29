FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" && playwright install chromium

FROM base AS runtime
COPY . .
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
