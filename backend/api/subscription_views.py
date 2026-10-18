from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import (
    Membership,
    Organization,
    OrganizationSubscription,
    SubscriptionChangeRequest,
    SubscriptionInvoice,
    SubscriptionPlan,
)
from api.permissions import FinancialRolePermission
from api.subscription_serializers import (
    OrganizationSubscriptionSerializer,
    SubscriptionChangeRequestSerializer,
    SubscriptionInvoiceSerializer,
    SubscriptionPlanRequestSerializer,
    SubscriptionPlanSerializer,
)
from api.subscription_services import USAGE_LIMITS, usage_for


def _organization_for_request(request, organization_id):
    return get_object_or_404(
        Organization.objects.filter(memberships__user=request.user),
        pk=organization_id,
    )


def _require_billing_admin(request, organization):
    membership = Membership.objects.filter(
        organization=organization, user=request.user
    ).first()
    if membership is None or membership.role not in {
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    }:
        raise PermissionDenied("Only organization owners and administrators can manage billing.")


class SubscriptionPlansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True)
        return Response(SubscriptionPlanSerializer(plans, many=True).data)


class OrganizationSubscriptionView(APIView):
    permission_classes = [FinancialRolePermission]

    def get_organization(self):
        return _organization_for_request(
            self.request, self.kwargs["organization_pk"]
        )

    def get(self, request, *args, **kwargs):
        organization = self.get_organization()
        subscription = (
            OrganizationSubscription.objects.filter(organization=organization)
            .select_related("plan")
            .first()
        )
        if (
            subscription
            and subscription.status == OrganizationSubscription.Status.ACTIVE
            and subscription.ends_on < timezone.localdate()
        ):
            subscription.status = OrganizationSubscription.Status.EXPIRED
            subscription.save(update_fields=["status", "updated_at"])
        pending_request = (
            SubscriptionChangeRequest.objects.filter(
                organization=organization,
                status=SubscriptionChangeRequest.Status.PENDING,
            )
            .select_related("requested_plan")
            .first()
        )
        usage = {
            resource: usage_for(organization, resource)
            for resource in USAGE_LIMITS
        }
        return Response(
            {
                "subscription": (
                    OrganizationSubscriptionSerializer(subscription).data
                    if subscription
                    else None
                ),
                "usage": usage,
                "pending_request": (
                    SubscriptionChangeRequestSerializer(pending_request).data
                    if pending_request
                    else None
                ),
            }
        )

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        organization = self.get_organization()
        _require_billing_admin(request, organization)
        Organization.objects.select_for_update().get(pk=organization.pk)

        plan_serializer = SubscriptionPlanRequestSerializer(data=request.data)
        plan_serializer.is_valid(raise_exception=True)
        plan = plan_serializer.validated_data["plan"]
        current = OrganizationSubscription.objects.filter(
            organization=organization
        ).first()
        request_type = (
            SubscriptionChangeRequest.RequestType.CHANGE_PLAN
            if current and current.status == OrganizationSubscription.Status.ACTIVE
            else SubscriptionChangeRequest.RequestType.ACTIVATE
        )
        if request_type == SubscriptionChangeRequest.RequestType.CHANGE_PLAN:
            if current.plan_id == plan.pk:
                raise ValidationError(
                    {"plan": "This organization is already using the selected plan."}
                )
        if SubscriptionChangeRequest.objects.filter(
            organization=organization,
            status=SubscriptionChangeRequest.Status.PENDING,
        ).exists():
            return Response(
                {"detail": "A subscription request is already awaiting review."},
                status=status.HTTP_409_CONFLICT,
            )
        change_request = SubscriptionChangeRequest.objects.create(
            organization=organization,
            requested_plan=plan,
            request_type=request_type,
            requested_by=request.user,
        )
        return Response(
            SubscriptionChangeRequestSerializer(change_request).data,
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        organization = self.get_organization()
        _require_billing_admin(request, organization)
        Organization.objects.select_for_update().get(pk=organization.pk)
        subscription = get_object_or_404(
            OrganizationSubscription.objects.select_for_update().filter(
                organization=organization
            )
        )
        if subscription.status != OrganizationSubscription.Status.ACTIVE:
            raise ValidationError(
                {"status": "Only an active subscription can be cancelled."}
            )
        subscription.status = OrganizationSubscription.Status.CANCELLED
        subscription.cancelled_at = timezone.now()
        subscription.save(update_fields=["status", "cancelled_at", "updated_at"])
        return Response(OrganizationSubscriptionSerializer(subscription).data)


class OrganizationSubscriptionInvoiceListView(APIView):
    permission_classes = [FinancialRolePermission]

    def get(self, request, organization_pk):
        organization = _organization_for_request(request, organization_pk)
        invoices = SubscriptionInvoice.objects.filter(
            subscription__organization=organization
        ).select_related("plan")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(invoices, request, view=self)
        return paginator.get_paginated_response(
            SubscriptionInvoiceSerializer(page, many=True).data
        )


class PlatformSubscriptionRequestListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        requests = SubscriptionChangeRequest.objects.filter(
            status=SubscriptionChangeRequest.Status.PENDING
        ).select_related("organization", "requested_plan", "requested_by")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(requests, request, view=self)
        return paginator.get_paginated_response(
            [
                {
                    **SubscriptionChangeRequestSerializer(item).data,
                    "organization_id": item.organization_id,
                    "organization_name": item.organization.name,
                }
                for item in page
            ]
        )


class PlatformSubscriptionRequestDecisionView(APIView):
    permission_classes = [IsAdminUser]

    @transaction.atomic
    def post(self, request, request_id):
        change_request = get_object_or_404(
            SubscriptionChangeRequest.objects.select_for_update().select_related(
                "organization", "requested_plan"
            ),
            pk=request_id,
        )
        if change_request.status != SubscriptionChangeRequest.Status.PENDING:
            return Response(
                SubscriptionChangeRequestSerializer(change_request).data
            )

        decision = request.data.get("decision")
        if not isinstance(decision, str) or decision not in {"approve", "reject"}:
            raise ValidationError(
                {"decision": "Choose either 'approve' or 'reject'."}
            )
        note = request.data.get("note", "")
        if not isinstance(note, str) or len(note) > 1000:
            raise ValidationError({"note": "Enter a note of at most 1000 characters."})
        change_request.decided_by = request.user
        change_request.decided_at = timezone.now()
        change_request.decision_note = note
        if decision == "reject":
            change_request.status = SubscriptionChangeRequest.Status.REJECTED
            change_request.save(
                update_fields=[
                    "status",
                    "decided_by",
                    "decided_at",
                    "decision_note",
                ]
            )
            return Response(SubscriptionChangeRequestSerializer(change_request).data)

        pilot = request.data.get("manual_pilot", False)
        if not isinstance(pilot, bool):
            raise ValidationError({"manual_pilot": "This value must be true or false."})
        if (
            pilot
            and change_request.request_type
            != SubscriptionChangeRequest.RequestType.ACTIVATE
        ):
            raise ValidationError(
                {"manual_pilot": "Pilot activation is only available for new activations."}
            )
        if pilot and OrganizationSubscription.objects.filter(
            organization=change_request.organization
        ).exists():
            raise ValidationError(
                {"manual_pilot": "A manual pilot can only be granted once per organization."}
            )
        organization = Organization.objects.select_for_update().get(
            pk=change_request.organization_id
        )
        starts_on = timezone.localdate()
        ends_on = starts_on + timedelta(days=change_request.requested_plan.period_days - 1)
        subscription, _ = OrganizationSubscription.objects.update_or_create(
            organization=organization,
            defaults={
                "plan": change_request.requested_plan,
                "status": OrganizationSubscription.Status.ACTIVE,
                "starts_on": starts_on,
                "ends_on": ends_on,
                "manual_pilot": pilot,
                "activated_at": timezone.now(),
                "cancelled_at": None,
                "activated_by": request.user,
            },
        )
        amount = 0 if pilot else change_request.requested_plan.price
        invoice_status = (
            SubscriptionInvoice.Status.PAID
            if amount == 0
            else SubscriptionInvoice.Status.ISSUED
        )
        invoice_number = (
            f"SFI-{organization.pk:05d}-"
            f"{SubscriptionInvoice.objects.filter(subscription=subscription).count() + 1:06d}"
        )
        SubscriptionInvoice.objects.create(
            subscription=subscription,
            plan=change_request.requested_plan,
            invoice_number=invoice_number,
            plan_name=change_request.requested_plan.name,
            period_start=starts_on,
            period_end=ends_on,
            amount=amount,
            status=invoice_status,
            due_on=starts_on + timedelta(days=14),
            paid_at=timezone.now() if invoice_status == SubscriptionInvoice.Status.PAID else None,
            marked_paid_by=request.user if invoice_status == SubscriptionInvoice.Status.PAID else None,
        )
        change_request.status = SubscriptionChangeRequest.Status.APPROVED
        change_request.manual_pilot = pilot
        change_request.save(
            update_fields=[
                "status",
                "manual_pilot",
                "decided_by",
                "decided_at",
                "decision_note",
            ]
        )
        return Response(
            {
                "request": SubscriptionChangeRequestSerializer(change_request).data,
                "subscription": OrganizationSubscriptionSerializer(
                    subscription
                ).data,
            }
        )


class PlatformSubscriptionInvoicePaymentView(APIView):
    permission_classes = [IsAdminUser]

    @transaction.atomic
    def post(self, request, invoice_id):
        invoice = get_object_or_404(
            SubscriptionInvoice.objects.select_for_update().select_related(
                "subscription__organization", "plan"
            ),
            pk=invoice_id,
        )
        reference = request.data.get("payment_reference", "")
        if not isinstance(reference, str) or not reference.strip() or len(reference) > 120:
            raise ValidationError(
                {"payment_reference": "Enter a non-empty reference of at most 120 characters."}
            )
        reference = reference.strip()
        if invoice.status == SubscriptionInvoice.Status.PAID:
            if invoice.payment_reference == reference:
                return Response(SubscriptionInvoiceSerializer(invoice).data)
            raise ValidationError(
                {"status": "This invoice has already been recorded as paid."}
            )
        if invoice.status != SubscriptionInvoice.Status.ISSUED:
            raise ValidationError({"status": "Only issued invoices can be marked paid."})
        invoice.status = SubscriptionInvoice.Status.PAID
        invoice.payment_reference = reference
        invoice.paid_at = timezone.now()
        invoice.marked_paid_by = request.user
        invoice.save(
            update_fields=[
                "status",
                "payment_reference",
                "paid_at",
                "marked_paid_by",
            ]
        )
        return Response(SubscriptionInvoiceSerializer(invoice).data)
