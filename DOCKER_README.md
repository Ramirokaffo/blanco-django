# Déploiement Docker - Blanco Django

Ce guide explique comment déployer l'application Django Blanco avec Docker et Docker Compose.

## Prérequis

- Docker installé (version 20.10 ou supérieure)
- Docker Compose installé (version 2.0 ou supérieure)

## Structure des fichiers Docker

- `Dockerfile` : Configuration de l'image Docker pour l'application Django (build en deux étapes, exécution en utilisateur non-root `app`)
- `docker-compose.yml` : Orchestration des services (Django + MySQL) en développement (Linux, réseau host pour le web)
- `docker-compose.prod.yml` : Variante production (image `ramirokaffo/blanco` publiée sur Docker Hub)
- `docker-compose.win.yml` : Variante Windows / Docker Desktop (réseau bridge, ports publiés)
- `docker-entrypoint.sh` : Script de démarrage pour les migrations et l'initialisation
- `.env` : Variables d'environnement lues par les fichiers compose (non versionné ; `.env.docker` n'est plus suivi par git)
- `.env.example` : Modèle de variables d'environnement
- `.dockerignore` : Fichiers à exclure de l'image Docker (aucun fichier `.env*` n'entre dans l'image)

## Configuration

### 1. Variables d'environnement

Les fichiers compose lisent `.env` (et non `.env.docker`, qui n'est plus versionné). Copiez le fichier `.env.example` vers `.env` et modifiez les valeurs selon vos besoins :

```bash
cp .env.example .env
```

Variables importantes :
- `SECRET_KEY` : Clé secrète Django (à changer en production)
- `DEBUG` : Mettre à `False` en production
- `ALLOWED_HOSTS` : Ajouter votre domaine (conserver `127.0.0.1`, utilisé par le healthcheck du conteneur)
- `MYSQL_ROOT_PASSWORD` : **Requis** par les fichiers compose (initialisation de MySQL et healthcheck)
- `MYSQL_USER` / `MYSQL_PASSWORD` : Utilisateur applicatif dédié, non root (ex. `blanco`), et son mot de passe (à changer en production)
- `MYSQL_HOST` : Doit être `127.0.0.1` : le service web tourne en `network_mode: host` et MySQL n'est publié que sur la boucle locale de l'hôte (`127.0.0.1:3306`). Sur Windows (`docker-compose.win.yml`, réseau bridge), utiliser `mysql` (nom du service).
- `DJANGO_SUPERUSER_PASSWORD` : Mot de passe du superutilisateur créé par `create_superuser.py` (voir plus bas)
- `USE_HTTPS` / `CSRF_TRUSTED_ORIGINS` : À renseigner uniquement derrière un reverse proxy TLS (voir `.env.example`)

### 2. Construction et démarrage

Le conteneur web s'exécute avec un utilisateur non-root (`app`). Les dossiers `./media` et `./staticfiles` montés depuis l'hôte doivent donc exister et être accessibles en écriture pour cet utilisateur (son UID ne correspond à aucun utilisateur de l'hôte) :

```bash
# Préparer les dossiers montés (une seule fois)
mkdir -p media staticfiles
chmod -R a+rwX media staticfiles
# Alternative plus stricte : donner les dossiers à l'UID de l'utilisateur `app` de l'image
# sudo chown -R $(docker run --rm --entrypoint id ramirokaffo/blanco:latest -u) media staticfiles

# Construire et démarrer les services
docker-compose up -d --build
```

Variantes :

```bash
docker-compose -f docker-compose.prod.yml up -d     # production : image ramirokaffo/blanco
docker-compose -f docker-compose.win.yml up -d      # Windows / Docker Desktop
```

### 3. Vérifier les logs

```bash
# Logs de tous les services
docker-compose logs -f

# Logs du service web uniquement
docker-compose logs -f web

# Logs de MySQL
docker-compose logs -f mysql
```

## Commandes utiles

### Gestion des services

```bash
# Démarrer les services
docker-compose up -d

# Arrêter les services
docker-compose down

# Redémarrer les services
docker-compose restart

# Arrêter et supprimer les volumes (ATTENTION : supprime les données)
docker-compose down -v
```

### Migrations Django

Les migrations sont **versionnées** et livrées dans l'image ; l'entrypoint ne
les régénère plus. Elles se créent sur le poste de développement, puis se
commitent.

```bash
# Contrôler schéma et historique (joué automatiquement avant chaque migrate)
docker-compose exec web python manage.py check_migration_baseline

# Appliquer les migrations
docker-compose exec web python manage.py migrate

# Vérifier l'état des migrations
docker-compose exec web python manage.py showmigrations
```

### Créer un superutilisateur

Le script `create_superuser.py` crée l'utilisateur `admin` s'il n'existe pas ; son mot de passe est lu dans la variable d'environnement `DJANGO_SUPERUSER_PASSWORD` (à définir dans `.env`). Le script n'est pas embarqué dans l'image : on l'exécute depuis l'hôte via l'entrée standard du conteneur :

```bash
docker-compose exec -T web python - < create_superuser.py
```

Alternative interactive (commande Django standard) :

```bash
docker-compose exec web python manage.py createsuperuser
```

### Collecter les fichiers statiques

```bash
docker-compose exec web python manage.py collectstatic --noinput
```

### Accéder au shell Django

```bash
docker-compose exec web python manage.py shell
```

### Accéder au conteneur

```bash
# Shell bash dans le conteneur web
docker-compose exec web bash

# Shell MySQL
docker-compose exec mysql mysql -u root -p
```

## Accès à l'application

- Application Django : http://localhost:8000
- Admin Django : http://localhost:8000/admin
- MySQL : `127.0.0.1:3306`, accessible uniquement depuis la boucle locale de l'hôte (non exposé sur le réseau)

## Sauvegarde et restauration

### Sauvegarde de la base de données

```bash
docker-compose exec mysql mysqldump -u root -p blanco-db > backup.sql
```

### Restauration de la base de données

```bash
docker-compose exec -T mysql mysql -u root -p blanco-db < backup.sql
```

## Dépannage

### Le service web ne démarre pas

1. Vérifier les logs : `docker-compose logs web`
2. Vérifier que MySQL est prêt : `docker-compose logs mysql`
3. Vérifier les variables d'environnement dans `.env`

### Erreur de connexion à MySQL

1. Vérifier que le service MySQL est en cours d'exécution : `docker-compose ps`
2. Vérifier le healthcheck : `docker-compose exec mysql sh -c 'MYSQL_PWD=$MYSQL_ROOT_PASSWORD mysqladmin ping -h 127.0.0.1 -u root'`
3. Vérifier que `MYSQL_HOST=127.0.0.1` dans `.env` (`mysql` avec `docker-compose.win.yml`)

### Problèmes de permissions (`Permission denied` sur `media/` ou `staticfiles/`)

Le conteneur tourne en non-root : les dossiers montés doivent être accessibles en écriture à l'utilisateur `app` de l'image.

```bash
chmod -R a+rwX media staticfiles
# ou, plus strict :
sudo chown -R $(docker run --rm --entrypoint id ramirokaffo/blanco:latest -u) media staticfiles
```

## Production

Pour un déploiement en production :

1. Changer `SECRET_KEY` dans `.env`
2. Mettre `DEBUG=False`
3. Configurer `ALLOWED_HOSTS` avec votre domaine
4. Utiliser un mot de passe MySQL fort
5. Configurer un reverse proxy (Nginx) devant l'application
6. Utiliser des volumes persistants pour les données
7. Mettre en place des sauvegardes régulières
8. Figer la version de l'image dans `docker-compose.prod.yml` (tag immuable ou digest `@sha256:`) plutôt que `:latest`
9. Derrière un reverse proxy TLS uniquement : `USE_HTTPS=True` et `CSRF_TRUSTED_ORIGINS=https://votre-domaine`

## Support

Pour toute question ou problème, consultez la documentation Django ou Docker.

