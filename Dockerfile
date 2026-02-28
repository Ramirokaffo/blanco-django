
# ==============================
# Stage 1 : Builder
# ==============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip

# Créer un dossier wheels propre
RUN mkdir /wheels

# Build uniquement les wheels
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# ==============================
# Stage 2 : Runtime
# ==============================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Copier uniquement les wheels
COPY --from=builder /wheels /wheels

# Installer uniquement les wheels
RUN pip install --no-cache-dir /wheels/*

# Copier le projet
COPY . .

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "blanco.wsgi:application"]