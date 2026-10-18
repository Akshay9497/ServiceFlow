import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from api.models import (
    Customer,
    ContractVisit,
    Equipment,
    Membership,
    Organization,
    PasswordResetOTP,
    ServiceJob,
    ServiceJobStatusHistory,
    ServiceContract,
)
from api.permissions import (
    MembershipManagementPermission,
    OrganizationRolePermission,
    ServiceJobPermission,
)
from api.serializers import (
    CurrentUserSerializer,
    ContractRenewalReminderSerializer,
    CustomerSerializer,
    ContractVisitSerializer,
    EmailTokenObtainPairSerializer,
    EquipmentSerializer,
    MembershipSerializer,
    MembershipOrganizationSerializer,
    OrganizationCreateSerializer,
    LogoutSerializer,
    PasswordResetCompleteSerializer,
    PasswordResetEmailChangeSerializer,
    PasswordResetOTPSerializer,
    PasswordResetRequestSerializer,
    RegistrationSerializer,
    ServiceJobSerializer,
    ServiceJobStatusHistorySerializer,
    ServiceJobWorkNoteSerializer,
    ServiceContractSerializer,
)
from api.subscription_services import enforce_usage_limit


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "ServiceFlow API"})


class PublicConfigurationView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {"registration_enabled": settings.PUBLIC_REGISTRATION_ENABLED}
        )


class RegistrationView(generics.CreateAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_register"
    serializer_class = RegistrationSerializer

    def create(self, request, *args, **kwargs):
        if not settings.PUBLIC_REGISTRATION_ENABLED:
            return Response(
                {
                    "detail": (
                        "New account registration is closed for this pilot. "
                        "Contact your ServiceFlow administrator."
                    )
                },
                status=403,
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(
            {
                "user": {
                    "id": result["user"].id,
                    "email": result["user"].email,
                    "name": result["user"].first_name,
                },
                "organization": {
                    "id": result["organization"].id,
                    "name": result["organization"].name,
                    "role": result["membership"].role,
                },
            },
            status=201,
        )


class EmailTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_token"
    serializer_class = EmailTokenObtainPairSerializer


class EmailTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_refresh"


class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_password_reset"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user_model = get_user_model()
        user = user_model._default_manager.filter(
            email__iexact=email, is_active=True
        ).first()

        if user and user.has_usable_password():
            now = timezone.now()
            code = f"{secrets.randbelow(1_000_000):06d}"
            with transaction.atomic():
                PasswordResetOTP.objects.filter(
                    user=user,
                    purpose=PasswordResetOTP.Purpose.ACCOUNT_RECOVERY,
                    consumed_at__isnull=True,
                ).update(consumed_at=now)
                challenge = PasswordResetOTP.objects.create(
                    user=user,
                    purpose=PasswordResetOTP.Purpose.ACCOUNT_RECOVERY,
                    email=user.email,
                    code_hash=make_password(code),
                    expires_at=now + timedelta(seconds=settings.PASSWORD_RESET_OTP_TIMEOUT),
                )
                send_mail(
                    subject="Your ServiceFlow verification code",
                    message=(
                        f"Hello {user.first_name or 'there'},\n\n"
                        f"Your password recovery code is {code}.\n"
                        f"It expires in {settings.PASSWORD_RESET_OTP_TIMEOUT // 60} minutes. "
                        "If you did not request this code, you can ignore this email."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[challenge.email],
                    fail_silently=False,
                )

        return Response(
            {
                "detail": (
                    "If an active account exists for that email, "
                    "a verification code has been sent."
                )
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetOTPVerifyView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_password_reset_otp"

    def post(self, request):
        serializer = PasswordResetOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = get_user_model()._default_manager.filter(
            email__iexact=email, is_active=True
        ).first()

        if not user or not user.has_usable_password():
            return Response(
                {"detail": "The code is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            challenge = (
                PasswordResetOTP.objects.select_for_update()
                .filter(
                    user=user,
                    purpose=PasswordResetOTP.Purpose.ACCOUNT_RECOVERY,
                    email__iexact=email,
                    verified_at__isnull=True,
                    consumed_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .first()
            )
            if not challenge or challenge.attempts >= settings.PASSWORD_RESET_OTP_MAX_ATTEMPTS:
                return Response(
                    {"detail": "The code is invalid or has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not check_password(serializer.validated_data["otp"], challenge.code_hash):
                challenge.attempts += 1
                challenge.save(update_fields=["attempts"])
                return Response(
                    {"detail": "The code is invalid or has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            challenge.verified_at = timezone.now()
            challenge.save(update_fields=["verified_at"])
            verification_token = signing.dumps(
                {"challenge_id": challenge.pk, "user_id": user.pk},
                salt="api.password-reset",
            )
        return Response(
            {
                "verification_token": verification_token,
            },
            status=status.HTTP_200_OK,
        )


def get_password_reset_challenge(verification_token):
    try:
        payload = signing.loads(
            verification_token,
            salt="api.password-reset",
            max_age=settings.PASSWORD_RESET_VERIFICATION_TIMEOUT,
        )
        challenge_id = payload["challenge_id"]
        user_id = payload["user_id"]
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise DjangoValidationError(
            "The verification has expired. Request a new code."
        ) from exc

    try:
        challenge = PasswordResetOTP.objects.select_related("user").get(
            pk=challenge_id,
            user_id=user_id,
            purpose=PasswordResetOTP.Purpose.ACCOUNT_RECOVERY,
            verified_at__isnull=False,
            consumed_at__isnull=True,
            expires_at__gt=timezone.now(),
            user__is_active=True,
        )
    except PasswordResetOTP.DoesNotExist as exc:
        raise DjangoValidationError(
            "The verification has expired. Request a new code."
        ) from exc

    if challenge.email.casefold() != challenge.user.email.casefold():
        raise DjangoValidationError(
            "The verification has expired. Request a new code."
        )
    return challenge


class PasswordResetEmailChangeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_password_reset"

    def post(self, request):
        serializer = PasswordResetEmailChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            challenge = get_password_reset_challenge(
                serializer.validated_data["verification_token"]
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )

        new_email = serializer.validated_data["new_email"]
        user = challenge.user
        if get_user_model()._default_manager.filter(
            email__iexact=new_email
        ).exclude(pk=user.pk).exists() or get_user_model()._default_manager.filter(
            username__iexact=new_email
        ).exclude(pk=user.pk).exists():
            return Response(
                {"detail": "That email is already used by another account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        code = f"{secrets.randbelow(1_000_000):06d}"
        with transaction.atomic():
            PasswordResetOTP.objects.filter(
                recovery_challenge=challenge,
                purpose=PasswordResetOTP.Purpose.NEW_EMAIL,
                consumed_at__isnull=True,
            ).update(consumed_at=now)
            email_challenge = PasswordResetOTP.objects.create(
                user=user,
                purpose=PasswordResetOTP.Purpose.NEW_EMAIL,
                email=new_email,
                code_hash=make_password(code),
                recovery_challenge=challenge,
                expires_at=now + timedelta(seconds=settings.PASSWORD_RESET_OTP_TIMEOUT),
            )
            send_mail(
                subject="Verify your new ServiceFlow login email",
                message=(
                    f"Your email verification code is {code}.\n"
                    f"It expires in {settings.PASSWORD_RESET_OTP_TIMEOUT // 60} minutes. "
                    "If you did not request this, you can ignore this email."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email_challenge.email],
                fail_silently=False,
            )
        return Response(
            {"detail": "A verification code has been sent to the new email address."},
            status=status.HTTP_200_OK,
        )


class PasswordResetCompleteView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth_password_reset_otp"

    def post(self, request):
        serializer = PasswordResetCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            challenge = get_password_reset_challenge(data["verification_token"])
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )

        user = challenge.user
        new_email = data["new_email"]
        if get_user_model()._default_manager.filter(
            email__iexact=new_email
        ).exclude(pk=user.pk).exists() or get_user_model()._default_manager.filter(
            username__iexact=new_email
        ).exclude(pk=user.pk).exists():
            return Response(
                {"detail": "That email is already used by another account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.email = new_email
        user.username = new_email
        try:
            validate_password(data["new_password"], user=user)
        except DjangoValidationError as exc:
            return Response(
                {"new_password": exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            challenge = PasswordResetOTP.objects.select_for_update().get(
                pk=challenge.pk
            )
            email_challenge = (
                PasswordResetOTP.objects.select_for_update()
                .filter(
                    recovery_challenge=challenge,
                    purpose=PasswordResetOTP.Purpose.NEW_EMAIL,
                    email__iexact=new_email,
                    verified_at__isnull=True,
                    consumed_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                .first()
            )
            if (
                challenge.consumed_at
                or not email_challenge
                or email_challenge.attempts >= settings.PASSWORD_RESET_OTP_MAX_ATTEMPTS
            ):
                return Response(
                    {"detail": "The code is invalid or has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not check_password(data["otp"], email_challenge.code_hash):
                email_challenge.attempts += 1
                email_challenge.save(update_fields=["attempts"])
                return Response(
                    {"detail": "The code is invalid or has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = get_user_model()._default_manager.select_for_update().get(
                pk=challenge.user_id
            )
            user.email = new_email
            user.username = new_email
            user.set_password(data["new_password"])
            try:
                with transaction.atomic():
                    user.save(update_fields=["email", "username", "password"])
            except IntegrityError:
                return Response(
                    {"detail": "That email is already used by another account."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            now = timezone.now()
            challenge.consumed_at = now
            challenge.save(update_fields=["consumed_at"])
            email_challenge.consumed_at = now
            email_challenge.verified_at = now
            email_challenge.save(update_fields=["consumed_at", "verified_at"])
            for outstanding_token in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=outstanding_token)

        return Response(
            {"detail": "Email and password updated. Sign in with your new email."},
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    def post(self, request):
        serializer = LogoutSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_205_RESET_CONTENT)


class CurrentUserView(APIView):
    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data)


class OrganizationListView(generics.ListCreateAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "organization_create"

    def get_throttles(self):
        if self.request.method != "POST":
            return []
        return super().get_throttles()

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OrganizationCreateSerializer
        return MembershipOrganizationSerializer

    def get_queryset(self):
        return Membership.objects.filter(user=self.request.user).select_related(
            "organization"
        )

    def create(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied(
                "Organizations can only be created by platform administrators in the Django superadmin."
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(
            MembershipOrganizationSerializer(
                membership, context=self.get_serializer_context()
            ).data,
            status=status.HTTP_201_CREATED,
        )


class OrganizationScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [OrganizationRolePermission]

    def get_organization(self):
        if not hasattr(self, "_organization"):
            self._organization = get_object_or_404(
                Organization.objects.filter(memberships__user=self.request.user),
                pk=self.kwargs["organization_pk"],
            )
        return self._organization

    def perform_create(self, serializer):
        serializer.save(organization=self.get_organization())


class CustomerViewSet(OrganizationScopedViewSet):
    serializer_class = CustomerSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "phone", "email", "address"]

    def get_queryset(self):
        return Customer.objects.filter(organization=self.get_organization())

    @transaction.atomic
    def perform_create(self, serializer):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        enforce_usage_limit(organization, "customers")
        serializer.save(organization=organization)

    def perform_destroy(self, instance):
        if instance.service_jobs.exists() or instance.service_contracts.exists():
            raise ValidationError(
                {
                    "detail": (
                        "This customer has service jobs or service contracts and "
                        "cannot be deleted. Keep the customer record to preserve "
                        "service history."
                    )
                }
            )
        instance.delete()


class EquipmentViewSet(OrganizationScopedViewSet):
    serializer_class = EquipmentSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "name",
        "manufacturer",
        "model_number",
        "serial_number",
        "customer__name",
    ]

    def get_queryset(self):
        return Equipment.objects.filter(
            organization=self.get_organization()
        ).select_related("customer")

    @transaction.atomic
    def perform_create(self, serializer):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        enforce_usage_limit(organization, "equipment")
        serializer.save(organization=organization)

    def perform_destroy(self, instance):
        if instance.service_contracts.exists():
            raise ValidationError(
                {
                    "detail": (
                        "Equipment covered by a service contract cannot be deleted."
                    )
                }
            )
        instance.delete()


class MembershipViewSet(viewsets.ModelViewSet):
    serializer_class = MembershipSerializer
    permission_classes = [MembershipManagementPermission]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_organization(self):
        if not hasattr(self, "_organization"):
            self._organization = get_object_or_404(
                Organization.objects.filter(memberships__user=self.request.user),
                pk=self.kwargs["organization_pk"],
            )
        return self._organization

    def get_queryset(self):
        return Membership.objects.filter(
            organization=self.get_organization()
        ).select_related("user")

    @transaction.atomic
    def perform_create(self, serializer):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        enforce_usage_limit(organization, "members")
        serializer.save()


class ServiceJobViewSet(OrganizationScopedViewSet):
    serializer_class = ServiceJobSerializer
    permission_classes = [ServiceJobPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "title",
        "description",
        "customer__name",
        "equipment__name",
        "equipment__serial_number",
        "assigned_technician__user__email",
    ]

    def get_queryset(self):
        queryset = (
            ServiceJob.objects.filter(organization=self.get_organization())
            .select_related(
                "customer",
                "equipment",
                "service_contract",
                "assigned_technician__user",
                "created_by",
            )
            .prefetch_related("status_history__changed_by", "work_notes__created_by")
        )
        if self.organization_membership.role == Membership.Role.TECHNICIAN:
            queryset = queryset.filter(
                assigned_technician=self.organization_membership
            )

        status = self.request.query_params.get("status")
        if status:
            valid_statuses = {choice for choice, _ in ServiceJob.Status.choices}
            if status not in valid_statuses:
                raise ValidationError({"status": "Choose a valid service job status."})
            queryset = queryset.filter(status=status)

        technician_id = self.request.query_params.get("technician")
        if technician_id:
            if not technician_id.isdecimal():
                raise ValidationError(
                    {"technician": "Choose a valid technician membership."}
                )
            queryset = queryset.filter(assigned_technician_id=technician_id)

        for parameter, lookup, error_message in (
            ("scheduled_from", "scheduled_for__date__gte", "Enter a valid start date."),
            ("scheduled_to", "scheduled_for__date__lte", "Enter a valid end date."),
        ):
            raw_date = self.request.query_params.get(parameter)
            if raw_date:
                parsed_date = parse_date(raw_date)
                if parsed_date is None:
                    raise ValidationError({parameter: error_message})
                queryset = queryset.filter(**{lookup: parsed_date})

        start_date = self.request.query_params.get("scheduled_from")
        end_date = self.request.query_params.get("scheduled_to")
        if start_date and end_date and parse_date(start_date) > parse_date(end_date):
            raise ValidationError(
                {"scheduled_to": "End date must be on or after the start date."}
            )

        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        enforce_usage_limit(organization, "jobs")
        if (
            serializer.validated_data.get("status", ServiceJob.Status.NEW)
            not in {ServiceJob.Status.NEW, ServiceJob.Status.SCHEDULED}
        ):
            raise ValidationError(
                {"status": "Create jobs as new or scheduled, then progress them."}
            )
        job = serializer.save(
            organization=organization, created_by=self.request.user
        )
        ServiceJobStatusHistory.objects.create(
            job=job,
            previous_status="",
            status=job.status,
            changed_by=self.request.user,
        )

    @transaction.atomic
    def perform_update(self, serializer):
        previous_status = serializer.instance.status
        job = ServiceJob.objects.select_for_update().get(
            pk=serializer.instance.pk, organization=self.get_organization()
        )
        serializer.instance = job
        job = serializer.save()
        if job.status != previous_status:
            ServiceJobStatusHistory.objects.create(
                job=job,
                previous_status=previous_status,
                status=job.status,
                note=(
                    job.completion_report
                    if job.status == ServiceJob.Status.COMPLETED
                    else job.technician_note
                ),
                changed_by=self.request.user,
            )
        if (
            job.status == ServiceJob.Status.COMPLETED
            and job.service_contract_id
            and not ContractVisit.objects.filter(job=job).exists()
        ):
            contract = ServiceContract.objects.select_for_update().get(
                pk=job.service_contract_id
            )
            today = timezone.localdate()
            if (
                contract.status != ServiceContract.Status.ACTIVE
                or today < contract.start_date
                or today > contract.end_date
            ):
                raise ValidationError(
                    {"service_contract": "The service contract is not active today."}
                )
            visits_consumed = ContractVisit.objects.filter(
                contract=contract
            ).count()
            if visits_consumed >= contract.included_visits:
                raise ValidationError(
                    {
                        "service_contract": (
                            "This contract has no included visits remaining."
                        )
                    }
                )
            ContractVisit.objects.create(
                contract=contract, job=job, recorded_by=self.request.user
            )

    def perform_destroy(self, instance):
        if instance.service_contract_id or hasattr(instance, "contract_visit"):
            raise ValidationError(
                {
                    "detail": (
                        "Jobs linked to a service contract or visit history cannot "
                        "be deleted."
                    )
                }
            )
        instance.delete()

    @action(detail=True, methods=["get"])
    def history(self, request, *args, **kwargs):
        job = self.get_object()
        history = job.status_history.select_related("changed_by")
        return Response(ServiceJobStatusHistorySerializer(history, many=True).data)

    @action(detail=True, methods=["get", "post"])
    def notes(self, request, *args, **kwargs):
        job = self.get_object()
        if request.method == "POST":
            serializer = ServiceJobWorkNoteSerializer(
                data=request.data,
                context={
                    **self.get_serializer_context(),
                    "job": job,
                    "request": request,
                },
            )
            serializer.is_valid(raise_exception=True)
            note = serializer.save()
            return Response(
                ServiceJobWorkNoteSerializer(note).data,
                status=status.HTTP_201_CREATED,
            )
        notes = job.work_notes.select_related("created_by")
        return Response(ServiceJobWorkNoteSerializer(notes, many=True).data)


class ServiceContractViewSet(OrganizationScopedViewSet):
    serializer_class = ServiceContractSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = (
            ServiceContract.objects.filter(organization=self.get_organization())
            .select_related("customer", "renewed_from", "renewal")
            .prefetch_related("covered_equipment", "visits")
            .annotate(_visits_consumed=Count("visits", distinct=True))
            .order_by("end_date", "contract_number")
        )
        status = self.request.query_params.get("status")
        if status:
            statuses = {choice for choice, _ in ServiceContract.Status.choices}
            if status not in statuses:
                raise ValidationError({"status": "Choose a valid contract status."})
            queryset = queryset.filter(status=status)
        customer_id = self.request.query_params.get("customer")
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        sequence = ServiceContract.objects.filter(organization=organization).count() + 1
        contract_number = f"AMC-{organization.pk:04d}-{sequence:06d}"
        serializer.save(
            organization=organization,
            created_by=self.request.user,
            contract_number=contract_number,
            currency="INR",
        )

    @transaction.atomic
    def perform_update(self, serializer):
        contract = ServiceContract.objects.select_for_update().get(
            pk=serializer.instance.pk, organization=self.get_organization()
        )
        serializer.instance = contract
        serializer.save()

    @action(detail=False, methods=["get"], url_path="upcoming-renewals")
    def upcoming_renewals(self, request, *args, **kwargs):
        raw_days = request.query_params.get("days", "30")
        try:
            days = int(raw_days)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"days": "Enter a whole number from 1 to 365."}) from exc
        if not 1 <= days <= 365:
            raise ValidationError({"days": "Enter a whole number from 1 to 365."})
        today = timezone.localdate()
        queryset = (
            self.get_queryset()
            .filter(
                status=ServiceContract.Status.ACTIVE,
                renewal_reminders_enabled=True,
                end_date__gte=today,
                end_date__lte=today + timedelta(days=days),
            )
        )
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"])
    def history(self, request, *args, **kwargs):
        contract = self.get_object()
        contract._visits_consumed = contract.visits.count()
        renewed = getattr(contract, "renewal", None)
        return Response(
            {
                "contract": self.get_serializer(contract).data,
                "renewal": (
                    self.get_serializer(renewed).data if renewed is not None else None
                ),
                "visits": ContractVisitSerializer(
                    contract.visits.select_related("job", "recorded_by"), many=True
                ).data,
            }
        )

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def renew(self, request, *args, **kwargs):
        organization = self.get_organization()
        contract = ServiceContract.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        if contract.status not in {
            ServiceContract.Status.ACTIVE,
            ServiceContract.Status.EXPIRED,
        }:
            raise ValidationError(
                {"status": "Only active or expired contracts can be renewed."}
            )
        existing = getattr(contract, "renewal", None)
        if existing is not None:
            raise ValidationError(
                {
                    "detail": (
                        f"This contract has already been renewed as "
                        f"{existing.contract_number}."
                    )
                }
            )
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        sequence = ServiceContract.objects.filter(organization=organization).count() + 1
        renewal_data = {
            "customer": contract.customer_id,
            "contract_type": contract.contract_type,
            "start_date": request.data.get(
                "start_date", (contract.end_date + timedelta(days=1)).isoformat()
            ),
            "end_date": request.data.get("end_date"),
            "contract_value": request.data.get(
                "contract_value", str(contract.contract_value)
            ),
            "covered_equipment": list(
                contract.covered_equipment.values_list("id", flat=True)
            ),
            "included_visits": contract.included_visits,
            "visit_frequency": contract.visit_frequency,
            "payment_terms": contract.payment_terms,
            "terms_and_conditions": contract.terms_and_conditions,
            "renewal_reminders_enabled": contract.renewal_reminders_enabled,
            "reminder_days": contract.reminder_days,
            "status": ServiceContract.Status.DRAFT,
        }
        serializer = self.get_serializer(data=renewal_data)
        serializer.is_valid(raise_exception=True)
        new_contract = serializer.save(
            organization=organization,
            created_by=request.user,
            contract_number=f"AMC-{organization.pk:04d}-{sequence:06d}",
            currency="INR",
            renewed_from=contract,
            contract_type=contract.contract_type,
            included_visits=contract.included_visits,
            visit_frequency=contract.visit_frequency,
            payment_terms=contract.payment_terms,
            terms_and_conditions=contract.terms_and_conditions,
            renewal_reminders_enabled=contract.renewal_reminders_enabled,
            reminder_days=contract.reminder_days,
            status=ServiceContract.Status.DRAFT,
            customer=contract.customer,
        )
        new_contract.covered_equipment.set(contract.covered_equipment.all())
        return Response(self.get_serializer(new_contract).data, status=201)

    @action(detail=True, methods=["get"])
    def reminders(self, request, *args, **kwargs):
        contract = self.get_object()
        reminders = contract.renewal_reminders.prefetch_related(
            "attempt_history"
        ).order_by("-updated_at")
        return Response(ContractRenewalReminderSerializer(reminders, many=True).data)
