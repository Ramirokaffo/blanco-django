"""
Formulaires Django pour l'application core.
"""

from django import forms
from core.models.inventory_models import Supply, Inventory
from core.models.product_models import Product
from core.models.user_models import Supplier
from core.models.accounting_models import DailyExpense, ExpenseType
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
        queryset=Supplier.objects.filter(delete_at__isnull=True).order_by('firstname'),
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

    unit_price = forms.DecimalField(
        label="Prix d'achat unitaire (FCFA)",
        min_value=0,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 1500', 'step': '1'}),
    )

    selling_price = forms.DecimalField(
        label='Prix de vente unitaire (FCFA)',
        min_value=0,
        max_digits=10,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Laisser vide pour garder le prix actuel', 'step': '1'}),
    )

    expiration_date = forms.DateField(
        label="Date d'expiration",
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    class Meta:
        model = Supply
        fields = ['product', 'supplier', 'quantity', 'unit_price', 'expiration_date']

    def clean_expiration_date(self):
        exp_date = self.cleaned_data.get('expiration_date')
        if exp_date:
            from datetime import date
            if exp_date <= date.today():
                raise forms.ValidationError("La date d'expiration doit être postérieure à aujourd'hui.")
        return exp_date

    def clean(self):
        cleaned_data = super().clean()
        unit_price = cleaned_data.get('unit_price')
        selling_price = cleaned_data.get('selling_price')

        if selling_price is not None and unit_price is not None:
            if selling_price <= unit_price:
                self.add_error('selling_price', "Le prix de vente doit être supérieur au prix d'achat.")

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

    class Meta:
        model = DailyExpense
        fields = ['expense_type', 'amount', 'description']


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
        widget=forms.Select(attrs={'class': 'form-control'}),
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


class SupplierForm(forms.ModelForm):
    """Formulaire de création/modification de fournisseur."""

    firstname = forms.CharField(
        label='Prénom',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Prénom du fournisseur'}),
    )

    lastname = forms.CharField(
        label='Nom',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du fournisseur'}),
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
        model = Supplier
        fields = ['firstname', 'lastname', 'phone_number', 'email', 'gender']

