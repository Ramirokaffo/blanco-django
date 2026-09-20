"""
Plan de contrôle de l'offre hébergée (SaaS).

Cette application n'existe que lorsque ``BLANCO_MODE=saas`` : elle n'est pas
chargée en installation mono-client. Elle vit exclusivement dans la base
``default`` et porte tout ce qui concerne *les* entreprises clientes
(routage, provisionnement, invitations, exploitation) — jamais leurs données
métier, qui restent dans ``core`` et dans la base propre à chaque société.

Règle d'architecture : ``core`` n'importe JAMAIS ``saas`` au niveau module.
L'inverse est permis.
"""

default_app_config = "saas.apps.SaasConfig"
