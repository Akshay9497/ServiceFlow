import smtplib
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import (
    Customer,
    Equipment,
    PasswordResetOTP,
    ContractRenewalReminder,
    ContractRenewalReminderAttempt,
    ContractVisit,
    Membership,
    Organization,
    ServiceContract,
    ServiceJob,
    ServiceJobStatusHistory,
    ServiceJobWorkNote,
)

User = get_user_model()


PASSWORD = "PhaseTwo-Test-Password-482!"


def register(client, email, organization_name):
    return client.post(
        "/api/auth/register/",
        {
            "name": "Test User",
            "email": email,
            "password": PASSWORD,
            "organization_name": organization_name,
        },
        format="json",
    )


class HealthCheckTests(SimpleTestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_check_returns_service_status_without_authentication(self):
        response = self.client.get("/api/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "ServiceFlow API"},
        )


class AuthenticationAndOrganizationTests(APITestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_public_configuration_reports_registration_status(self):
        response = self.client.get("/api/public-config/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("registration_enabled", response.data)

    @override_settings(PUBLIC_REGISTRATION_ENABLED=False)
    def test_registration_can_be_disabled_for_a_controlled_pilot(self):
        response = register(self.client, "closed@example.com", "Closed Pilot")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Organization.objects.count(), 0)

    def test_registration_creates_user_organization_and_owner_membership(self):
        response = register(self.client, "owner@example.com", "Owner's Services")

        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(email="owner@example.com")
        organization = Organization.objects.get(name="Owner's Services")
        membership = Membership.objects.get(user=user, organization=organization)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(membership.role, Membership.Role.OWNER)

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        register(self.client, "owner@example.com", "First Organization")

        response = register(self.client, "OWNER@example.com", "Second Organization")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Organization.objects.count(), 1)

    def test_registration_rejects_weak_password_without_creating_records(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "name": "Test User",
                "email": "owner@example.com",
                "password": "password",
                "organization_name": "Not Created",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Organization.objects.count(), 0)

    def test_login_and_current_user_return_only_memberships(self):
        register(self.client, "owner@example.com", "Owner's Services")
        response = self.client.post(
            "/api/auth/token/",
            {"username": "OWNER@EXAMPLE.COM", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

        current_user = self.client.get("/api/auth/me/")
        organizations = self.client.get("/api/organizations/")

        self.assertEqual(current_user.status_code, 200)
        self.assertEqual(len(current_user.data["organizations"]), 1)
        self.assertEqual(current_user.data["organizations"][0]["role"], "owner")
        self.assertEqual(len(organizations.data["results"]), 1)

    def test_authenticated_user_can_create_an_organization_as_its_owner(self):
        register(self.client, "multi-owner@example.com", "First Services")
        user = User.objects.get(email="multi-owner@example.com")
        self.client.force_authenticate(user=user)

        # Non-superusers are forbidden from creating organizations via the regular endpoint
        denied_response = self.client.post(
            "/api/organizations/",
            {"name": "Second Services"},
            format="json",
        )
        self.assertEqual(denied_response.status_code, 403)

        # Superusers can provision organizations
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])

        response = self.client.post(
            "/api/organizations/",
            {"name": "Second Services"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        organization = Organization.objects.get(name="Second Services")
        membership = Membership.objects.get(
            user=user, organization=organization
        )
        self.assertEqual(response.data["id"], organization.id)
        self.assertEqual(response.data["role"], Membership.Role.OWNER)
        self.assertEqual(membership.role, Membership.Role.OWNER)
        self.assertEqual(response.data["name"], "Second Services")
        self.assertEqual(
            {
                entry["name"]
                for entry in self.client.get("/api/organizations/").data["results"]
            },
            {"First Services", "Second Services"},
        )
        self.assertEqual(
            set(self.client.get("/api/organizations/").data["results"][0]),
            {"id", "membership_id", "name", "role"},
        )

    def test_django_admin_creates_organization_with_owner_membership(self):
        from django.contrib.admin.sites import AdminSite
        from api.admin import OrganizationAdmin

        superuser = User.objects.create_superuser(
            username="admin@example.com",
            email="admin@example.com",
            password=PASSWORD,
        )
        admin_site = AdminSite()
        org_admin = OrganizationAdmin(Organization, admin_site)

        org = Organization(name="Admin Provisioned Org")
        request = type("MockRequest", (), {"user": superuser})()
        org_admin.save_model(request, org, form=None, change=False)

        self.assertEqual(org.created_by, superuser)
        membership = Membership.objects.get(organization=org, user=superuser)
        self.assertEqual(membership.role, Membership.Role.OWNER)
        self.assertEqual(org_admin.member_count(org), 1)

    def test_logout_blacklists_the_refresh_token(self):
        user = User.objects.create_user(
            username="logout@example.com",
            email="logout@example.com",
            password=PASSWORD,
        )
        refresh = str(RefreshToken.for_user(user))
        self.client.force_authenticate(user=user)

        response = self.client.post(
            "/api/auth/logout/",
            {"refresh": refresh},
            format="json",
        )
        refresh_response = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh},
            format="json",
        )

        self.assertEqual(response.status_code, 205)
        self.assertEqual(refresh_response.status_code, 401)

    def test_logout_rejects_invalid_refresh_tokens(self):
        user = User.objects.create_user(
            username="logout-invalid@example.com",
            email="logout-invalid@example.com",
            password=PASSWORD,
        )
        self.client.force_authenticate(user=user)

        response = self.client.post(
            "/api/auth/logout/",
            {"refresh": "invalid"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_logout_cannot_revoke_another_accounts_refresh_token(self):
        user = User.objects.create_user(
            username="logout-owner@example.com",
            email="logout-owner@example.com",
            password=PASSWORD,
        )
        other_user = User.objects.create_user(
            username="other-account@example.com",
            email="other-account@example.com",
            password=PASSWORD,
        )
        refresh = str(RefreshToken.for_user(other_user))
        self.client.force_authenticate(user=user)

        response = self.client.post(
            "/api/auth/logout/",
            {"refresh": refresh},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        still_valid = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(still_valid.status_code, 200)

    def test_protected_endpoints_require_authentication(self):
        response = self.client.get("/api/organizations/")

        self.assertEqual(response.status_code, 401)


class PasswordResetTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="password-reset@example.com",
            email="password-reset@example.com",
            password=PASSWORD,
            first_name="Reset User",
        )

    def tearDown(self):
        cache.clear()

    @staticmethod
    def code_from_email(message):
        return message.body.split("code is ", 1)[1].split(".", 1)[0]

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_two_otp_steps_change_login_email_and_password(self):
        old_refresh_token = str(RefreshToken.for_user(self.user))
        response = self.client.post(
            "/api/auth/password-reset/",
            {"email": "PASSWORD-RESET@EXAMPLE.COM"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["detail"],
            "If an active account exists for that email, a verification code has been sent.",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        first_code = self.code_from_email(mail.outbox[0])
        verified = self.client.post(
            "/api/auth/password-reset/verify/",
            {"email": self.user.email, "otp": first_code},
            format="json",
        )
        self.assertEqual(verified.status_code, 200, verified.data)
        verification_token = verified.data["verification_token"]

        email_change = self.client.post(
            "/api/auth/password-reset/new-email/",
            {
                "verification_token": verification_token,
                "new_email": "new-login@example.com",
            },
            format="json",
        )
        self.assertEqual(email_change.status_code, 200, email_change.data)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["new-login@example.com"])
        second_code = self.code_from_email(mail.outbox[1])

        old_password_login = self.client.post(
            "/api/auth/token/",
            {"username": "new-login@example.com", "password": PASSWORD},
            format="json",
        )
        reset = self.client.post(
            "/api/auth/password-reset/complete/",
            {
                "verification_token": verification_token,
                "new_email": "new-login@example.com",
                "otp": second_code,
                "new_password": "Reset-Only-Strong-2026!",
                "confirm_password": "Reset-Only-Strong-2026!",
            },
            format="json",
        )
        self.assertEqual(reset.status_code, 200, reset.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new-login@example.com")
        self.assertEqual(self.user.username, "new-login@example.com")
        self.assertEqual(old_password_login.status_code, 401)
        revoked_refresh = self.client.post(
            "/api/auth/token/refresh/",
            {"refresh": old_refresh_token},
            format="json",
        )
        self.assertEqual(revoked_refresh.status_code, 401)

        new_password_login = self.client.post(
            "/api/auth/token/",
            {
                "username": "NEW-LOGIN@example.com",
                "password": "Reset-Only-Strong-2026!",
            },
            format="json",
        )
        self.assertEqual(new_password_login.status_code, 200)
        replay = self.client.post(
            "/api/auth/password-reset/complete/",
            {
                "verification_token": verification_token,
                "new_email": "new-login@example.com",
                "otp": second_code,
                "new_password": "Another-Strong-Password-2026!",
                "confirm_password": "Another-Strong-Password-2026!",
            },
            format="json",
        )
        self.assertEqual(replay.status_code, 400)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_unknown_email_gets_same_response_without_sending_email(self):
        response = self.client.post(
            "/api/auth/password-reset/",
            {"email": "unknown@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["detail"],
            "If an active account exists for that email, a verification code has been sent.",
        )
        self.assertEqual(mail.outbox, [])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_new_email_requires_otp_and_password_mismatch_is_rejected(self):
        self.client.post(
            "/api/auth/password-reset/",
            {"email": self.user.email},
            format="json",
        )
        verified = self.client.post(
            "/api/auth/password-reset/verify/",
            {"email": self.user.email, "otp": self.code_from_email(mail.outbox[0])},
            format="json",
        )
        verification_token = verified.data["verification_token"]
        self.client.post(
            "/api/auth/password-reset/new-email/",
            {
                "verification_token": verification_token,
                "new_email": "new-login@example.com",
            },
            format="json",
        )
        email_code = self.code_from_email(mail.outbox[1])
        data = {
            "verification_token": verification_token,
            "new_email": "new-login@example.com",
            "otp": email_code,
            "new_password": "Reset-Only-Strong-2026!",
            "confirm_password": "Different-Strong-Password-2026!",
        }
        mismatch = self.client.post(
            "/api/auth/password-reset/complete/", data, format="json"
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertEqual(self.user.email, "password-reset@example.com")

        data["confirm_password"] = data["new_password"]
        reset = self.client.post(
            "/api/auth/password-reset/complete/", data, format="json"
        )
        self.assertEqual(reset.status_code, 200, reset.data)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_THROTTLE_RATES": {"auth_password_reset_otp": "20/hour"}
        }
    )
    def test_wrong_otp_is_rate_limited_per_challenge(self):
        self.client.post(
            "/api/auth/password-reset/",
            {"email": self.user.email},
            format="json",
        )
        correct_code = self.code_from_email(mail.outbox[0])
        wrong_code = "000000" if correct_code != "000000" else "000001"
        for _ in range(5):
            response = self.client.post(
                "/api/auth/password-reset/verify/",
                {"email": self.user.email, "otp": wrong_code},
                format="json",
            )
            self.assertEqual(response.status_code, 400)
        self.assertEqual(
            PasswordResetOTP.objects.get(
                purpose=PasswordResetOTP.Purpose.ACCOUNT_RECOVERY
            ).attempts,
            5,
        )


class AuthenticationThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_registration_is_throttled(self):
        responses = []
        for index in range(6):
            responses.append(
                self.client.post(
                    "/api/auth/register/",
                    {
                        "name": "Pilot Owner",
                        "email": f"pilot-owner-{index}@example.com",
                        "password": PASSWORD,
                        "organization_name": f"Pilot Services {index}",
                    },
                    format="json",
                    HTTP_X_FORWARDED_FOR=f"192.0.2.{index + 1}",
                )
            )

        self.assertEqual([response.status_code for response in responses[:5]], [201] * 5)
        self.assertEqual(responses[5].status_code, 429)
        self.assertEqual(Organization.objects.count(), 5)


class TenantIsolationAndRoleTests(APITestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(
            username="owner-a@example.com",
            email="owner-a@example.com",
            password=PASSWORD,
            first_name="Owner A",
        )
        self.owner_b = User.objects.create_user(
            username="owner-b@example.com",
            email="owner-b@example.com",
            password=PASSWORD,
            first_name="Owner B",
        )
        self.organization_a = Organization.objects.create(
            name="Organization A", created_by=self.owner_a
        )
        self.organization_b = Organization.objects.create(
            name="Organization B", created_by=self.owner_b
        )
        Membership.objects.create(
            user=self.owner_a,
            organization=self.organization_a,
            role=Membership.Role.OWNER,
        )
        Membership.objects.create(
            user=self.owner_b,
            organization=self.organization_b,
            role=Membership.Role.OWNER,
        )
        self.customer_a = Customer.objects.create(
            organization=self.organization_a,
            name="Customer A",
        )
        self.customer_b = Customer.objects.create(
            organization=self.organization_b,
            name="Customer B",
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def test_organization_cannot_list_or_retrieve_another_tenants_customer(self):
        self.authenticate_as(self.owner_b)

        listing = self.client.get(
            f"/api/organizations/{self.organization_b.id}/customers/"
        )
        foreign_detail = self.client.get(
            f"/api/organizations/{self.organization_b.id}/customers/{self.customer_a.id}/"
        )

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            [row["id"] for row in listing.data["results"]], [self.customer_b.id]
        )
        self.assertEqual(foreign_detail.status_code, 404)

    def test_customer_search_and_pagination_are_tenant_scoped(self):
        for index in range(55):
            Customer.objects.create(
                organization=self.organization_a,
                name=f"Northwind customer {index:02d}",
                phone=f"900000{index:04d}",
            )
        Customer.objects.create(
            organization=self.organization_b,
            name="Private Northwind account",
        )
        self.authenticate_as(self.owner_a)
        base_url = f"/api/organizations/{self.organization_a.id}/customers/"

        first_page = self.client.get(base_url)
        second_page = self.client.get(f"{base_url}?page=2")
        search = self.client.get(f"{base_url}?search=northwind")
        foreign_search = self.client.get(f"{base_url}?search=Private")

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.data["count"], 56)
        self.assertEqual(len(first_page.data["results"]), 50)
        self.assertIsNotNone(first_page.data["next"])
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data["results"]), 6)
        self.assertIsNone(second_page.data["next"])
        self.assertEqual(search.data["count"], 55)
        self.assertTrue(
            all("Northwind" in row["name"] for row in search.data["results"])
        )
        self.assertEqual(foreign_search.data["count"], 0)

    def test_nonmember_cannot_access_another_organizations_route(self):
        self.authenticate_as(self.owner_a)

        response = self.client.get(
            f"/api/organizations/{self.organization_b.id}/customers/"
        )

        self.assertEqual(response.status_code, 403)

    def test_equipment_cannot_reference_a_customer_from_another_tenant(self):
        self.authenticate_as(self.owner_b)

        response = self.client.post(
            f"/api/organizations/{self.organization_b.id}/equipment/",
            {"customer": self.customer_a.id, "name": "Foreign equipment"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Equipment.objects.count(), 0)

    def test_equipment_update_cannot_change_customer_to_another_tenant(self):
        equipment = Equipment.objects.create(
            organization=self.organization_a,
            customer=self.customer_a,
            name="Local equipment",
        )
        self.authenticate_as(self.owner_a)

        response = self.client.patch(
            f"/api/organizations/{self.organization_a.id}/equipment/{equipment.id}/",
            {"customer": self.customer_b.id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        equipment.refresh_from_db()
        self.assertEqual(equipment.customer_id, self.customer_a.id)

    def test_technician_can_read_but_cannot_write_customer_records(self):
        technician = User.objects.create_user(
            username="tech@example.com", password=PASSWORD
        )
        Membership.objects.create(
            user=technician,
            organization=self.organization_a,
            role=Membership.Role.TECHNICIAN,
        )
        self.authenticate_as(technician)
        base_url = f"/api/organizations/{self.organization_a.id}/customers/"

        listing = self.client.get(base_url)
        update = self.client.patch(
            f"{base_url}{self.customer_a.id}/",
            {"name": "Unauthorized update"},
            format="json",
        )

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(update.status_code, 403)
        self.customer_a.refresh_from_db()
        self.assertEqual(self.customer_a.name, "Customer A")

    def test_manager_can_create_customer_only_in_their_organization(self):
        manager = User.objects.create_user(
            username="manager@example.com", password=PASSWORD
        )
        Membership.objects.create(
            user=manager,
            organization=self.organization_a,
            role=Membership.Role.MANAGER,
        )
        self.authenticate_as(manager)

        response = self.client.post(
            f"/api/organizations/{self.organization_a.id}/customers/",
            {"name": "New customer"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            Customer.objects.get(name="New customer").organization,
            self.organization_a,
        )

    def test_customer_validation_rejects_blank_names_and_invalid_email(self):
        self.authenticate_as(self.owner_a)
        base_url = f"/api/organizations/{self.organization_a.id}/customers/"

        blank_name = self.client.post(
            base_url,
            {"name": "   ", "email": "valid@example.com"},
            format="json",
        )
        invalid_email = self.client.post(
            base_url,
            {"name": "Valid name", "email": "not-an-email"},
            format="json",
        )

        self.assertEqual(blank_name.status_code, 400)
        self.assertIn("name", blank_name.data)
        self.assertEqual(invalid_email.status_code, 400)
        self.assertIn("email", invalid_email.data)
        self.assertFalse(
            Customer.objects.filter(organization=self.organization_a)
            .exclude(pk=self.customer_a.pk)
            .exists()
        )

    def test_customer_with_service_jobs_cannot_be_deleted(self):
        ServiceJob.objects.create(
            organization=self.organization_a,
            customer=self.customer_a,
            created_by=self.owner_a,
            title="Historical service",
        )
        self.authenticate_as(self.owner_a)

        response = self.client.delete(
            f"/api/organizations/{self.organization_a.id}/customers/{self.customer_a.id}/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("service jobs", response.data["detail"])
        self.assertTrue(Customer.objects.filter(pk=self.customer_a.pk).exists())

    def test_owner_can_add_existing_user_as_organization_member(self):
        colleague = User.objects.create_user(
            username="colleague@example.com",
            email="colleague@example.com",
            password=PASSWORD,
        )
        self.authenticate_as(self.owner_a)

        response = self.client.post(
            f"/api/organizations/{self.organization_a.id}/members/",
            {"user_email": colleague.email, "role": "technician"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            Membership.objects.filter(
                user=colleague,
                organization=self.organization_a,
                role=Membership.Role.TECHNICIAN,
            ).exists()
        )

    def test_administrator_cannot_grant_owner_or_admin_roles(self):
        administrator = User.objects.create_user(
            username="admin@example.com", password=PASSWORD
        )
        colleague = User.objects.create_user(
            username="colleague@example.com",
            email="colleague@example.com",
            password=PASSWORD,
        )
        Membership.objects.create(
            user=administrator,
            organization=self.organization_a,
            role=Membership.Role.ADMIN,
        )
        self.authenticate_as(administrator)

        response = self.client.post(
            f"/api/organizations/{self.organization_a.id}/members/",
            {"user_email": colleague.email, "role": "owner"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            Membership.objects.filter(
                user=colleague, organization=self.organization_a
            ).exists()
        )

    def test_owner_cannot_remove_the_only_owner_membership(self):
        owner_membership = Membership.objects.get(
            user=self.owner_a, organization=self.organization_a
        )
        self.authenticate_as(self.owner_a)

        response = self.client.delete(
            f"/api/organizations/{self.organization_a.id}/members/{owner_membership.id}/"
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            Membership.objects.filter(
                user=self.owner_a, organization=self.organization_a
            ).exists()
        )

    def test_equipment_crud_is_scoped_to_active_organization(self):
        equipment = Equipment.objects.create(
            organization=self.organization_a,
            customer=self.customer_a,
            name="Air conditioner",
            serial_number="SF-001",
        )
        Equipment.objects.create(
            organization=self.organization_b,
            customer=self.customer_b,
            name="Water pump",
        )
        self.authenticate_as(self.owner_a)
        base_url = f"/api/organizations/{self.organization_a.id}/equipment/"

        listing = self.client.get(base_url)
        update = self.client.patch(
            f"{base_url}{equipment.id}/",
            {"name": "Updated air conditioner"},
            format="json",
        )
        foreign_detail = self.client.get(
            f"{base_url}{Equipment.objects.get(name='Water pump').id}/"
        )

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.data["customer_name"], self.customer_a.name)
        self.assertEqual(foreign_detail.status_code, 404)

    def test_equipment_search_includes_customer_and_asset_fields_with_tenant_scope(self):
        Equipment.objects.create(
            organization=self.organization_a,
            customer=self.customer_a,
            name="Compressor",
            manufacturer="Northwind",
            serial_number="NW-9300",
        )
        Equipment.objects.create(
            organization=self.organization_b,
            customer=self.customer_b,
            name="Compressor",
            manufacturer="Northwind",
            serial_number="NW-9301",
        )
        self.customer_a.name = "Northwind Facilities"
        self.customer_a.save(update_fields=["name"])
        self.authenticate_as(self.owner_a)
        base_url = f"/api/organizations/{self.organization_a.id}/equipment/"

        by_serial = self.client.get(f"{base_url}?search=NW-9300")
        by_manufacturer = self.client.get(f"{base_url}?search=northwind")
        by_customer = self.client.get(f"{base_url}?search=Facilities")

        self.assertEqual(by_serial.data["count"], 1)
        self.assertEqual(by_manufacturer.data["count"], 1)
        self.assertEqual(by_customer.data["count"], 1)
        self.assertEqual(by_customer.data["results"][0]["customer_name"], "Northwind Facilities")

    def test_equipment_list_uses_standard_pagination(self):
        for index in range(51):
            Equipment.objects.create(
                organization=self.organization_a,
                customer=self.customer_a,
                name=f"Asset {index:02d}",
            )
        self.authenticate_as(self.owner_a)
        base_url = f"/api/organizations/{self.organization_a.id}/equipment/"

        first_page = self.client.get(base_url)
        second_page = self.client.get(f"{base_url}?page=2")

        self.assertEqual(first_page.data["count"], 51)
        self.assertEqual(len(first_page.data["results"]), 50)
        self.assertEqual(len(second_page.data["results"]), 1)

    def test_equipment_rejects_warranty_expiry_before_installation(self):
        self.authenticate_as(self.owner_a)

        response = self.client.post(
            f"/api/organizations/{self.organization_a.id}/equipment/",
            {
                "customer": self.customer_a.id,
                "name": "Invalid dates",
                "installed_at": "2025-04-01",
                "warranty_expires_at": "2025-03-31",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("warranty_expires_at", response.data)

    def test_technician_cannot_write_equipment(self):
        technician = User.objects.create_user(
            username="equipment-tech@example.com",
            email="equipment-tech@example.com",
            password=PASSWORD,
        )
        Membership.objects.create(
            user=technician,
            organization=self.organization_a,
            role=Membership.Role.TECHNICIAN,
        )
        self.authenticate_as(technician)

        response = self.client.post(
            f"/api/organizations/{self.organization_a.id}/equipment/",
            {"customer": self.customer_a.id, "name": "Restricted asset"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Equipment.objects.filter(name="Restricted asset").exists())


class ServiceJobTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="jobs-owner@example.com",
            email="jobs-owner@example.com",
            password=PASSWORD,
            first_name="Jobs Owner",
        )
        self.manager = User.objects.create_user(
            username="jobs-manager@example.com",
            email="jobs-manager@example.com",
            password=PASSWORD,
            first_name="Jobs Manager",
        )
        self.technician_user = User.objects.create_user(
            username="jobs-tech@example.com",
            email="jobs-tech@example.com",
            password=PASSWORD,
            first_name="Assigned Technician",
        )
        self.other_technician_user = User.objects.create_user(
            username="other-tech@example.com",
            email="other-tech@example.com",
            password=PASSWORD,
            first_name="Other Technician",
        )
        self.foreign_owner = User.objects.create_user(
            username="foreign-owner@example.com",
            email="foreign-owner@example.com",
            password=PASSWORD,
        )
        self.organization = Organization.objects.create(
            name="Jobs Organization", created_by=self.owner
        )
        self.foreign_organization = Organization.objects.create(
            name="Foreign Jobs Organization", created_by=self.foreign_owner
        )
        self.owner_membership = Membership.objects.create(
            user=self.owner,
            organization=self.organization,
            role=Membership.Role.OWNER,
        )
        self.manager_membership = Membership.objects.create(
            user=self.manager,
            organization=self.organization,
            role=Membership.Role.MANAGER,
        )
        self.technician_membership = Membership.objects.create(
            user=self.technician_user,
            organization=self.organization,
            role=Membership.Role.TECHNICIAN,
        )
        self.other_technician_membership = Membership.objects.create(
            user=self.other_technician_user,
            organization=self.organization,
            role=Membership.Role.TECHNICIAN,
        )
        self.foreign_membership = Membership.objects.create(
            user=self.foreign_owner,
            organization=self.foreign_organization,
            role=Membership.Role.OWNER,
        )
        self.customer = Customer.objects.create(
            organization=self.organization, name="Service customer"
        )
        self.equipment = Equipment.objects.create(
            organization=self.organization,
            customer=self.customer,
            name="Service unit",
        )
        self.foreign_customer = Customer.objects.create(
            organization=self.foreign_organization, name="Foreign customer"
        )
        self.base_url = f"/api/organizations/{self.organization.id}/jobs/"

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def create_job(self, **overrides):
        payload = {
            "customer": self.customer.id,
            "title": "Annual equipment service",
            "description": "Inspect and service unit",
        }
        payload.update(overrides)
        return self.client.post(self.base_url, payload, format="json")

    def test_manager_creates_scheduled_job_and_initial_status_history(self):
        self.authenticate_as(self.manager)

        response = self.create_job(
            equipment=self.equipment.id,
            assigned_technician=self.technician_membership.id,
            status="scheduled",
            scheduled_for="2026-10-20T10:00:00+05:30",
        )

        self.assertEqual(response.status_code, 201, response.data)
        job = ServiceJob.objects.get(pk=response.data["id"])
        self.assertEqual(job.organization, self.organization)
        self.assertEqual(job.created_by, self.manager)
        self.assertEqual(job.assigned_technician, self.technician_membership)
        self.assertEqual(job.status_history.count(), 1)
        self.assertEqual(job.status_history.first().status, ServiceJob.Status.SCHEDULED)

    def test_scheduling_requires_a_technician_and_schedule_time(self):
        self.authenticate_as(self.manager)

        missing_assignment = self.create_job(
            status="scheduled", scheduled_for="2026-10-20T10:00:00+05:30"
        )
        missing_schedule = self.create_job(
            assigned_technician=self.technician_membership.id,
            status="scheduled",
        )

        self.assertEqual(missing_assignment.status_code, 400)
        self.assertIn("assigned_technician", missing_assignment.data)
        self.assertEqual(missing_schedule.status_code, 400)
        self.assertIn("scheduled_for", missing_schedule.data)
        self.assertEqual(ServiceJob.objects.count(), 0)

    def test_job_filters_search_scheduled_window_and_technician(self):
        assigned = ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            assigned_technician=self.technician_membership,
            created_by=self.manager,
            title="Compressor inspection",
            status=ServiceJob.Status.SCHEDULED,
            scheduled_for="2026-10-20T10:00:00+05:30",
        )
        ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            assigned_technician=self.other_technician_membership,
            created_by=self.manager,
            title="Pump service",
            status=ServiceJob.Status.SCHEDULED,
            scheduled_for="2026-11-20T10:00:00+05:30",
        )
        self.authenticate_as(self.manager)

        response = self.client.get(
            self.base_url
            + "?search=compressor&status=scheduled&technician="
            + str(self.technician_membership.id)
            + "&scheduled_from=2026-10-20&scheduled_to=2026-10-31"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], assigned.id)

    def test_job_filter_rejects_invalid_or_reversed_schedule_dates(self):
        self.authenticate_as(self.manager)

        invalid_date = self.client.get(f"{self.base_url}?scheduled_from=not-a-date")
        reversed_range = self.client.get(
            f"{self.base_url}?scheduled_from=2026-10-30&scheduled_to=2026-10-01"
        )

        self.assertEqual(invalid_date.status_code, 400)
        self.assertIn("scheduled_from", invalid_date.data)
        self.assertEqual(reversed_range.status_code, 400)
        self.assertIn("scheduled_to", reversed_range.data)

    def test_manager_can_read_team_members_to_assign_jobs_but_not_modify_memberships(self):
        self.authenticate_as(self.manager)

        listing = self.client.get(
            f"/api/organizations/{self.organization.id}/members/"
        )
        add_attempt = self.client.post(
            f"/api/organizations/{self.organization.id}/members/",
            {"user_email": "new-tech@example.com", "role": "technician"},
            format="json",
        )

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 4)
        self.assertEqual(add_attempt.status_code, 403)

    def test_job_rejects_equipment_that_belongs_to_a_different_customer(self):
        self.authenticate_as(self.manager)

        response = self.create_job(
            customer=self.foreign_customer.id,
            equipment=self.equipment.id,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ServiceJob.objects.count(), 0)

    def test_user_cannot_assign_a_technician_from_another_organization(self):
        self.authenticate_as(self.foreign_owner)

        response = self.client.post(
            f"/api/organizations/{self.foreign_organization.id}/jobs/",
            {
                "customer": self.foreign_customer.id,
                "title": "Foreign job",
                "assigned_technician": self.technician_membership.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ServiceJob.objects.count(), 0)

    def test_technician_sees_only_assigned_jobs_and_can_advance_status(self):
        assigned = ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            equipment=self.equipment,
            assigned_technician=self.technician_membership,
            created_by=self.manager,
            title="Assigned service",
            status=ServiceJob.Status.SCHEDULED,
            scheduled_for="2026-10-20T10:00:00+05:30",
        )
        ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            created_by=self.manager,
            title="Unassigned service",
        )
        self.authenticate_as(self.technician_user)

        listing = self.client.get(self.base_url)
        update = self.client.patch(
            f"{self.base_url}{assigned.id}/",
            {
                "status": "in_progress",
                "technician_note": "Inspection started.",
            },
            format="json",
        )

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data["count"], 1)
        self.assertEqual(listing.data["results"][0]["id"], assigned.id)
        self.assertEqual(update.status_code, 200, update.data)
        self.assertEqual(update.data["status"], ServiceJob.Status.IN_PROGRESS)
        assigned.refresh_from_db()
        self.assertEqual(assigned.status_history.count(), 1)
        self.assertEqual(assigned.status_history.first().note, "Inspection started.")

    def test_assigned_technician_must_submit_completion_report(self):
        job = ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            assigned_technician=self.technician_membership,
            created_by=self.manager,
            title="Finish repair",
            status=ServiceJob.Status.IN_PROGRESS,
            scheduled_for="2026-10-20T10:00:00+05:30",
        )
        self.authenticate_as(self.technician_user)

        missing_report = self.client.patch(
            f"{self.base_url}{job.id}/",
            {"status": "completed"},
            format="json",
        )
        oversized_report = self.client.patch(
            f"{self.base_url}{job.id}/",
            {"status": "completed", "completion_report": "R" * 10001},
            format="json",
        )
        completed = self.client.patch(
            f"{self.base_url}{job.id}/",
            {
                "status": "completed",
                "completion_report": "Replaced compressor and tested operation.",
            },
            format="json",
        )

        self.assertEqual(missing_report.status_code, 400)
        self.assertIn("completion_report", missing_report.data)
        self.assertEqual(oversized_report.status_code, 400)
        self.assertIn("completion_report", oversized_report.data)
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(
            completed.data["completion_report"],
            "Replaced compressor and tested operation.",
        )
        job.refresh_from_db()
        self.assertEqual(job.status, ServiceJob.Status.COMPLETED)
        self.assertEqual(job.status_history.count(), 1)
        self.assertEqual(
            job.status_history.get().note,
            "Replaced compressor and tested operation.",
        )

        locked_report = self.client.patch(
            f"{self.base_url}{job.id}/",
            {"completion_report": "Changed after closure."},
            format="json",
        )
        self.assertEqual(locked_report.status_code, 400)
        self.assertIn("completion_report", locked_report.data)
        job.refresh_from_db()
        self.assertEqual(
            job.completion_report,
            "Replaced compressor and tested operation.",
        )

    def test_work_notes_are_append_only_and_scoped_to_assigned_technician(self):
        job = ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            assigned_technician=self.technician_membership,
            created_by=self.manager,
            title="Document inspection",
            status=ServiceJob.Status.SCHEDULED,
            scheduled_for="2026-10-20T10:00:00+05:30",
        )
        notes_url = f"{self.base_url}{job.id}/notes/"
        self.authenticate_as(self.technician_user)

        first = self.client.post(
            notes_url, {"note": "Filter cleaned."}, format="json"
        )
        blank = self.client.post(notes_url, {"note": "  "}, format="json")
        oversized = self.client.post(
            notes_url, {"note": "N" * 5001}, format="json"
        )
        second = self.client.post(
            notes_url, {"note": "Pressure checked."}, format="json"
        )
        listed = self.client.get(notes_url)

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            [row["note"] for row in listed.data],
            ["Filter cleaned.", "Pressure checked."],
        )
        self.assertEqual(ServiceJobWorkNote.objects.filter(job=job).count(), 2)
        first_note = ServiceJobWorkNote.objects.get(job=job, note="Filter cleaned.")
        self.assertEqual(first_note.created_by, self.technician_user)
        self.assertIsNotNone(first_note.created_at)

        self.client.force_authenticate(user=self.other_technician_user)
        denied = self.client.post(notes_url, {"note": "Not assigned."}, format="json")
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(ServiceJobWorkNote.objects.filter(job=job).count(), 2)

    def test_job_pagination_keeps_results_inside_the_organization(self):
        for index in range(51):
            ServiceJob.objects.create(
                organization=self.organization,
                customer=self.customer,
                created_by=self.manager,
                title=f"Job {index}",
            )
        ServiceJob.objects.create(
            organization=self.foreign_organization,
            customer=self.foreign_customer,
            created_by=self.foreign_owner,
            title="Foreign job",
        )
        self.authenticate_as(self.manager)

        first_page = self.client.get(self.base_url)
        second_page = self.client.get(f"{self.base_url}?page=2")

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.data["count"], 51)
        self.assertEqual(len(first_page.data["results"]), 50)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(second_page.data["count"], 51)
        self.assertEqual(len(second_page.data["results"]), 1)
        self.assertTrue(
            all(
                job["customer"] == self.customer.id
                for job in first_page.data["results"] + second_page.data["results"]
            )
        )

    def test_technician_cannot_update_unassigned_job_or_edit_job_details(self):
        assigned_to_other = ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            assigned_technician=self.other_technician_membership,
            created_by=self.manager,
            title="Other technician job",
            status=ServiceJob.Status.SCHEDULED,
            scheduled_for="2026-10-20T10:00:00+05:30",
        )
        self.authenticate_as(self.technician_user)

        foreign_assignment = self.client.get(f"{self.base_url}{assigned_to_other.id}/")
        create_attempt = self.create_job()
        details_update = self.client.patch(
            f"{self.base_url}{assigned_to_other.id}/",
            {"title": "Unauthorized"},
            format="json",
        )

        self.assertEqual(foreign_assignment.status_code, 404)
        self.assertEqual(create_attempt.status_code, 403)
        self.assertEqual(details_update.status_code, 404)
        assigned_to_other.refresh_from_db()
        self.assertEqual(assigned_to_other.title, "Other technician job")

    def test_job_status_cannot_skip_or_reopen_completed_work(self):
        job = ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            created_by=self.manager,
            title="Completed job",
            status=ServiceJob.Status.COMPLETED,
        )
        self.authenticate_as(self.manager)

        response = self.client.patch(
            f"{self.base_url}{job.id}/",
            {"status": "scheduled"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)
        job.refresh_from_db()
        self.assertEqual(job.status, ServiceJob.Status.COMPLETED)

    def test_job_history_route_is_organization_scoped(self):
        job = ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            created_by=self.manager,
            title="History job",
        )
        ServiceJobStatusHistory.objects.create(
            job=job,
            status=job.status,
            changed_by=self.manager,
        )
        self.authenticate_as(self.foreign_owner)

        response = self.client.get(f"{self.base_url}{job.id}/history/")

        self.assertEqual(response.status_code, 403)

    def test_owner_can_read_jobs_but_technician_data_is_not_exposed_to_other_tenants(self):
        job = ServiceJob.objects.create(
            organization=self.organization,
            customer=self.customer,
            assigned_technician=self.technician_membership,
            created_by=self.manager,
            title="Private service job",
        )
        self.authenticate_as(self.foreign_owner)

        response = self.client.get(
            f"/api/organizations/{self.foreign_organization.id}/jobs/{job.id}/"
        )

        self.assertEqual(response.status_code, 404)


class ServiceContractTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="amc-owner@example.com",
            email="amc-owner@example.com",
            password=PASSWORD,
            first_name="AMC Owner",
        )
        self.foreign_owner = User.objects.create_user(
            username="amc-foreign@example.com",
            email="amc-foreign@example.com",
            password=PASSWORD,
        )
        self.technician = User.objects.create_user(
            username="amc-tech@example.com",
            email="amc-tech@example.com",
            password=PASSWORD,
            first_name="AMC Technician",
        )
        self.organization = Organization.objects.create(
            name="AMC Organization", created_by=self.owner
        )
        self.foreign_organization = Organization.objects.create(
            name="Foreign AMC Organization", created_by=self.foreign_owner
        )
        Membership.objects.create(
            user=self.owner,
            organization=self.organization,
            role=Membership.Role.OWNER,
        )
        self.technician_membership = Membership.objects.create(
            user=self.technician,
            organization=self.organization,
            role=Membership.Role.TECHNICIAN,
        )
        Membership.objects.create(
            user=self.foreign_owner,
            organization=self.foreign_organization,
            role=Membership.Role.OWNER,
        )
        self.customer = Customer.objects.create(
            organization=self.organization,
            name="AMC Customer",
            email="customer@example.com",
        )
        self.equipment = Equipment.objects.create(
            organization=self.organization,
            customer=self.customer,
            name="Covered AC",
            serial_number="AC-001",
        )
        self.foreign_customer = Customer.objects.create(
            organization=self.foreign_organization, name="Foreign AMC Customer"
        )
        self.today = timezone.localdate()
        self.base_url = f"/api/organizations/{self.organization.id}/contracts/"
        self.client.force_authenticate(user=self.owner)

    def create_contract(self, **overrides):
        payload = {
            "customer": self.customer.id,
            "covered_equipment": [self.equipment.id],
            "contract_type": "comprehensive",
            "start_date": self.today.isoformat(),
            "end_date": (self.today + timedelta(days=365)).isoformat(),
            "contract_value": "12500.00",
            "included_visits": 4,
            "visit_frequency": "quarterly",
            "payment_terms": "Annual payment in advance",
            "terms_and_conditions": "Standard service coverage.",
            "renewal_reminders_enabled": True,
            "reminder_days": [30, 7, 1],
            "status": "active",
        }
        payload.update(overrides)
        return self.client.post(self.base_url, payload, format="json")

    def test_create_contract_assigns_tenant_scoped_number_and_visit_balance(self):
        response = self.create_contract()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["contract_number"].startswith("AMC-"))
        self.assertEqual(response.data["currency"], "INR")
        self.assertEqual(response.data["visits_consumed"], 0)
        self.assertEqual(response.data["visits_remaining"], 4)
        contract = ServiceContract.objects.get(pk=response.data["id"])
        self.assertEqual(list(contract.covered_equipment.all()), [self.equipment])

    def test_contract_rejects_foreign_customer_or_equipment(self):
        foreign_equipment = Equipment.objects.create(
            organization=self.foreign_organization,
            customer=self.foreign_customer,
            name="Foreign unit",
        )

        customer_response = self.create_contract(customer=self.foreign_customer.id)
        equipment_response = self.create_contract(
            covered_equipment=[foreign_equipment.id]
        )

        self.assertEqual(customer_response.status_code, 400)
        self.assertEqual(equipment_response.status_code, 400)
        self.assertEqual(ServiceContract.objects.count(), 0)

    def test_user_cannot_read_another_tenant_contract(self):
        created = self.create_contract()
        self.client.force_authenticate(user=self.foreign_owner)

        response = self.client.get(
            f"/api/organizations/{self.foreign_organization.id}/contracts/{created.data['id']}/"
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_can_explicitly_renew_contract_once(self):
        contract_response = self.create_contract()
        contract = ServiceContract.objects.get(pk=contract_response.data["id"])
        self.client.force_authenticate(user=self.owner)

        response = self.client.post(
            f"{self.base_url}{contract.id}/renew/",
            {
                "end_date": (contract.end_date + timedelta(days=366)).isoformat(),
                "contract_value": "14000.00",
            },
            format="json",
        )
        repeated = self.client.post(
            f"{self.base_url}{contract.id}/renew/",
            {
                "end_date": (contract.end_date + timedelta(days=366)).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        renewed = ServiceContract.objects.get(pk=response.data["id"])
        self.assertEqual(renewed.renewed_from, contract)
        self.assertEqual(renewed.status, ServiceContract.Status.DRAFT)
        self.assertEqual(renewed.start_date, contract.end_date + timedelta(days=1))
        self.assertEqual(renewed.contract_value, Decimal("14000.00"))
        self.assertEqual(list(renewed.covered_equipment.all()), [self.equipment])
        self.assertEqual(repeated.status_code, 400)
        self.assertEqual(ServiceContract.objects.count(), 2)

    def test_upcoming_renewals_filters_by_range_and_tenant(self):
        due = self.create_contract(
            end_date=(self.today + timedelta(days=7)).isoformat()
        )
        self.assertEqual(due.status_code, 201, due.data)
        later = self.create_contract(
            end_date=(self.today + timedelta(days=60)).isoformat()
        )
        self.assertEqual(later.status_code, 201, later.data)

        response = self.client.get(f"{self.base_url}upcoming-renewals/?days=30")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["days_until_expiry"], 7)

    @override_settings(TIME_ZONE="Asia/Kolkata")
    def test_upcoming_renewals_include_today_and_last_day_in_business_timezone(self):
        from unittest.mock import patch

        self.create_contract(
            start_date="2026-10-01",
            end_date="2026-10-13",
        )
        expires_today = self.create_contract(
            start_date="2026-10-01",
            end_date="2026-10-14",
        )
        expires_on_range_end = self.create_contract(
            start_date="2026-10-01",
            end_date="2026-11-13",
        )
        self.create_contract(
            start_date="2026-10-01",
            end_date="2026-11-14",
        )
        utc_now_after_india_midnight = datetime(
            2026, 10, 13, 18, 45, tzinfo=datetime_timezone.utc
        )

        with patch(
            "django.utils.timezone.now",
            return_value=utc_now_after_india_midnight,
        ):
            response = self.client.get(f"{self.base_url}upcoming-renewals/?days=30")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        expiry_days = {
            row["id"]: row["days_until_expiry"] for row in response.data["results"]
        }
        self.assertEqual(expiry_days[expires_today.data["id"]], 0)
        self.assertEqual(expiry_days[expires_on_range_end.data["id"]], 30)

    def test_upcoming_renewal_days_are_validated(self):
        response = self.client.get(f"{self.base_url}upcoming-renewals/?days=500")

        self.assertEqual(response.status_code, 400)
        self.assertIn("days", response.data)

    def test_invalid_contract_dates_and_duplicate_reminder_intervals_are_rejected(self):
        invalid_dates = self.create_contract(
            end_date=(self.today - timedelta(days=1)).isoformat()
        )
        invalid_reminders = self.create_contract(reminder_days=[7, 7])

        self.assertEqual(invalid_dates.status_code, 400)
        self.assertEqual(invalid_reminders.status_code, 400)
        self.assertEqual(ServiceContract.objects.count(), 0)

    def test_completed_contracted_job_consumes_exactly_one_included_visit(self):
        contract_response = self.create_contract()
        contract_id = contract_response.data["id"]
        jobs_url = f"/api/organizations/{self.organization.id}/jobs/"
        job_response = self.client.post(
            jobs_url,
            {
                "customer": self.customer.id,
                "equipment": self.equipment.id,
                "service_contract": contract_id,
                "assigned_technician": self.technician_membership.id,
                "title": "AMC preventive visit",
            },
            format="json",
        )
        self.assertEqual(job_response.status_code, 201, job_response.data)
        job_id = job_response.data["id"]
        self.client.patch(
            f"{jobs_url}{job_id}/",
            {
                "status": "scheduled",
                "scheduled_for": f"{self.today.isoformat()}T10:00:00+05:30",
            },
            format="json",
        )
        self.client.patch(f"{jobs_url}{job_id}/", {"status": "in_progress"}, format="json")

        completed = self.client.patch(
            f"{jobs_url}{job_id}/",
            {
                "status": "completed",
                "completion_report": "Preventive visit completed and tested.",
            },
            format="json",
        )
        contract = ServiceContract.objects.get(pk=contract_id)
        self.assertEqual(completed.status_code, 200, completed.data)
        self.assertEqual(ContractVisit.objects.filter(contract=contract).count(), 1)
        self.assertEqual(contract.visits.count(), 1)

    @override_settings(TIME_ZONE="Asia/Kolkata")
    def test_contract_visit_dates_include_local_start_and_end_day(self):
        from unittest.mock import patch

        active_today = self.create_contract(
            start_date="2026-10-14",
            end_date="2026-10-14",
            included_visits=1,
        )
        starts_tomorrow = self.create_contract(
            start_date="2026-10-15",
            end_date="2026-10-15",
            included_visits=1,
        )
        expired_yesterday = self.create_contract(
            start_date="2026-10-01",
            end_date="2026-10-13",
            included_visits=1,
        )
        jobs_url = f"/api/organizations/{self.organization.id}/jobs/"

        def prepare_job(contract_id, title):
            response = self.client.post(
                jobs_url,
                {
                    "customer": self.customer.id,
                    "equipment": self.equipment.id,
                    "service_contract": contract_id,
                    "assigned_technician": self.technician_membership.id,
                    "title": title,
                    "status": "scheduled",
                    "scheduled_for": "2026-10-14T10:00:00+05:30",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.data)
            job_url = f"{jobs_url}{response.data['id']}/"
            started = self.client.patch(
                job_url, {"status": "in_progress"}, format="json"
            )
            self.assertEqual(started.status_code, 200, started.data)
            return job_url

        covered_today_job = prepare_job(active_today.data["id"], "Last coverage day")
        over_quota_job = prepare_job(active_today.data["id"], "Extra included visit")
        future_coverage_job = prepare_job(starts_tomorrow.data["id"], "Early visit")
        after_expiry_job = prepare_job(expired_yesterday.data["id"], "Late visit")
        utc_now_after_india_midnight = datetime(
            2026, 10, 13, 18, 45, tzinfo=datetime_timezone.utc
        )

        with patch(
            "django.utils.timezone.now",
            return_value=utc_now_after_india_midnight,
        ):
            covered_today = self.client.patch(
                covered_today_job,
                {
                    "status": "completed",
                    "completion_report": "Visit completed on the contract end date.",
                },
                format="json",
            )
            over_quota = self.client.patch(
                over_quota_job,
                {
                    "status": "completed",
                    "completion_report": "This visit exceeds the allowance.",
                },
                format="json",
            )
            before_start = self.client.patch(
                future_coverage_job,
                {
                    "status": "completed",
                    "completion_report": "Attempted before coverage begins.",
                },
                format="json",
            )
            after_expiry = self.client.patch(
                after_expiry_job,
                {
                    "status": "completed",
                    "completion_report": "Attempted after coverage ended.",
                },
                format="json",
            )

        self.assertEqual(covered_today.status_code, 200, covered_today.data)
        self.assertEqual(over_quota.status_code, 400)
        self.assertIn("service_contract", over_quota.data)
        self.assertEqual(before_start.status_code, 400)
        self.assertIn("service_contract", before_start.data)
        self.assertEqual(after_expiry.status_code, 400)
        self.assertIn("service_contract", after_expiry.data)
        self.assertEqual(
            ContractVisit.objects.filter(
                contract_id=active_today.data["id"]
            ).count(),
            1,
        )
        self.assertFalse(
            ContractVisit.objects.filter(
                contract_id=starts_tomorrow.data["id"]
            ).exists()
        )
        self.assertFalse(
            ContractVisit.objects.filter(
                contract_id=expired_yesterday.data["id"]
            ).exists()
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_due_reminders_send_once_even_when_command_runs_twice(self):
        self.create_contract(
            end_date=(self.today + timedelta(days=7)).isoformat(),
            reminder_days=[7],
        )

        call_command("send_contract_renewal_reminders", verbosity=0)
        call_command("send_contract_renewal_reminders", verbosity=0)

        self.assertEqual(len(mail.outbox), 1)
        reminder = ContractRenewalReminder.objects.get()
        self.assertEqual(reminder.status, ContractRenewalReminder.Status.SENT)
        self.assertEqual(reminder.attempts, 1)
        self.assertIsNotNone(reminder.sent_at)
        attempts = list(reminder.attempt_history.all())
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].attempt_number, 1)
        self.assertEqual(attempts[0].recipient, self.customer.email)
        self.assertEqual(attempts[0].status, ContractRenewalReminderAttempt.Status.SENT)

        history = self.client.get(f"{self.base_url}{reminder.contract_id}/reminders/")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.data[0]["attempt_history"]), 1)
        self.assertEqual(
            history.data[0]["attempt_history"][0]["recipient"],
            self.customer.email,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContractRenewalReminder.objects.create(
                    contract=reminder.contract,
                    contract_end_date=reminder.contract_end_date,
                    days_before_expiry=reminder.days_before_expiry,
                )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        TIME_ZONE="Asia/Kolkata",
    )
    def test_reminder_due_date_uses_india_calendar_day_across_utc_midnight(self):
        from unittest.mock import patch

        self.create_contract(
            start_date="2026-10-01",
            end_date="2026-10-15",
            reminder_days=[1],
        )
        utc_now_after_india_midnight = datetime(
            2026, 10, 13, 18, 45, tzinfo=datetime_timezone.utc
        )

        with patch(
            "django.utils.timezone.now",
            return_value=utc_now_after_india_midnight,
        ):
            call_command("send_contract_renewal_reminders", verbosity=0)

        reminder = ContractRenewalReminder.objects.get()
        self.assertEqual(reminder.contract_end_date.isoformat(), "2026-10-15")
        self.assertEqual(reminder.days_before_expiry, 1)
        self.assertEqual(reminder.status, ContractRenewalReminder.Status.SENT)
        self.assertEqual(reminder.attempt_history.get().status, "sent")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_reminder_command_observes_expiry_day_and_configured_interval_boundaries(self):
        self.create_contract(
            end_date=(self.today - timedelta(days=1)).isoformat(),
            reminder_days=[1],
        )
        self.create_contract(
            end_date=self.today.isoformat(),
            reminder_days=[1],
        )
        due_exactly_one_day = self.create_contract(
            end_date=(self.today + timedelta(days=1)).isoformat(),
            reminder_days=[1],
        )
        self.create_contract(
            end_date=(self.today + timedelta(days=2)).isoformat(),
            reminder_days=[1],
        )

        call_command("send_contract_renewal_reminders", verbosity=0)

        self.assertEqual(len(mail.outbox), 1)
        reminder = ContractRenewalReminder.objects.get()
        self.assertEqual(reminder.contract_id, due_exactly_one_day.data["id"])
        self.assertEqual(reminder.days_before_expiry, 1)
        self.assertEqual(ContractRenewalReminderAttempt.objects.count(), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_failed_reminder_is_reported_and_can_be_retried(self):
        from unittest.mock import patch

        self.create_contract(
            end_date=(self.today + timedelta(days=1)).isoformat(),
            reminder_days=[1],
        )

        with patch(
            "api.management.commands.send_contract_renewal_reminders.send_mail",
            side_effect=smtplib.SMTPException("mail unavailable"),
        ):
            with self.assertRaises(CommandError):
                call_command("send_contract_renewal_reminders", verbosity=0)
        failed = ContractRenewalReminder.objects.get()
        self.assertEqual(failed.status, ContractRenewalReminder.Status.FAILED)
        self.assertEqual(failed.attempts, 1)
        self.assertNotIn("mail unavailable", failed.last_error)

        call_command("send_contract_renewal_reminders", verbosity=0)

        failed.refresh_from_db()
        self.assertEqual(failed.status, ContractRenewalReminder.Status.SENT)
        self.assertEqual(failed.attempts, 2)
        self.assertEqual(len(mail.outbox), 1)
        attempts = list(failed.attempt_history.all())
        self.assertEqual(
            [attempt.status for attempt in attempts],
            [
                ContractRenewalReminderAttempt.Status.FAILED,
                ContractRenewalReminderAttempt.Status.SENT,
            ],
        )
        self.assertEqual(
            attempts[0].detail,
            "Email delivery failed: SMTPException.",
        )

    def test_missing_customer_email_is_recorded_as_a_delivery_failure(self):
        self.customer.email = ""
        self.customer.save(update_fields=["email"])
        self.create_contract(
            end_date=(self.today + timedelta(days=1)).isoformat(),
            reminder_days=[1],
        )

        with self.assertRaises(CommandError):
            call_command("send_contract_renewal_reminders", verbosity=0)

        reminder = ContractRenewalReminder.objects.get()
        self.assertEqual(reminder.status, ContractRenewalReminder.Status.FAILED)
        self.assertEqual(reminder.last_error, "Customer has no email address.")
        attempt = reminder.attempt_history.get()
        self.assertEqual(attempt.status, ContractRenewalReminderAttempt.Status.FAILED)
        self.assertEqual(attempt.recipient, "")
        self.assertEqual(attempt.detail, "Customer has no email address.")
