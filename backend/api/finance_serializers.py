from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from api.finance import (
    MAX_JOURNAL_AMOUNT,
    invoice_totals,
    line_totals,
    log_financial_event,
    money,
)
from api.models import (
    CashBankTransfer,
    Customer,
    Expense,
    FinancialAuditEvent,
    Invoice,
    InvoiceLine,
    JournalEntry,
    JournalLine,
    Payment,
    PaymentAllocation,
    Quotation,
    QuotationLine,
)


class InvoiceLineInputSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=300)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0.001")
    )
    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0")
    )
    gst_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100")
    )

    def validate(self, attrs):
        taxable = money(attrs["quantity"] * attrs["unit_price"])
        tax = money(taxable * attrs["gst_rate"] / Decimal("100"))
        if taxable > MAX_JOURNAL_AMOUNT or tax > MAX_JOURNAL_AMOUNT:
            raise serializers.ValidationError(
                "The line amount exceeds the maximum supported by the ledger."
            )
        return attrs


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "description",
            "quantity",
            "unit_price",
            "gst_rate",
            "taxable_amount",
            "tax_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
        ]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    lines = InvoiceLineInputSerializer(many=True, required=False)
    subtotal = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    allocated_total = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()
    journal_reference = serializers.CharField(
        source="journal_entry.reference", read_only=True, allow_null=True
    )

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "customer",
            "customer_name",
            "tax_mode",
            "status",
            "issue_date",
            "due_date",
            "notes",
            "lines",
            "subtotal",
            "tax_total",
            "total",
            "allocated_total",
            "outstanding",
            "journal_reference",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "invoice_number",
            "status",
            "issue_date",
            "subtotal",
            "tax_total",
            "total",
            "allocated_total",
            "outstanding",
            "journal_reference",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        view = self.context.get("view")
        if view is not None:
            self.fields["customer"].queryset = Customer.objects.filter(
                organization=view.get_organization()
            )

    def validate(self, attrs):
        if self.instance and self.instance.status != Invoice.Status.DRAFT:
            raise serializers.ValidationError(
                "Issued or reversed invoices cannot be edited."
            )
        if self.instance is None and not attrs.get("lines"):
            raise serializers.ValidationError(
                {"lines": "Add at least one invoice line."}
            )
        if "lines" in attrs and not attrs["lines"]:
            raise serializers.ValidationError(
                {"lines": "An invoice must contain at least one line."}
            )
        if "lines" in attrs:
            total = sum(
                (
                    money(item["quantity"] * item["unit_price"])
                    + money(
                        money(item["quantity"] * item["unit_price"])
                        * item["gst_rate"]
                        / Decimal("100")
                    )
                    for item in attrs["lines"]
                ),
                Decimal("0.00"),
            )
        elif self.instance:
            total = invoice_totals(self.instance)["total"]
        else:
            total = Decimal("0.00")
        if total > MAX_JOURNAL_AMOUNT:
            raise serializers.ValidationError(
                {"lines": "The invoice total exceeds the maximum supported by the ledger."}
            )
        due_date = attrs.get("due_date", self.instance.due_date if self.instance else None)
        issue_date = attrs.get(
            "issue_date", self.instance.issue_date if self.instance else None
        )
        if due_date and issue_date and due_date < issue_date:
            raise serializers.ValidationError(
                {"due_date": "The due date cannot precede the issue date."}
            )
        return attrs

    def _create_lines(self, invoice, lines):
        for item in lines:
            taxable = money(item["quantity"] * item["unit_price"])
            tax = money(taxable * item["gst_rate"] / Decimal("100"))
            cgst = sgst = igst = Decimal("0.00")
            if invoice.tax_mode == Invoice.TaxMode.INTRA_STATE:
                cgst = money(tax / 2)
                sgst = tax - cgst
            else:
                igst = tax
            InvoiceLine.objects.create(
                invoice=invoice,
                **item,
                taxable_amount=taxable,
                tax_amount=tax,
                cgst_amount=cgst,
                sgst_amount=sgst,
                igst_amount=igst,
            )

    @transaction.atomic
    def create(self, validated_data):
        from api.models import Organization

        lines = validated_data.pop("lines")
        view = self.context["view"]
        organization = view.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        sequence = Invoice.objects.filter(organization=organization).count() + 1
        invoice = Invoice.objects.create(
            organization=organization,
            invoice_number=f"INV-{organization.pk:04d}-{sequence:06d}",
            created_by=view.request.user,
            **validated_data,
        )
        self._create_lines(invoice, lines)
        log_financial_event(
            organization=organization,
            actor=view.request.user,
            action="created",
            entity_type="invoice",
            entity_id=invoice.pk,
            reference=invoice.invoice_number,
            details={"total": str(invoice_totals(invoice)["total"])},
        )
        return invoice

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)
        if (
            lines is None
            and validated_data.get("tax_mode", instance.tax_mode) != instance.tax_mode
        ):
            lines = list(instance.lines.values(
                "description", "quantity", "unit_price", "gst_rate"
            ))
        instance = super().update(instance, validated_data)
        if lines is not None:
            instance.lines.all().delete()
            self._create_lines(instance, lines)
        log_financial_event(
            organization=instance.organization,
            actor=self.context["request"].user,
            action="updated",
            entity_type="invoice",
            entity_id=instance.pk,
            reference=instance.invoice_number,
            details={
                "updated_fields": sorted(
                    set(validated_data) | ({"lines"} if lines is not None else set())
                )
            },
        )
        return instance

    def get_subtotal(self, invoice):
        return str(invoice_totals(invoice)["subtotal"])

    def get_tax_total(self, invoice):
        return str(invoice_totals(invoice)["tax"])

    def get_total(self, invoice):
        return str(invoice_totals(invoice)["total"])

    def get_allocated_total(self, invoice):
        amount = invoice.allocations.filter(
            payment__status=Payment.Status.RECEIVED, reversed_at__isnull=True
        ).aggregate(total=Sum("amount"))["total"]
        return str(money(amount if amount is not None else Decimal("0.00")))

    def get_outstanding(self, invoice):
        if invoice.status != Invoice.Status.ISSUED:
            return "0.00"
        return str(
            money(
                invoice_totals(invoice)["total"]
                - Decimal(self.get_allocated_total(invoice))
            )
        )

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["lines"] = InvoiceLineSerializer(
            instance.lines.all(), many=True
        ).data
        return representation


class QuotationLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationLine
        fields = [
            "id",
            "description",
            "quantity",
            "unit_price",
            "gst_rate",
            "taxable_amount",
            "tax_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
        ]
        read_only_fields = fields


class QuotationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    lines = InvoiceLineInputSerializer(many=True, required=False)
    subtotal = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    converted_invoice_number = serializers.CharField(
        source="converted_invoice.invoice_number", read_only=True, allow_null=True
    )

    class Meta:
        model = Quotation
        fields = [
            "id",
            "quotation_number",
            "customer",
            "customer_name",
            "tax_mode",
            "valid_until",
            "notes",
            "status",
            "sent_at",
            "accepted_at",
            "declined_at",
            "converted_invoice",
            "converted_invoice_number",
            "lines",
            "subtotal",
            "tax_total",
            "total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "quotation_number",
            "status",
            "sent_at",
            "accepted_at",
            "declined_at",
            "converted_invoice",
            "converted_invoice_number",
            "subtotal",
            "tax_total",
            "total",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        view = self.context.get("view")
        if view is not None:
            self.fields["customer"].queryset = Customer.objects.filter(
                organization=view.get_organization()
            )

    def validate(self, attrs):
        if self.instance and self.instance.status != Quotation.Status.DRAFT:
            raise serializers.ValidationError(
                "Only draft quotations can be edited."
            )
        if self.instance is None and not attrs.get("lines"):
            raise serializers.ValidationError(
                {"lines": "Add at least one quotation line."}
            )
        if "lines" in attrs and not attrs["lines"]:
            raise serializers.ValidationError(
                {"lines": "A quotation must contain at least one line."}
            )
        if "lines" in attrs:
            lines = attrs["lines"]
        elif self.instance:
            lines = list(self.instance.lines.values(
                "quantity", "unit_price", "gst_rate"
            ))
        else:
            lines = []
        total = sum(
            (
                money(item["quantity"] * item["unit_price"])
                + money(
                    money(item["quantity"] * item["unit_price"])
                    * item["gst_rate"]
                    / Decimal("100")
                )
                for item in lines
            ),
            Decimal("0.00"),
        )
        if total > MAX_JOURNAL_AMOUNT:
            raise serializers.ValidationError(
                {"lines": "The quotation total exceeds the supported document limit."}
            )
        return attrs

    def _create_lines(self, quotation, lines):
        for item in lines:
            taxable = money(item["quantity"] * item["unit_price"])
            tax = money(taxable * item["gst_rate"] / Decimal("100"))
            cgst = sgst = igst = Decimal("0.00")
            if quotation.tax_mode == Invoice.TaxMode.INTRA_STATE:
                cgst = money(tax / 2)
                sgst = tax - cgst
            else:
                igst = tax
            QuotationLine.objects.create(
                quotation=quotation,
                **item,
                taxable_amount=taxable,
                tax_amount=tax,
                cgst_amount=cgst,
                sgst_amount=sgst,
                igst_amount=igst,
            )

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        view = self.context["view"]
        organization = view.get_organization()
        from api.models import Organization

        Organization.objects.select_for_update().get(pk=organization.pk)
        sequence = Quotation.objects.filter(organization=organization).count() + 1
        quotation = Quotation.objects.create(
            organization=organization,
            quotation_number=f"QUO-{organization.pk:04d}-{sequence:06d}",
            created_by=view.request.user,
            **validated_data,
        )
        self._create_lines(quotation, lines)
        log_financial_event(
            organization=organization,
            actor=view.request.user,
            action="created",
            entity_type="quotation",
            entity_id=quotation.pk,
            reference=quotation.quotation_number,
            details={"total": str(line_totals(quotation.lines)["total"])},
        )
        return quotation

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)
        instance = super().update(instance, validated_data)
        if lines is not None:
            instance.lines.all().delete()
            self._create_lines(instance, lines)
        log_financial_event(
            organization=instance.organization,
            actor=self.context["request"].user,
            action="updated",
            entity_type="quotation",
            entity_id=instance.pk,
            reference=instance.quotation_number,
            details={
                "updated_fields": sorted(
                    set(validated_data) | ({"lines"} if lines is not None else set())
                )
            },
        )
        return instance

    def get_subtotal(self, quotation):
        return str(line_totals(quotation.lines)["subtotal"])

    def get_tax_total(self, quotation):
        return str(line_totals(quotation.lines)["tax"])

    def get_total(self, quotation):
        return str(line_totals(quotation.lines)["total"])

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["lines"] = QuotationLineSerializer(
            instance.lines.all(), many=True
        ).data
        return representation


class PaymentCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    received_on = serializers.DateField()
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        view = self.context.get("view")
        if view is not None:
            self.fields["customer"].queryset = Customer.objects.filter(
                organization=view.get_organization()
            )

    def validate_customer(self, customer):
        if customer.organization_id != self.context["view"].get_organization().id:
            raise serializers.ValidationError("Select a customer in this organization.")
        return customer


class PaymentAllocationCreateSerializer(serializers.Serializer):
    invoice = serializers.PrimaryKeyRelatedField(queryset=Invoice.objects.all())
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    idempotency_key = serializers.CharField(max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        organization = self.context.get("organization")
        if organization is not None:
            self.fields["invoice"].queryset = Invoice.objects.filter(
                organization=organization
            )


class PaymentAllocationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = PaymentAllocation
        fields = [
            "id",
            "invoice",
            "invoice_number",
            "amount",
            "idempotency_key",
            "created_at",
            "reversed_at",
        ]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    allocations = PaymentAllocationSerializer(many=True, read_only=True)
    unallocated_amount = serializers.SerializerMethodField()
    journal_reference = serializers.CharField(
        source="journal_entry.reference", read_only=True
    )

    class Meta:
        model = Payment
        fields = [
            "id",
            "customer",
            "customer_name",
            "amount",
            "method",
            "received_on",
            "reference",
            "idempotency_key",
            "status",
            "allocations",
            "unallocated_amount",
            "journal_reference",
            "created_at",
            "reversed_at",
        ]
        read_only_fields = fields

    def get_unallocated_amount(self, payment):
        if payment.status != Payment.Status.RECEIVED:
            return "0.00"
        allocated = payment.allocations.filter(reversed_at__isnull=True).aggregate(
            total=Sum("amount")
        )["total"]
        allocated = allocated if allocated is not None else Decimal("0.00")
        return str(money(Decimal(payment.amount) - Decimal(allocated)))


class ExpenseCreateSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=300)
    category = serializers.CharField(max_length=100)
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    method = serializers.ChoiceField(choices=Expense.Method.choices)
    incurred_on = serializers.DateField()
    idempotency_key = serializers.CharField(max_length=100)


class ExpenseSerializer(serializers.ModelSerializer):
    journal_reference = serializers.CharField(
        source="journal_entry.reference", read_only=True
    )

    class Meta:
        model = Expense
        fields = [
            "id",
            "expense_number",
            "description",
            "category",
            "amount",
            "method",
            "incurred_on",
            "idempotency_key",
            "status",
            "journal_reference",
            "created_at",
            "reversed_at",
        ]
        read_only_fields = fields


class CashBankTransferCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    transferred_on = serializers.DateField()
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=100)


class CashBankTransferSerializer(serializers.ModelSerializer):
    journal_reference = serializers.CharField(
        source="journal_entry.reference", read_only=True
    )

    class Meta:
        model = CashBankTransfer
        fields = [
            "id",
            "transfer_number",
            "amount",
            "transferred_on",
            "reference",
            "idempotency_key",
            "status",
            "journal_reference",
            "created_at",
            "reversed_at",
        ]
        read_only_fields = fields


class JournalLineSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="get_account_display", read_only=True)
    customer_name = serializers.CharField(
        source="customer.name", read_only=True, allow_null=True
    )

    class Meta:
        model = JournalLine
        fields = [
            "id",
            "account",
            "account_name",
            "customer",
            "customer_name",
            "debit",
            "credit",
        ]
        read_only_fields = fields


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)
    debit_total = serializers.SerializerMethodField()
    credit_total = serializers.SerializerMethodField()

    class Meta:
        model = JournalEntry
        fields = [
            "id",
            "reference",
            "description",
            "entry_date",
            "posted",
            "posted_at",
            "reverses",
            "lines",
            "debit_total",
            "credit_total",
        ]
        read_only_fields = fields

    def get_debit_total(self, entry):
        return str(money(sum((line.debit for line in entry.lines.all()), Decimal("0"))))

    def get_credit_total(self, entry):
        return str(money(sum((line.credit for line in entry.lines.all()), Decimal("0"))))


class FinancialAuditEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.get_full_name", read_only=True)
    actor_email = serializers.EmailField(source="actor.email", read_only=True)

    class Meta:
        model = FinancialAuditEvent
        fields = [
            "id",
            "action",
            "entity_type",
            "entity_id",
            "reference",
            "actor_name",
            "actor_email",
            "details",
            "created_at",
        ]
        read_only_fields = fields
