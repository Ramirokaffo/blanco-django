"""Formulaires du plan de contrôle."""

from django import forms
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from saas.services import slug_service


class SignupForm(forms.Form):
    """Inscription d'une nouvelle entreprise."""

    nom = forms.CharField(
        max_length=200,
        label=_("Nom de votre entreprise"),
        widget=forms.TextInput(attrs={"placeholder": _("Ex. : Boutique Awa"), "autofocus": True}),
    )
    slug = forms.CharField(
        max_length=slug_service.LONGUEUR_MAX,
        label=_("Adresse de votre espace"),
        help_text=_("Lettres minuscules, chiffres et tirets."),
        widget=forms.TextInput(attrs={"placeholder": _("ex-boutique-awa"), "autocomplete": "off"}),
    )
    email = forms.EmailField(
        label=_("Votre adresse e-mail"),
        help_text=_("Elle servira à confirmer votre inscription et à vous contacter."),
    )
    contact_nom = forms.CharField(
        max_length=150, required=False, label=_("Votre nom"),
    )
    contact_telephone = forms.CharField(
        max_length=50, required=False, label=_("Votre téléphone"),
    )
    mot_de_passe = forms.CharField(
        label=_("Mot de passe"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        strip=False,
    )
    mot_de_passe_confirmation = forms.CharField(
        label=_("Confirmez le mot de passe"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        strip=False,
    )
    langue = forms.ChoiceField(
        choices=settings.LANGUAGES, initial="fr", label=_("Langue"),
    )
    conditions = forms.BooleanField(
        label=_("J'accepte les conditions d'utilisation"),
        error_messages={"required": _("Vous devez accepter les conditions pour continuer.")},
    )

    def clean_slug(self):
        domaine = getattr(settings, "BLANCO_PLATFORM_DOMAIN", "")
        try:
            return slug_service.valider_disponibilite(self.cleaned_data["slug"], domaine)
        except slug_service.SlugInvalide as exc:
            raise ValidationError(str(exc)) from exc

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        donnees = super().clean()
        mot_de_passe = donnees.get("mot_de_passe")
        confirmation = donnees.get("mot_de_passe_confirmation")

        if mot_de_passe and confirmation and mot_de_passe != confirmation:
            self.add_error(
                "mot_de_passe_confirmation",
                _("Les deux mots de passe ne correspondent pas."),
            )
        if mot_de_passe:
            try:
                validate_password(mot_de_passe)
            except ValidationError as exc:
                self.add_error("mot_de_passe", exc)
        return donnees
