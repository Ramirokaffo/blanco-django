# blanco-django

Back-office et API du point de vente **Blanco** (Django 4.2 + Django REST Framework).

## Installation

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # puis renseigner les variables

python manage.py migrate               # crée les tables ET charge les données par défaut
                                       # (les migrations sont versionnées : rien à générer)
DJANGO_SUPERUSER_PASSWORD='...' python create_superuser.py   # crée « admin » (mot de passe généré et affiché si la variable est absente)
python manage.py runserver 0.0.0.0:8000
```

### Migrations

Les migrations sont **versionnées** (`core/migrations/`) : ne jamais relancer
`makemigrations` au démarrage d'un conteneur. `django_migrations` ne stocke
aucun condensat du contenu, donc une migration régénérée serait considérée
comme déjà appliquée et les changements de modèle ne seraient jamais appliqués.

```bash
python manage.py makemigrations core            # uniquement après un changement de modèle, puis commiter
python manage.py makemigrations --check --dry-run  # garde-fou d'intégration continue
python manage.py check_migration_baseline       # contrôle schéma + historique avant migrate
```

`check_migration_baseline` est appelée par l'entrypoint Docker avant `migrate`.
Elle bloque si le schéma réel manque une table ou une colonne, avertit si
l'historique contient une migration générée localement (réparable avec
`--repair-history`), et indique la manœuvre de rattrapage pour une base
peuplée sans historique.

### Données par défaut (modules applicatifs, plan comptable)

Les modules applicatifs (onglets de la navigation, attribuables par utilisateur)
et le plan comptable OHADA sont créés **automatiquement après chaque `migrate`**.
Ils peuvent aussi être (re)chargés manuellement, sans risque de doublon :

```bash
python manage.py init_modules            # crée les modules manquants (-v 2 pour les lister)
python manage.py init_modules --update   # réaligne aussi nom / icône / ordre sur les valeurs par défaut
python manage.py init_accounts           # crée les comptes comptables manquants
```

## Sécurité (résumé)

- L'API mobile applique les **modules** de l'utilisateur (`sales`, `products`, `inventory`) : un compte sans module ne peut rien faire.
- L'inscription depuis l'app mobile (`POST /api/staff/`) crée un compte **inactif** ; un administrateur l'active dans l'admin Django.
- Un utilisateur désactivé ou soft-supprimé (`delete_at`) perd immédiatement ses tokens API et ne peut plus se connecter.
- Une vente dont l'écriture comptable a échoué est marquée `accounting_pending` : `python manage.py replay_accounting` la rejoue.
- Derrière un reverse proxy TLS, mettre `USE_HTTPS=True` (cookies `Secure`, HSTS, redirection) et `CSRF_TRUSTED_ORIGINS`.

## Langues (français / anglais)

L'interface web, les messages de l'API et le JavaScript sont bilingues. Le français est la langue source du code ; l'anglais est traduit dans `locale/en/LC_MESSAGES/django.po` (Python + templates) et `djangojs.po` (JavaScript). Chaque utilisateur choisit sa langue avec le sélecteur **FR / EN** de l'en-tête (ou de la page de connexion) ; le choix est mémorisé un an dans un cookie. Sans choix explicite, la langue du navigateur (`Accept-Language`) est utilisée, puis le français.

Les binaires GNU gettext ne sont pas nécessaires : la commande `translations` s'appuie sur Babel.

```bash
python manage.py translations extract   # met à jour les .po après avoir ajouté/modifié des chaînes
python manage.py translations check     # chaînes non traduites et erreurs de placeholders
python manage.py translations compile   # génère les .mo (non versionnés) : à lancer après un checkout et après chaque édition des .po
```

Le `docker-entrypoint.sh` compile les traductions au démarrage. Pour ajouter une chaîne : l'écrire en français dans un appel `gettext`/`{% trans %}`/`gettext()` JS, lancer `translations extract`, renseigner le `msgstr` anglais, puis `translations compile`.

## Tests

```bash
python manage.py test core
```

## Application Windows (.exe)

Le projet se compile en application de bureau installable (icône, double clic,
serveur local + ouverture du navigateur), pour un poste sans Docker ni Python :

```powershell
powershell -ExecutionPolicy Bypass -File installer\build_windows.ps1
```

La compilation est aussi automatisée : pousser un tag `test-v1.2.3` (préversion)
ou `prod-v1.2.3` (production) déclenche GitHub Actions, qui lance les tests,
compile et publie l'installeur dans une release.

Voir `WINDOWS_README.md` (compilation, publication, emplacement des données,
accès depuis l'application mobile, dépannage).

## Docker

Voir `DOCKER_README.md`.
