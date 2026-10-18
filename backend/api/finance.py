import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from api.models import FinancialAuditEvent, JournalEntry, JournalLine

CENT = Decimal("0.01")
MAX_JOURNAL_AMOUNT = Decimal("999999999999.99")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def request_fingerprint(payload):
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def log_financial_event(
    *,
    organization,
    actor,
    action,
    entity_type,
    entity_id,
    reference,
    details=None,
):
    return FinancialAuditEvent.objects.create(
        organization=organization,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        reference=reference,
        details=details or {},
    )


def payment_account(method):
    return {
        "cash": JournalLine.Account.CASH,
        "bank": JournalLine.Account.BANK,
        "upi": JournalLine.Account.UPI_CLEARING,
    }[method]


def invoice_totals(invoice):
    return line_totals(invoice.lines)


def line_totals(lines):
    from django.db.models import Sum

    totals = lines.aggregate(
        taxable=Sum("taxable_amount"),
        tax=Sum("tax_amount"),
        cgst=Sum("cgst_amount"),
        sgst=Sum("sgst_amount"),
        igst=Sum("igst_amount"),
    )
    return {
        "subtotal": money(totals["taxable"] or 0),
        "tax": money(totals["tax"] or 0),
        "cgst": money(totals["cgst"] or 0),
        "sgst": money(totals["sgst"] or 0),
        "igst": money(totals["igst"] or 0),
        "total": money((totals["taxable"] or 0) + (totals["tax"] or 0)),
    }


def post_journal(
    *,
    organization,
    reference,
    description,
    entry_date,
    lines,
    reverses=None,
):
    normalized = []
    debits = Decimal("0.00")
    credits = Decimal("0.00")
    for line in lines:
        if len(line) == 3:
            account, debit, credit = line
            customer = None
        else:
            account, debit, credit, customer = line
        debit = money(debit)
        credit = money(credit)
        if debit < 0 or credit < 0 or (debit > 0) == (credit > 0):
            raise ValidationError("Each journal line must have one positive side.")
        normalized.append((account, debit, credit, customer))
        debits += debit
        credits += credit
    if len(normalized) < 2 or debits <= 0 or debits != credits:
        raise ValidationError("A posted journal must have balanced debit and credit totals.")
    if JournalEntry.objects.filter(
        organization=organization, reference=reference
    ).exists():
        raise ValidationError(
            {"reference": "A journal entry with this reference already exists."}
        )

    entry = JournalEntry.objects.create(
        organization=organization,
        reference=reference,
        description=description,
        entry_date=entry_date,
        reverses=reverses,
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                journal_entry=entry,
                account=account,
                debit=debit,
                credit=credit,
                customer=customer,
            )
            for account, debit, credit, customer in normalized
        ]
    )
    entry.posted = True
    entry.posted_at = timezone.now()
    entry.save(update_fields=["posted", "posted_at"])
    return entry


@transaction.atomic
def reverse_journal(entry, *, entry_date=None):
    locked = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    existing = JournalEntry.objects.filter(reverses=locked).first()
    if existing is not None:
        return existing
    if not locked.posted:
        raise ValidationError("Only posted journal entries can be reversed.")
    original_lines = list(locked.lines.all())
    return post_journal(
        organization=locked.organization,
        reference=f"REV-{locked.pk}",
        description=f"Reversal of {locked.reference}",
        entry_date=entry_date or timezone.localdate(),
        lines=[
            (line.account, line.credit, line.debit, line.customer)
            for line in original_lines
        ],
        reverses=locked,
    )
