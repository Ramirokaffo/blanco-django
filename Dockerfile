
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

# netcat n'est plus installé : l'entrypoint ne l'utilise pas (l'attente de MySQL
# est assurée par le healthcheck + depends_on de docker-compose).
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur applicatif non-root
RUN addgroup --system app && adduser --system --ingroup app --home /app app

# Copier uniquement les wheels
COPY --from=builder /wheels /wheels

# Installer uniquement les wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copier le projet
COPY . .

# ./media et ./staticfiles sont montés par docker-compose : les dossiers doivent
# exister dans l'image et appartenir à l'utilisateur applicatif (voir DOCKER_README.md
# pour les permissions côté hôte).
RUN mkdir -p /app/media /app/staticfiles \
    && chmod +x /app/docker-entrypoint.sh \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/test-connection/', timeout=4).status==200 else 1)"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "--forwarded-allow-ips", "127.0.0.1", "blanco.wsgi:application"]
