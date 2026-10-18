from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from api.finance import (
    invoice_totals,
    line_totals,
    log_financial_event,
    money,
    payment_account,
    post_journal,
    request_fingerprint,
    reverse_journal,
)
from api.finance_documents import invoice_pdf, quotation_pdf
from api.finance_serializers import (
    CashBankTransferCreateSerializer,
    CashBankTransferSerializer,
    ExpenseCreateSerializer,
    ExpenseSerializer,
    FinancialAuditEventSerializer,
    InvoiceSerializer,
    JournalEntrySerializer,
    PaymentAllocationCreateSerializer,
    PaymentAllocationSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    QuotationSerializer,
)
from api.models import (
    CashBankTransfer,
    Customer,
    Expense,
    FinancialAuditEvent,
    Invoice,
    JournalEntry,
    JournalLine,
    Organization,
    Payment,
    PaymentAllocation,
    Quotation,
    QuotationLine,
    InvoiceLine,
)
from api.permissions import FinancialRolePermission
from api.views import OrganizationScopedViewSet


def _allocation_sum(queryset):
    total = queryset.filter(reversed_at__isnull=True).aggregate(
        total=Sum("amount")
    )["total"]
    return total if total is not None else Decimal("0.00")


def _report_date_range(request):
    parsed = {}
    for parameter in ("date_from", "date_to"):
        raw = request.query_params.get(parameter)
        if raw:
            value = parse_date(raw)
            if value is None:
                raise ValidationError({parameter: "Enter a valid ISO date (YYYY-MM-DD)."})
            parsed[parameter] = value
    start = parsed.get("date_from")
    end = parsed.get("date_to")
    if start and end and end < start:
        raise ValidationError({"date_to": "End date must be on or after the start date."})
    return start, end


class InvoiceViewSet(OrganizationScopedViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [FinancialRolePermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = (
            Invoice.objects.filter(organization=self.get_organization())
            .select_related("customer", "journal_entry")
            .prefetch_related("lines", "allocations")
        )
        if self.request.method in {"PATCH", "PUT"}:
            queryset = queryset.select_for_update(of=("self",))
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save()

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def issue(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        invoice = Invoice.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        if invoice.status == Invoice.Status.ISSUED:
            return Response(self.get_serializer(invoice).data)
        if invoice.status != Invoice.Status.DRAFT:
            raise ValidationError({"status": "Only draft invoices can be issued."})
        if not invoice.lines.exists():
            raise ValidationError({"lines": "Add at least one line before issuing."})

        issue_date = timezone.localdate()
        due_date = invoice.due_date or issue_date
        if due_date < issue_date:
            raise ValidationError({"due_date": "The due date cannot precede issue date."})
        totals = invoice_totals(invoice)
        if totals["total"] <= 0:
            raise ValidationError({"lines": "An invoice total must be greater than zero."})

        journal_lines = [
            (
                JournalLine.Account.ACCOUNTS_RECEIVABLE,
                totals["total"],
                Decimal("0.00"),
                invoice.customer,
            ),
            (JournalLine.Account.SALES_REVENUE, Decimal("0.00"), totals["subtotal"]),
        ]
        for account, amount in (
            (JournalLine.Account.CGST_PAYABLE, totals["cgst"]),
            (JournalLine.Account.SGST_PAYABLE, totals["sgst"]),
            (JournalLine.Account.IGST_PAYABLE, totals["igst"]),
        ):
            if amount:
                journal_lines.append((account, Decimal("0.00"), amount))
        journal = post_journal(
            organization=organization,
            reference=f"INVOICE-{invoice.pk}-ISSUE",
            description=f"Issued invoice {invoice.invoice_number}",
            entry_date=issue_date,
            lines=journal_lines,
        )
        invoice.status = Invoice.Status.ISSUED
        invoice.issue_date = issue_date
        invoice.due_date = due_date
        invoice.journal_entry = journal
        invoice.save(
            update_fields=["status", "issue_date", "due_date", "journal_entry", "updated_at"]
        )
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="issued",
            entity_type="invoice",
            entity_id=invoice.pk,
            reference=invoice.invoice_number,
            details={"journal_reference": journal.reference, "total": str(totals["total"])},
        )
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reverse(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        invoice = Invoice.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        if invoice.status == Invoice.Status.REVERSED:
            return Response(self.get_serializer(invoice).data)
        if invoice.status != Invoice.Status.ISSUED or invoice.journal_entry_id is None:
            raise ValidationError({"status": "Only issued invoices can be reversed."})
        if _allocation_sum(invoice.allocations.all()) > 0:
            raise ValidationError(
                {"allocations": "Reverse invoice allocations before reversing this invoice."}
            )
        reverse_journal(invoice.journal_entry)
        invoice.status = Invoice.Status.REVERSED
        invoice.save(update_fields=["status", "updated_at"])
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="reversed",
            entity_type="invoice",
            entity_id=invoice.pk,
            reference=invoice.invoice_number,
            details={"journal_reference": invoice.journal_entry.reference},
        )
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=["get"], url_path="document")
    def document(self, request, *args, **kwargs):
        return invoice_pdf(self.get_object())


class QuotationViewSet(OrganizationScopedViewSet):
    serializer_class = QuotationSerializer
    permission_classes = [FinancialRolePermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return (
            Quotation.objects.filter(organization=self.get_organization())
            .select_related("customer", "converted_invoice")
            .prefetch_related("lines")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def send(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        quotation = Quotation.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        if quotation.status != Quotation.Status.DRAFT:
            raise ValidationError({"status": "Only draft quotations can be sent."})
        if quotation.valid_until < timezone.localdate():
            raise ValidationError({"valid_until": "An expired quotation cannot be sent."})
        if not quotation.lines.exists():
            raise ValidationError({"lines": "Add at least one line before sending."})
        if line_totals(quotation.lines)["total"] <= 0:
            raise ValidationError({"lines": "A quotation total must be greater than zero."})
        quotation.status = Quotation.Status.SENT
        quotation.sent_at = timezone.now()
        quotation.save(update_fields=["status", "sent_at", "updated_at"])
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="sent",
            entity_type="quotation",
            entity_id=quotation.pk,
            reference=quotation.quotation_number,
        )
        return Response(self.get_serializer(quotation).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def accept(self, request, *args, **kwargs):
        quotation = Quotation.objects.select_for_update().get(
            pk=self.get_object().pk, organization=self.get_organization()
        )
        if quotation.status != Quotation.Status.SENT:
            raise ValidationError(
                {"status": "Only sent quotations can be marked accepted."}
            )
        if quotation.valid_until < timezone.localdate():
            raise ValidationError({"valid_until": "This quotation has expired."})
        quotation.status = Quotation.Status.ACCEPTED
        quotation.accepted_at = timezone.now()
        quotation.save(update_fields=["status", "accepted_at", "updated_at"])
        log_financial_event(
            organization=quotation.organization,
            actor=request.user,
            action="accepted",
            entity_type="quotation",
            entity_id=quotation.pk,
            reference=quotation.quotation_number,
        )
        return Response(self.get_serializer(quotation).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def decline(self, request, *args, **kwargs):
        quotation = Quotation.objects.select_for_update().get(
            pk=self.get_object().pk, organization=self.get_organization()
        )
        if quotation.status != Quotation.Status.SENT:
            raise ValidationError(
                {"status": "Only sent quotations can be marked declined."}
            )
        quotation.status = Quotation.Status.DECLINED
        quotation.declined_at = timezone.now()
        quotation.save(update_fields=["status", "declined_at", "updated_at"])
        log_financial_event(
            organization=quotation.organization,
            actor=request.user,
            action="declined",
            entity_type="quotation",
            entity_id=quotation.pk,
            reference=quotation.quotation_number,
        )
        return Response(self.get_serializer(quotation).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def convert(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        quotation = Quotation.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        if quotation.status == Quotation.Status.CONVERTED:
            return Response(self.get_serializer(quotation).data)
        if quotation.status != Quotation.Status.ACCEPTED:
            raise ValidationError(
                {"status": "Only accepted quotations can be converted to invoices."}
            )
        sequence = Invoice.objects.filter(organization=organization).count() + 1
        invoice = Invoice.objects.create(
            organization=organization,
            invoice_number=f"INV-{organization.pk:04d}-{sequence:06d}",
            customer=quotation.customer,
            tax_mode=quotation.tax_mode,
            notes=quotation.notes,
            created_by=request.user,
        )
        InvoiceLine.objects.bulk_create([
            InvoiceLine(invoice=invoice, **line)
            for line in quotation.lines.order_by("id").values(
                "description",
                "quantity",
                "unit_price",
                "gst_rate",
                "taxable_amount",
                "tax_amount",
                "cgst_amount",
                "sgst_amount",
                "igst_amount",
            )
        ])
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="created_from_quotation",
            entity_type="invoice",
            entity_id=invoice.pk,
            reference=invoice.invoice_number,
            details={
                "quotation_reference": quotation.quotation_number,
                "total": str(invoice_totals(invoice)["total"]),
            },
        )
        quotation.status = Quotation.Status.CONVERTED
        quotation.converted_invoice = invoice
        quotation.save(update_fields=["status", "converted_invoice", "updated_at"])
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="converted",
            entity_type="quotation",
            entity_id=quotation.pk,
            reference=quotation.quotation_number,
            details={"invoice_reference": invoice.invoice_number},
        )
        return Response(self.get_serializer(quotation).data)

    @action(detail=True, methods=["get"], url_path="document")
    def document(self, request, *args, **kwargs):
        return quotation_pdf(self.get_object())


class PaymentViewSet(OrganizationScopedViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [FinancialRolePermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return (
            Payment.objects.filter(organization=self.get_organization())
            .select_related("customer", "journal_entry")
            .prefetch_related("allocations__invoice")
        )

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        serializer = PaymentCreateSerializer(data=request.data, context={"view": self})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        normalized = {
            "customer": data["customer"].pk,
            "amount": str(data["amount"]),
            "method": data["method"],
            "received_on": data["received_on"].isoformat(),
            "reference": data.get("reference", ""),
            "idempotency_key": data["idempotency_key"],
        }
        fingerprint = request_fingerprint(normalized)
        existing = Payment.objects.filter(
            organization=organization, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if existing.request_hash != fingerprint:
                return Response(
                    {"detail": "Idempotency key was already used for another request."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(self.get_serializer(existing).data)

        sequence = Payment.objects.filter(organization=organization).count() + 1
        reference = f"PAY-{organization.pk:04d}-{sequence:08d}"
        journal = post_journal(
            organization=organization,
            reference=f"{reference}-RECEIPT",
            description=f"Payment received from {data['customer'].name}",
            entry_date=data["received_on"],
            lines=[
                (payment_account(data["method"]), data["amount"], Decimal("0.00")),
                (
                    JournalLine.Account.CUSTOMER_ADVANCES,
                    Decimal("0.00"),
                    data["amount"],
                    data["customer"],
                ),
            ],
        )
        payment = Payment.objects.create(
            organization=organization,
            customer=data["customer"],
            amount=data["amount"],
            method=data["method"],
            received_on=data["received_on"],
            reference=data.get("reference", ""),
            idempotency_key=data["idempotency_key"],
            request_hash=fingerprint,
            journal_entry=journal,
            created_by=request.user,
        )
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="received",
            entity_type="payment",
            entity_id=payment.pk,
            reference=reference,
            details={
                "amount": str(data["amount"]),
                "method": data["method"],
                "customer_id": data["customer"].pk,
            },
        )
        return Response(self.get_serializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def allocations(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        payment = Payment.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        serializer = PaymentAllocationCreateSerializer(
            data=request.data, context={"organization": organization}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        invoice_ref = data["invoice"]
        normalized = {
            "invoice": invoice_ref.pk,
            "amount": str(data["amount"]),
            "idempotency_key": data["idempotency_key"],
        }
        fingerprint = request_fingerprint(normalized)
        existing = PaymentAllocation.objects.filter(
            payment=payment, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if existing.request_hash != fingerprint:
                return Response(
                    {"detail": "Idempotency key was already used for another request."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(PaymentAllocationSerializer(existing).data)
        if payment.status != Payment.Status.RECEIVED:
            raise ValidationError({"payment": "A reversed payment cannot be allocated."})

        invoice = get_object_or_404(
            Invoice.objects.select_for_update().filter(organization=organization),
            pk=invoice_ref.pk,
        )
        if invoice.customer_id != payment.customer_id:
            raise ValidationError({"invoice": "The invoice belongs to another customer."})
        if invoice.status != Invoice.Status.ISSUED:
            raise ValidationError({"invoice": "Only issued invoices can receive payments."})
        invoice_total = invoice_totals(invoice)["total"]
        invoice_allocated = _allocation_sum(invoice.allocations.all())
        payment_allocated = _allocation_sum(payment.allocations.all())
        amount = data["amount"]
        if amount > invoice_total - invoice_allocated:
            raise ValidationError({"amount": "Allocation exceeds the invoice balance."})
        if amount > payment.amount - payment_allocated:
            raise ValidationError({"amount": "Allocation exceeds the unapplied payment."})

        sequence = payment.allocations.count() + 1
        journal = post_journal(
            organization=organization,
            reference=f"PAY-{payment.pk}-ALLOC-{sequence}",
            description=f"Payment allocation to {invoice.invoice_number}",
            entry_date=timezone.localdate(),
            lines=[
                (
                    JournalLine.Account.CUSTOMER_ADVANCES,
                    amount,
                    Decimal("0.00"),
                    payment.customer,
                ),
                (
                    JournalLine.Account.ACCOUNTS_RECEIVABLE,
                    Decimal("0.00"),
                    amount,
                    payment.customer,
                ),
            ],
        )
        allocation = PaymentAllocation.objects.create(
            payment=payment,
            invoice=invoice,
            amount=amount,
            idempotency_key=data["idempotency_key"],
            request_hash=fingerprint,
            journal_entry=journal,
        )
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="allocated",
            entity_type="payment_allocation",
            entity_id=allocation.pk,
            reference=journal.reference,
            details={
                "payment_id": payment.pk,
                "invoice_id": invoice.pk,
                "amount": str(amount),
            },
        )
        return Response(
            PaymentAllocationSerializer(allocation).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path=r"allocations/(?P<allocation_pk>[^/.]+)/reverse")
    @transaction.atomic
    def reverse_allocation(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        payment = Payment.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        allocation = get_object_or_404(
            PaymentAllocation.objects.select_for_update().filter(payment=payment),
            pk=kwargs["allocation_pk"],
        )
        if allocation.reversed_at is None:
            reverse_journal(allocation.journal_entry)
            allocation.reversed_at = timezone.now()
            allocation.save(update_fields=["reversed_at"])
            log_financial_event(
                organization=organization,
                actor=request.user,
                action="allocation_reversed",
                entity_type="payment_allocation",
                entity_id=allocation.pk,
                reference=allocation.journal_entry.reference,
                details={"payment_id": payment.pk, "invoice_id": allocation.invoice_id},
            )
        return Response(PaymentAllocationSerializer(allocation).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reverse(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        payment = Payment.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        if payment.status == Payment.Status.REVERSED:
            return Response(self.get_serializer(payment).data)
        if _allocation_sum(payment.allocations.all()) > 0:
            raise ValidationError(
                {"allocations": "Reverse payment allocations before reversing payment."}
            )
        reverse_journal(payment.journal_entry)
        payment.status = Payment.Status.REVERSED
        payment.reversed_at = timezone.now()
        payment.save(update_fields=["status", "reversed_at"])
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="reversed",
            entity_type="payment",
            entity_id=payment.pk,
            reference=payment.journal_entry.reference,
        )
        return Response(self.get_serializer(payment).data)


class ExpenseViewSet(OrganizationScopedViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [FinancialRolePermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return Expense.objects.filter(
            organization=self.get_organization()
        ).select_related("journal_entry")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        serializer = ExpenseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        normalized = {
            "description": data["description"],
            "category": data["category"],
            "amount": str(data["amount"]),
            "method": data["method"],
            "incurred_on": data["incurred_on"].isoformat(),
            "idempotency_key": data["idempotency_key"],
        }
        fingerprint = request_fingerprint(normalized)
        existing = Expense.objects.filter(
            organization=organization, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if existing.request_hash != fingerprint:
                return Response(
                    {"detail": "Idempotency key was already used for another request."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(self.get_serializer(existing).data)

        sequence = Expense.objects.filter(organization=organization).count() + 1
        expense_number = f"EXP-{organization.pk:04d}-{sequence:08d}"
        journal = post_journal(
            organization=organization,
            reference=f"{expense_number}-POST",
            description=data["description"],
            entry_date=data["incurred_on"],
            lines=[
                (JournalLine.Account.OPERATING_EXPENSE, data["amount"], Decimal("0.00")),
                (payment_account(data["method"]), Decimal("0.00"), data["amount"]),
            ],
        )
        expense = Expense.objects.create(
            organization=organization,
            expense_number=expense_number,
            description=data["description"],
            category=data["category"],
            amount=data["amount"],
            method=data["method"],
            incurred_on=data["incurred_on"],
            idempotency_key=data["idempotency_key"],
            request_hash=fingerprint,
            journal_entry=journal,
            created_by=request.user,
        )
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="posted",
            entity_type="expense",
            entity_id=expense.pk,
            reference=expense.expense_number,
            details={
                "amount": str(expense.amount),
                "method": expense.method,
                "category": expense.category,
            },
        )
        return Response(self.get_serializer(expense).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reverse(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        expense = Expense.objects.select_for_update().get(
            pk=self.get_object().pk, organization=organization
        )
        if expense.status == Expense.Status.REVERSED:
            return Response(self.get_serializer(expense).data)
        reverse_journal(expense.journal_entry)
        expense.status = Expense.Status.REVERSED
        expense.reversed_at = timezone.now()
        expense.save(update_fields=["status", "reversed_at"])
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="reversed",
            entity_type="expense",
            entity_id=expense.pk,
            reference=expense.expense_number,
        )
        return Response(self.get_serializer(expense).data)


class CashBankTransferViewSet(OrganizationScopedViewSet):
    serializer_class = CashBankTransferSerializer
    permission_classes = [FinancialRolePermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return CashBankTransfer.objects.filter(
            organization=self.get_organization()
        ).select_related("journal_entry")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        serializer = CashBankTransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        normalized = {
            "amount": str(data["amount"]),
            "transferred_on": data["transferred_on"].isoformat(),
            "reference": data.get("reference", ""),
            "idempotency_key": data["idempotency_key"],
        }
        fingerprint = request_fingerprint(normalized)
        existing = CashBankTransfer.objects.filter(
            organization=organization,
            idempotency_key=data["idempotency_key"],
        ).first()
        if existing:
            if existing.request_hash != fingerprint:
                return Response(
                    {"detail": "Idempotency key was already used for another request."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(self.get_serializer(existing).data)

        sequence = CashBankTransfer.objects.filter(
            organization=organization
        ).count() + 1
        transfer_number = f"TRF-{organization.pk:04d}-{sequence:08d}"
        journal = post_journal(
            organization=organization,
            reference=f"{transfer_number}-POST",
            description="Cash deposited to bank",
            entry_date=data["transferred_on"],
            lines=[
                (JournalLine.Account.BANK, data["amount"], Decimal("0.00")),
                (JournalLine.Account.CASH, Decimal("0.00"), data["amount"]),
            ],
        )
        transfer = CashBankTransfer.objects.create(
            organization=organization,
            transfer_number=transfer_number,
            amount=data["amount"],
            transferred_on=data["transferred_on"],
            reference=data.get("reference", ""),
            idempotency_key=data["idempotency_key"],
            request_hash=fingerprint,
            journal_entry=journal,
            created_by=request.user,
        )
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="posted",
            entity_type="cash_bank_transfer",
            entity_id=transfer.pk,
            reference=transfer.transfer_number,
            details={"amount": str(transfer.amount)},
        )
        return Response(
            self.get_serializer(transfer).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reverse(self, request, *args, **kwargs):
        organization = self.get_organization()
        Organization.objects.select_for_update().get(pk=organization.pk)
        transfer = CashBankTransfer.objects.select_for_update().get(
            pk=self.get_object().pk,
            organization=organization,
        )
        if transfer.status == CashBankTransfer.Status.REVERSED:
            return Response(self.get_serializer(transfer).data)
        reverse_journal(transfer.journal_entry)
        transfer.status = CashBankTransfer.Status.REVERSED
        transfer.reversed_at = timezone.now()
        transfer.save(update_fields=["status", "reversed_at"])
        log_financial_event(
            organization=organization,
            actor=request.user,
            action="reversed",
            entity_type="cash_bank_transfer",
            entity_id=transfer.pk,
            reference=transfer.transfer_number,
        )
        return Response(self.get_serializer(transfer).data)


class JournalEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = JournalEntrySerializer
    permission_classes = [FinancialRolePermission]
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        organization = get_object_or_404(
            Organization.objects.filter(memberships__user=self.request.user),
            pk=self.kwargs["organization_pk"],
        )
        return (
            JournalEntry.objects.filter(organization=organization, posted=True)
            .prefetch_related("lines")
            .order_by("-entry_date", "-id")
        )


class FinancialAuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FinancialAuditEventSerializer
    permission_classes = [FinancialRolePermission]

    def get_queryset(self):
        organization = get_object_or_404(
            Organization.objects.filter(memberships__user=self.request.user),
            pk=self.kwargs["organization_pk"],
        )
        return FinancialAuditEvent.objects.filter(
            organization=organization
        ).select_related("actor")


class FinancialReportViewSet(viewsets.ViewSet):
    permission_classes = [FinancialRolePermission]

    def _organization(self):
        return get_object_or_404(
            Organization.objects.filter(memberships__user=self.request.user),
            pk=self.kwargs["organization_pk"],
        )

    def _dated(self, queryset, field, start, end):
        if start:
            queryset = queryset.filter(**{f"{field}__gte": start})
        if end:
            queryset = queryset.filter(**{f"{field}__lte": end})
        return queryset

    @action(detail=False, methods=["get"], url_path=r"customers/(?P<customer_id>\d+)/ledger")
    def customer_ledger(self, request, *args, **kwargs):
        organization = self._organization()
        customer = get_object_or_404(
            Customer.objects.filter(organization=organization),
            pk=kwargs["customer_id"],
        )
        start, end = _report_date_range(request)
        lines = JournalLine.objects.filter(
            journal_entry__organization=organization,
            journal_entry__posted=True,
            customer=customer,
        ).select_related("journal_entry", "customer")
        if end:
            lines = lines.filter(journal_entry__entry_date__lte=end)
        opening_balance = Decimal("0.00")
        if start:
            opening = lines.filter(
                journal_entry__entry_date__lt=start
            ).aggregate(
                debit=Sum("debit"), credit=Sum("credit")
            )
            opening_balance = money(
                (opening["debit"] or Decimal("0.00"))
                - (opening["credit"] or Decimal("0.00"))
            )
            lines = lines.filter(journal_entry__entry_date__gte=start)

        running_balance = opening_balance
        results = []
        for line in lines.order_by("journal_entry__entry_date", "journal_entry_id", "id"):
            running_balance = money(
                running_balance + line.debit - line.credit
            )
            results.append(
                {
                    "id": line.pk,
                    "date": line.journal_entry.entry_date,
                    "journal_reference": line.journal_entry.reference,
                    "description": line.journal_entry.description,
                    "account": line.account,
                    "account_name": line.get_account_display(),
                    "debit": str(line.debit),
                    "credit": str(line.credit),
                    "running_balance": str(running_balance),
                }
            )

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(results, request, view=self)
        response = paginator.get_paginated_response(page)
        response.data["customer"] = {"id": customer.pk, "name": customer.name}
        response.data["opening_balance"] = str(opening_balance)
        response.data["closing_balance"] = str(running_balance)
        return response

    @action(detail=False, methods=["get"], url_path="trial-balance")
    def trial_balance(self, request, *args, **kwargs):
        organization = self._organization()
        raw_as_of = request.query_params.get("as_of")
        as_of = parse_date(raw_as_of) if raw_as_of else None
        if raw_as_of and as_of is None:
            raise ValidationError({"as_of": "Enter a valid ISO date (YYYY-MM-DD)."})
        lines = JournalLine.objects.filter(
            journal_entry__organization=organization,
            journal_entry__posted=True,
        )
        if as_of:
            lines = lines.filter(journal_entry__entry_date__lte=as_of)
        balances = {
            row["account"]: row
            for row in lines.values("account").annotate(
                debits=Sum("debit"), credits=Sum("credit")
            )
        }

        debit_balance_total = Decimal("0.00")
        credit_balance_total = Decimal("0.00")
        accounts = []
        for account, label in JournalLine.Account.choices:
            values = balances.get(account, {})
            debits = money(values.get("debits") or Decimal("0.00"))
            credits = money(values.get("credits") or Decimal("0.00"))
            net = money(debits - credits)
            debit_balance = max(net, Decimal("0.00"))
            credit_balance = max(-net, Decimal("0.00"))
            debit_balance_total += debit_balance
            credit_balance_total += credit_balance
            accounts.append(
                {
                    "account": account,
                    "account_name": label,
                    "debits": str(debits),
                    "credits": str(credits),
                    "debit_balance": str(debit_balance),
                    "credit_balance": str(credit_balance),
                }
            )
        return Response(
            {
                "as_of": as_of.isoformat() if as_of else None,
                "debit_balance_total": str(money(debit_balance_total)),
                "credit_balance_total": str(money(credit_balance_total)),
                "balanced": debit_balance_total == credit_balance_total,
                "accounts": accounts,
            }
        )

    @action(detail=False, methods=["get"])
    def collections(self, request, *args, **kwargs):
        organization = self._organization()
        start, end = _report_date_range(request)
        payments = Payment.objects.filter(
            organization=organization,
            status=Payment.Status.RECEIVED,
        )
        payments = self._dated(payments, "received_on", start, end)
        totals = payments.aggregate(amount=Sum("amount"))["amount"]
        by_method = payments.values("method").annotate(
            count=Count("id"), amount=Sum("amount")
        ).order_by("method")
        by_customer = payments.values(
            "customer_id", "customer__name"
        ).annotate(count=Count("id"), amount=Sum("amount")).order_by(
            "customer__name", "customer_id"
        )
        return Response(
            {
                "date_from": start.isoformat() if start else None,
                "date_to": end.isoformat() if end else None,
                "receipt_count": payments.count(),
                "total": str(money(totals if totals is not None else Decimal("0.00"))),
                "by_method": [
                    {
                        "method": row["method"],
                        "count": row["count"],
                        "amount": str(money(row["amount"])),
                    }
                    for row in by_method
                ],
                "by_customer": [
                    {
                        "customer": row["customer_id"],
                        "customer_name": row["customer__name"],
                        "count": row["count"],
                        "amount": str(money(row["amount"])),
                    }
                    for row in by_customer
                ],
            }
        )

    @action(detail=False, methods=["get"])
    def expenses(self, request, *args, **kwargs):
        organization = self._organization()
        start, end = _report_date_range(request)
        expenses = Expense.objects.filter(
            organization=organization,
            status=Expense.Status.POSTED,
        )
        expenses = self._dated(expenses, "incurred_on", start, end)
        total = expenses.aggregate(amount=Sum("amount"))["amount"]
        by_category = expenses.values("category").annotate(
            count=Count("id"), amount=Sum("amount")
        ).order_by("category")
        by_method = expenses.values("method").annotate(
            count=Count("id"), amount=Sum("amount")
        ).order_by("method")
        return Response(
            {
                "date_from": start.isoformat() if start else None,
                "date_to": end.isoformat() if end else None,
                "expense_count": expenses.count(),
                "total": str(money(total if total is not None else Decimal("0.00"))),
                "by_category": [
                    {
                        "category": row["category"],
                        "count": row["count"],
                        "amount": str(money(row["amount"])),
                    }
                    for row in by_category
                ],
                "by_method": [
                    {
                        "method": row["method"],
                        "count": row["count"],
                        "amount": str(money(row["amount"])),
                    }
                    for row in by_method
                ],
            }
        )

    @action(detail=False, methods=["get"])
    def outstanding(self, request, *args, **kwargs):
        organization = self._organization()
        invoices = Invoice.objects.filter(
            organization=organization, status=Invoice.Status.ISSUED
        ).prefetch_related("lines", "allocations")
        invoiced_total = Decimal("0.00")
        allocated_total = Decimal("0.00")
        outstanding_total = Decimal("0.00")
        open_invoices = 0
        for invoice in invoices:
            total = invoice_totals(invoice)["total"]
            allocated = _allocation_sum(invoice.allocations.filter(
                payment__status=Payment.Status.RECEIVED
            ))
            due = money(total - allocated)
            invoiced_total += total
            allocated_total += allocated
            outstanding_total += due
            if due > 0:
                open_invoices += 1
        payment_totals = Payment.objects.filter(
            organization=organization, status=Payment.Status.RECEIVED
        ).aggregate(amount=Sum("amount"))["amount"]
        payment_totals = (
            payment_totals if payment_totals is not None else Decimal("0.00")
        )
        advance_allocations = PaymentAllocation.objects.filter(
            payment__organization=organization,
            payment__status=Payment.Status.RECEIVED,
            reversed_at__isnull=True,
        ).aggregate(amount=Sum("amount"))["amount"]
        advance_allocations = (
            advance_allocations
            if advance_allocations is not None
            else Decimal("0.00")
        )
        return Response(
            {
                "invoice_count": invoices.count(),
                "open_invoice_count": open_invoices,
                "invoiced_total": str(money(invoiced_total)),
                "allocated_total": str(money(allocated_total)),
                "outstanding_total": str(money(outstanding_total)),
                "customer_advances_total": str(
                    money(Decimal(payment_totals) - Decimal(advance_allocations))
                ),
            }
        )

    @action(detail=False, methods=["get"])
    def reconciliation(self, request, *args, **kwargs):
        organization = self._organization()
        aggregates = JournalLine.objects.filter(
            journal_entry__organization=organization,
            journal_entry__posted=True,
        ).values("account").annotate(debits=Sum("debit"), credits=Sum("credit"))
        balances = {
            account: {
                "debits": money(values["debits"] or 0),
                "credits": money(values["credits"] or 0),
            }
            for account, values in (
                (row["account"], row) for row in aggregates
            )
        }
        debit_total = money(sum(
            (item["debits"] for item in balances.values()), Decimal("0.00")
        ))
        credit_total = money(sum(
            (item["credits"] for item in balances.values()), Decimal("0.00")
        ))
        receivable_account = balances.get(
            JournalLine.Account.ACCOUNTS_RECEIVABLE,
            {"debits": Decimal("0.00"), "credits": Decimal("0.00")},
        )
        customer_receivables = JournalLine.objects.filter(
            journal_entry__organization=organization,
            journal_entry__posted=True,
            account=JournalLine.Account.ACCOUNTS_RECEIVABLE,
            customer__isnull=False,
        ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
        customer_receivables_balance = money(
            (customer_receivables["debit"] or Decimal("0.00"))
            - (customer_receivables["credit"] or Decimal("0.00"))
        )
        receivables_balance = money(
            receivable_account["debits"] - receivable_account["credits"]
        )
        accounts = [
            {
                "account": account,
                "account_name": label,
                "debits": str(values["debits"]),
                "credits": str(values["credits"]),
                "balance": str(money(values["debits"] - values["credits"])),
            }
            for account, values in sorted(
                balances.items(), key=lambda item: item[0]
            )
            for label in [
                JournalLine.Account(account).label
            ]
        ]
        return Response(
            {
                "posted_journal_count": JournalEntry.objects.filter(
                    organization=organization, posted=True
                ).count(),
                "debit_total": str(debit_total),
                "credit_total": str(credit_total),
                "difference": str(money(debit_total - credit_total)),
                "balanced": debit_total == credit_total,
                "receivables_reconciled": (
                    receivables_balance == customer_receivables_balance
                ),
                "accounts_receivable_balance": str(receivables_balance),
                "customer_receivables_balance": str(customer_receivables_balance),
                "receivables_subledger_difference": str(
                    money(receivables_balance - customer_receivables_balance)
                ),
                "accounts": accounts,
            }
        )
