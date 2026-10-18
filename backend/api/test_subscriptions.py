from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Customer,
    Membership,
    Organization,
    OrganizationSubscription,
    SubscriptionChangeRequest,
    SubscriptionInvoice,
    SubscriptionPlan,
)

User = get_user_model()


class SubscriptionWorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="subscription-owner@example.com",
            email="subscription-owner@example.com",
            password="subscription-test-password",
        )
        self.organization = Organization.objects.create(
            name="Subscription Services", created_by=self.owner
        )
        Membership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=Membership.Role.OWNER,
        )
        self.plan = SubscriptionPlan.objects.create(
            code="pilot",
            name="Pilot",
            description="Controlled pilot plan",
            price=Decimal("999.00"),
            billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
            period_days=30,
            max_members=2,
            max_customers=1,
            max_equipment=3,
            max_jobs=2,
            features=["Core workflows"],
        )
        self.second_plan = SubscriptionPlan.objects.create(
            code="growth",
            name="Growth",
            price=Decimal("2999.00"),
            billing_period=SubscriptionPlan.BillingPeriod.YEARLY,
            period_days=365,
            max_members=10,
            max_customers=100,
            max_equipment=300,
            max_jobs=500,
        )
        self.base = f"/api/organizations/{self.organization.pk}"
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def request_plan(self, plan=None):
        return self.client.post(
            f"{self.base}/subscription/",
            {"plan": (plan or self.plan).pk},
            format="json",
        )

    def approve_request(self, change_request, **extra):
        staff = User.objects.create_user(
            username="platform-admin@example.com",
            email="platform-admin@example.com",
            password="platform-test-password",
            is_staff=True,
        )
        admin_client = APIClient()
        admin_client.force_authenticate(staff)
        return admin_client.post(
            f"/api/platform/subscription-requests/{change_request.pk}/decision/",
            {"decision": "approve", **extra},
            format="json",
        ), admin_client

    def test_configured_plans_manual_pilot_activation_and_usage_limits(self):
        plans_response = self.client.get("/api/subscription/plans/")
        self.assertEqual(plans_response.status_code, 200)
        self.assertEqual({item["id"] for item in plans_response.data}, {
            self.plan.pk,
            self.second_plan.pk,
        })

        requested = self.request_plan()
        self.assertEqual(requested.status_code, 201, requested.data)
        change_request = SubscriptionChangeRequest.objects.get(
            pk=requested.data["id"]
        )
        activated, admin_client = self.approve_request(
            change_request, manual_pilot=True
        )
        self.assertEqual(activated.status_code, 200, activated.data)
        subscription = OrganizationSubscription.objects.get(
            organization=self.organization
        )
        self.assertEqual(subscription.status, OrganizationSubscription.Status.ACTIVE)
        self.assertTrue(subscription.manual_pilot)
        self.assertEqual(
            subscription.ends_on - subscription.starts_on, timedelta(days=29)
        )
        invoice = SubscriptionInvoice.objects.get(subscription=subscription)
        self.assertEqual(invoice.amount, Decimal("0.00"))
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.PAID)
        self.assertEqual(activated.data["request"]["status"], "approved")
        self.assertEqual(
            SubscriptionInvoice.objects.filter(subscription=subscription).count(), 1
        )

        created_customer = self.client.post(
            f"{self.base}/customers/", {"name": "Allowed"}, format="json"
        )
        self.assertEqual(created_customer.status_code, 201, created_customer.data)
        over_limit_customer = self.client.post(
            f"{self.base}/customers/", {"name": "Over limit"}, format="json"
        )
        self.assertEqual(over_limit_customer.status_code, 400)
        self.assertEqual(over_limit_customer.data["resource"], "customers")
        self.assertEqual(Customer.objects.filter(organization=self.organization).count(), 1)

        attempted_member = self.client.post(
            f"{self.base}/members/",
            {"user_email": self._create_user("limit-member@example.com").email, "role": "technician"},
            format="json",
        )
        self.assertEqual(attempted_member.status_code, 201)
        next_user = self._create_user("over-limit-member@example.com")
        over_limit_member = self.client.post(
            f"{self.base}/members/",
            {"user_email": next_user.email, "role": "technician"},
            format="json",
        )
        self.assertEqual(over_limit_member.status_code, 400)
        self.assertEqual(over_limit_member.data["resource"], "members")

        self.plan.max_equipment = 0
        self.plan.max_jobs = 0
        self.plan.save(update_fields=["max_equipment", "max_jobs"])
        equipment_response = self.client.post(
            f"{self.base}/equipment/",
            {"customer": created_customer.data["id"], "name": "Blocked equipment"},
            format="json",
        )
        self.assertEqual(equipment_response.status_code, 400)
        self.assertEqual(equipment_response.data["resource"], "equipment")
        job_response = self.client.post(
            f"{self.base}/jobs/",
            {"customer": created_customer.data["id"], "title": "Blocked job"},
            format="json",
        )
        self.assertEqual(job_response.status_code, 400)
        self.assertEqual(job_response.data["resource"], "jobs")

        overview = self.client.get(f"{self.base}/subscription/")
        self.assertEqual(overview.status_code, 200, overview.data)
        self.assertEqual(overview.data["usage"]["customers"]["used"], 1)
        self.assertEqual(overview.data["usage"]["customers"]["limit"], 1)

        invoice_page = self.client.get(f"{self.base}/subscription/invoices/")
        self.assertEqual(invoice_page.status_code, 200)
        self.assertEqual(invoice_page.data["count"], 1)
        self.assertEqual(invoice_page.data["results"][0]["invoice_number"], invoice.invoice_number)
        self.assertEqual(admin_client.get("/api/platform/subscription-requests/").status_code, 200)

    def test_plan_features_require_a_list_of_nonblank_strings(self):
        invalid_features = ({"feature": "not a list"}, ["  "], ["valid", 1])
        for index, features in enumerate(invalid_features):
            with self.subTest(features=features):
                invalid = SubscriptionPlan(
                    code=f"invalid-features-{index}",
                    name="Invalid",
                    price=Decimal("1.00"),
                    billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
                    features=features,
                )
                with self.assertRaises(ValidationError):
                    invalid.full_clean()

    def test_plan_change_cancellation_and_manual_invoice_settlement_are_idempotent(self):
        requested = self.request_plan()
        change_request = SubscriptionChangeRequest.objects.get(pk=requested.data["id"])
        activation, admin_client = self.approve_request(change_request)
        self.assertEqual(activation.status_code, 200, activation.data)
        subscription = OrganizationSubscription.objects.get(
            organization=self.organization
        )
        invoice = SubscriptionInvoice.objects.get(subscription=subscription)
        self.assertEqual(invoice.amount, Decimal("999.00"))
        self.assertEqual(invoice.status, SubscriptionInvoice.Status.ISSUED)

        paid = admin_client.post(
            f"/api/platform/subscription-invoices/{invoice.pk}/mark-paid/",
            {"payment_reference": "pilot-bank-reference"},
            format="json",
        )
        self.assertEqual(paid.status_code, 200, paid.data)
        repeated_paid = admin_client.post(
            f"/api/platform/subscription-invoices/{invoice.pk}/mark-paid/",
            {"payment_reference": "pilot-bank-reference"},
            format="json",
        )
        self.assertEqual(repeated_paid.status_code, 200)
        self.assertEqual(SubscriptionInvoice.objects.count(), 1)
        conflicting_paid = admin_client.post(
            f"/api/platform/subscription-invoices/{invoice.pk}/mark-paid/",
            {"payment_reference": "different-reference"},
            format="json",
        )
        self.assertEqual(conflicting_paid.status_code, 400)

        plan_change = self.request_plan(self.second_plan)
        self.assertEqual(plan_change.status_code, 201, plan_change.data)
        change = SubscriptionChangeRequest.objects.get(pk=plan_change.data["id"])
        self.assertEqual(change.request_type, SubscriptionChangeRequest.RequestType.CHANGE_PLAN)
        approved_change = admin_client.post(
            f"/api/platform/subscription-requests/{change.pk}/decision/",
            {"decision": "approve"},
            format="json",
        )
        self.assertEqual(approved_change.status_code, 200, approved_change.data)
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan_id, self.second_plan.pk)
        self.assertEqual(SubscriptionInvoice.objects.filter(subscription=subscription).count(), 2)

        cancelled = self.client.delete(f"{self.base}/subscription/")
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["status"], OrganizationSubscription.Status.CANCELLED)
        self.assertIsNotNone(cancelled.data["cancelled_at"])
        repeated_cancel = self.client.delete(f"{self.base}/subscription/")
        self.assertEqual(repeated_cancel.status_code, 400)

        reactivation = self.request_plan(self.plan)
        self.assertEqual(reactivation.status_code, 201, reactivation.data)
        reactivation_request = SubscriptionChangeRequest.objects.get(
            pk=reactivation.data["id"]
        )
        repeated_pilot = admin_client.post(
            f"/api/platform/subscription-requests/{reactivation_request.pk}/decision/",
            {"decision": "approve", "manual_pilot": True},
            format="json",
        )
        self.assertEqual(repeated_pilot.status_code, 400)
        reactivated = admin_client.post(
            f"/api/platform/subscription-requests/{reactivation_request.pk}/decision/",
            {"decision": "approve"},
            format="json",
        )
        self.assertEqual(reactivated.status_code, 200, reactivated.data)
        self.assertEqual(SubscriptionInvoice.objects.count(), 3)
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, OrganizationSubscription.Status.ACTIVE)

    def test_pending_requests_are_unique_and_platform_actions_require_staff(self):
        first_request = self.request_plan()
        self.assertEqual(first_request.status_code, 201)
        second_request = self.request_plan(self.second_plan)
        self.assertEqual(second_request.status_code, 409)

        non_staff_attempt = self.client.get("/api/platform/subscription-requests/")
        self.assertEqual(non_staff_attempt.status_code, 403)
        non_staff_decision = self.client.post(
            f"/api/platform/subscription-requests/{first_request.data['id']}/decision/",
            {"decision": "approve", "manual_pilot": True},
            format="json",
        )
        self.assertEqual(non_staff_decision.status_code, 403)

        request = SubscriptionChangeRequest.objects.get(pk=first_request.data["id"])
        response, staff_client = self.approve_request(
            request, manual_pilot=True
        )
        self.assertEqual(response.status_code, 200)
        duplicate_approval = staff_client.post(
            f"/api/platform/subscription-requests/{request.pk}/decision/",
            {"decision": "approve", "manual_pilot": True},
            format="json",
        )
        self.assertEqual(duplicate_approval.status_code, 200)
        self.assertEqual(SubscriptionInvoice.objects.count(), 1)

    def test_manager_cannot_request_or_cancel_subscription(self):
        manager = self._create_user("subscription-manager@example.com")
        Membership.objects.create(
            organization=self.organization,
            user=manager,
            role=Membership.Role.MANAGER,
        )
        self.client.force_authenticate(manager)
        denied_request = self.request_plan()
        self.assertEqual(denied_request.status_code, 403)

    def test_subscription_status_expires_after_inclusive_end_date(self):
        request_response = self.request_plan()
        change_request = SubscriptionChangeRequest.objects.get(
            pk=request_response.data["id"]
        )
        approved, _ = self.approve_request(change_request, manual_pilot=True)
        self.assertEqual(approved.status_code, 200)
        subscription = OrganizationSubscription.objects.get(
            organization=self.organization
        )
        subscription.ends_on = timezone.localdate() - timedelta(days=1)
        subscription.save(update_fields=["ends_on"])

        response = self.client.get(f"{self.base}/subscription/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["subscription"]["status"],
            OrganizationSubscription.Status.EXPIRED,
        )
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, OrganizationSubscription.Status.EXPIRED)

    def _create_user(self, email):
        return User.objects.create_user(
            username=email,
            email=email,
            password="subscription-test-password",
        )
