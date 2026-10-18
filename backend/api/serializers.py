from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import (
    Customer,
    ContractRenewalReminder,
    ContractRenewalReminderAttempt,
    Equipment,
    ContractVisit,
    Membership,
    Organization,
    ServiceJob,
    ServiceJobStatusHistory,
    ServiceJobWorkNote,
    ServiceContract,
)

User = get_user_model()


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        attrs["username"] = attrs["username"].strip().lower()
        return super().validate(attrs)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return User.objects.normalize_email(value).lower()


class PasswordResetOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.RegexField(regex=r"^\d{6}$")

    def validate_email(self, value):
        return User.objects.normalize_email(value).lower()


class PasswordResetEmailChangeSerializer(serializers.Serializer):
    verification_token = serializers.CharField()
    new_email = serializers.EmailField(max_length=150)

    def validate_new_email(self, value):
        return User.objects.normalize_email(value).lower()


class PasswordResetCompleteSerializer(serializers.Serializer):
    verification_token = serializers.CharField()
    new_email = serializers.EmailField(max_length=150)
    otp = serializers.RegexField(regex=r"^\d{6}$")
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_email(self, value):
        return User.objects.normalize_email(value).lower()

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "The passwords do not match."}
            )
        return attrs


class RegistrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    organization_name = serializers.CharField(max_length=200)

    def validate_email(self, value):
        email = User.objects.normalize_email(value).lower()
        if len(email) > 150:
            raise serializers.ValidationError("Email must be 150 characters or fewer.")
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )
        return email

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Name cannot be blank.")
        return value.strip()

    def validate_organization_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Organization name cannot be blank.")
        return value.strip()

    def validate_password(self, value):
        validate_password(value)
        return value

    @transaction.atomic
    def create(self, validated_data):
        email = validated_data["email"]
        user = User.objects.create_user(
            username=email,
            email=email,
            password=validated_data["password"],
            first_name=validated_data["name"],
        )
        organization = Organization.objects.create(
            name=validated_data["organization_name"], created_by=user
        )
        membership = Membership.objects.create(
            organization=organization,
            user=user,
            role=Membership.Role.OWNER,
        )
        return {"user": user, "organization": organization, "membership": membership}


class OrganizationCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Organization name cannot be blank.")
        return value.strip()

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        organization = Organization.objects.create(
            name=validated_data["name"], created_by=user
        )
        return Membership.objects.create(
            organization=organization,
            user=user,
            role=Membership.Role.OWNER,
        )


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True)

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)
        except TokenError as exc:
            raise serializers.ValidationError(
                "Refresh token is invalid or expired."
            ) from exc
        if str(token.get("user_id")) != str(self.context["request"].user.pk):
            raise serializers.ValidationError(
                "Refresh token does not belong to the authenticated account."
            )
        return value

    def create(self, validated_data):
        RefreshToken(validated_data["refresh"]).blacklist()
        return True


class MembershipOrganizationSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="organization.id", read_only=True)
    membership_id = serializers.IntegerField(source="id", read_only=True)
    name = serializers.CharField(source="organization.name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "membership_id", "name", "role"]


class MembershipSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    name = serializers.CharField(source="user.first_name", read_only=True)
    user_email = serializers.EmailField(write_only=True, required=False)

    class Meta:
        model = Membership
        fields = ["id", "user_id", "email", "name", "user_email", "role", "joined_at"]
        read_only_fields = ["id", "user_id", "email", "name", "joined_at"]

    def validate_user_email(self, value):
        try:
            user = User.objects.get(email__iexact=value.strip())
        except User.DoesNotExist as exc:
            raise serializers.ValidationError(
                "No registered user has this email address."
            ) from exc
        view = self.context["view"]
        if self.instance is None and Membership.objects.filter(
            organization=view.get_organization(), user=user
        ).exists():
            raise serializers.ValidationError(
                "This user is already a member of the organization."
            )
        return user

    def validate(self, attrs):
        if self.context["view"].organization_membership.role == Membership.Role.MANAGER:
            raise serializers.ValidationError(
                "Managers may view memberships but cannot modify them."
            )
        if self.instance is None and "user_email" not in attrs:
            raise serializers.ValidationError(
                {"user_email": "This field is required when adding a member."}
            )
        if self.instance is not None and "user_email" in attrs:
            raise serializers.ValidationError(
                {"user_email": "A member's account cannot be changed."}
            )
        role = attrs.get("role", getattr(self.instance, "role", None))
        actor_role = self.context["view"].organization_membership.role
        if actor_role == Membership.Role.ADMIN and role in {
            Membership.Role.ADMIN,
            Membership.Role.OWNER,
        }:
            raise serializers.ValidationError(
                {"role": "Administrators can assign manager or technician roles only."}
            )
        return attrs

    def create(self, validated_data):
        user = validated_data.pop("user_email")
        organization = self.context["view"].get_organization()
        return Membership.objects.create(
            organization=organization, user=user, **validated_data
        )

    def update(self, instance, validated_data):
        validated_data.pop("user_email", None)
        return super().update(instance, validated_data)


class CurrentUserSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="first_name", read_only=True)
    organizations = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "organizations", "is_superuser"]

    def get_organizations(self, user):
        memberships = (
            Membership.objects.filter(user=user)
            .select_related("organization")
            .order_by("organization__name", "organization_id")
        )
        return MembershipOrganizationSerializer(
            memberships, many=True, context=self.context
        ).data


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "phone",
            "email",
            "address",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class EquipmentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = Equipment
        fields = [
            "id",
            "customer",
            "customer_name",
            "name",
            "manufacturer",
            "model_number",
            "serial_number",
            "installed_at",
            "warranty_expires_at",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "customer_name", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        view = self.context.get("view")
        if view is not None:
            self.fields["customer"].queryset = Customer.objects.filter(
                organization=view.get_organization()
            )

    def validate_customer(self, customer):
        organization = self.context["view"].get_organization()
        if customer.organization_id != organization.id:
            raise serializers.ValidationError(
                "Select a customer in the active organization."
            )
        return customer

    def validate(self, attrs):
        installed_at = attrs.get(
            "installed_at",
            getattr(self.instance, "installed_at", None),
        )
        warranty_expires_at = attrs.get(
            "warranty_expires_at",
            getattr(self.instance, "warranty_expires_at", None),
        )
        if (
            installed_at is not None
            and warranty_expires_at is not None
            and warranty_expires_at < installed_at
        ):
            raise serializers.ValidationError(
                {
                    "warranty_expires_at": (
                        "Warranty expiry cannot be before the installation date."
                    )
                }
            )
        return attrs


class ServiceJobStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(
        source="changed_by.get_full_name", read_only=True
    )

    class Meta:
        model = ServiceJobStatusHistory
        fields = [
            "id",
            "previous_status",
            "status",
            "note",
            "changed_by_name",
            "changed_at",
        ]
        read_only_fields = fields


class ServiceJobWorkNoteSerializer(serializers.ModelSerializer):
    note = serializers.CharField(max_length=5000)
    created_by_name = serializers.CharField(
        source="created_by.get_full_name", read_only=True
    )

    class Meta:
        model = ServiceJobWorkNote
        fields = ["id", "note", "created_by_name", "created_at"]
        read_only_fields = ["id", "created_by_name", "created_at"]

    def validate_note(self, value):
        if not value.strip():
            raise serializers.ValidationError("Work note cannot be blank.")
        return value.strip()

    def create(self, validated_data):
        return ServiceJobWorkNote.objects.create(
            job=self.context["job"],
            created_by=self.context["request"].user,
            **validated_data,
        )


class ContractVisitSerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source="job.title", read_only=True)
    job_status = serializers.CharField(source="job.status", read_only=True)
    recorded_by_name = serializers.CharField(
        source="recorded_by.get_full_name", read_only=True
    )

    class Meta:
        model = ContractVisit
        fields = ["id", "job", "job_title", "job_status", "recorded_by_name", "recorded_at"]
        read_only_fields = fields


class ServiceJobSerializer(serializers.ModelSerializer):
    completion_report = serializers.CharField(
        required=False, allow_blank=True, max_length=10000
    )
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    equipment_name = serializers.CharField(
        source="equipment.name", read_only=True, allow_null=True
    )
    assigned_technician_name = serializers.CharField(
        source="assigned_technician.user.get_full_name",
        read_only=True,
        allow_null=True,
    )
    assigned_technician_email = serializers.EmailField(
        source="assigned_technician.user.email",
        read_only=True,
        allow_null=True,
    )
    service_contract_number = serializers.CharField(
        source="service_contract.contract_number", read_only=True, allow_null=True
    )
    status_history = ServiceJobStatusHistorySerializer(many=True, read_only=True)
    work_notes = ServiceJobWorkNoteSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceJob
        fields = [
            "id",
            "customer",
            "customer_name",
            "equipment",
            "equipment_name",
            "assigned_technician",
            "assigned_technician_name",
            "assigned_technician_email",
            "service_contract",
            "service_contract_number",
            "title",
            "description",
            "status",
            "scheduled_for",
            "technician_note",
            "completion_report",
            "status_history",
            "work_notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "customer_name",
            "equipment_name",
            "assigned_technician_name",
            "assigned_technician_email",
            "service_contract_number",
            "status_history",
            "work_notes",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        view = self.context.get("view")
        if view is None:
            return
        organization = view.get_organization()
        self.fields["customer"].queryset = Customer.objects.filter(
            organization=organization
        )
        self.fields["equipment"].queryset = Equipment.objects.filter(
            organization=organization
        )
        self.fields["assigned_technician"].queryset = Membership.objects.filter(
            organization=organization, role=Membership.Role.TECHNICIAN
        )
        self.fields["service_contract"].queryset = ServiceContract.objects.filter(
            organization=organization, status=ServiceContract.Status.ACTIVE
        )

    def validate(self, attrs):
        instance = self.instance
        customer = attrs.get("customer", instance.customer if instance else None)
        equipment = attrs.get("equipment", instance.equipment if instance else None)
        technician = attrs.get(
            "assigned_technician",
            instance.assigned_technician if instance else None,
        )
        contract = attrs.get(
            "service_contract",
            instance.service_contract if instance else None,
        )
        status = attrs.get(
            "status", instance.status if instance else ServiceJob.Status.NEW
        )
        scheduled_for = attrs.get(
            "scheduled_for", instance.scheduled_for if instance else None
        )

        if equipment is not None and (
            customer is None or equipment.customer_id != customer.id
        ):
            raise serializers.ValidationError(
                {"equipment": "Equipment must belong to the selected customer."}
            )
        if contract is not None:
            if customer is None or contract.customer_id != customer.id:
                raise serializers.ValidationError(
                    {"service_contract": "The contract must belong to the selected customer."}
                )
            if contract.status != ServiceContract.Status.ACTIVE:
                raise serializers.ValidationError(
                    {"service_contract": "Only active contracts can cover service jobs."}
                )
            if equipment is not None and contract.covered_equipment.exists() and not (
                contract.covered_equipment.filter(pk=equipment.pk).exists()
            ):
                raise serializers.ValidationError(
                    {"equipment": "This equipment is not covered by the selected contract."}
                )

        if instance is not None and status != instance.status:
            transitions = {
                ServiceJob.Status.NEW: {
                    ServiceJob.Status.SCHEDULED,
                    ServiceJob.Status.CANCELLED,
                },
                ServiceJob.Status.SCHEDULED: {
                    ServiceJob.Status.IN_PROGRESS,
                    ServiceJob.Status.CANCELLED,
                },
                ServiceJob.Status.IN_PROGRESS: {
                    ServiceJob.Status.COMPLETED,
                    ServiceJob.Status.CANCELLED,
                },
                ServiceJob.Status.COMPLETED: set(),
                ServiceJob.Status.CANCELLED: set(),
            }
            if status not in transitions[instance.status]:
                raise serializers.ValidationError(
                    {
                        "status": (
                            f"Cannot change a {instance.get_status_display().lower()} "
                            f"job to {ServiceJob.Status(status).label.lower()}."
                        )
                    }
                )
            if (
                status == ServiceJob.Status.COMPLETED
                and not attrs.get(
                    "completion_report", instance.completion_report
                ).strip()
            ):
                raise serializers.ValidationError(
                    {
                        "completion_report": (
                            "Add a completion report before completing the job."
                        )
                    }
                )
            if (
                self.context["view"].organization_membership.role
                == Membership.Role.TECHNICIAN
            ):
                technician_transitions = {
                    ServiceJob.Status.SCHEDULED: ServiceJob.Status.IN_PROGRESS,
                    ServiceJob.Status.IN_PROGRESS: ServiceJob.Status.COMPLETED,
                }
                if technician_transitions.get(instance.status) != status:
                    raise serializers.ValidationError(
                        {
                            "status": (
                                "Technicians can only start scheduled jobs or "
                                "complete in-progress jobs."
                            )
                        }
                    )

        if status in {ServiceJob.Status.SCHEDULED, ServiceJob.Status.IN_PROGRESS}:
            if scheduled_for is None:
                raise serializers.ValidationError(
                    {"scheduled_for": "Set a scheduled date and time for this status."}
                )
            if technician is None:
                raise serializers.ValidationError(
                    {"assigned_technician": "Assign a technician for this status."}
                )

        if (
            instance is not None
            and instance.status in {ServiceJob.Status.COMPLETED, ServiceJob.Status.CANCELLED}
            and "completion_report" in attrs
            and attrs["completion_report"] != instance.completion_report
        ):
            raise serializers.ValidationError(
                {"completion_report": "The report is locked after the job closes."}
            )
        if instance is None and status == ServiceJob.Status.COMPLETED:
            raise serializers.ValidationError(
                {"status": "Create and schedule the job before completing it."}
            )
        return attrs


class ServiceContractSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    covered_equipment_names = serializers.SerializerMethodField()
    visits_consumed = serializers.SerializerMethodField()
    visits_remaining = serializers.SerializerMethodField()
    visit_history = serializers.SerializerMethodField()
    days_until_expiry = serializers.SerializerMethodField()
    renewed_from_number = serializers.CharField(
        source="renewed_from.contract_number", read_only=True, allow_null=True
    )
    renewal_contract_number = serializers.CharField(
        source="renewal.contract_number", read_only=True, allow_null=True
    )

    class Meta:
        model = ServiceContract
        fields = [
            "id",
            "contract_number",
            "customer",
            "customer_name",
            "covered_equipment",
            "covered_equipment_names",
            "contract_type",
            "start_date",
            "end_date",
            "contract_value",
            "currency",
            "included_visits",
            "visits_consumed",
            "visits_remaining",
            "visit_history",
            "days_until_expiry",
            "visit_frequency",
            "payment_terms",
            "terms_and_conditions",
            "renewal_reminders_enabled",
            "reminder_days",
            "status",
            "renewed_from",
            "renewed_from_number",
            "renewal_contract_number",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "contract_number",
            "currency",
            "visits_consumed",
            "visits_remaining",
            "visit_history",
            "days_until_expiry",
            "renewed_from",
            "renewed_from_number",
            "renewal_contract_number",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        view = self.context.get("view")
        if view is not None:
            organization = view.get_organization()
            self.fields["customer"].queryset = Customer.objects.filter(
                organization=organization
            )
            self.fields["covered_equipment"].queryset = Equipment.objects.filter(
                organization=organization
            )

    def get_covered_equipment_names(self, contract):
        return [equipment.name for equipment in contract.covered_equipment.all()]

    def get_visits_consumed(self, contract):
        consumed = getattr(contract, "_visits_consumed", None)
        return consumed if consumed is not None else contract.visits.count()

    def get_visits_remaining(self, contract):
        return max(
            0,
            contract.included_visits - self.get_visits_consumed(contract),
        )

    def get_visit_history(self, contract):
        visits = contract.visits.select_related("job", "recorded_by")
        return ContractVisitSerializer(visits, many=True).data

    def get_days_until_expiry(self, contract):
        from django.utils import timezone

        return (contract.end_date - timezone.localdate()).days

    def validate_reminder_days(self, value):
        if not isinstance(value, list) or any(
            isinstance(day, bool) or not isinstance(day, int) for day in value
        ):
            raise serializers.ValidationError(
                "Reminder days must be a list of whole numbers."
            )
        if len(value) > 10 or any(day < 1 or day > 365 for day in value):
            raise serializers.ValidationError(
                "Choose up to 10 reminder intervals between 1 and 365 days."
            )
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Reminder intervals must be unique.")
        return sorted(value, reverse=True)

    def validate_contract_number(self, value):
        organization = self.context["view"].get_organization()
        queryset = ServiceContract.objects.filter(
            organization=organization, contract_number=value.strip()
        )
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "This contract number is already used in this organization."
            )
        return value.strip()

    def validate(self, attrs):
        customer = attrs.get(
            "customer", self.instance.customer if self.instance else None
        )
        equipment = attrs.get("covered_equipment")
        if equipment is None and self.instance:
            equipment = list(self.instance.covered_equipment.all())
        if customer and equipment and any(
            item.customer_id != customer.id for item in equipment
        ):
            raise serializers.ValidationError(
                {
                    "covered_equipment": (
                        "Covered equipment must belong to the contract customer."
                    )
                }
            )
        start_date = attrs.get(
            "start_date", self.instance.start_date if self.instance else None
        )
        end_date = attrs.get("end_date", self.instance.end_date if self.instance else None)
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "Contract end date cannot precede its start date."}
            )
        if self.instance and self.instance.status != ServiceContract.Status.DRAFT:
            immutable = {"customer", "start_date", "end_date", "contract_number"}
            changed = {
                key for key in immutable
                if key in attrs
                and getattr(self.instance, key) != attrs[key]
            }
            if changed:
                raise serializers.ValidationError(
                    "Active and historical contracts cannot change customer or dates."
                )
        next_status = attrs.get(
            "status", self.instance.status if self.instance else ServiceContract.Status.DRAFT
        )
        if self.instance and next_status != self.instance.status:
            allowed = {
                ServiceContract.Status.DRAFT: {
                    ServiceContract.Status.ACTIVE,
                    ServiceContract.Status.CANCELLED,
                },
                ServiceContract.Status.ACTIVE: {
                    ServiceContract.Status.EXPIRED,
                    ServiceContract.Status.CANCELLED,
                },
                ServiceContract.Status.EXPIRED: set(),
                ServiceContract.Status.CANCELLED: set(),
            }
            if next_status not in allowed[self.instance.status]:
                raise serializers.ValidationError(
                    {"status": "This contract status transition is not allowed."}
                )
        return attrs

    def create(self, validated_data):
        equipment = validated_data.pop("covered_equipment", [])
        contract = super().create(validated_data)
        contract.covered_equipment.set(equipment)
        return contract

    def update(self, instance, validated_data):
        equipment = validated_data.pop("covered_equipment", None)
        contract = super().update(instance, validated_data)
        if equipment is not None:
            contract.covered_equipment.set(equipment)
        return contract


class ContractRenewalReminderAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContractRenewalReminderAttempt
        fields = [
            "attempt_number",
            "recipient",
            "status",
            "detail",
            "attempted_at",
        ]
        read_only_fields = fields


class ContractRenewalReminderSerializer(serializers.ModelSerializer):
    contract_number = serializers.CharField(
        source="contract.contract_number", read_only=True
    )
    customer_name = serializers.CharField(
        source="contract.customer.name", read_only=True
    )
    customer_email = serializers.EmailField(
        source="contract.customer.email", read_only=True, allow_blank=True
    )
    attempt_history = ContractRenewalReminderAttemptSerializer(many=True, read_only=True)

    class Meta:
        model = ContractRenewalReminder
        fields = [
            "id",
            "contract_number",
            "customer_name",
            "customer_email",
            "contract_end_date",
            "days_before_expiry",
            "status",
            "attempts",
            "sent_at",
            "updated_at",
            "attempt_history",
        ]
        read_only_fields = fields
