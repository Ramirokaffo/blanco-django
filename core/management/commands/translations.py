"""
Extraction et compilation des traductions sans les binaires GNU gettext.

`makemessages` / `compilemessages` de Django exigent xgettext et msgfmt, absents de
l'image Docker (python:*-slim) et de la plupart des postes Windows. Cette commande
fait le même travail avec Babel :

    python manage.py translations extract          # met à jour locale/<lang>/LC_MESSAGES/django.po et djangojs.po
    python manage.py translations compile          # génère les .mo à partir des .po (à lancer après chaque édition)
    python manage.py translations check            # liste les chaînes non traduites / floues et les erreurs de format

Sources analysées :
  - domaine ``django``   : *.py du projet (gettext, gettext_lazy, pgettext, ngettext, _ ...),
                           templates *.html / *.txt ({% trans %}, {% blocktrans %}, _("...")) ;
  - domaine ``djangojs`` : core/static/**/*.js et les blocs <script> inline des templates
                           (gettext(), ngettext(), pgettext(), npgettext()).

La langue source du code est le français (settings.LANGUAGE_CODE) ; les msgid sont donc
les textes français et seules les autres langues de settings.LANGUAGES ont un .po.
"""

import io
import os
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation.template import templatize

try:
    from babel.messages import Catalog
    from babel.messages.extract import extract
    from babel.messages.mofile import write_mo
    from babel.messages.pofile import read_po, write_po
except ImportError:  # pragma: no cover - dépendance déclarée dans requirements.txt
    Catalog = None


# Fonctions reconnues comme appels de traduction (spécification Babel : index des
# arguments singulier / pluriel / contexte).
KEYWORDS = {
    '_': None,
    'gettext': None,
    'gettext_lazy': None,
    'gettext_noop': None,
    'N_': None,
    'ngettext': (1, 2),
    'ngettext_lazy': (1, 2),
    'pgettext': ((1, 'c'), 2),
    'pgettext_lazy': ((1, 'c'), 2),
    'npgettext': ((1, 'c'), 2, 3),
    'npgettext_lazy': ((1, 'c'), 2, 3),
}
COMMENT_TAGS = ('Translators',)

PY_EXCLUDED_DIRS = {
    'venv', '.venv', 'env', 'ENV', 'node_modules', 'staticfiles', 'mediafiles',
    'media', 'migrations', 'locale', '.git', '__pycache__', 'build', 'dist',
}
TEMPLATE_EXTENSIONS = ('.html', '.txt')

SCRIPT_RE = re.compile(r'<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script>', re.S | re.I)
TEMPLATE_TAG_RE = re.compile(r'{%.*?%}|{{.*?}}|{#.*?#}', re.S)

# Le lexer JavaScript de Babel traite un template literal `...${gettext('x')}...` comme un seul
# jeton : les appels imbriqués dans ``${}`` lui échappent. Cette seconde passe repère tout appel
# gettext/ngettext/pgettext/npgettext dont les arguments sont des littéraux de chaîne.
_JS_STR = r"""(?:'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*")"""
JS_CALL_RE = re.compile(
    r'\b(?P<func>npgettext|ngettext|pgettext|gettext)\s*\(\s*(?P<a>' + _JS_STR + r')'
    r'(?:\s*,\s*(?P<b>' + _JS_STR + r'))?(?:\s*,\s*(?P<c>' + _JS_STR + r'))?'
)


def _is_translated(message):
    """Vrai si la chaîne (ou toutes ses formes plurielles) est traduite et non floue."""
    if message.fuzzy:
        return False
    if isinstance(message.string, (tuple, list)):
        return all(message.string)
    return bool(message.string)


def _blank(text):
    """Remplace tout sauf les retours à la ligne par des espaces (conserve la numérotation)."""
    return re.sub(r'[^\n]', ' ', text)


def _inline_scripts(template_source):
    """Retourne le code JS des <script> inline d'un template, le reste étant blanchi."""
    out = []
    pos = 0
    found = False
    for match in SCRIPT_RE.finditer(template_source):
        out.append(_blank(template_source[pos:match.start('body')]))
        if re.search(r'\bsrc\s*=', match.group('attrs')):
            out.append(_blank(match.group('body')))
        else:
            found = True
            out.append(TEMPLATE_TAG_RE.sub(lambda m: _blank(m.group(0)), match.group('body')))
        pos = match.end('body')
    if not found:
        return None
    out.append(_blank(template_source[pos:]))
    return ''.join(out)


class Command(BaseCommand):
    help = "Extraction (extract), compilation (compile) et vérification (check) des traductions, sans gettext."

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['extract', 'compile', 'check'])
        parser.add_argument(
            '--locale', '-l', action='append', dest='locales',
            help="Langue(s) cible(s) (défaut : toutes celles de settings.LANGUAGES sauf la langue source).",
        )

    # ------------------------------------------------------------------ utils
    @property
    def base_dir(self):
        return Path(settings.BASE_DIR)

    @property
    def locale_dir(self):
        return Path(settings.LOCALE_PATHS[0])

    def target_locales(self, options):
        if options.get('locales'):
            return options['locales']
        source = settings.LANGUAGE_CODE.split('-')[0]
        return [code for code, _name in settings.LANGUAGES if code.split('-')[0] != source]

    def rel(self, path):
        try:
            return str(Path(path).relative_to(self.base_dir))
        except ValueError:
            return str(path)

    def po_path(self, locale, domain):
        return self.locale_dir / locale / 'LC_MESSAGES' / f'{domain}.po'

    # ------------------------------------------------------------------ handle
    def handle(self, *args, **options):
        if Catalog is None:
            raise CommandError("Babel n'est pas installé : pip install -r requirements.txt")
        action = options['action']
        if action == 'extract':
            self.do_extract(options)
        elif action == 'compile':
            self.do_compile(options)
        else:
            self.do_check(options)

    # ----------------------------------------------------------------- extract
    def do_extract(self, options):
        catalogs = {'django': Catalog(charset='utf-8'), 'djangojs': Catalog(charset='utf-8')}
        self._extract_python(catalogs['django'])
        self._extract_templates(catalogs['django'], catalogs['djangojs'])
        self._extract_javascript(catalogs['djangojs'])

        for domain, template in catalogs.items():
            self.stdout.write(f"{domain}: {len(template)} chaîne(s) trouvée(s)")

        for locale in self.target_locales(options):
            for domain, template in catalogs.items():
                path = self.po_path(locale, domain)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    with open(path, 'rb') as fh:
                        catalog = read_po(fh, locale=locale, domain=domain)
                    catalog.update(template, no_fuzzy_matching=False)
                else:
                    catalog = Catalog(locale=locale, domain=domain, charset='utf-8',
                                      project='Blanco', version='1.0')
                    for message in template:
                        if message.id:
                            catalog[message.id] = message.clone()
                catalog.fuzzy = False
                catalog.project = 'Blanco'
                catalog.version = '1.0'
                with open(path, 'wb') as fh:
                    write_po(fh, catalog, width=100, sort_by_file=True, include_previous=False)
                untranslated = sum(1 for m in catalog if m.id and not _is_translated(m))
                self.stdout.write(f"  {self.rel(path)} mis à jour ({len(catalog)} chaînes, {untranslated} à traduire)")

    def _add(self, catalog, method, source, origin):
        fileobj = io.BytesIO(source.encode('utf-8'))
        try:
            results = list(extract(method, fileobj, keywords=KEYWORDS, comment_tags=COMMENT_TAGS,
                                   options={'encoding': 'utf-8'}))
        except Exception as exc:  # syntaxe inattendue : on signale sans interrompre
            self.stderr.write(f"  [ignoré] {self.rel(origin)} : {exc}")
            return
        if method == 'javascript':
            results.extend(self._js_literal_calls(source))
        rel = self.rel(origin)
        for lineno, message, comments, context in results:
            if not message or (isinstance(message, str) and not message.strip()):
                continue
            existing = catalog.get(message, context)
            if existing is not None and (rel, lineno) in existing.locations:
                continue  # déjà vu par l'autre passe
            catalog.add(message, None, [(rel, lineno)], auto_comments=comments, context=context)

    @staticmethod
    def _js_literal_calls(source):
        """Appels gettext(...) à arguments littéraux, y compris dans les template literals."""
        from babel.messages.jslexer import unquote_string

        for match in JS_CALL_RE.finditer(source):
            lineno = source.count('\n', 0, match.start()) + 1
            args = [unquote_string(match.group(g)) for g in ('a', 'b', 'c') if match.group(g) is not None]
            func = match.group('func')
            if func == 'gettext':
                yield lineno, args[0], [], None
            elif func == 'ngettext' and len(args) >= 2:
                yield lineno, (args[0], args[1]), [], None
            elif func == 'pgettext' and len(args) >= 2:
                yield lineno, args[1], [], args[0]
            elif func == 'npgettext' and len(args) >= 3:
                yield lineno, (args[1], args[2]), [], args[0]

    def _iter_files(self, root, extensions, excluded=()):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in excluded)
            for filename in sorted(filenames):
                if filename.endswith(extensions):
                    yield Path(dirpath) / filename

    def _extract_python(self, catalog):
        for path in self._iter_files(self.base_dir, ('.py',), PY_EXCLUDED_DIRS):
            self._add(catalog, 'python', path.read_text(encoding='utf-8'), path)

    def _template_dirs(self):
        dirs = [Path(d) for d in settings.TEMPLATES[0].get('DIRS', [])]
        for app_config in apps.get_app_configs():
            candidate = Path(app_config.path) / 'templates'
            if not candidate.is_dir():
                continue
            try:
                parts = candidate.relative_to(self.base_dir).parts
            except ValueError:  # application installée hors du projet (venv système, etc.)
                continue
            if not any(part in PY_EXCLUDED_DIRS for part in parts):
                dirs.append(candidate)
        seen, result = set(), []
        for d in dirs:
            if d.is_dir() and d.resolve() not in seen:
                seen.add(d.resolve())
                result.append(d)
        return result

    def _extract_templates(self, catalog, js_catalog):
        for tdir in self._template_dirs():
            for path in self._iter_files(tdir, TEMPLATE_EXTENSIONS):
                source = path.read_text(encoding='utf-8')
                try:
                    pseudo_python = templatize(source, origin=str(path))
                except Exception as exc:
                    raise CommandError(f"{self.rel(path)} : {exc}")
                # templatize() conserve l'indentation du HTML ; le tokenizer Python (utilisé par
                # Babel) la refuserait comme indentation incohérente : on aplatit chaque ligne.
                pseudo_python = re.sub(r'(?m)^[ \t]+', '', pseudo_python)
                self._add(catalog, 'python', pseudo_python, path)
                scripts = _inline_scripts(source)
                if scripts:
                    self._add(js_catalog, 'javascript', scripts, path)

    def _extract_javascript(self, catalog):
        roots = [Path(d) for d in getattr(settings, 'STATICFILES_DIRS', [])]
        for root in roots:
            for path in self._iter_files(root, ('.js',), {'vendor', 'node_modules'}):
                self._add(catalog, 'javascript', path.read_text(encoding='utf-8'), path)

    # ----------------------------------------------------------------- compile
    def _po_files(self, options):
        locales = self.target_locales(options)
        for locale in locales:
            for domain in ('django', 'djangojs'):
                path = self.po_path(locale, domain)
                if path.exists():
                    yield locale, domain, path

    def do_compile(self, options):
        count = 0
        for locale, domain, path in self._po_files(options):
            with open(path, 'rb') as fh:
                catalog = read_po(fh, locale=locale, domain=domain)
            mo_path = path.with_suffix('.mo')
            with open(mo_path, 'wb') as fh:
                write_mo(fh, catalog, use_fuzzy=False)
            count += 1
            self.stdout.write(f"{self.rel(mo_path)} compilé")
        if not count:
            self.stdout.write(self.style.WARNING("Aucun fichier .po trouvé dans %s" % self.rel(self.locale_dir)))

    # ------------------------------------------------------------------- check
    def do_check(self, options):
        problems = 0
        for locale, domain, path in self._po_files(options):
            with open(path, 'rb') as fh:
                catalog = read_po(fh, locale=locale, domain=domain)
            missing = [m for m in catalog if m.id and not m.fuzzy and not _is_translated(m)]
            fuzzy = [m for m in catalog if m.id and m.fuzzy]
            errors = list(catalog.check())
            self.stdout.write(
                f"{self.rel(path)} : {len(catalog)} chaînes, {len(missing)} non traduite(s), "
                f"{len(fuzzy)} floue(s), {len(errors)} erreur(s) de format"
            )
            for message in missing[:50]:
                self.stdout.write(f"  [manquante] {message.id!r}")
            for message in fuzzy[:50]:
                self.stdout.write(f"  [floue] {message.id!r}")
            for message, errs in errors:
                for err in errs:
                    self.stdout.write(self.style.ERROR(f"  [format] {message.id!r} : {err}"))
            problems += len(missing) + len(fuzzy) + len(errors)
        if problems:
            self.stdout.write(self.style.WARNING(f"{problems} point(s) à corriger"))
        else:
            self.stdout.write(self.style.SUCCESS("Toutes les traductions sont complètes"))
