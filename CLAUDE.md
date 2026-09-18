# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Blanco" is a point-of-sale / back-office system for a small retail shop in Cameroon (currency FCFA, timezone Africa/Douala, OHADA accounting, 19.25% VAT). It is a Django 4.2 project (`blanco/`) with a single app (`core/`) that serves two clients:

- **Server-rendered HTML pages** (`core/views.py`, `core/urls.py`, `core/templates/`) used as the desktop back-office.
- **A DRF JSON API under `/api/`** (`core/api_urls.py`, `core/api_views/`, `core/serializers/`) consumed by a Flutter mobile app (`blanco_mobile`, a sibling repo referenced in `blanco-full.code-workspace`). The API is a port of a legacy Flask server; docstrings note the old Flask route (`Ancien Flask: GET /get_product_by_id/<id>`) and responses keep the legacy `{"status": 1|0, ...}` envelope. Auth is DRF token auth (`POST /api/auth/login/`).

Code comments, UI strings, `verbose_name`s, and commit messages are in **French**. The UI is bilingual (French source, English translation): every new user-facing string must be written in French **and wrapped** in a translation call (`gettext`/`gettext_lazy`, `{% trans %}`, JS `gettext()`), then `python manage.py translations extract` and an English `msgstr` added in `locale/en/LC_MESSAGES/`. See "Internationalisation" below.

## Commands

### Environment (required before anything runs)

Settings use `python-decouple`. Copy `.env.example` to `.env` (or export the variables). **Every** variable in `.env.example` is required even when using SQLite:
`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT`. `DATABASE_ENGINE` defaults to SQLite; set it to `django.db.backends.mysql` for MySQL. Optional: `GET_IP_METHOD=1` switches LAN-IP detection to `ip route` (needed inside Docker host networking); `USE_HTTPS=True` turns on Secure cookies, HSTS and SSL redirect (only behind TLS); `CSRF_TRUSTED_ORIGINS` (comma separated); `LOGIN_RATELIMIT_ATTEMPTS` / `LOGIN_RATELIMIT_WINDOW_SECONDS` (web login throttling, default 5 per 15 min); `API_LOGIN_THROTTLE` / `API_SIGNUP_THROTTLE` (DRF scoped throttles, default `10/min` and `5/hour`); `DJANGO_SUPERUSER_PASSWORD` (read by `create_superuser.py`). There is no CORS configuration: `django-cors-headers` is not installed and the API is consumed by a native app.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Migrations are NOT committed

`.gitignore` excludes `*/migrations/*.py` (except `__init__.py`). A fresh checkout has no migrations, so `migrate` and `test` fail with "Dependency on app with no migrations: core" until you generate them:

```bash
python manage.py makemigrations core
python manage.py migrate
```

The Docker entrypoint does the same (`makemigrations --noinput && migrate --noinput && collectstatic`). Consequence: there is no migration history to reason about; schema changes are just model edits.

### Reference data (modules, chart of accounts)

`AppModule` rows and the OHADA `Account` rows are **seeded automatically after every `migrate`** by a `post_migrate` handler (`core/signals.py`, connected in `CoreConfig.ready()` with `sender=core`). Both seeds are idempotent, so a fresh install gets its 12 modules and 29 accounts as soon as `migrate` runs, and the test database gets them too. Without modules the sidebar is empty (superusers see only active `AppModule` rows) and users cannot be granted anything; without accounts the accounting calls in `SaleService.create_sale` fail silently.

They can also be run by hand:

```bash
python manage.py init_modules            # creates missing modules; -v 2 lists them
python manage.py init_modules --update   # also realigns name/icon/order on DEFAULT_MODULES (keeps is_active and user grants)
python manage.py init_accounts           # creates missing OHADA accounts
```

### Run

```bash
python manage.py runserver 0.0.0.0:8000   # bind to 0.0.0.0 so the mobile app on the LAN can reach it
DJANGO_SUPERUSER_PASSWORD='...' python create_superuser.py   # creates 'admin' if missing (random password printed once when the variable is absent)
python manage.py replay_accounting          # re-runs the journal entry of sales flagged accounting_pending
python init_daily_session.py               # creates an open Exercise + Daily for testing
```

With `DEBUG=False`, WhiteNoise's manifest storage requires `python manage.py collectstatic` first.

### Tests

Django's test runner, SQLite, no pytest config:

```bash
python manage.py test core
python manage.py test core.tests.SalesCancellationTests
python manage.py test core.tests.SalesCancellationTests.test_cancel_cash_sale_restores_stock_creates_refund_and_cancels_invoice
```

Test classes that render views are decorated with `@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')` because the WhiteNoise manifest storage fails without a `collectstatic` run. Modules and accounts are already present in the test database thanks to the `post_migrate` seed; existing tests still call `AppModule.init_default_modules()` and `AccountingService.init_chart_of_accounts()` in `setUp`, which is harmless (idempotent). `test_models.py` at the root is a manual DB smoke script (MySQL only), not part of the suite.

No linter or formatter is configured.

### Translations (français / anglais)

French is the source language (`LANGUAGE_CODE = 'fr'`, msgids are the French texts); English lives in `locale/en/LC_MESSAGES/django.po` (Python + templates) and `djangojs.po` (JavaScript, including inline `<script>` blocks). GNU gettext is **not** required: the `translations` management command does extraction and compilation with Babel (listed in `requirements.txt`).

```bash
python manage.py translations extract   # updates locale/en/LC_MESSAGES/{django,djangojs}.po (keeps existing msgstr, flags obsolete ones)
python manage.py translations check     # lists untranslated / fuzzy strings and placeholder mismatches
python manage.py translations compile   # writes the .mo files (gitignored) — run after a checkout and after every .po edit
```

The Docker entrypoint runs `translations compile` before `collectstatic`. Without `.mo` files the app silently stays in French. The language is chosen by `LocaleMiddleware` from the `blanco_language` cookie (set by the FR/EN switcher in `components/header.html` and `login.html` via `django.views.i18n.set_language`), then `Accept-Language`, then French.

### Docker

Compose files read `.env` (not `.env.docker`, despite `DOCKER_README.md`) and additionally need `MYSQL_ROOT_PASSWORD`.

```bash
docker-compose up -d --build                        # dev: builds image, host network mode (Linux)
docker-compose -f docker-compose.prod.yml up -d     # prod: pulls ramirokaffo/blanco:latest
docker-compose -f docker-compose.win.yml up -d      # Windows: port mapping instead of host network
```

## Architecture

### Layering

`views.py` / `api_views/*` → `services/*` → `models/*`. Services are classes of `@staticmethod`s (`SaleService`, `SupplyService`, `AccountingService`, `ProductService`, `DailyService`, `ExerciseService`, ...). Anything that changes stock, credit balances, or accounting must go through a service inside `transaction.atomic()` with `select_for_update()` on `Product`. Note the exception: supply *creation* still lives inline in the `add_supply` view; cancellation/partial return are in `SupplyService`.

`core/views.py` is a single ~5,200-line file and `accounting_service.py` ~1,850 lines; use grep by function name rather than reading whole files.

### Models

Split by domain under `core/models/` and re-exported from `core.models` (`from core.models import Sale` works). Every table has an explicit legacy `db_table`. `AUTH_USER_MODEL = core.CustomUser` (table `staff`); `Staff` is an alias for `CustomUser`.

**Soft delete everywhere.** Nearly all models inherit `SoftDeleteModel` with `create_at` / `delete_at` (note: `create_at`, not `created_at`). "Deleting" or cancelling sets `delete_at`; every query must filter `delete_at__isnull=True`. Cancelling a sale/supply soft-deletes it, restores stock, writes a reversing journal entry, and soft-deletes related `CreditSale`/`CreditSupply` and `PaymentSchedule` rows.

### Time model: Exercise → Daily

`Exercise` is the fiscal year (open while `end_date` is null). `Daily` is a business-day session inside an exercise. `DailyService.get_or_create_active_daily()` returns the open daily or creates one (and an exercise) on demand; every `Sale`, `Supply`, `DailyExpense`, `DailyRecipe`, `Payment` is attached to the daily it was recorded in. Closing the day (`close_daily` view, JSON POST) writes a `DailyInventory` cash snapshot, sets `Daily.end_date`, and in DEFERRED VAT mode generates the day's VAT entries. Closing the exercise (`AccountingService.close_exercise` / `open_new_exercise`) writes result and carry-forward entries and records an `ExerciseClosing`.

### Accounting engine

Double-entry, OHADA/SYSCOHADA chart. `AccountingService.record_sale / record_supply / record_expense / record_recipe / record_credit_payment / record_supplier_payment / record_*_cancellation / record_partial_*_return` each create one `JournalEntry` (reference `VE-YYYYMMDD-001`, journals VE/AC/CA/BQ/OD) plus balanced `JournalEntryLine`s. Account codes are hardcoded strings: 701 sales, 601 purchases, 411 clients, 401 suppliers, 4431/4451 VAT collected/deductible, 571 cash, 521 bank, 585 mobile money; `PAYMENT_METHOD_ACCOUNT_MAP` maps `CASH/MOBILE_MONEY/BANK_TRANSFER/CHECK` to treasury accounts. Accounts must exist first: `AccountingService.init_chart_of_accounts()` seeds `DEFAULT_ACCOUNTS` idempotently. In `SaleService.create_sale` the accounting call is wrapped in a bare `except: pass` so a sale is never blocked by an accounting failure.

VAT behaviour is driven by the `SystemSettings` singleton (`enable_tva_accounting`, `tva_accounting_mode` IMMEDIATE vs DEFERRED) and `Product.has_vat`; `Sale.tva_accounting_created` tracks whether VAT entries exist. Reports (trial balance, ledger, income statement, balance sheet, aged balance, VAT declaration, bank reconciliation) are all query methods on `AccountingService`.

### Credit tracking

`CreditSale` / `CreditSupply` are one-to-one with `Sale` / `Supply` (`related_name='credit_info'`) and hold `amount_paid` / `amount_remaining`. `PaymentSchedule` rows are the instalment plan (type CLIENT or SUPPLIER). `Payment` and `SupplierPayment` record settlements and update both the credit record and the schedule statuses.

### Module-based access control

`AppModule` rows (codes `dashboard, sales, products, suppliers, supplies, expenses, contacts, inventory, accounting, treasury, reports, settings`, seeded by `AppModule.init_default_modules()` automatically after `migrate` or via `manage.py init_modules`) are granted per user via `CustomUser.allowed_modules`; superusers bypass. Every page view is decorated `@login_required` + `@module_required('<code>')` (`core/decorators.py`), and `components/navigation.html` shows links based on the `user_modules` context variable. A new page needs both the decorator and a nav entry gated on the same code.

The API applies the same model through DRF permissions in `core/api_permissions.py`: `HasModule('sales', 'products', 'inventory')` for catalogue reads, `HasModule('products')` for product writes, `HasModule('sales')` for sales, `HasModule('inventory')` for inventories, `IsSelfOrSuperUser` for user updates (`username`/`role` are superuser-only, own password change needs `current_password` and rotates the token). `POST /api/staff/` stays public for the mobile signup screen but creates an **inactive** account (a superuser calling it creates an active one); `GET /api/images/<folder>/<image>/` stays public but is confined to `media/product/`. `CustomUser.save()` forces `is_active=False` when `delete_at` is set and revokes DRF tokens whenever the account is inactive or soft-deleted; `core/auth_backends.py` enforces the same rule at login and token authentication.

### Security invariants to keep

- Business invariants live in the services, not only in serializers/forms: `SaleService.create_sale` re-validates price > 0, price caps, stock and quantities under `select_for_update`; `SaleService`/`SupplyService` refuse cancellations and returns on a closed exercise; payments (`record_credit_payment`, `record_supply_payment` views) lock the credit row and cap the amount.
- `AccountingService._create_entry(journal, **fields)` is the only way to create a `JournalEntry` (unique reference with retry). `get_account()` only returns active accounts; `record_expense`/`record_recipe` refuse accounts outside class 6/7; `treasury_account_code()` raises on unknown payment methods.
- A failed sale journal entry no longer passes silently: the sale is flagged `accounting_pending` and `manage.py replay_accounting` retries it.
- `close_daily` (module `sales`) never creates a daily, validates amounts as `Decimal >= 0`, and generates deferred VAT before closing, in one transaction. Closing an inventory no longer closes the exercise; `close_exercise` + `open_new_exercise` run in one transaction and are idempotent.
- Web login is rate limited per IP/username via the cache, `next` is validated with `url_has_allowed_host_and_scheme`, logout and invoice generation are POST-only. CSV exports go through `_SafeCsvWriter` (formula injection).
- Front-end: never build HTML from API data without `escapeHtml()` (defined in `core/static/js/main.js`); use `data-*` attributes + `addEventListener` instead of inline `onclick` with strings.

### Internationalisation

- Python: `gettext as _` in views/services/API/decorators (evaluated at request time), `gettext_lazy as _` for model/form/serializer/admin class-level declarations (`verbose_name`, `choices` labels, `label`, `help_text`). Never `_(f"...")`: use `_("... %(x)s") % {'x': v}`. Business exceptions (`ValueError(_("..."))`) are translated in the services so both the web views and the API return localized messages. Generated journal descriptions are translated at creation time (stored in the active language).
- Reference data seeded in the DB (`DEFAULT_MODULES` names, `DEFAULT_ACCOUNTS` names) stays French in the database but is marked with `gettext_noop()` so the msgids are extracted; templates display it with `{% trans account.name %}` / `{% trans module.name %}` (runtime lookup, falls back to the raw value for user-created rows), and `Account.__str__` / `AppModule.__str__` apply `gettext()` too (so form selects and the admin are translated).
- Ambiguous French words get a context: `pgettext_lazy('type de compte', 'Actif')` (Assets, vs the `is_active` label "Actif" = Active), `pgettext('classe comptable', 'Produits')` (Revenue, vs the catalogue "Produits" = Products), `pgettext_lazy('nom de modèle', 'Approvisionnement')` (Supply, vs the menu label = Supplies). Add a context whenever one French msgid would need two English translations.
- `{% blocktrans count counter=x|default:0 %}`: always guard counters, an aggregate that returns `None` raises `TemplateSyntaxError` at render time.
- Templates: `{% load i18n %}` then `{% trans "..." %}` / `{% blocktrans with x=var|filter %}...{{ x }}...{% endblocktrans %}` (no tags or filters inside a blocktrans). `base.html` sets `<html lang="{{ LANGUAGE_CODE }}">` and loads the JS catalog from `/jsi18n/` (`JavaScriptCatalog`) **before** every other script; `login.html` (which does not extend `base.html`) does the same.
- JavaScript (static files **and** inline `<script>` blocks): `gettext('...')`, `ngettext()`, `interpolate(gettext('... %(name)s'), {name: v}, true)`. Never `{% trans %}` inside JS. Strings must be literals inside the call to be extracted. Number formatting uses `document.documentElement.lang` instead of a hardcoded `'fr-FR'`.
- The API follows `Accept-Language` (the Flutter app can send the device locale); without the header it answers in French.

### Global template context

`core/context_processors.py` injects `system_settings` (the pk=1 `SystemSettings` singleton: company name, logo, currency, receipt text, VAT mode), `user_modules`, and `server_qr_base64` / `server_address`.

### LAN discovery / QR code

The mobile app finds the server by scanning a QR code of `ip:port`. `blanco/settings.py` imports `QRCodeService` at import time to detect the LAN IP and append it to `ALLOWED_HOSTS`, and `CoreConfig.ready()` generates the QR (guarded so it runs once under runserver's reloader). `GET /api/qr/refresh/` regenerates it if the IP changed. Expect a printed `ALLOWED_HOSTS` list and a "QR Code serveur généré" line on every startup, including test runs.

### Other things to know

- `core/__init__.py` calls `pymysql.install_as_MySQLdb()` and fakes the version so Django 4.2 accepts PyMySQL.
- `ProductService.create_product` also creates an initial `Supply` when `stock > 0`.
- `core/services/migration_service.py` + the settings "migration" page import data from the legacy system by parsing raw SQL `VALUES (...)` text pasted into a form.
- Static assets live in `core/static/` (plain CSS/JS per page, no build step); templates extend `base.html`.
- `docs/API_UPDATE_PRODUCT.md` documents the product update endpoint used by the mobile app, but is stale: it says `PATCH /api/products/by-code/<code>/update/` while the actual route is `PATCH /api/products/<id>/update/`.
