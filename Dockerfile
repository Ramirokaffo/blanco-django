# # Utiliser une image Python officielle comme base
# FROM python:3.11-slim

# # Définir les variables d'environnement
# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     DEBIAN_FRONTEND=noninteractive

# # Définir le répertoire de travail
# WORKDIR /app

# # Installer les dépendances système nécessaires
# RUN apt-get update && apt-get install -y \
#     gcc \
#     default-libmysqlclient-dev \
#     default-mysql-client \
#     pkg-config \
#     netcat-traditional \
#     && rm -rf /var/lib/apt/lists/*


# # Copier le fichier requirements.txt
# COPY requirements.txt /app/

# # Installer les dépendances Python
# RUN pip install --no-cache-dir --upgrade pip && \
#     pip install --no-cache-dir -r requirements.txt

# # Copier le projet Django
# COPY . /app/

# # Créer les répertoires pour les fichiers statiques et médias
# RUN mkdir -p /app/staticfiles /app/blanco

# # Collecter les fichiers statiques
# RUN python manage.py collectstatic --noinput || true

# # Exposer le port 8000
# EXPOSE 8000

# # Script d'entrée pour attendre MySQL et lancer les migrations
# COPY docker-entrypoint.sh /app/docker-entrypoint.sh
# RUN chmod +x /app/docker-entrypoint.sh

# # Commande par défaut
# ENTRYPOINT ["/app/docker-entrypoint.sh"]
# CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "blanco.wsgi:application"]




# ==============================
# Stage 1 : Builder
# ==============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dépendances build uniquement
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt

# ==============================
# Stage 2 : Runtime (image finale)
# ==============================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Seulement les libs runtime
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Copier les wheels compilés
COPY --from=builder /app /wheels

RUN pip install --no-cache /wheels/*

# Copier le projet
COPY . .

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "blanco.wsgi:application"]