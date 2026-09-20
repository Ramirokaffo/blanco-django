"""
Signaux de l'application core.

`seed_default_data` est branché sur `post_migrate` (voir CoreConfig.ready) :
après chaque `python manage.py migrate`, les données de référence
indispensables au fonctionnement de l'application sont créées si elles
manquent :

- les modules applicatifs (AppModule) : sans eux, aucun onglet n'apparaît
  dans la navigation et aucun module ne peut être attribué aux utilisateurs ;
- le plan comptable OHADA (Account) : sans lui, les écritures comptables
  des ventes / achats / dépenses échouent silencieusement.

Les deux initialisations sont idempotentes. Elles peuvent aussi être lancées
à la main : `python manage.py init_modules` et `python manage.py init_accounts`.
"""


def seed_default_data(sender, **kwargs):
    """Crée les modules applicatifs et le plan comptable manquants après `migrate`."""
    from core.models.settings_models import AppModule
    from core.services.accounting_service import AccountingService

    # `post_migrate` transmet l'alias réellement migré. Il DOIT être propagé :
    # sans lui, un `migrate --database=<alias>` sèmerait dans la base par
    # défaut au lieu de celle qui vient d'être créée, laissant la nouvelle
    # base sans modules ni plan comptable.
    using = kwargs.get('using')

    created_modules = AppModule.init_default_modules(using=using)
    created_accounts = AccountingService.init_chart_of_accounts(using=using)

    verbosity = kwargs.get('verbosity', 1)
    if verbosity >= 1 and (created_modules or created_accounts):
        print(
            f"✅ Données par défaut : {created_modules} module(s) applicatif(s) "
            f"et {created_accounts} compte(s) comptable(s) créé(s)."
        )
