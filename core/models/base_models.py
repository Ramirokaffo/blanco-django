"""
Base models for the application.
Contains abstract models used by other models.
"""

from django.db import models


class BaseUser(models.Model):
    """
    Abstract base class for user-related models (Staff, Client, Supplier).
    """
    firstname = models.CharField(max_length=255, null=True, blank=True)
    lastname = models.CharField(max_length=255, null=True, blank=True)
    phone_number = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    create_at = models.DateTimeField(auto_now_add=True)
    delete_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        abstract = True
    
    def get_full_name(self):
        """Return the full name of the user."""
        return f"{self.firstname or ''} {self.lastname or ''}".strip()
    
    def __str__(self):
        return self.get_full_name() or f"User #{self.id}"


class SoftDeleteModel(models.Model):
    """
    Abstract model for soft delete functionality.
    """
    create_at = models.DateTimeField(auto_now_add=True)
    delete_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        abstract = True
    
    def soft_delete(self):
        """Soft delete the object by setting delete_at timestamp."""
        from django.utils import timezone
        self.delete_at = timezone.now()
        self.save()
    
    def is_deleted(self):
        """Check if the object is soft deleted."""
        return self.delete_at is not None

