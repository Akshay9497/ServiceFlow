from django.contrib import admin
from django.db import transaction

from api.models import (
    Customer,
    Equipment,
    Expense,
    Invoice,
    Membership,
    Organization,
    OrganizationSubscription,
    Payment,
    ServiceContract,
    ServiceJob,
    SubscriptionChangeRequest,
    SubscriptionInvoice,
    SubscriptionPlan,
)


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 1
    fields = ("user", "role", "joined_at")
    readonly_fields = ("joined_at",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "member_count", "created_at")
    search_fields = ("name", "created_by__email", "created_by__first_name", "created_by__last_name")
    list_filter = ("created_at",)
    readonly_fields = ("created_at",)
    inlines = [MembershipInline]

    @admin.display(description="Members")
    def member_count(self, obj):
        return obj.memberships.count()

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        if not change:
            with transaction.atomic():
                Membership.objects.get_or_create(
                    organization=obj,
                    user=obj.created_by,
                    defaults={"role": Membership.Role.OWNER},
                )


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "joined_at")
    list_filter = ("role", "organization")
    search_fields = ("user__email", "user__first_name", "user__last_name", "organization__name")
    readonly_fields = ("joined_at",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "email", "phone", "created_at")
    list_filter = ("organization", "created_at")
    search_fields = ("name", "email", "phone", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "customer", "serial_number", "model_number")
    list_filter = ("organization",)
    search_fields = ("name", "serial_number", "model_number", "customer__name", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ServiceJob)
class ServiceJobAdmin(admin.ModelAdmin):
    list_display = ("title", "organization", "customer", "assigned_technician", "status", "scheduled_for", "created_at")
    list_filter = ("status", "organization")
    search_fields = ("title", "customer__name", "assigned_technician__user__email", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ServiceContract)
class ServiceContractAdmin(admin.ModelAdmin):
    list_display = ("contract_number", "organization", "customer", "status", "start_date", "end_date", "contract_value")
    list_filter = ("status", "organization")
    search_fields = ("contract_number", "customer__name", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "organization", "customer", "status", "issue_date", "due_date")
    list_filter = ("status", "organization")
    search_fields = ("invoice_number", "customer__name", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "organization", "customer", "amount", "method", "status", "received_on")
    list_filter = ("method", "status", "organization")
    search_fields = ("reference", "customer__name", "organization__name")
    readonly_fields = ("created_at",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("expense_number", "description", "organization", "category", "amount", "method", "status", "incurred_on")
    list_filter = ("category", "method", "status", "organization")
    search_fields = ("expense_number", "description", "organization__name")
    readonly_fields = ("created_at",)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "price",
        "billing_period",
        "period_days",
        "is_active",
    )
    list_filter = ("billing_period", "is_active")
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OrganizationSubscription)
class OrganizationSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("organization", "plan", "status", "starts_on", "ends_on", "manual_pilot")
    list_filter = ("status", "manual_pilot", "plan")
    search_fields = ("organization__name", "plan__name")
    readonly_fields = ("activated_at", "cancelled_at", "updated_at")


@admin.register(SubscriptionChangeRequest)
class SubscriptionChangeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "request_type",
        "requested_plan",
        "status",
        "requested_by",
        "created_at",
    )
    list_filter = ("status", "request_type", "requested_plan")
    search_fields = ("organization__name", "requested_by__email")
    readonly_fields = ("created_at", "decided_at")


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "subscription",
        "plan",
        "amount",
        "status",
        "due_on",
    )
    list_filter = ("status", "plan")
    search_fields = ("invoice_number", "subscription__organization__name")
    readonly_fields = ("issued_at", "paid_at")
