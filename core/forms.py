"""
Formulaires Django pour l'application core.
"""

import json
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext, gettext_lazy as _
from core.models.inventory_models import Supply, Inventory
from core.models.product_models import Product
from core.models.user_models import Supplier, CustomUser
from core.models.accounting_models import (
    DailyExpense, DailyRecipe, ExpenseType, Payment, SupplierPayment,
    PAYMENT_METHOD_CHOICES, Account, RecipeType, TaxRate
)
from core.models.user_models import Client
from core.models.settings_models import SystemSettings, AppModule


class TaxRateSelect(forms.Select):
    """
    Select de taux de TVA qui expose ``rate``/``is_default`` sur chaque
    <option> (data-rate / data-is-default), pour le calcul de la TVA et la
    présélection automatique côté JS (core/templates/core/supplies_add.html).
    """

    def __init__(self, *args, rates_by_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.rates_by_id = rates_by_id or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        rate_info = self.rates_by_id.get(str(value))
        if rate_info:
            option['attrs']['data-rate'] = rate_info['rate']
            if rate_info['is_default']:
                option['attrs']['data-is-default'] = 'true'
        return option


class SupplyForm(forms.ModelForm):
    """Formulaire d'ajout d'approvisionnement."""

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Produit'),
        empty_label=_('-- Sélectionner un produit --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Fournisseur'),
        required=False,
        empty_label=_('-- Aucun fournisseur --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    quantity = forms.IntegerField(
        label=_('Quantité'),
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 50')}),
    )

    purchase_cost = forms.DecimalField(
        label=_("Prix d'achat unitaire (FCFA)"),
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': _('Prérempli selon le produit sélectionné'),
            'step': '1',
            'id': 'id_purchase_cost',
        }),
    )

    selling_price = forms.DecimalField(
        label=_('Prix de vente unitaire (FCFA)'),
        min_value=0,
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': _('Prérempli avec le prix de vente actuel du produit'),
            'step': '1',
            'id': 'id_selling_price',
        }),
    )

    expiration_date = forms.DateField(
        label=_("Date d'expiration"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    payment_method = forms.ChoiceField(
        label=_('Mode de paiement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    is_credit = forms.BooleanField(
        label=_('Achat à crédit'),
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    due_date = forms.DateField(
        label=_("Date d'échéance (pour achat à crédit)"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    tax_rate = forms.ModelChoiceField(
        queryset=TaxRate.objects.filter(delete_at__isnull=True, is_active=True).order_by('name'),
        label=_('Taux de TVA'),
        required=False,
        empty_label=_('-- Sans TVA --'),
        widget=TaxRateSelect(attrs={'class': 'form-control'}),
    )

    expense_type = forms.ModelChoiceField(
        queryset=ExpenseType.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Type de dépense (approvisionnement)'),
        required=False,
        empty_label=_('-- Sélectionner un type --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text=_('Ce type de dépense sera utilisé pour créer automatiquement la dépense liée à cet approvisionnement')
    )

    @staticmethod
    def _format_decimal_for_input(value):
        if value is None:
            return ''

        normalized = format(value, 'f')
        if '.' in normalized:
            normalized = normalized.rstrip('0').rstrip('.')
        return normalized

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pré-remplir le type de dépense depuis les paramètres système
        from core.models.settings_models import SystemSettings
        settings = SystemSettings.get_settings()
        if settings.default_supply_expense_type:
            self.initial['expense_type'] = settings.default_supply_expense_type

        # Exposer le taux (et le caractère "par défaut") de chaque taux de
        # TVA sur son <option>, pour le calcul et la présélection côté JS.
        self.fields['tax_rate'].widget.rates_by_id = {
            str(tax_rate.pk): {
                'rate': self._format_decimal_for_input(tax_rate.rate),
                'is_default': tax_rate.is_default,
            }
            for tax_rate in self.fields['tax_rate'].queryset
        }

        # Dernier fournisseur / mode de paiement / statut crédit utilisés par
        # produit, pour le préremplissage (un seul passage sur les
        # approvisionnements actifs, le plus récent par produit gagne).
        last_supply_by_product = {}
        for row in Supply.objects.filter(delete_at__isnull=True).order_by('-create_at', '-id').values(
            'product_id', 'supplier_id', 'payment_method', 'is_credit'
        ):
            last_supply_by_product.setdefault(row['product_id'], row)

        # Ajouter les métadonnées du produit pour le préremplissage et la TVA.
        active_products = Product.objects.filter(delete_at__isnull=True).only(
            'id', 'has_vat', 'actual_price', 'last_purchase_price'
        )
        product_meta_map = {}
        for product in active_products:
            last_supply = last_supply_by_product.get(product.id)
            product_meta_map[str(product.id)] = {
                'has_vat': product.has_vat,
                'selling_price': self._format_decimal_for_input(product.actual_price),
                'purchase_cost': self._format_decimal_for_input(product.last_purchase_price),
                'last_supplier_id': last_supply['supplier_id'] if last_supply else None,
                'last_payment_method': last_supply['payment_method'] if last_supply else None,
                'last_is_credit': last_supply['is_credit'] if last_supply else False,
            }
        self.fields['product'].widget.attrs['data-product-meta-map'] = json.dumps(product_meta_map)

    class Meta:
        model = Supply
        fields = ['product', 'supplier', 'quantity', 'purchase_cost', 'selling_price', 'expiration_date', 'is_credit', 'tax_rate', 'expense_type']

    def clean_expiration_date(self):
        exp_date = self.cleaned_data.get('expiration_date')
        if exp_date:
            from datetime import date
            if exp_date <= date.today():
                raise forms.ValidationError(gettext("La date d'expiration doit être postérieure à aujourd'hui."))
        return exp_date

    def clean(self):
        cleaned_data = super().clean()
        purchase_cost = cleaned_data.get('purchase_cost')
        selling_price = cleaned_data.get('selling_price')
        product = cleaned_data.get('product')
        tax_rate = cleaned_data.get('tax_rate')

        if selling_price is not None and purchase_cost is not None:
            if selling_price <= purchase_cost:
                self.add_error('selling_price', gettext("Le prix de vente doit être supérieur au prix d'achat."))

        # Vérifier que la TVA est fournie si le produit y est sujet
        if product and product.has_vat and not tax_rate:
            self.add_error('tax_rate', gettext('Ce produit est soumis à la TVA. Veuillez sélectionner un taux de TVA.'))

        return cleaned_data


class PurchaseOrderForm(forms.Form):
    """
    Formulaire de commande fournisseur.

    Volontairement plus court que ``SupplyForm`` : à la commande, ni le
    stock ni l'écriture comptable ne sont touchés (voir
    ``SupplyService.receive_purchase_order``), donc le mode de paiement, la
    TVA et le type de dépense — qui ne concernent que la réception — n'ont
    pas leur place ici. Formulaire simple (non lié à un modèle) : la création
    passe systématiquement par ``SupplyService.create_purchase_order``.
    """

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Produit'),
        empty_label=_('-- Sélectionner un produit --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Fournisseur'),
        required=False,
        empty_label=_('-- Aucun fournisseur --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    quantity = forms.IntegerField(
        label=_('Quantité commandée'),
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 50')}),
    )

    purchase_cost = forms.DecimalField(
        label=_("Prix d'achat unitaire estimé (FCFA)"),
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '1'}),
        help_text=_("Pourra être ajusté au montant réel à la réception."),
    )


class ReceiveSupplyForm(forms.Form):
    """
    Formulaire de réception d'une commande fournisseur : les décisions liées
    au paiement (mode, crédit, TVA, type de dépense) sont prises maintenant,
    au moment où la marchandise et la facture arrivent réellement.
    """

    purchase_cost = forms.DecimalField(
        label=_("Prix d'achat unitaire réel (FCFA)"),
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '1'}),
    )

    selling_price = forms.DecimalField(
        label=_('Prix de vente unitaire (FCFA)'),
        min_value=0,
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '1'}),
    )

    payment_method = forms.ChoiceField(
        label=_('Mode de paiement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    is_credit = forms.BooleanField(
        label=_('Achat à crédit'),
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    due_date = forms.DateField(
        label=_("Date d'échéance (pour achat à crédit)"),
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    tax_rate = forms.ModelChoiceField(
        queryset=TaxRate.objects.filter(delete_at__isnull=True, is_active=True).order_by('name'),
        label=_('Taux de TVA'),
        required=False,
        empty_label=_('-- Sans TVA --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    expense_type = forms.ModelChoiceField(
        queryset=ExpenseType.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Type de dépense (approvisionnement)'),
        required=False,
        empty_label=_('-- Sélectionner un type --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._product = product
        from core.models.settings_models import SystemSettings
        settings = SystemSettings.get_settings()
        if settings.default_supply_expense_type:
            self.initial['expense_type'] = settings.default_supply_expense_type

    def clean(self):
        cleaned_data = super().clean()
        purchase_cost = cleaned_data.get('purchase_cost')
        selling_price = cleaned_data.get('selling_price')
        tax_rate = cleaned_data.get('tax_rate')

        if selling_price is not None and purchase_cost is not None and selling_price <= purchase_cost:
            self.add_error('selling_price', gettext("Le prix de vente doit être supérieur au prix d'achat."))

        if self._product is not None and self._product.has_vat and not tax_rate:
            self.add_error('tax_rate', gettext('Ce produit est soumis à la TVA. Veuillez sélectionner un taux de TVA.'))

        return cleaned_data


class ExpenseForm(forms.ModelForm):
    """Formulaire d'ajout de dépense quotidienne."""

    expense_type = forms.ModelChoiceField(
        queryset=ExpenseType.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Type de dépense'),
        empty_label=_('-- Sélectionner un type --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    amount = forms.DecimalField(
        label=_('Montant (FCFA)'),
        min_value=1,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 5000'), 'step': '1'}),
    )

    description = forms.CharField(
        label=_('Description'),
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': _('Description de la dépense (optionnel)'),
            'rows': 3,
        }),
    )

    payment_method = forms.ChoiceField(
        label=_('Mode de paiement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True, delete_at__isnull=True).order_by('code'),
        label=_('Compte comptable (optionnel)'),
        required=False,
        empty_label=_('-- Par défaut (6xx) --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = DailyExpense
        fields = ['expense_type', 'amount', 'description', 'account', 'payment_method']


class RecipeForm(forms.ModelForm):
    """Formulaire d'ajout de recette quotidienne."""

    recipe_type = forms.ModelChoiceField(
        queryset=RecipeType.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Type de recette'),
        empty_label=_('-- Sélectionner un type --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    amount = forms.DecimalField(
        label=_('Montant (FCFA)'),
        min_value=1,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 5000'), 'step': '1'}),
    )

    description = forms.CharField(
        label=_('Description'),
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': _('Description de la recette (optionnel)'),
            'rows': 3,
        }),
    )

    payment_method = forms.ChoiceField(
        label=_('Mode de paiement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True, delete_at__isnull=True).order_by('code'),
        label=_('Compte comptable (optionnel)'),
        required=False,
        empty_label=_('-- Par défaut (7xx) --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = DailyRecipe
        fields = ['recipe_type', 'amount', 'description', 'account']


GENDER_CHOICES = [
    ('', _('-- Non spécifié --')),
    ('M', _('Masculin')),
    ('F', _('Féminin')),
]


class ClientForm(forms.ModelForm):
    """Formulaire de création/modification de client."""

    firstname = forms.CharField(
        label=_('Prénom'),
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Prénom du client')}),
    )

    lastname = forms.CharField(
        label=_('Nom'),
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Nom du client')}),
    )

    phone_number = forms.CharField(
        label=_('Téléphone'),
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 6XXXXXXXX')}),
    )

    email = forms.EmailField(
        label=_('Email'),
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': _('email@exemple.com')}),
    )

    gender = forms.ChoiceField(
        label=_('Genre'),
        choices=GENDER_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = Client
        fields = ['firstname', 'lastname', 'phone_number', 'email', 'gender']


class StaffForm(forms.ModelForm):
    """
    Formulaire de création/modification d'un membre du personnel.

    À la création (``editing=False``), un mot de passe est requis. En
    modification, les champs de mot de passe sont retirés : la
    réinitialisation passe par un formulaire dédié (``StaffPasswordResetForm``)
    pour ne pas mélanger les deux actions dans un même écran.
    """

    password1 = forms.CharField(
        label=_('Mot de passe'),
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    password2 = forms.CharField(
        label=_('Confirmer le mot de passe'),
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    allowed_modules = forms.ModelMultipleChoiceField(
        queryset=AppModule.objects.all().order_by('order'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_('Modules autorisés'),
        help_text=_("Sans effet pour un administrateur : il a accès à tout."),
    )

    class Meta:
        model = CustomUser
        fields = [
            'username', 'firstname', 'lastname', 'email', 'phone_number',
            'role', 'gender', 'is_superuser', 'is_active', 'allowed_modules',
        ]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'firstname': forms.TextInput(attrs={'class': 'form-control'}),
            'lastname': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Ex: Caissière, Gérant...')}),
            'gender': forms.Select(choices=GENDER_CHOICES, attrs={'class': 'form-control'}),
            'is_superuser': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'is_superuser': _('Administrateur (accès total)'),
            'is_active': _('Compte actif'),
        }

    def __init__(self, *args, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.editing = editing
        if editing:
            del self.fields['password1']
            del self.fields['password2']
        else:
            self.fields['password1'].required = True
            self.fields['password2'].required = True
            # Toujours actif à la création : la désactivation est une action
            # dédiée (case à cocher non soumise = False, ce qui créerait un
            # compte inutilisable par défaut si le champ restait ici).
            del self.fields['is_active']

    def clean_username(self):
        username = self.cleaned_data['username']
        qs = CustomUser.objects.filter(username=username)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("Ce nom d'utilisateur est déjà utilisé."))
        return username

    def clean(self):
        cleaned_data = super().clean()
        if not self.editing:
            password1 = cleaned_data.get('password1')
            password2 = cleaned_data.get('password2')
            if password1 and password2 and password1 != password2:
                self.add_error('password2', _('Les mots de passe ne correspondent pas.'))
            elif password1:
                try:
                    validate_password(password1)
                except DjangoValidationError as exc:
                    self.add_error('password1', exc)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if not self.editing:
            user.set_password(self.cleaned_data['password1'])
            user.is_active = True
        if commit:
            user.save()
            self.save_m2m()
        return user


class StaffPasswordResetForm(forms.Form):
    """Réinitialisation du mot de passe d'un membre du personnel par un administrateur."""

    new_password1 = forms.CharField(
        label=_('Nouveau mot de passe'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )
    new_password2 = forms.CharField(
        label=_('Confirmer le nouveau mot de passe'),
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('new_password1')
        password2 = cleaned_data.get('new_password2')
        if password1 and password2 and password1 != password2:
            self.add_error('new_password2', _('Les mots de passe ne correspondent pas.'))
        elif password1:
            try:
                validate_password(password1)
            except DjangoValidationError as exc:
                self.add_error('new_password1', exc)
        return cleaned_data


class InventoryForm(forms.ModelForm):
    """Formulaire d'ajout d'inventaire."""

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Produit'),
        empty_label=_('-- Sélectionner un produit --'),
        widget=forms.HiddenInput(attrs={'id': 'id_product'}),
    )

    valid_product_count = forms.IntegerField(
        label=_('Produits valides'),
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 50')}),
    )

    invalid_product_count = forms.IntegerField(
        label=_('Produits invalides'),
        min_value=0,
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 3')}),
    )

    notes = forms.CharField(
        label=_('Notes'),
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': _('Notes ou observations (optionnel)'),
            'rows': 3,
        }),
    )

    class Meta:
        model = Inventory
        fields = ['product', 'valid_product_count', 'invalid_product_count', 'notes']


MIGRATION_TEXTAREA_ATTRS = {
    'class': 'form-control',
    'rows': 6,
    'style': 'font-family: monospace; font-size: 12px;',
}


class DataMigrationForm(forms.Form):
    """Formulaire de migration des données depuis l'ancien système SQL."""

    categories_sql = forms.CharField(
        label=_('Catégories (SQL VALUES)'),
        required=False,
        help_text=_('Colonnes: id, name, description, create_at, delete_at'),
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'placeholder': "(1,'VIN',NULL,'2024-03-06 10:05:31',NULL),(2,'WHISKY',NULL,...)",
        }),
    )

    gammes_sql = forms.CharField(
        label=_('Gammes (SQL VALUES)'),
        required=False,
        help_text=_('Colonnes: id, name, description, create_at, delete_at'),
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'placeholder': "(1,'350g',NULL,'2024-03-13 11:25:23',NULL),...",
        }),
    )

    rayons_sql = forms.CharField(
        label=_('Rayons (SQL VALUES)'),
        required=False,
        help_text=_('Colonnes: id, name, description, create_at, delete_at'),
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'placeholder': "(1,'A',NULL,'2024-03-06 10:05:59',NULL),...",
        }),
    )

    grammage_types_sql = forms.CharField(
        label=_('Types de grammage (SQL VALUES)'),
        required=False,
        help_text=_('Colonnes: id, name, description, create_at, delete_at'),
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'placeholder': "(1,'LITRE',NULL,'2024-03-06 10:11:35',NULL),...",
        }),
    )

    products_sql = forms.CharField(
        label=_('Produits (SQL VALUES)'),
        required=False,
        help_text=_('Colonnes: id, code, name, description, brand, color, stock_limit, grammage, exp_alert_period, is_price_reducible, grammage_type_id, gamme_id, category_id, rayon_id, create_at, delete_at, max_salable_price'),
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'rows': 10,
            'placeholder': "(3,'6171100130059','huile oleo 5l','','',NULL,NULL,NULL,NULL,0,NULL,NULL,7,1,'2024-03-06 10:27:39',NULL,NULL),...",
        }),
    )

    images_sql = forms.CharField(
        label=_('Images produits (SQL VALUES)'),
        required=False,
        help_text=_('Colonnes: id, path, description, product_id, create_at, delete_at'),
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'rows': 8,
            'placeholder': "(3,'b8480c8d-f477...8921310146555742365.jpg','',3,'2024-03-06 10:27:40',NULL),...",
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        # Au moins un champ doit être rempli
        has_data = any(
            cleaned_data.get(field, '').strip()
            for field in [
                'categories_sql', 'gammes_sql', 'rayons_sql',
                'grammage_types_sql', 'products_sql', 'images_sql',
            ]
        )
        if not has_data:
            raise forms.ValidationError(
                gettext("Veuillez remplir au moins un champ avec des données à migrer.")
            )
        return cleaned_data


class SupplierForm(forms.ModelForm):
    """Formulaire de création/modification de fournisseur (entreprise)."""

    name = forms.CharField(
        label=_("Nom de l'entreprise"),
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _("Nom de l'entreprise")}),
    )

    address = forms.CharField(
        label=_('Adresse'),
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': _('Adresse du fournisseur'), 'rows': 2}),
    )

    niu = forms.CharField(
        label=_('NIU'),
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Numéro d\'Identifiant Unique')}),
    )

    contact_phone = forms.CharField(
        label=_('Téléphone'),
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 6XXXXXXXX')}),
    )

    contact_email = forms.EmailField(
        label=_('Email'),
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': _('email@exemple.com')}),
    )

    website = forms.URLField(
        label=_('Site web'),
        required=False,
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': _('https://www.exemple.com')}),
    )

    description = forms.CharField(
        label=_('Description'),
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': _('Description du fournisseur'), 'rows': 3}),
    )

    class Meta:
        model = Supplier
        fields = ['name', 'address', 'niu', 'contact_phone', 'contact_email', 'website', 'description']



# ── Formulaires Phase 2 — Paiements ──────────────────────────────────

class PaymentForm(forms.ModelForm):
    """Formulaire d'enregistrement d'un paiement sur vente à crédit."""

    amount = forms.DecimalField(
        label=_('Montant (FCFA)'),
        min_value=1,
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Montant du paiement'), 'step': '1'}),
    )

    payment_method = forms.ChoiceField(
        label=_('Mode de paiement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    payment_date = forms.DateField(
        label=_('Date de paiement'),
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    reference = forms.CharField(
        label=_('Référence (n° chèque, ID transaction...)'),
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Référence (optionnel)')}),
    )

    notes = forms.CharField(
        label=_('Notes'),
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': _('Notes (optionnel)'), 'rows': 2}),
    )

    class Meta:
        model = Payment
        fields = ['amount', 'payment_method', 'payment_date', 'reference', 'notes']

    def __init__(self, *args, credit_sale=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.credit_sale = credit_sale
        if not self.initial.get('payment_date'):
            from datetime import date
            self.initial['payment_date'] = date.today()

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if self.credit_sale and amount:
            if amount > self.credit_sale.amount_remaining:
                raise forms.ValidationError(
                    gettext("Le montant dépasse le solde restant (%(remaining)s FCFA).")
                    % {'remaining': format(self.credit_sale.amount_remaining, ',.0f')}
                )
        return amount


class SaleCancellationForm(forms.Form):
    """Formulaire minimal d'annulation totale d'une vente."""

    reason = forms.CharField(
        label=_("Motif d'annulation"),
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': _('Ex: retour client / erreur de caisse'),
        }),
    )

    refund_payment_method = forms.ChoiceField(
        label=_('Mode de remboursement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, sale=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sale = sale

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError(gettext("Veuillez préciser le motif d'annulation."))
        return reason

    def clean(self):
        cleaned_data = super().clean()
        if self.sale and self.sale.delete_at is not None:
            raise forms.ValidationError(gettext("Cette vente est déjà annulée."))
        return cleaned_data


class SalePartialReturnForm(forms.Form):
    """Formulaire dynamique de retour partiel par ligne de vente."""

    reason = forms.CharField(
        label=_("Motif du retour"),
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': _('Ex: produit abîmé / retour partiel client'),
        }),
    )

    refund_payment_method = forms.ChoiceField(
        label=_('Mode de remboursement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, sale=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sale = sale
        self.sale_lines = []

        if sale is not None:
            self.sale_lines = list(
                sale.sale_products.filter(delete_at__isnull=True, quantity__gt=0).select_related('product')
            )
            for sale_product in self.sale_lines:
                field_name = f'return_quantity_{sale_product.id}'
                self.fields[field_name] = forms.IntegerField(
                    required=False,
                    min_value=0,
                    initial=0,
                    label=gettext("%(product)s (max %(max)s)") % {
                        'product': sale_product.product.name, 'max': sale_product.quantity,
                    },
                    widget=forms.NumberInput(attrs={
                        'class': 'form-control',
                        'min': 0,
                        'max': sale_product.quantity,
                        'step': 1,
                    }),
                )

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError(gettext("Veuillez préciser le motif du retour."))
        return reason

    def clean(self):
        cleaned_data = super().clean()
        if self.sale and self.sale.delete_at is not None:
            raise forms.ValidationError(gettext("Cette vente est déjà annulée."))
        if not self.sale_lines:
            raise forms.ValidationError(gettext("Aucune ligne active n'est disponible pour ce retour."))

        returned_items = []
        remaining_quantity_exists = False

        for sale_product in self.sale_lines:
            field_name = f'return_quantity_{sale_product.id}'
            quantity = cleaned_data.get(field_name) or 0

            if quantity > sale_product.quantity:
                self.add_error(field_name, gettext("Maximum autorisé : %(max)s.") % {'max': sale_product.quantity})
                continue

            if quantity > 0:
                returned_items.append({
                    'sale_product': sale_product,
                    'quantity': quantity,
                })

            if sale_product.quantity - quantity > 0:
                remaining_quantity_exists = True

        if self.errors:
            return cleaned_data

        if not returned_items:
            raise forms.ValidationError(gettext("Veuillez renseigner au moins une quantité à retourner."))
        if not remaining_quantity_exists:
            raise forms.ValidationError(gettext("Ce retour couvre toute la vente. Utilisez l'annulation totale."))

        cleaned_data['returned_items'] = returned_items
        return cleaned_data


class SupplyCancellationForm(forms.Form):
    """Formulaire minimal d'annulation totale d'un approvisionnement."""

    reason = forms.CharField(
        label=_("Motif d'annulation"),
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': _('Ex: retour fournisseur / erreur de réception'),
        }),
    )

    refund_payment_method = forms.ChoiceField(
        label=_('Mode de remboursement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, supply=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.supply = supply

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError(gettext("Veuillez préciser le motif d'annulation."))
        return reason

    def clean(self):
        cleaned_data = super().clean()
        if self.supply and self.supply.delete_at is not None:
            raise forms.ValidationError(gettext("Cet approvisionnement est déjà annulé."))
        return cleaned_data


class SupplyPartialReturnForm(forms.Form):
    """Formulaire de retour partiel d'un approvisionnement fournisseur."""

    returned_quantity = forms.IntegerField(
        label=_('Quantité à retourner'),
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': 1,
            'step': 1,
        }),
    )

    reason = forms.CharField(
        label=_("Motif du retour"),
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': _('Ex: marchandise défectueuse / écart de livraison'),
        }),
    )

    refund_payment_method = forms.ChoiceField(
        label=_('Mode de remboursement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, supply=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.supply = supply

        if supply is not None:
            self.fields['returned_quantity'].label = (
                gettext("Quantité à retourner (max %(max)s)") % {'max': max(supply.quantity - 1, 1)}
            )
            self.fields['returned_quantity'].widget.attrs['max'] = max(supply.quantity - 1, 1)

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError(gettext("Veuillez préciser le motif du retour."))
        return reason

    def clean(self):
        cleaned_data = super().clean()
        returned_quantity = cleaned_data.get('returned_quantity') or 0

        if self.supply and self.supply.delete_at is not None:
            raise forms.ValidationError(gettext("Cet approvisionnement est déjà annulé."))
        if self.supply and self.supply.quantity <= 1:
            raise forms.ValidationError(
                gettext("Ce retour couvre tout l'approvisionnement. Utilisez l'annulation totale.")
            )
        if self.supply and returned_quantity > self.supply.quantity:
            self.add_error('returned_quantity', gettext("Maximum autorisé : %(max)s.") % {'max': self.supply.quantity})
        if self.supply and returned_quantity >= self.supply.quantity:
            raise forms.ValidationError(
                gettext("Ce retour couvre tout l'approvisionnement. Utilisez l'annulation totale.")
            )
        return cleaned_data


class SupplierPaymentForm(forms.ModelForm):
    """Formulaire d'enregistrement d'un paiement fournisseur."""

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Fournisseur'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    amount = forms.DecimalField(
        label=_('Montant (FCFA)'),
        min_value=1,
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': _('Montant du paiement'), 'step': '1'}),
    )

    payment_method = forms.ChoiceField(
        label=_('Mode de paiement'),
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    payment_date = forms.DateField(
        label=_('Date de paiement'),
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    reference = forms.CharField(
        label=_('Référence'),
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Référence (optionnel)')}),
    )

    notes = forms.CharField(
        label=_('Notes'),
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': _('Notes (optionnel)'), 'rows': 2}),
    )

    class Meta:
        model = SupplierPayment
        fields = ['supplier', 'amount', 'payment_method', 'payment_date', 'reference', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get('payment_date'):
            from datetime import date
            self.initial['payment_date'] = date.today()


# ──────────────────────────────────────────────────────────────────────────────
# Formulaire d'écriture comptable manuelle (Journal des Opérations Diverses)
# ──────────────────────────────────────────────────────────────────────────────

from core.models.accounting_models import Account, JournalEntry, JournalEntryLine, Exercise


class JournalEntryForm(forms.Form):
    """Formulaire pour créer une écriture comptable manuelle."""

    date = forms.DateField(
        label=_('Date'),
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    description = forms.CharField(
        label=_('Libellé de l\'écriture'),
        max_length=500,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Description de l\'opération')}),
    )

    # Pour les lignes d'écriture
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialiser la date du jour
        if not self.initial.get('date'):
            from datetime import date
            self.initial['date'] = date.today()

    def clean(self):
        cleaned_data = super().clean()
        # La validation des lignes se fera côté vue
        return cleaned_data


class JournalEntryLineForm(forms.Form):
    """Formulaire pour une ligne d'écriture comptable."""

    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(
            is_active=True, delete_at__isnull=True
        ).order_by('code'),
        label=_('Compte'),
        widget=forms.Select(attrs={'class': 'form-control account-select'}),
    )

    debit = forms.DecimalField(
        label=_('Débit'),
        required=False,
        min_value=0,
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control amount-input debit-input',
            'placeholder': '0.00',
            'step': '0.01',
            'min': '0'
        }),
    )

    credit = forms.DecimalField(
        label=_('Crédit'),
        required=False,
        min_value=0,
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control amount-input credit-input',
            'placeholder': '0.00',
            'step': '0.01',
            'min': '0'
        }),
    )

    line_description = forms.CharField(
        label=_('Libellé ligne'),
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Libellé (optionnel)')
        }),
    )


class ProductForm(forms.ModelForm):
    """
    Formulaire produit pour le back-office web.

    Le stock ne peut être saisi qu'à la création (``editing=False``) : il
    génère un approvisionnement initial via ``ProductService.create_product``.
    En modification, le champ est retiré du formulaire — le stock ne doit
    changer que via un approvisionnement ou un inventaire (traçabilité
    stock / comptabilité), jamais par une édition directe du produit.
    """

    class Meta:
        model = Product
        fields = [
            'code', 'name', 'description', 'brand', 'color', 'stock',
            'stock_limit', 'min_salable_price', 'max_salable_price', 'last_purchase_price', 'actual_price',
            'exp_alert_period', 'grammage', 'is_price_reducible', 'has_vat',
            'category', 'gamme', 'grammage_type', 'rayon',
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 6171100130059')}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'brand': forms.TextInput(attrs={'class': 'form-control'}),
            'color': forms.TextInput(attrs={'class': 'form-control'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'stock_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'min_salable_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'max_salable_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'last_purchase_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'actual_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'exp_alert_period': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'grammage': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'is_price_reducible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'has_vat': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'gamme': forms.Select(attrs={'class': 'form-control'}),
            'grammage_type': forms.Select(attrs={'class': 'form-control'}),
            'rayon': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ('category', 'gamme', 'grammage_type', 'rayon'):
            field = self.fields[field_name]
            field.queryset = field.queryset.filter(delete_at__isnull=True).order_by('name')
            field.empty_label = _('-- Aucun(e) --')
        if editing:
            del self.fields['stock']
        else:
            self.fields['stock'].required = False
            self.fields['stock'].help_text = _(
                "Génère un approvisionnement initial si supérieur à zéro."
            )

    def clean_stock(self):
        return self.cleaned_data.get('stock') or 0

    def clean_code(self):
        code = self.cleaned_data['code']
        qs = Product.objects.filter(code=code, delete_at__isnull=True)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_('Ce code produit est déjà utilisé.'))
        return code

    def clean(self):
        cleaned_data = super().clean()
        actual_price = cleaned_data.get('actual_price')
        min_salable_price = cleaned_data.get('min_salable_price')
        max_salable_price = cleaned_data.get('max_salable_price')

        if actual_price is not None and min_salable_price is not None and min_salable_price >= actual_price:
            self.add_error(
                'min_salable_price',
                _('Le prix minimum doit être inférieur au prix de vente du produit.'),
            )
        if actual_price is not None and max_salable_price is not None and max_salable_price <= actual_price:
            self.add_error(
                'max_salable_price',
                _('Le prix maximum doit être supérieur au prix de vente du produit.'),
            )
        return cleaned_data


class ReferenceDataForm(forms.Form):
    """
    Formulaire générique pour les données de référence produit (catégorie,
    gamme, rayon, type de grammage), qui partagent toutes les mêmes champs
    ``name``/``description``.
    """

    name = forms.CharField(
        label=_('Nom'),
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    description = forms.CharField(
        label=_('Description'),
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )


class TaxRateForm(forms.ModelForm):
    """Formulaire de gestion des taux de TVA configurables (menu Comptabilité)."""

    class Meta:
        model = TaxRate
        fields = ['name', 'rate', 'is_default', 'is_active', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class SystemSettingsForm(forms.ModelForm):
    """Formulaire d'édition des paramètres système (instance singleton, pk=1)."""

    default_supply_expense_type = forms.ModelChoiceField(
        queryset=ExpenseType.objects.filter(delete_at__isnull=True).order_by('name'),
        label=_('Type de dépense par défaut pour les approvisionnements'),
        required=False,
        empty_label=_('-- Aucun --'),
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text=_("Type de dépense proposé automatiquement sur la page d'ajout d'approvisionnement."),
    )

    class Meta:
        model = SystemSettings
        fields = [
            'company_name', 'company_address', 'company_phone', 'company_email',
            'company_website', 'company_logo',
            'tax_id', 'trade_register',
            'currency_symbol', 'currency_code',
            'receipt_header', 'receipt_footer',
            'low_stock_threshold',
            'enable_tva_accounting', 'tva_accounting_mode',
            'default_supply_expense_type',
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _("Nom de l'entreprise")}),
            'company_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': _("Adresse de l'entreprise")}),
            'company_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Ex: 6XXXXXXXX')}),
            'company_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': _('email@exemple.com')}),
            'company_website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'company_logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control'}),
            'trade_register': forms.TextInput(attrs={'class': 'form-control'}),
            'currency_symbol': forms.TextInput(attrs={'class': 'form-control'}),
            'currency_code': forms.TextInput(attrs={'class': 'form-control'}),
            'receipt_header': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': _('Texte affiché en haut des reçus/tickets')}),
            'receipt_footer': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': _('Texte affiché en bas des reçus/tickets')}),
            'low_stock_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'enable_tva_accounting': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tva_accounting_mode': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'enable_tva_accounting': _('Activer la comptabilité TVA'),
        }