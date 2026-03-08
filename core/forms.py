"""
Formulaires Django pour l'application core.
"""

import json
from django import forms
from core.models.inventory_models import Supply, Inventory
from core.models.product_models import Product
from core.models.user_models import Supplier
from core.models.accounting_models import (
    DailyExpense, DailyRecipe, ExpenseType, Payment, SupplierPayment,
    PAYMENT_METHOD_CHOICES, Account, RecipeType, TaxRate
)
from core.models.user_models import Client


class SupplyForm(forms.ModelForm):
    """Formulaire d'ajout d'approvisionnement."""

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(delete_at__isnull=True).order_by('name'),
        label='Produit',
        empty_label='-- Sélectionner un produit --',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(delete_at__isnull=True).order_by('name'),
        label='Fournisseur',
        required=False,
        empty_label='-- Aucun fournisseur --',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    quantity = forms.IntegerField(
        label='Quantité',
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 50'}),
    )

    purchase_cost = forms.DecimalField(
        label="Prix d'achat unitaire (FCFA)",
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Prérempli selon le produit sélectionné',
            'step': '1',
            'id': 'id_purchase_cost',
        }),
    )

    selling_price = forms.DecimalField(
        label='Prix de vente unitaire (FCFA)',
        min_value=0,
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Prérempli avec le prix de vente actuel du produit',
            'step': '1',
            'id': 'id_selling_price',
        }),
    )

    expiration_date = forms.DateField(
        label="Date d'expiration",
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    payment_method = forms.ChoiceField(
        label='Mode de paiement',
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    is_credit = forms.BooleanField(
        label='Achat à crédit',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    due_date = forms.DateField(
        label="Date d'échéance (pour achat à crédit)",
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    tax_rate = forms.ModelChoiceField(
        queryset=TaxRate.objects.filter(delete_at__isnull=True, is_active=True).order_by('name'),
        label='Taux de TVA',
        required=False,
        empty_label='-- Sans TVA --',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    expense_type = forms.ModelChoiceField(
        queryset=ExpenseType.objects.filter(delete_at__isnull=True).order_by('name'),
        label='Type de dépense (approvisionnement)',
        required=False,
        empty_label='-- Sélectionner un type --',
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Ce type de dépense sera utilisé pour créer automatiquement la dépense liée à cet approvisionnement'
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

        # Ajouter les métadonnées du produit pour le préremplissage et la TVA.
        active_products = Product.objects.filter(delete_at__isnull=True).only(
            'id', 'has_vat', 'actual_price', 'last_purchase_price'
        )
        self.fields['product'].widget.attrs['data-product-meta-map'] = json.dumps({
            str(product.id): {
                'has_vat': product.has_vat,
                'selling_price': self._format_decimal_for_input(product.actual_price),
                'purchase_cost': self._format_decimal_for_input(product.last_purchase_price),
            }
            for product in active_products
        })

    class Meta:
        model = Supply
        fields = ['product', 'supplier', 'quantity', 'purchase_cost', 'selling_price', 'expiration_date', 'is_credit', 'tax_rate', 'expense_type']

    def clean_expiration_date(self):
        exp_date = self.cleaned_data.get('expiration_date')
        if exp_date:
            from datetime import date
            if exp_date <= date.today():
                raise forms.ValidationError("La date d'expiration doit être postérieure à aujourd'hui.")
        return exp_date

    def clean(self):
        cleaned_data = super().clean()
        purchase_cost = cleaned_data.get('purchase_cost')
        selling_price = cleaned_data.get('selling_price')
        product = cleaned_data.get('product')
        tax_rate = cleaned_data.get('tax_rate')

        if selling_price is not None and purchase_cost is not None:
            if selling_price <= purchase_cost:
                self.add_error('selling_price', "Le prix de vente doit être supérieur au prix d'achat.")

        # Vérifier que la TVA est fournie si le produit y est sujet
        if product and product.has_vat and not tax_rate:
            self.add_error('tax_rate', 'Ce produit est soumis à la TVA. Veuillez sélectionner un taux de TVA.')

        return cleaned_data


class ExpenseForm(forms.ModelForm):
    """Formulaire d'ajout de dépense quotidienne."""

    expense_type = forms.ModelChoiceField(
        queryset=ExpenseType.objects.filter(delete_at__isnull=True).order_by('name'),
        label='Type de dépense',
        empty_label='-- Sélectionner un type --',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    amount = forms.DecimalField(
        label='Montant (FCFA)',
        min_value=1,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 5000', 'step': '1'}),
    )

    description = forms.CharField(
        label='Description',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Description de la dépense (optionnel)',
            'rows': 3,
        }),
    )

    payment_method = forms.ChoiceField(
        label='Mode de paiement',
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True, delete_at__isnull=True).order_by('code'),
        label='Compte comptable (optionnel)',
        required=False,
        empty_label='-- Par défaut (6xx) --',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = DailyExpense
        fields = ['expense_type', 'amount', 'description', 'account', 'payment_method']


class RecipeForm(forms.ModelForm):
    """Formulaire d'ajout de recette quotidienne."""

    recipe_type = forms.ModelChoiceField(
        queryset=RecipeType.objects.filter(delete_at__isnull=True).order_by('name'),
        label='Type de recette',
        empty_label='-- Sélectionner un type --',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    amount = forms.DecimalField(
        label='Montant (FCFA)',
        min_value=1,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 5000', 'step': '1'}),
    )

    description = forms.CharField(
        label='Description',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Description de la recette (optionnel)',
            'rows': 3,
        }),
    )

    payment_method = forms.ChoiceField(
        label='Mode de paiement',
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True, delete_at__isnull=True).order_by('code'),
        label='Compte comptable (optionnel)',
        required=False,
        empty_label='-- Par défaut (7xx) --',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = DailyRecipe
        fields = ['recipe_type', 'amount', 'description', 'account']


GENDER_CHOICES = [
    ('', '-- Non spécifié --'),
    ('M', 'Masculin'),
    ('F', 'Féminin'),
]


class ClientForm(forms.ModelForm):
    """Formulaire de création/modification de client."""

    firstname = forms.CharField(
        label='Prénom',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Prénom du client'}),
    )

    lastname = forms.CharField(
        label='Nom',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du client'}),
    )

    phone_number = forms.CharField(
        label='Téléphone',
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 6XXXXXXXX'}),
    )

    email = forms.EmailField(
        label='Email',
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemple.com'}),
    )

    gender = forms.ChoiceField(
        label='Genre',
        choices=GENDER_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = Client
        fields = ['firstname', 'lastname', 'phone_number', 'email', 'gender']


class InventoryForm(forms.ModelForm):
    """Formulaire d'ajout d'inventaire."""

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(delete_at__isnull=True).order_by('name'),
        label='Produit',
        empty_label='-- Sélectionner un produit --',
        widget=forms.HiddenInput(attrs={'id': 'id_product'}),
    )

    valid_product_count = forms.IntegerField(
        label='Produits valides',
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 50'}),
    )

    invalid_product_count = forms.IntegerField(
        label='Produits invalides',
        min_value=0,
        initial=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 3'}),
    )

    notes = forms.CharField(
        label='Notes',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Notes ou observations (optionnel)',
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
        label='Catégories (SQL VALUES)',
        required=False,
        help_text='Colonnes: id, name, description, create_at, delete_at',
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'placeholder': "(1,'VIN',NULL,'2024-03-06 10:05:31',NULL),(2,'WHISKY',NULL,...)",
        }),
    )

    gammes_sql = forms.CharField(
        label='Gammes (SQL VALUES)',
        required=False,
        help_text='Colonnes: id, name, description, create_at, delete_at',
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'placeholder': "(1,'350g',NULL,'2024-03-13 11:25:23',NULL),...",
        }),
    )

    rayons_sql = forms.CharField(
        label='Rayons (SQL VALUES)',
        required=False,
        help_text='Colonnes: id, name, description, create_at, delete_at',
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'placeholder': "(1,'A',NULL,'2024-03-06 10:05:59',NULL),...",
        }),
    )

    grammage_types_sql = forms.CharField(
        label='Types de grammage (SQL VALUES)',
        required=False,
        help_text='Colonnes: id, name, description, create_at, delete_at',
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'placeholder': "(1,'LITRE',NULL,'2024-03-06 10:11:35',NULL),...",
        }),
    )

    products_sql = forms.CharField(
        label='Produits (SQL VALUES)',
        required=False,
        help_text='Colonnes: id, code, name, description, brand, color, stock_limit, grammage, exp_alert_period, is_price_reducible, grammage_type_id, gamme_id, category_id, rayon_id, create_at, delete_at, max_salable_price',
        widget=forms.Textarea(attrs={
            **MIGRATION_TEXTAREA_ATTRS,
            'rows': 10,
            'placeholder': "(3,'6171100130059','huile oleo 5l','','',NULL,NULL,NULL,NULL,0,NULL,NULL,7,1,'2024-03-06 10:27:39',NULL,NULL),...",
        }),
    )

    images_sql = forms.CharField(
        label='Images produits (SQL VALUES)',
        required=False,
        help_text='Colonnes: id, path, description, product_id, create_at, delete_at',
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
                "Veuillez remplir au moins un champ avec des données à migrer."
            )
        return cleaned_data


class SupplierForm(forms.ModelForm):
    """Formulaire de création/modification de fournisseur (entreprise)."""

    name = forms.CharField(
        label="Nom de l'entreprise",
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Nom de l'entreprise"}),
    )

    address = forms.CharField(
        label='Adresse',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Adresse du fournisseur', 'rows': 2}),
    )

    niu = forms.CharField(
        label='NIU',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Numéro d\'Identifiant Unique'}),
    )

    contact_phone = forms.CharField(
        label='Téléphone',
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 6XXXXXXXX'}),
    )

    contact_email = forms.EmailField(
        label='Email',
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemple.com'}),
    )

    website = forms.URLField(
        label='Site web',
        required=False,
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://www.exemple.com'}),
    )

    description = forms.CharField(
        label='Description',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Description du fournisseur', 'rows': 3}),
    )

    class Meta:
        model = Supplier
        fields = ['name', 'address', 'niu', 'contact_phone', 'contact_email', 'website', 'description']



# ── Formulaires Phase 2 — Paiements ──────────────────────────────────

class PaymentForm(forms.ModelForm):
    """Formulaire d'enregistrement d'un paiement sur vente à crédit."""

    amount = forms.DecimalField(
        label='Montant (FCFA)',
        min_value=1,
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Montant du paiement', 'step': '1'}),
    )

    payment_method = forms.ChoiceField(
        label='Mode de paiement',
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    payment_date = forms.DateField(
        label='Date de paiement',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    reference = forms.CharField(
        label='Référence (n° chèque, ID transaction...)',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Référence (optionnel)'}),
    )

    notes = forms.CharField(
        label='Notes',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Notes (optionnel)', 'rows': 2}),
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
                    f"Le montant dépasse le solde restant ({self.credit_sale.amount_remaining:,.0f} FCFA)."
                )
        return amount


class SaleCancellationForm(forms.Form):
    """Formulaire minimal d'annulation totale d'une vente."""

    reason = forms.CharField(
        label="Motif d'annulation",
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Ex: retour client / erreur de caisse',
        }),
    )

    refund_payment_method = forms.ChoiceField(
        label='Mode de remboursement',
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
            raise forms.ValidationError("Veuillez préciser le motif d'annulation.")
        return reason

    def clean(self):
        cleaned_data = super().clean()
        if self.sale and self.sale.delete_at is not None:
            raise forms.ValidationError("Cette vente est déjà annulée.")
        return cleaned_data


class SalePartialReturnForm(forms.Form):
    """Formulaire dynamique de retour partiel par ligne de vente."""

    reason = forms.CharField(
        label="Motif du retour",
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Ex: produit abîmé / retour partiel client',
        }),
    )

    refund_payment_method = forms.ChoiceField(
        label='Mode de remboursement',
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
                    label=f"{sale_product.product.name} (max {sale_product.quantity})",
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
            raise forms.ValidationError("Veuillez préciser le motif du retour.")
        return reason

    def clean(self):
        cleaned_data = super().clean()
        if self.sale and self.sale.delete_at is not None:
            raise forms.ValidationError("Cette vente est déjà annulée.")
        if not self.sale_lines:
            raise forms.ValidationError("Aucune ligne active n'est disponible pour ce retour.")

        returned_items = []
        remaining_quantity_exists = False

        for sale_product in self.sale_lines:
            field_name = f'return_quantity_{sale_product.id}'
            quantity = cleaned_data.get(field_name) or 0

            if quantity > sale_product.quantity:
                self.add_error(field_name, f"Maximum autorisé : {sale_product.quantity}.")
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
            raise forms.ValidationError("Veuillez renseigner au moins une quantité à retourner.")
        if not remaining_quantity_exists:
            raise forms.ValidationError("Ce retour couvre toute la vente. Utilisez l'annulation totale.")

        cleaned_data['returned_items'] = returned_items
        return cleaned_data


class SupplyCancellationForm(forms.Form):
    """Formulaire minimal d'annulation totale d'un approvisionnement."""

    reason = forms.CharField(
        label="Motif d'annulation",
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Ex: retour fournisseur / erreur de réception',
        }),
    )

    refund_payment_method = forms.ChoiceField(
        label='Mode de remboursement',
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
            raise forms.ValidationError("Veuillez préciser le motif d'annulation.")
        return reason

    def clean(self):
        cleaned_data = super().clean()
        if self.supply and self.supply.delete_at is not None:
            raise forms.ValidationError("Cet approvisionnement est déjà annulé.")
        return cleaned_data


class SupplyPartialReturnForm(forms.Form):
    """Formulaire de retour partiel d'un approvisionnement fournisseur."""

    returned_quantity = forms.IntegerField(
        label='Quantité à retourner',
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': 1,
            'step': 1,
        }),
    )

    reason = forms.CharField(
        label="Motif du retour",
        required=True,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Ex: marchandise défectueuse / écart de livraison',
        }),
    )

    refund_payment_method = forms.ChoiceField(
        label='Mode de remboursement',
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, supply=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.supply = supply

        if supply is not None:
            self.fields['returned_quantity'].label = (
                f"Quantité à retourner (max {max(supply.quantity - 1, 1)})"
            )
            self.fields['returned_quantity'].widget.attrs['max'] = max(supply.quantity - 1, 1)

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError("Veuillez préciser le motif du retour.")
        return reason

    def clean(self):
        cleaned_data = super().clean()
        returned_quantity = cleaned_data.get('returned_quantity') or 0

        if self.supply and self.supply.delete_at is not None:
            raise forms.ValidationError("Cet approvisionnement est déjà annulé.")
        if self.supply and self.supply.quantity <= 1:
            raise forms.ValidationError(
                "Ce retour couvre tout l'approvisionnement. Utilisez l'annulation totale."
            )
        if self.supply and returned_quantity > self.supply.quantity:
            self.add_error('returned_quantity', f"Maximum autorisé : {self.supply.quantity}.")
        if self.supply and returned_quantity >= self.supply.quantity:
            raise forms.ValidationError(
                "Ce retour couvre tout l'approvisionnement. Utilisez l'annulation totale."
            )
        return cleaned_data


class SupplierPaymentForm(forms.ModelForm):
    """Formulaire d'enregistrement d'un paiement fournisseur."""

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(delete_at__isnull=True).order_by('name'),
        label='Fournisseur',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    amount = forms.DecimalField(
        label='Montant (FCFA)',
        min_value=1,
        max_digits=15,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Montant du paiement', 'step': '1'}),
    )

    payment_method = forms.ChoiceField(
        label='Mode de paiement',
        choices=PAYMENT_METHOD_CHOICES,
        initial='CASH',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    payment_date = forms.DateField(
        label='Date de paiement',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    reference = forms.CharField(
        label='Référence',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Référence (optionnel)'}),
    )

    notes = forms.CharField(
        label='Notes',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Notes (optionnel)', 'rows': 2}),
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
        label='Date',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    description = forms.CharField(
        label='Libellé de l\'écriture',
        max_length=500,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Description de l\'opération'}),
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
        label='Compte',
        widget=forms.Select(attrs={'class': 'form-control account-select'}),
    )

    debit = forms.DecimalField(
        label='Débit',
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
        label='Crédit',
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
        label='Libellé ligne',
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Libellé (optionnel)'
        }),
    )