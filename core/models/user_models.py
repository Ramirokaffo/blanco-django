"""
User-related models: CustomUser (Staff), Client, Supplier.
"""

from django.db import models
from django.contrib.auth.models import AbstractUser
from .base_models import BaseUser


class CustomUser(AbstractUser):
    """
    Custom User model extending Django's AbstractUser.
    Replaces the old Staff model for authentication.
    """
    # Champs additionnels pour le personnel
    firstname = models.CharField(max_length=255, null=True, blank=True, verbose_name="Prénom")
    lastname = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nom")
    phone_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="Téléphone")
    role = models.CharField(max_length=50, null=True, blank=True, verbose_name="Rôle")
    gender = models.CharField(max_length=10, null=True, blank=True, verbose_name="Genre")
    profil = models.CharField(max_length=255, null=True, blank=True, verbose_name="Profil")
    delete_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de suppression")

    class Meta:
        db_table = 'staff'  # Utiliser la table staff existante
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'

    def get_full_name(self):
        """Return the full name of the user."""
        if self.firstname and self.lastname:
            return f"{self.firstname} {self.lastname}".strip()
        return f"{self.first_name} {self.last_name}".strip() or self.username

    def __str__(self):
        return f"{self.get_full_name()} (@{self.username})"


# Alias pour compatibilité avec le code existant
Staff = CustomUser


class Client(BaseUser):
    """
    Client/Customer model.
    """
    gender = models.CharField(max_length=10, null=True, blank=True)
    
    class Meta:
        db_table = 'client'
        # managed = False
        verbose_name = 'Client'
        verbose_name_plural = 'Clients'
    
    def __str__(self):
        return self.get_full_name() or f"Client #{self.id}"


class Supplier(models.Model):
    """
    Supplier model representing a company/business that supplies products.
    """
    name = models.CharField(max_length=255, verbose_name="Nom de l'entreprise", default="Fournisseur")
    address = models.TextField(null=True, blank=True, verbose_name="Adresse")
    niu = models.CharField(max_length=100, null=True, blank=True, verbose_name="NIU")
    contact_phone = models.CharField(max_length=50, null=True, blank=True, verbose_name="Téléphone")
    contact_email = models.EmailField(max_length=255, null=True, blank=True, verbose_name="Email")
    website = models.URLField(max_length=255, null=True, blank=True, verbose_name="Site web")
    description = models.TextField(null=True, blank=True, verbose_name="Description")
    create_at = models.DateTimeField(auto_now_add=True)
    delete_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'supplier'
        verbose_name = 'Fournisseur'
        verbose_name_plural = 'Fournisseurs'
        ordering = ['name']

    def __str__(self):
        return self.name or f"Fournisseur #{self.id}"

