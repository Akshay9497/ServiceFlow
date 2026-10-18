from rest_framework import serializers

from api.models import (
    OrganizationSubscription,
    SubscriptionChangeRequest,
    SubscriptionInvoice,
    SubscriptionPlan,
)


class SubscriptionPlanRequestSerializer(serializers.Serializer):
    plan = serializers.IntegerField(min_value=1)

    def validate_plan(self, value):
        try:
            return SubscriptionPlan.objects.get(pk=value, is_active=True)
        except SubscriptionPlan.DoesNotExist as exc:
            raise serializers.ValidationError(
                "Select an active subscription plan."
            ) from exc


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "code",
            "name",
            "description",
            "price",
            "billing_period",
            "period_days",
            "max_members",
            "max_customers",
            "max_equipment",
            "max_jobs",
            "features",
        ]


class SubscriptionChangeRequestSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="requested_plan.name", read_only=True)
    requested_by_name = serializers.CharField(
        source="requested_by.get_full_name", read_only=True
    )
    decided_by_name = serializers.CharField(
        source="decided_by.get_full_name", read_only=True, allow_null=True
    )

    class Meta:
        model = SubscriptionChangeRequest
        fields = [
            "id",
            "request_type",
            "status",
            "requested_plan",
            "plan_name",
            "requested_by_name",
            "decided_by_name",
            "manual_pilot",
            "decision_note",
            "created_at",
            "decided_at",
        ]
        read_only_fields = fields


class SubscriptionInvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionInvoice
        fields = [
            "id",
            "invoice_number",
            "plan_name",
            "period_start",
            "period_end",
            "amount",
            "status",
            "issued_at",
            "due_on",
            "paid_at",
            "payment_reference",
        ]
        read_only_fields = fields


class OrganizationSubscriptionSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)

    class Meta:
        model = OrganizationSubscription
        fields = [
            "id",
            "plan",
            "status",
            "starts_on",
            "ends_on",
            "manual_pilot",
            "activated_at",
            "cancelled_at",
        ]
        read_only_fields = fields
