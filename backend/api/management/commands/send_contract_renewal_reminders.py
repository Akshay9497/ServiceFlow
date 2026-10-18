import smtplib

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import (
    ContractRenewalReminder,
    ContractRenewalReminderAttempt,
    ServiceContract,
)


class Command(BaseCommand):
    help = "Send due AMC renewal reminders once per contract, expiry date, and interval."

    def handle(self, *args, **options):
        today = timezone.localdate()
        contracts = (
            ServiceContract.objects.filter(
                status=ServiceContract.Status.ACTIVE,
                renewal_reminders_enabled=True,
                end_date__gte=today,
            )
            .select_related("customer", "organization")
            .order_by("organization_id", "end_date", "id")
        )
        sent = 0
        skipped = 0
        failures = 0

        for candidate in contracts.iterator():
            days_before_expiry = (candidate.end_date - today).days
            if days_before_expiry not in candidate.reminder_days:
                continue

            with transaction.atomic():
                contract = (
                    ServiceContract.objects.select_for_update()
                    .select_related("customer", "organization")
                    .get(pk=candidate.pk)
                )
                if (
                    contract.status != ServiceContract.Status.ACTIVE
                    or not contract.renewal_reminders_enabled
                    or contract.end_date != candidate.end_date
                ):
                    skipped += 1
                    continue

                reminder, _ = ContractRenewalReminder.objects.get_or_create(
                    contract=contract,
                    contract_end_date=contract.end_date,
                    days_before_expiry=days_before_expiry,
                )
                reminder = ContractRenewalReminder.objects.select_for_update().get(
                    pk=reminder.pk
                )
                if reminder.status == ContractRenewalReminder.Status.SENT:
                    skipped += 1
                    continue

                reminder.status = ContractRenewalReminder.Status.PENDING
                reminder.attempts += 1
                reminder.last_error = ""
                reminder.save(update_fields=["status", "attempts", "last_error", "updated_at"])
                attempt_number = reminder.attempts
                attempted_at = timezone.now()
                recipient = contract.customer.email
                detail = ""

                if not recipient:
                    reminder.status = ContractRenewalReminder.Status.FAILED
                    reminder.last_error = "Customer has no email address."
                    detail = reminder.last_error
                else:
                    subject = f"Service contract {contract.contract_number} renewal reminder"
                    message = (
                        f"Hello {contract.customer.name},\n\n"
                        f"Your service contract {contract.contract_number} with "
                        f"{contract.organization.name} expires on "
                        f"{contract.end_date:%d %B %Y} "
                        f"({days_before_expiry} days from today).\n\n"
                        "Please contact your service provider to discuss renewal. "
                        "This message does not renew your contract automatically.\n"
                    )
                    try:
                        delivered = send_mail(
                            subject,
                            message,
                            None,
                            [recipient],
                            fail_silently=False,
                        )
                    except (OSError, smtplib.SMTPException, ValueError) as exc:
                        reminder.status = ContractRenewalReminder.Status.FAILED
                        detail = (
                            f"Email delivery failed: {exc.__class__.__name__}."
                        )
                        reminder.last_error = detail
                    else:
                        if delivered == 1:
                            reminder.status = ContractRenewalReminder.Status.SENT
                            reminder.sent_at = timezone.now()
                        else:
                            reminder.status = ContractRenewalReminder.Status.FAILED
                            detail = "Email backend did not confirm delivery."
                            reminder.last_error = detail

                reminder.save(
                    update_fields=[
                        "status",
                        "sent_at",
                        "last_error",
                        "updated_at",
                    ]
                )
                ContractRenewalReminderAttempt.objects.create(
                    reminder=reminder,
                    attempt_number=attempt_number,
                    recipient=recipient,
                    status=reminder.status,
                    detail=detail,
                    attempted_at=attempted_at,
                )
                if reminder.status == ContractRenewalReminder.Status.SENT:
                    sent += 1
                else:
                    failures += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Contract reminders sent: {sent}; skipped: {skipped}; failed: {failures}."
            )
        )
        if failures:
            raise CommandError(
                f"{failures} contract renewal reminder(s) failed. "
                "Review reminder records and email configuration, then retry."
            )
