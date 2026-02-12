# Déploiement Docker - Blanco Django

Ce guide explique comment déployer l'application Django Blanco avec Docker et Docker Compose.

## Prérequis

- Docker installé (version 20.10 ou supérieure)
- Docker Compose installé (version 2.0 ou supérieure)

## Structure des fichiers Docker

- `Dockerfile` : Configuration de l'image Docker pour l'application Django
- `docker-compose.yml` : Orchestration des services (Django + MySQL)
- `docker-entrypoint.sh` : Script de démarrage pour les migrations et l'initialisation
- `.env.docker` : Variables d'environnement pour Docker
- `.dockerignore` : Fichiers à exclure de l'image Docker

## Configuration

### 1. Variables d'environnement

Copiez le fichier `.env.example` vers `.env.docker` et modifiez les valeurs selon vos besoins :

```bash
cp .env.example .env.docker
```

Variables importantes :
- `SECRET_KEY` : Clé secrète Django (à changer en production)
- `DEBUG` : Mettre à `False` en production
- `ALLOWED_HOSTS` : Ajouter votre domaine
- `MYSQL_PASSWORD` : Mot de passe MySQL (à changer en production)
- `MYSQL_HOST` : Doit être `mysql` (nom du service Docker)

### 2. Construction et démarrage

```bash
# Créer le réseau Docker (si nécessaire)
docker network create blanco-network

# Construire et démarrer les services
docker-compose up -d --build
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

```bash
# Créer de nouvelles migrations
docker-compose exec web python manage.py makemigrations

# Appliquer les migrations
docker-compose exec web python manage.py migrate

# Vérifier l'état des migrations
docker-compose exec web python manage.py showmigrations
```

### Créer un superutilisateur

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
- MySQL : localhost:3306

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
3. Vérifier les variables d'environnement dans `.env.docker`

### Erreur de connexion à MySQL

1. Vérifier que le service MySQL est en cours d'exécution : `docker-compose ps`
2. Vérifier le healthcheck : `docker-compose exec mysql mysqladmin ping -h localhost -u root -p`
3. Vérifier que `MYSQL_HOST=mysql` dans `.env.docker`

### Problèmes de permissions

```bash
# Donner les permissions aux fichiers
sudo chown -R $USER:$USER media staticfiles
```

## Production

Pour un déploiement en production :

1. Changer `SECRET_KEY` dans `.env.docker`
2. Mettre `DEBUG=False`
3. Configurer `ALLOWED_HOSTS` avec votre domaine
4. Utiliser un mot de passe MySQL fort
5. Configurer un reverse proxy (Nginx) devant l'application
6. Utiliser des volumes persistants pour les données
7. Mettre en place des sauvegardes régulières

## Support

Pour toute question ou problème, consultez la documentation Django ou Docker.

