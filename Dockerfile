FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Опционально: точная ревизия сборки для /version.
#   docker compose build --build-arg BUILD_SHA=$(git rev-parse --short HEAD)
ARG BUILD_SHA=""
ENV BUILD_SHA=$BUILD_SHA

EXPOSE 8000

CMD ["python", "main.py"]
