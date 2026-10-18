from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def default_contract_reminder_days():
    return [30, 7, 1]


class PasswordResetOTP(models.Model):
    class Purpose(models.TextChoices):
        ACCOUNT_RECOVERY = "account_recovery", "Account recovery"
        NEW_EMAIL = "new_email", "New email verification"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_otps",
    )
    purpose = models.CharField(max_length=24, choices=Purpose.choices)
    email = models.EmailField(max_length=150)
    code_hash = models.CharField(max_length=128)
    recovery_challenge = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="email_change_otps",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    verified_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["user", "purpose", "created_at"],
                name="password_reset_otp_user_idx",
            )
        ]


class Organization(models.Model):
    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_organizations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Administrator"
        MANAGER = "manager", "Manager"
        TECHNICIAN = "technician", "Technician"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="unique_org_membership"
            )
        ]
        ordering = ["organization__name", "id"]

    def __str__(self):
        return f"{self.user} — {self.organization} ({self.role})"


class Customer(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="customers"
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["organization", "name"], name="customer_org_name_idx")
        ]

    def __str__(self):
        return self.name


class Equipment(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="equipment"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="equipment"
    )
    name = models.CharField(max_length=200)
    manufacturer = models.CharField(max_length=120, blank=True)
    model_number = models.CharField(max_length=120, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    installed_at = models.DateField(null=True, blank=True)
    warranty_expires_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["organization", "name"], name="equipment_org_name_idx")
        ]

    def __str__(self):
        return f"{self.name} — {self.customer.name}"


class ServiceJob(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="service_jobs"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="service_jobs"
    )
    equipment = models.ForeignKey(
        Equipment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_jobs",
    )
    service_contract = models.ForeignKey(
        "ServiceContract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_jobs",
    )
    assigned_technician = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_service_jobs",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_service_jobs",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NEW
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    technician_note = models.TextField(blank=True)
    completion_report = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["organization", "status"], name="servicejob_org_status_idx"
            ),
            models.Index(
                fields=["organization", "scheduled_for"],
                name="servicejob_org_schedule_idx",
            ),
        ]

    def __str__(self):
        return f"{self.title} — {self.customer.name}"


class ServiceJobWorkNote(models.Model):
    job = models.ForeignKey(
        ServiceJob, on_delete=models.CASCADE, related_name="work_notes"
    )
    note = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="service_job_work_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ServiceJobStatusHistory(models.Model):
    job = models.ForeignKey(
        ServiceJob, on_delete=models.CASCADE, related_name="status_history"
    )
    previous_status = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=ServiceJob.Status.choices)
    note = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="service_job_status_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["changed_at", "id"]

    def __str__(self):
        return f"{self.job_id}: {self.previous_status} → {self.status}"


class ServiceContract(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    class ContractType(models.TextChoices):
        COMPREHENSIVE = "comprehensive", "Comprehensive"
        NON_COMPREHENSIVE = "non_comprehensive", "Non-comprehensive"
        LABOUR_ONLY = "labour_only", "Labour only"
        CUSTOM = "custom", "Custom"

    class VisitFrequency(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        HALF_YEARLY = "half_yearly", "Half-yearly"
        ANNUAL = "annual", "Annual"
        CUSTOM = "custom", "Custom"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="service_contracts"
    )
    contract_number = models.CharField(max_length=40)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="service_contracts"
    )
    covered_equipment = models.ManyToManyField(
        Equipment, blank=True, related_name="service_contracts"
    )
    contract_type = models.CharField(
        max_length=24,
        choices=ContractType.choices,
        default=ContractType.COMPREHENSIVE,
    )
    start_date = models.DateField()
    end_date = models.DateField(db_index=True)
    contract_value = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    included_visits = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(999)]
    )
    visit_frequency = models.CharField(
        max_length=20,
        choices=VisitFrequency.choices,
        default=VisitFrequency.ANNUAL,
    )
    payment_terms = models.CharField(max_length=500, blank=True)
    terms_and_conditions = models.TextField(blank=True)
    renewal_reminders_enabled = models.BooleanField(default=True)
    reminder_days = models.JSONField(default=default_contract_reminder_days)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    renewed_from = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="renewal",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_service_contracts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["end_date", "contract_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "contract_number"],
                name="unique_org_contract_number",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="contract_end_after_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "end_date"],
                name="contract_org_status_end_idx",
            )
        ]

    def __str__(self):
        return f"{self.contract_number} — {self.customer.name}"


class ContractVisit(models.Model):
    contract = models.ForeignKey(
        ServiceContract, on_delete=models.PROTECT, related_name="visits"
    )
    job = models.OneToOneField(
        ServiceJob, on_delete=models.PROTECT, related_name="contract_visit"
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_contract_visits",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at", "id"]

    def __str__(self):
        return f"{self.contract.contract_number} visit for job {self.job_id}"


class ContractRenewalReminder(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    contract = models.ForeignKey(
        ServiceContract, on_delete=models.CASCADE, related_name="renewal_reminders"
    )
    contract_end_date = models.DateField()
    days_before_expiry = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(365)]
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sent_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "contract_end_date", "days_before_expiry"],
                name="unique_contract_expiry_reminder",
            )
        ]

    def __str__(self):
        return (
            f"{self.contract.contract_number}: "
            f"{self.days_before_expiry}-day renewal reminder"
        )


class ContractRenewalReminderAttempt(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    reminder = models.ForeignKey(
        ContractRenewalReminder,
        on_delete=models.CASCADE,
        related_name="attempt_history",
    )
    attempt_number = models.PositiveSmallIntegerField()
    recipient = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    detail = models.CharField(max_length=300, blank=True)
    attempted_at = models.DateTimeField()

    class Meta:
        ordering = ["attempt_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["reminder", "attempt_number"],
                name="unique_contract_reminder_attempt",
            )
        ]

    def __str__(self):
        return f"{self.reminder_id} attempt {self.attempt_number}: {self.status}"


class Invoice(models.Model):
    class TaxMode(models.TextChoices):
        INTRA_STATE = "cgst_sgst", "CGST + SGST"
        INTER_STATE = "igst", "IGST"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        REVERSED = "reversed", "Reversed"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invoices"
    )
    invoice_number = models.CharField(max_length=40)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="invoices"
    )
    tax_mode = models.CharField(max_length=12, choices=TaxMode.choices)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invoices",
    )
    journal_entry = models.OneToOneField(
        "JournalEntry",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoice",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "invoice_number"],
                name="unique_org_invoice_number",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(due_date__isnull=True)
                    | models.Q(issue_date__isnull=True)
                    | models.Q(due_date__gte=models.F("issue_date"))
                ),
                name="invoice_due_after_issue",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "due_date"],
                name="invoice_org_status_due_idx",
            )
        ]

    def __str__(self):
        return self.invoice_number


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="lines"
    )
    description = models.CharField(max_length=300)
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    gst_rate = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2)
    cgst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="invoice_line_quantity_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="invoice_line_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(gst_rate__gte=0) & models.Q(gst_rate__lte=100),
                name="invoice_line_gst_rate_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(taxable_amount__gte=0)
                & models.Q(tax_amount__gte=0)
                & models.Q(cgst_amount__gte=0)
                & models.Q(sgst_amount__gte=0)
                & models.Q(igst_amount__gte=0),
                name="invoice_line_amounts_nonnegative",
            ),
        ]


class FinancialAuditEvent(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="financial_audit_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="financial_audit_events",
    )
    action = models.CharField(max_length=32)
    entity_type = models.CharField(max_length=24)
    entity_id = models.PositiveBigIntegerField()
    reference = models.CharField(max_length=80)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["organization", "-created_at"],
                name="finance_audit_org_date_idx",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Financial audit events are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Financial audit events cannot be deleted.")

    def __str__(self):
        return f"{self.action}: {self.reference}"


class Quotation(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        CONVERTED = "converted", "Converted"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="quotations"
    )
    quotation_number = models.CharField(max_length=40)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="quotations"
    )
    tax_mode = models.CharField(max_length=12, choices=Invoice.TaxMode.choices)
    valid_until = models.DateField()
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)
    converted_invoice = models.OneToOneField(
        Invoice,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_quotation",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_quotations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "quotation_number"],
                name="unique_org_quotation_number",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "valid_until"],
                name="quotation_org_status_valid_idx",
            )
        ]

    def __str__(self):
        return self.quotation_number


class QuotationLine(models.Model):
    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="lines"
    )
    description = models.CharField(max_length=300)
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2)
    cgst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="quotation_line_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="quotation_line_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(gst_rate__gte=0) & models.Q(gst_rate__lte=100),
                name="quotation_line_gst_rate_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(taxable_amount__gte=0)
                    & models.Q(tax_amount__gte=0)
                    & models.Q(cgst_amount__gte=0)
                    & models.Q(sgst_amount__gte=0)
                    & models.Q(igst_amount__gte=0)
                ),
                name="quotation_line_amounts_nonnegative",
            ),
        ]


class JournalEntry(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="journal_entries"
    )
    reference = models.CharField(max_length=100)
    description = models.CharField(max_length=500)
    entry_date = models.DateField()
    posted = models.BooleanField(default=False)
    posted_at = models.DateTimeField(null=True, blank=True)
    reverses = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversal",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["entry_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"],
                name="unique_org_journal_reference",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            prior = type(self).objects.filter(pk=self.pk, posted=True).exists()
            if prior:
                raise ValidationError("Posted journal entries are immutable.")
        if self.posted:
            totals = self.lines.aggregate(
                debit=models.Sum("debit"),
                credit=models.Sum("credit"),
                line_count=models.Count("id"),
            )
            debit = totals["debit"] or Decimal("0.00")
            credit = totals["credit"] or Decimal("0.00")
            if totals["line_count"] < 2 or debit <= 0 or debit != credit:
                raise ValidationError(
                    "A journal entry must have at least two lines and balance before posting."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.posted:
            raise ValidationError("Posted journal entries cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.reference


class JournalLine(models.Model):
    class Account(models.TextChoices):
        CASH = "cash", "Cash"
        BANK = "bank", "Bank"
        UPI_CLEARING = "upi_clearing", "UPI clearing"
        ACCOUNTS_RECEIVABLE = "accounts_receivable", "Accounts receivable"
        CUSTOMER_ADVANCES = "customer_advances", "Customer advances"
        SALES_REVENUE = "sales_revenue", "Sales revenue"
        CGST_PAYABLE = "cgst_payable", "CGST payable"
        SGST_PAYABLE = "sgst_payable", "SGST payable"
        IGST_PAYABLE = "igst_payable", "IGST payable"
        OPERATING_EXPENSE = "operating_expense", "Operating expense"

    journal_entry = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="lines"
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_lines",
    )
    account = models.CharField(max_length=32, choices=Account.choices)
    debit = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    credit = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(debit__gt=0) & models.Q(credit=0))
                    | (models.Q(credit__gt=0) & models.Q(debit=0))
                ),
                name="journal_line_one_positive_side",
            )
        ]

    def save(self, *args, **kwargs):
        if self.journal_entry_id and self.journal_entry.posted:
            raise ValidationError("Lines in posted journals are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.journal_entry.posted:
            raise ValidationError("Lines in posted journals are immutable.")
        return super().delete(*args, **kwargs)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        UPI = "upi", "UPI"
        BANK = "bank", "Bank transfer"

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        REVERSED = "reversed", "Reversed"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="payments"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    method = models.CharField(max_length=8, choices=Method.choices)
    received_on = models.DateField()
    reference = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.RECEIVED
    )
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, related_name="payment"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_payments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_on", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_org_payment_idempotency",
            )
        ]


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="allocations"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="allocations"
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    idempotency_key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, related_name="allocation"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "idempotency_key"],
                name="unique_payment_allocation_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="payment_allocation_amount_positive",
            ),
        ]


class CashBankTransfer(models.Model):
    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="cash_bank_transfers"
    )
    transfer_number = models.CharField(max_length=40)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    transferred_on = models.DateField()
    reference = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.POSTED
    )
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, related_name="cash_bank_transfer"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_cash_bank_transfers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-transferred_on", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "transfer_number"],
                name="unique_org_transfer_number",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_org_transfer_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="cash_bank_transfer_amount_positive",
            ),
        ]


class Expense(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK = "bank", "Bank transfer"
        UPI = "upi", "UPI"

    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="expenses"
    )
    expense_number = models.CharField(max_length=40)
    description = models.CharField(max_length=300)
    category = models.CharField(max_length=100)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    method = models.CharField(max_length=8, choices=Method.choices)
    incurred_on = models.DateField()
    idempotency_key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.POSTED
    )
    journal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, related_name="expense"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_expenses",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-incurred_on", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "expense_number"],
                name="unique_org_expense_number",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_org_expense_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="expense_amount_positive"
            ),
        ]


class SubscriptionPlan(models.Model):
    class BillingPeriod(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    billing_period = models.CharField(max_length=10, choices=BillingPeriod.choices)
    period_days = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1)]
    )
    max_members = models.PositiveIntegerField(null=True, blank=True)
    max_customers = models.PositiveIntegerField(null=True, blank=True)
    max_equipment = models.PositiveIntegerField(null=True, blank=True)
    max_jobs = models.PositiveIntegerField(null=True, blank=True)
    features = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["price", "name", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(period_days__gt=0),
                name="subscription_plan_period_positive",
            )
        ]

    def clean(self):
        super().clean()
        if not isinstance(self.features, list) or any(
            not isinstance(feature, str) or not feature.strip()
            for feature in self.features
        ):
            raise ValidationError(
                {"features": "Features must be a list of non-empty text values."}
            )

    def __str__(self):
        return self.name


class OrganizationSubscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        SUSPENDED = "suspended", "Suspended"

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    manual_pilot = models.BooleanField(default=False)
    activated_at = models.DateTimeField()
    cancelled_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="manually_activated_subscriptions",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.organization}: {self.plan} ({self.status})"


class SubscriptionChangeRequest(models.Model):
    class RequestType(models.TextChoices):
        ACTIVATE = "activate", "Activate"
        CHANGE_PLAN = "change_plan", "Change plan"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="subscription_requests"
    )
    requested_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name="change_requests"
    )
    request_type = models.CharField(max_length=12, choices=RequestType.choices)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subscription_change_requests",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decided_subscription_requests",
    )
    manual_pilot = models.BooleanField(default=False)
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(status="pending"),
                name="one_pending_subscription_request",
            )
        ]

    def __str__(self):
        return f"{self.organization}: {self.request_type} {self.requested_plan}"


class SubscriptionInvoice(models.Model):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        PAID = "paid", "Paid"
        VOID = "void", "Void"

    subscription = models.ForeignKey(
        OrganizationSubscription, on_delete=models.PROTECT, related_name="invoices"
    )
    plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name="invoices"
    )
    invoice_number = models.CharField(max_length=40, unique=True)
    plan_name = models.CharField(max_length=100, blank=True)
    period_start = models.DateField()
    period_end = models.DateField()
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ISSUED
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    due_on = models.DateField()
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(max_length=120, blank=True)
    marked_paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manually_settled_subscription_invoices",
    )

    class Meta:
        ordering = ["-issued_at", "-id"]

    def __str__(self):
        return self.invoice_number
