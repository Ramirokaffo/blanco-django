# Roadmap fonctionnelle — manques identifiés (hors sécurité)

Audit du 2026-09-22. Objectif : combler les manques fonctionnels critiques pour un
usage back-office autonome (sans dépendre de `/admin/` ni de l'app mobile), en
particulier en mode `saas` où `/admin/` n'est pas monté (`blanco/urls_tenant.py`).

Statut : `[ ]` à faire, `[~]` en cours, `[x]` fait.

## Phase 1 — Bloquant pour un usage quotidien autonome

- [x] **CRUD produit dans le back-office web.** `add_product`/`edit_product`
  (`core/forms.py:ProductForm`, passe par `ProductService`) /
  `delete_product` (soft-delete) ; le stock n'est modifiable qu'à la
  création (génère l'approvisionnement initial), jamais en édition. Tests :
  `ProductCrudPagesTests`.
- [x] **CRUD Catégories / Gammes / Rayons / Types de grammage** dans l'UI web
  (`product_references`/`add_reference`/`edit_reference`/`delete_reference`,
  page à onglets accessible depuis Produits). La désactivation est bloquée
  si des produits actifs y sont encore rattachés. Tests :
  `ProductCrudPagesTests.test_category_crud_via_web`,
  `test_reference_delete_blocked_when_products_attached`.
- [x] **Gestion du personnel (staff) depuis l'UI web**, réservée aux
  superusers (`core/decorators.py:superuser_required`) : `add_staff` /
  `edit_staff` (`StaffForm`, modules via checkboxes), `toggle_staff_active`
  (activer/désactiver en un clic) et `reset_staff_password`, tous protégés
  par le garde-fou `StaffService.ensure_not_last_superuser`. Intégré dans
  l'onglet Personnel de `contacts.html`. Les stubs orphelins `staff.html` et
  `clients.html` ("Contenu à venir…", jamais référencés) ont été supprimés.
  Tests : `StaffManagementPagesTests`.
- [x] **Page Paramètres fonctionnelle** : `SystemSettingsForm` (core/forms.py)
  édite le singleton `SystemSettings` (nom société, logo, adresse, NIF/RCCM,
  devise, en-tête/pied de ticket, seuil de stock bas, mode TVA) ; lien de nav
  réactivé. Tests : `SettingsPageTests`.
- [x] **TVA calculée ligne par ligne, pas sur le total de la vente.**
  `AccountingService.taxable_amount()` ventile désormais le TTC entre part
  taxable (`Product.has_vat=True`) et part exonérée ; `record_sale` et
  `record_deferred_tva_for_daily` ne calculent la TVA que sur la part
  taxable. Test : `SalesCancellationTests.test_record_sale_applies_vat_only_to_taxable_lines`.
- [x] **Protection du soft-delete dans `/admin/`.** Nouvelle base
  `SoftDeleteAdmin` (core/admin.py) désactive la suppression physique et
  ajoute une action « Désactiver la sélection » (`delete_at`) ; appliquée à
  `ProductAdmin`, `CategoryAdmin`, `GammeAdmin`, `RayonAdmin`,
  `GrammageTypeAdmin`.

## Phase 2 — Manques importants

- [x] **Workflow "commande fournisseur" distinct de la réception.**
  Nouveau modèle `PurchaseOrder` (table séparée de `Supply`, pas un statut
  dessus : une commande non reçue n'a ainsi aucune chance de polluer les
  nombreux totaux/rapports qui parcourent déjà `Supply.objects` en
  confiance — dashboard, statistiques, historique). `add_purchase_order`
  crée la commande sans toucher stock ni comptabilité ;
  `receive_purchase_order` crée le `Supply` réel (stock + écriture
  comptable + crédit fournisseur), exactement comme le faisait la création
  immédiate historique, mais déclenché à la réception ;
  `cancel_purchase_order` annule une commande non reçue (rien à
  contrepasser). Page dédiée liée depuis Approvisionnements. Tests :
  `PurchaseOrderWorkflowTests`.
- [x] **Facture PDF téléchargeable** : `InvoicePdfService` (reportlab, pur
  Python — pas de dépendance système, compatible avec le packaging
  PyInstaller/Windows) génère un PDF depuis `invoices.html` (bouton
  téléchargement). Le ticket de caisse reste au format HTML imprimante
  thermique existant (`window.print()`), jugé suffisant. Test :
  `InvoicePdfTests`.
- [x] **Alertes UI persistantes** pour stock bas et échéances de paiement en
  retard : cloche de notification dans le header (`alerts_context`,
  `components/header.html`), gated par module (`products`/`reports`),
  visible sur toutes les pages (plus seulement le dashboard). Pas d'email/SMS
  (aucune infra de messagerie requise en mode standalone). Tests :
  `AlertsBadgeTests`.
- [x] **Suppression (désactivation) client/fournisseur** : `delete_client`
  bloqué si créance en cours (`CreditSale` non soldée), `delete_supplier`
  bloqué si dette fournisseur en cours (`CreditSupply` non soldée). Tests :
  `ClientSupplierDeactivationTests`.
- [x] **Import/export en masse du catalogue produit (prix)** :
  `export_products_csv` / `import_products_csv`, mise à jour par code
  produit uniquement — ne crée jamais de produit, ne touche jamais au stock
  (cohérent avec `ProductService.update_product`). Tests :
  `ProductBulkImportExportTests`.
- [ ] Export Excel des rapports comptables (actuellement CSV/TXT
  uniquement) — nécessiterait une dépendance supplémentaire (openpyxl),
  reporté.

## Phase 3 — Manques structurants (scalabilité)

- [ ] Multi-dépôt / transfert de stock entre emplacements (stock = un entier
  global par produit aujourd'hui).
- [ ] Variantes produit (taille/couleur) et code-barres (génération,
  étiquette imprimable, lecture caméra côté web).
- [ ] Moteur de remises/promotions/grille tarifaire par client.
- [ ] CRM : fidélité, fiche client 360°.
- [ ] Sauvegarde/restauration depuis l'UI, devises multiples, journal
  d'audit consultable ("qui a fait quoi").
- [ ] Parité mobile : écrans comptabilité/trésorerie/crédits/rapports côté
  Flutter, et vraie file d'attente hors-ligne pour les ventes (le cache local
  ne fait aujourd'hui que du cache produit/réglages en lecture).

## Notes d'implémentation (phase 1)

- Respecter la couche `views.py` → `services/*` → `models/*` : toute
  création/modification de produit passe par `ProductService`, jamais par un
  `.save()` direct dans la vue.
- Chaque page nécessite `@login_required` + `@module_required('<code>')`
  (`core/decorators.py`) et une entrée de nav gated sur le même code.
- Toute chaîne visible doit être en français, entourée de `gettext`/`{% trans %}`,
  puis extraite (`python manage.py translations extract`) avec `msgstr`
  anglais ajouté dans `locale/en/LC_MESSAGES/`.
- Soft delete partout : `delete_at`, jamais de `.delete()` direct sur un
  modèle métier.
