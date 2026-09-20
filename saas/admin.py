"""
Administration du plan de contrôle.

Tant que le back-office dédié n'existe pas, l'exploitation quotidienne se fait
d'ici : suivre les inscriptions, relancer un provisionnement, suspendre un
espace. L'audience est de deux ou trois personnes internes, l'administration
Django suffit donc largement.

Deux règles strictes :

* ces modèles ne sont **jamais** accessibles depuis l'espace d'un client —
  ``blanco/urls_tenant.py`` ne monte pas ``/admin/``, et le propriétaire d'un
  espace est créé avec ``is_staff=False`` ;
* le journal d'audit et les travaux sont en **lecture seule** : le premier doit
  rester probant, le second reflète un état piloté par le moteur de travaux.
"""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _, ngettext

from saas.models import (
    Company,
    CompanyStatus,
    Domain,
    Invitation,
    Plan,
    PlatformAuditLog,
    ProvisioningJob,
    SignupRequest,
)


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 0
    fields = ("hostname", "kind", "is_primary", "is_verified", "tls_status")


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "contact_email", "provisioned_at")
    list_filter = ("status", "plan", "language")
    search_fields = ("name", "slug", "contact_email", "db_name", "domains__hostname")
    ordering = ("name",)
    inlines = [DomainInline]
    readonly_fields = ("create_at", "provisioned_at", "owner_user_id", "owner_username")
    fieldsets = (
        (None, {"fields": ("name", "slug", "status", "plan", "trial_ends_at")}),
        (_("Base de données"), {
            "fields": ("db_name", "db_host"),
            "description": _(
                "Chaque entreprise dispose de sa propre base. Ne jamais la "
                "créer par clonage d'une autre : deux bases clonées "
                "partageraient les mêmes comptes utilisateurs."
            ),
        }),
        (_("Contact"), {
            "fields": ("contact_email", "contact_name", "contact_phone", "language"),
        }),
        (_("Propriétaire"), {"fields": ("owner_user_id", "owner_username")}),
        (_("Cycle de vie"), {
            "fields": (
                "create_at", "provisioned_at", "suspended_at",
                "suspended_reason", "deletion_scheduled_at", "delete_at",
            ),
        }),
    )
    actions = ["suspendre", "reactiver", "relancer_le_provisionnement"]

    @admin.action(description=_("Suspendre les espaces sélectionnés"))
    def suspendre(self, request, queryset):
        from saas.constants import ActionsAudit
        from saas.middleware import oublier_hote
        from saas.services import audit_service

        nombre = 0
        for entreprise in queryset.exclude(status=CompanyStatus.SUSPENDED):
            entreprise.suspend(reason=_("Suspension depuis l'administration."))
            for domaine in entreprise.domains.all():
                oublier_hote(domaine.hostname)
            audit_service.log(
                ActionsAudit.COMPANY_SUSPENDED, company=entreprise,
                actor=request.user, request=request,
            )
            nombre += 1
        self.message_user(request, ngettext(
            "%(n)d espace suspendu.", "%(n)d espaces suspendus.", nombre
        ) % {"n": nombre})

    @admin.action(description=_("Réactiver les espaces sélectionnés"))
    def reactiver(self, request, queryset):
        from saas.constants import ActionsAudit
        from saas.middleware import oublier_hote
        from saas.services import audit_service

        nombre = 0
        for entreprise in queryset.filter(status=CompanyStatus.SUSPENDED):
            entreprise.reactivate()
            for domaine in entreprise.domains.all():
                oublier_hote(domaine.hostname)
            audit_service.log(
                ActionsAudit.COMPANY_REACTIVATED, company=entreprise,
                actor=request.user, request=request,
            )
            nombre += 1
        self.message_user(request, ngettext(
            "%(n)d espace réactivé.", "%(n)d espaces réactivés.", nombre
        ) % {"n": nombre})

    @admin.action(description=_("Relancer la création des espaces sélectionnés"))
    def relancer_le_provisionnement(self, request, queryset):
        from saas.services.provisioning_service import mettre_en_file

        nombre = 0
        for entreprise in queryset.exclude(status=CompanyStatus.ACTIVE):
            mettre_en_file(entreprise)
            nombre += 1
        self.message_user(request, ngettext(
            "%(n)d création remise en file.", "%(n)d créations remises en file.", nombre
        ) % {"n": nombre})


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("hostname", "company", "kind", "is_primary", "is_verified", "tls_status")
    list_filter = ("kind", "is_primary", "is_verified", "tls_status")
    search_fields = ("hostname", "company__name", "company__slug")


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price_xaf", "max_users", "is_active", "is_default")
    list_filter = ("is_active", "is_default")
    search_fields = ("code", "name")


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "company", "status", "expires_at", "create_at")
    list_filter = ("status",)
    search_fields = ("email", "company__name", "company__slug")
    # Le jeton n'est jamais consultable : seule son empreinte est stockée, et
    # l'afficher n'aurait aucune utilité.
    exclude = ("token_hash",)
    readonly_fields = ("create_at", "accepted_at", "accepted_user_id", "send_count", "last_sent_at")


@admin.register(SignupRequest)
class SignupRequestAdmin(admin.ModelAdmin):
    list_display = ("email", "company", "verified_at", "expires_at", "create_at")
    search_fields = ("email", "company__name", "company__slug")
    exclude = ("token_hash", "password_hash", "login_ticket_hash")
    readonly_fields = ("create_at", "verified_at", "send_count", "last_sent_at", "ip", "user_agent")


class LectureSeuleAdmin(admin.ModelAdmin):
    """Consultation uniquement : ni ajout, ni modification, ni suppression."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProvisioningJob)
class ProvisioningJobAdmin(LectureSeuleAdmin):
    list_display = ("pk", "kind", "company", "status", "step", "attempts", "run_after")
    list_filter = ("kind", "status")
    search_fields = ("company__name", "company__slug", "last_error")
    ordering = ("-create_at",)


@admin.register(PlatformAuditLog)
class PlatformAuditLogAdmin(LectureSeuleAdmin):
    list_display = ("create_at", "action", "company_slug", "actor_label", "target")
    list_filter = ("action", "actor_kind")
    search_fields = ("company_slug", "actor_label", "target")
    date_hierarchy = "create_at"
    ordering = ("-create_at",)
