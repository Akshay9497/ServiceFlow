from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.test import APIClient, APITestCase

from api.models import (
    CashBankTransfer,
    Customer,
    Expense,
    FinancialAuditEvent,
    Invoice,
    JournalEntry,
    JournalLine,
    Membership,
    Organization,
    Payment,
    PaymentAllocation,
    Quotation,
    QuotationLine,
)
from api.finance import post_journal

User = get_user_model()


class FinancialWorkflowTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="finance-owner@example.com",
            email="finance-owner@example.com",
            password="Finance-Test-Password-348!",
        )
        self.organization = Organization.objects.create(
            name="Finance Services", created_by=self.owner
        )
        Membership.objects.create(
            user=self.owner,
            organization=self.organization,
            role=Membership.Role.OWNER,
        )
        self.customer = Customer.objects.create(
            organization=self.organization,
            name="Finance Customer",
            email="finance-customer@example.com",
        )
        self.base = f"/api/organizations/{self.organization.pk}"
        self.client.force_authenticate(self.owner)

    def create_invoice(self, *, tax_mode="cgst_sgst", lines=None):
        return self.client.post(
            f"{self.base}/invoices/",
            {
                "customer": self.customer.pk,
                "tax_mode": tax_mode,
                "due_date": (timezone.localdate() + timedelta(days=30)).isoformat(),
                "notes": "Net 30",
                "lines": lines
                or [
                    {
                        "description": "Service and parts",
                        "quantity": "2.000",
                        "unit_price": "250.00",
                        "gst_rate": "18.00",
                    }
                ],
            },
            format="json",
        )

    def issue_invoice(self, **kwargs):
        response = self.create_invoice(**kwargs)
        self.assertEqual(response.status_code, 201, response.data)
        return self.client.post(
            f"{self.base}/invoices/{response.data['id']}/issue/", {}, format="json"
        )

    def create_payment(self, *, amount="700.00", method="bank", key="receipt-key"):
        return self.client.post(
            f"{self.base}/payments/",
            {
                "customer": self.customer.pk,
                "amount": amount,
                "method": method,
                "received_on": timezone.localdate().isoformat(),
                "reference": "bank ref",
                "idempotency_key": key,
            },
            format="json",
        )

    def allocate(self, payment_id, invoice_id, amount="200.00", key="allocation-key"):
        return self.client.post(
            f"{self.base}/payments/{payment_id}/allocations/",
            {
                "invoice": invoice_id,
                "amount": amount,
                "idempotency_key": key,
            },
            format="json",
        )

    def test_invoice_totals_rounding_tax_modes_and_balanced_issue_journal(self):
        invoice_response = self.create_invoice()

        self.assertEqual(invoice_response.status_code, 201, invoice_response.data)
        invoice = Invoice.objects.get(pk=invoice_response.data["id"])
        self.assertEqual(invoice_response.data["subtotal"], "500.00")
        self.assertEqual(invoice_response.data["tax_total"], "90.00")
        self.assertEqual(invoice_response.data["total"], "590.00")
        line = invoice.lines.get()
        self.assertEqual(line.cgst_amount, Decimal("45.00"))
        self.assertEqual(line.sgst_amount, Decimal("45.00"))
        self.assertEqual(line.igst_amount, Decimal("0.00"))

        issued = self.client.post(
            f"{self.base}/invoices/{invoice.pk}/issue/", {}, format="json"
        )
        self.assertEqual(issued.status_code, 200, issued.data)
        invoice.refresh_from_db()
        journal = invoice.journal_entry
        journal.refresh_from_db()
        self.assertTrue(journal.posted)
        self.assertEqual(issued.data["outstanding"], "590.00")
        self.assertEqual(
            sum((row.debit for row in journal.lines.all()), Decimal("0.00")),
            Decimal("590.00"),
        )
        self.assertEqual(
            sum((row.credit for row in journal.lines.all()), Decimal("0.00")),
            Decimal("590.00"),
        )
        repeated_issue = self.client.post(
            f"{self.base}/invoices/{invoice.pk}/issue/", {}, format="json"
        )
        self.assertEqual(repeated_issue.status_code, 200)
        self.assertEqual(JournalEntry.objects.count(), 1)

        igst_response = self.create_invoice(
            tax_mode="igst",
            lines=[
                {
                    "description": "Small part",
                    "quantity": "1.000",
                    "unit_price": "0.10",
                    "gst_rate": "5.00",
                }
            ],
        )
        self.assertEqual(igst_response.status_code, 201, igst_response.data)
        self.assertEqual(igst_response.data["tax_total"], "0.01")
        igst_line = Invoice.objects.get(pk=igst_response.data["id"]).lines.get()
        self.assertEqual(igst_line.igst_amount, Decimal("0.01"))

        tax_mode_change = self.create_invoice(
            lines=[{
                "description": "Mode conversion",
                "quantity": "1.000",
                "unit_price": "100.00",
                "gst_rate": "18.00",
            }]
        )
        changed_mode = self.client.patch(
            f"{self.base}/invoices/{tax_mode_change.data['id']}/",
            {"tax_mode": "igst"},
            format="json",
        )
        self.assertEqual(changed_mode.status_code, 200, changed_mode.data)
        changed_line = Invoice.objects.get(pk=tax_mode_change.data["id"]).lines.get()
        self.assertEqual(changed_line.igst_amount, Decimal("18.00"))
        self.assertEqual(changed_line.cgst_amount, Decimal("0.00"))
        self.assertEqual(changed_line.sgst_amount, Decimal("0.00"))

    def test_payment_partial_allocation_customer_advance_and_reconciliation(self):
        issued = self.issue_invoice()
        self.assertEqual(issued.status_code, 200, issued.data)
        invoice_id = issued.data["id"]
        received = self.create_payment()

        self.assertEqual(received.status_code, 201, received.data)
        payment_id = received.data["id"]
        self.assertEqual(received.data["unallocated_amount"], "700.00")
        payment_journal = Payment.objects.get(pk=payment_id).journal_entry
        self.assertTrue(
            payment_journal.lines.filter(
                account=JournalLine.Account.BANK,
                debit=Decimal("700.00"),
            ).exists()
        )

        allocated = self.allocate(payment_id, invoice_id, amount="200.00")
        self.assertEqual(allocated.status_code, 201, allocated.data)
        invoice = self.client.get(f"{self.base}/invoices/{invoice_id}/")
        payment = self.client.get(f"{self.base}/payments/{payment_id}/")
        self.assertEqual(invoice.data["allocated_total"], "200.00")
        self.assertEqual(invoice.data["outstanding"], "390.00")
        self.assertEqual(payment.data["unallocated_amount"], "500.00")

        over_invoice = self.allocate(
            payment_id, invoice_id, amount="400.00", key="over-invoice"
        )
        self.assertEqual(over_invoice.status_code, 400)
        self.assertEqual(PaymentAllocation.objects.count(), 1)
        over_payment = self.allocate(
            payment_id, invoice_id, amount="501.00", key="over-payment"
        )
        self.assertEqual(over_payment.status_code, 400)

        remainder = self.allocate(
            payment_id, invoice_id, amount="300.00", key="second-allocation"
        )
        self.assertEqual(remainder.status_code, 201, remainder.data)
        report = self.client.get(f"{self.base}/reports/outstanding/")
        self.assertEqual(report.status_code, 200, report.data)
        self.assertEqual(report.data["invoiced_total"], "590.00")
        self.assertEqual(report.data["allocated_total"], "500.00")
        self.assertEqual(report.data["outstanding_total"], "90.00")
        self.assertEqual(report.data["customer_advances_total"], "200.00")

        reconciliation = self.client.get(f"{self.base}/reports/reconciliation/")
        self.assertEqual(reconciliation.status_code, 200, reconciliation.data)
        self.assertTrue(reconciliation.data["balanced"])
        self.assertEqual(reconciliation.data["difference"], "0.00")
        for entry in JournalEntry.objects.filter(organization=self.organization, posted=True):
            self.assertEqual(
                sum((line.debit for line in entry.lines.all()), Decimal("0.00")),
                sum((line.credit for line in entry.lines.all()), Decimal("0.00")),
            )

    def test_payment_methods_use_cash_bank_and_upi_ledger_accounts(self):
        expected_accounts = {
            "cash": JournalLine.Account.CASH,
            "bank": JournalLine.Account.BANK,
            "upi": JournalLine.Account.UPI_CLEARING,
        }
        for index, (method, account) in enumerate(expected_accounts.items()):
            response = self.create_payment(
                amount="100.00", method=method, key=f"method-{index}"
            )
            self.assertEqual(response.status_code, 201, response.data)
            payment = Payment.objects.get(pk=response.data["id"])
            self.assertTrue(
                payment.journal_entry.lines.filter(
                    account=account, debit=Decimal("100.00")
                ).exists()
            )

    def test_customer_ledger_dimensions_reconcile_with_receivables_control(self):
        issued = self.issue_invoice()
        self.assertEqual(issued.status_code, 200, issued.data)
        receipt = self.create_payment(amount="700.00", key="ledger-receipt")
        self.assertEqual(receipt.status_code, 201, receipt.data)
        allocation = self.allocate(
            receipt.data["id"],
            issued.data["id"],
            amount="200.00",
            key="ledger-allocation",
        )
        self.assertEqual(allocation.status_code, 201, allocation.data)

        invoice = Invoice.objects.get(pk=issued.data["id"])
        self.assertTrue(
            invoice.journal_entry.lines.filter(
                account=JournalLine.Account.ACCOUNTS_RECEIVABLE,
                customer=self.customer,
                debit=Decimal("590.00"),
            ).exists()
        )
        payment = Payment.objects.get(pk=receipt.data["id"])
        self.assertTrue(
            payment.journal_entry.lines.filter(
                account=JournalLine.Account.CUSTOMER_ADVANCES,
                customer=self.customer,
                credit=Decimal("700.00"),
            ).exists()
        )
        allocation_journal = PaymentAllocation.objects.get(
            pk=allocation.data["id"]
        ).journal_entry
        self.assertEqual(
            allocation_journal.lines.filter(customer=self.customer).count(), 2
        )

        ledger = self.client.get(
            f"{self.base}/reports/customers/{self.customer.pk}/ledger/"
        )
        self.assertEqual(ledger.status_code, 200, ledger.data)
        self.assertEqual(ledger.data["customer"]["id"], self.customer.pk)
        self.assertEqual(ledger.data["closing_balance"], "-110.00")
        self.assertEqual(
            [row["running_balance"] for row in ledger.data["results"]],
            ["590.00", "-110.00", "90.00", "-110.00"],
        )

        reconciliation = self.client.get(f"{self.base}/reports/reconciliation/")
        self.assertEqual(reconciliation.status_code, 200, reconciliation.data)
        self.assertEqual(reconciliation.data["accounts_receivable_balance"], "390.00")
        self.assertEqual(reconciliation.data["customer_receivables_balance"], "390.00")
        self.assertEqual(reconciliation.data["receivables_subledger_difference"], "0.00")
        self.assertTrue(reconciliation.data["receivables_reconciled"])

        post_journal(
            organization=self.organization,
            reference="UNATTRIBUTED-AR-TEST",
            description="Unattributed AR control test",
            entry_date=timezone.localdate(),
            lines=[
                (
                    JournalLine.Account.ACCOUNTS_RECEIVABLE,
                    Decimal("5.00"),
                    Decimal("0.00"),
                ),
                (
                    JournalLine.Account.SALES_REVENUE,
                    Decimal("0.00"),
                    Decimal("5.00"),
                ),
            ],
        )
        discrepancy = self.client.get(f"{self.base}/reports/reconciliation/")
        self.assertTrue(discrepancy.data["balanced"])
        self.assertFalse(discrepancy.data["receivables_reconciled"])
        self.assertEqual(
            discrepancy.data["receivables_subledger_difference"], "5.00"
        )

    def test_cash_bank_transfer_idempotency_reversal_and_tenant_isolation(self):
        transfer_input = {
            "amount": "125.50",
            "transferred_on": timezone.localdate().isoformat(),
            "reference": "Deposit slip 123",
            "idempotency_key": "cash-bank-transfer-key",
        }
        path = f"{self.base}/cash-bank-transfers/"
        created = self.client.post(path, transfer_input, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        transfer = CashBankTransfer.objects.get(pk=created.data["id"])
        lines = list(transfer.journal_entry.lines.all())
        self.assertEqual(len(lines), 2)
        self.assertTrue(
            any(
                line.account == JournalLine.Account.BANK
                and line.debit == Decimal("125.50")
                for line in lines
            )
        )
        self.assertTrue(
            any(
                line.account == JournalLine.Account.CASH
                and line.credit == Decimal("125.50")
                for line in lines
            )
        )
        repeated = self.client.post(path, transfer_input, format="json")
        self.assertEqual(repeated.status_code, 200, repeated.data)
        self.assertEqual(repeated.data["id"], created.data["id"])
        self.assertEqual(CashBankTransfer.objects.count(), 1)
        conflicting = self.client.post(
            path, {**transfer_input, "amount": "126.00"}, format="json"
        )
        self.assertEqual(conflicting.status_code, 409)

        reversed_transfer = self.client.post(
            f"{path}{transfer.pk}/reverse/", {}, format="json"
        )
        self.assertEqual(reversed_transfer.status_code, 200, reversed_transfer.data)
        self.assertEqual(reversed_transfer.data["status"], CashBankTransfer.Status.REVERSED)
        self.assertEqual(
            JournalEntry.objects.filter(reverses=transfer.journal_entry).count(), 1
        )
        again = self.client.post(f"{path}{transfer.pk}/reverse/", {}, format="json")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(
            JournalEntry.objects.filter(reverses=transfer.journal_entry).count(), 1
        )
        transfer_events = self.client.get(f"{self.base}/financial-audit/")
        self.assertIn(
            ("cash_bank_transfer", "posted"),
            {
                (event["entity_type"], event["action"])
                for event in transfer_events.data["results"]
            },
        )
        self.assertIn(
            ("cash_bank_transfer", "reversed"),
            {
                (event["entity_type"], event["action"])
                for event in transfer_events.data["results"]
            },
        )

        other_user = User.objects.create_user(
            username="transfer-outsider@example.com",
            email="transfer-outsider@example.com",
            password="finance-test-password",
        )
        other_org = Organization.objects.create(
            name="Transfer Outsider", created_by=other_user
        )
        Membership.objects.create(
            user=other_user, organization=other_org, role=Membership.Role.OWNER
        )
        self.client.force_authenticate(other_user)
        foreign_list = self.client.get(path)
        self.assertIn(foreign_list.status_code, (403, 404))
        foreign_create = self.client.post(path, transfer_input, format="json")
        self.assertIn(foreign_create.status_code, (403, 404))

    def test_trial_balance_collections_expenses_and_report_date_validation(self):
        self.issue_invoice()
        payment = self.create_payment(amount="300.00", method="upi", key="report-upi")
        self.assertEqual(payment.status_code, 201, payment.data)
        expense = self.client.post(
            f"{self.base}/expenses/",
            {
                "description": "Reportable parts",
                "category": "Parts",
                "amount": "45.75",
                "method": "cash",
                "incurred_on": timezone.localdate().isoformat(),
                "idempotency_key": "report-expense",
            },
            format="json",
        )
        self.assertEqual(expense.status_code, 201, expense.data)
        report_query = f"?date_from={timezone.localdate().isoformat()}&date_to={timezone.localdate().isoformat()}"

        trial_balance = self.client.get(
            f"{self.base}/reports/trial-balance/?as_of={timezone.localdate().isoformat()}"
        )
        self.assertEqual(trial_balance.status_code, 200, trial_balance.data)
        self.assertTrue(trial_balance.data["balanced"])
        self.assertEqual(
            trial_balance.data["debit_balance_total"],
            trial_balance.data["credit_balance_total"],
        )

        collections = self.client.get(f"{self.base}/reports/collections/{report_query}")
        self.assertEqual(collections.status_code, 200, collections.data)
        self.assertEqual(collections.data["receipt_count"], 1)
        self.assertEqual(collections.data["total"], "300.00")
        self.assertEqual(collections.data["by_method"][0]["method"], "upi")

        expenses = self.client.get(f"{self.base}/reports/expenses/{report_query}")
        self.assertEqual(expenses.status_code, 200, expenses.data)
        self.assertEqual(expenses.data["expense_count"], 1)
        self.assertEqual(expenses.data["total"], "45.75")
        self.assertEqual(expenses.data["by_category"][0]["category"], "Parts")

        reversed_payment = self.client.post(
            f"{self.base}/payments/{payment.data['id']}/reverse/", {}, format="json"
        )
        self.assertEqual(reversed_payment.status_code, 200, reversed_payment.data)
        reversed_expense = self.client.post(
            f"{self.base}/expenses/{expense.data['id']}/reverse/", {}, format="json"
        )
        self.assertEqual(reversed_expense.status_code, 200, reversed_expense.data)
        collections_after_reversal = self.client.get(
            f"{self.base}/reports/collections/{report_query}"
        )
        expenses_after_reversal = self.client.get(
            f"{self.base}/reports/expenses/{report_query}"
        )
        self.assertEqual(collections_after_reversal.data["receipt_count"], 0)
        self.assertEqual(collections_after_reversal.data["total"], "0.00")
        self.assertEqual(expenses_after_reversal.data["expense_count"], 0)
        self.assertEqual(expenses_after_reversal.data["total"], "0.00")

        invalid_range = self.client.get(
            f"{self.base}/reports/collections/?date_from=2026-02-02&date_to=2026-02-01"
        )
        self.assertEqual(invalid_range.status_code, 400)
        invalid_as_of = self.client.get(
            f"{self.base}/reports/trial-balance/?as_of=not-a-date"
        )
        self.assertEqual(invalid_as_of.status_code, 400)

    def test_customer_ledger_opening_balance_date_boundary_and_customer_tenant_scope(self):
        issued = self.issue_invoice()
        self.assertEqual(issued.status_code, 200, issued.data)
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        ledger = self.client.get(
            f"{self.base}/reports/customers/{self.customer.pk}/ledger/"
            f"?date_from={tomorrow}&date_to={tomorrow}"
        )
        self.assertEqual(ledger.status_code, 200, ledger.data)
        self.assertEqual(ledger.data["opening_balance"], "590.00")
        self.assertEqual(ledger.data["closing_balance"], "590.00")
        self.assertEqual(ledger.data["results"], [])

        invalid_range = self.client.get(
            f"{self.base}/reports/customers/{self.customer.pk}/ledger/"
            "?date_from=2026-03-02&date_to=2026-03-01"
        )
        self.assertEqual(invalid_range.status_code, 400)

        foreign_customer = Customer.objects.create(
            organization=Organization.objects.create(
                name="Ledger Scope", created_by=self.owner
            ),
            name="Foreign ledger customer",
        )
        foreign_ledger = self.client.get(
            f"{self.base}/reports/customers/{foreign_customer.pk}/ledger/"
        )
        self.assertEqual(foreign_ledger.status_code, 404)

    def test_post_journal_rejects_duplicate_reference(self):
        issued = self.issue_invoice()
        self.assertEqual(issued.status_code, 200, issued.data)
        invoice = Invoice.objects.get(pk=issued.data["id"])
        with self.assertRaisesMessage(ApiValidationError, "already exists"):
            post_journal(
                organization=self.organization,
                reference=f"INVOICE-{invoice.pk}-ISSUE",
                description="Duplicate",
                entry_date=timezone.localdate(),
                lines=[
                    (JournalLine.Account.CASH, Decimal("1.00"), Decimal("0.00")),
                    (
                        JournalLine.Account.BANK,
                        Decimal("0.00"),
                        Decimal("1.00"),
                    ),
                ],
            )

    def test_financial_audit_captures_mutations_and_is_tenant_scoped(self):
        issued = self.issue_invoice()
        self.assertEqual(issued.status_code, 200, issued.data)
        receipt = self.create_payment(amount="100.00", key="audited-receipt")
        allocation = self.allocate(
            receipt.data["id"],
            issued.data["id"],
            amount="50.00",
            key="audited-allocation",
        )
        expense = self.client.post(
            f"{self.base}/expenses/",
            {
                "description": "Audited supplies",
                "category": "Supplies",
                "amount": "25.50",
                "method": "upi",
                "incurred_on": timezone.localdate().isoformat(),
                "idempotency_key": "audited-expense",
            },
            format="json",
        )
        self.assertEqual(receipt.status_code, 201, receipt.data)
        self.assertEqual(allocation.status_code, 201, allocation.data)
        self.assertEqual(expense.status_code, 201, expense.data)
        self.client.post(
            f"{self.base}/payments/{receipt.data['id']}/allocations/"
            f"{allocation.data['id']}/reverse/",
            {},
            format="json",
        )
        self.client.post(
            f"{self.base}/expenses/{expense.data['id']}/reverse/",
            {},
            format="json",
        )

        events = self.client.get(f"{self.base}/financial-audit/")
        self.assertEqual(events.status_code, 200, events.data)
        event_keys = {
            (event["entity_type"], event["action"])
            for event in events.data["results"]
        }
        self.assertTrue(
            {
                ("invoice", "created"),
                ("invoice", "issued"),
                ("payment", "received"),
                ("payment_allocation", "allocated"),
                ("payment_allocation", "allocation_reversed"),
                ("expense", "posted"),
                ("expense", "reversed"),
            }.issubset(event_keys)
        )
        invoice_event = next(
            event
            for event in events.data["results"]
            if event["entity_type"] == "invoice" and event["action"] == "issued"
        )
        self.assertEqual(invoice_event["actor_email"], self.owner.email)
        self.assertEqual(invoice_event["reference"], issued.data["invoice_number"])

        audit_event = FinancialAuditEvent.objects.get(pk=invoice_event["id"])
        with self.assertRaises(DjangoValidationError):
            audit_event.delete()
        audit_event.action = "modified"
        with self.assertRaises(DjangoValidationError):
            audit_event.save()

        foreign_owner = User.objects.create_user(
            username="finance-audit-foreign@example.com",
            email="finance-audit-foreign@example.com",
            password="test-only-password-123!",
        )
        foreign_organization = Organization.objects.create(
            name="Foreign Audit", created_by=foreign_owner
        )
        Membership.objects.create(
            user=foreign_owner,
            organization=foreign_organization,
            role=Membership.Role.OWNER,
        )
        self.client.force_authenticate(foreign_owner)
        foreign_events = self.client.get(
            f"/api/organizations/{foreign_organization.pk}/financial-audit/"
        )
        self.assertEqual(foreign_events.status_code, 200)
        self.assertEqual(foreign_events.data["count"], 0)

        cross_audit = self.client.get(
            f"/api/organizations/{self.organization.pk}/financial-audit/"
        )
        self.assertEqual(cross_audit.status_code, 403)
        for report in ("trial-balance/", "collections/", "expenses/", "outstanding/", "reconciliation/"):
            cross_report = self.client.get(
                f"/api/organizations/{self.organization.pk}/reports/{report}"
            )
            self.assertEqual(cross_report.status_code, 403)

    def test_duplicate_payment_and_allocation_requests_are_idempotent(self):
        issued = self.issue_invoice()
        first = self.create_payment(amount="250.00", key="stable-payment-key")
        repeated = self.create_payment(amount="250.00", key="stable-payment-key")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(first.data["id"], repeated.data["id"])
        self.assertEqual(Payment.objects.count(), 1)

        changed = self.create_payment(amount="251.00", key="stable-payment-key")
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(JournalEntry.objects.count(), 2)

        allocation = self.allocate(
            first.data["id"], issued.data["id"], amount="100.00", key="stable-allocation"
        )
        duplicate_allocation = self.allocate(
            first.data["id"], issued.data["id"], amount="100.00", key="stable-allocation"
        )
        self.assertEqual(allocation.status_code, 201)
        self.assertEqual(duplicate_allocation.status_code, 200)
        self.assertEqual(allocation.data["id"], duplicate_allocation.data["id"])
        self.assertEqual(PaymentAllocation.objects.count(), 1)

        allocation_conflict = self.allocate(
            first.data["id"], issued.data["id"], amount="101.00", key="stable-allocation"
        )
        self.assertEqual(allocation_conflict.status_code, 409)

    def test_allocations_and_invoice_payment_expense_reversals_restore_balances(self):
        issued = self.issue_invoice()
        payment_response = self.create_payment(amount="590.00", key="reverse-payment")
        payment_id = payment_response.data["id"]
        allocation = self.allocate(
            payment_id, issued.data["id"], amount="590.00", key="reverse-allocation"
        )
        allocation_id = allocation.data["id"]

        blocked_invoice_reverse = self.client.post(
            f"{self.base}/invoices/{issued.data['id']}/reverse/", {}, format="json"
        )
        self.assertEqual(blocked_invoice_reverse.status_code, 400)

        reversed_allocation = self.client.post(
            f"{self.base}/payments/{payment_id}/allocations/{allocation_id}/reverse/",
            {},
            format="json",
        )
        self.assertEqual(reversed_allocation.status_code, 200)
        reversed_allocation_twice = self.client.post(
            f"{self.base}/payments/{payment_id}/allocations/{allocation_id}/reverse/",
            {},
            format="json",
        )
        self.assertEqual(reversed_allocation_twice.status_code, 200)
        self.assertEqual(JournalEntry.objects.filter(reverses__isnull=False).count(), 1)

        reverse_payment = self.client.post(
            f"{self.base}/payments/{payment_id}/reverse/", {}, format="json"
        )
        self.assertEqual(reverse_payment.status_code, 200)
        reverse_payment_again = self.client.post(
            f"{self.base}/payments/{payment_id}/reverse/", {}, format="json"
        )
        self.assertEqual(reverse_payment_again.status_code, 200)
        self.assertEqual(
            JournalEntry.objects.filter(reverses__isnull=False).count(), 2
        )
        self.assertEqual(
            self.client.get(f"{self.base}/invoices/{issued.data['id']}/").data[
                "outstanding"
            ],
            "590.00",
        )

        expense = self.client.post(
            f"{self.base}/expenses/",
            {
                "description": "Workshop supplies",
                "category": "Supplies",
                "amount": "75.25",
                "method": "cash",
                "incurred_on": timezone.localdate().isoformat(),
                "idempotency_key": "expense-key",
            },
            format="json",
        )
        self.assertEqual(expense.status_code, 201, expense.data)
        expense_id = expense.data["id"]
        expense_journal = Expense.objects.get(pk=expense_id).journal_entry
        self.assertTrue(expense_journal.lines.filter(
            account=JournalLine.Account.OPERATING_EXPENSE,
            debit=Decimal("75.25"),
        ).exists())
        self.assertTrue(expense_journal.lines.filter(
            account=JournalLine.Account.CASH,
            credit=Decimal("75.25"),
        ).exists())
        duplicate_expense = self.client.post(
            f"{self.base}/expenses/",
            {
                "description": "Workshop supplies",
                "category": "Supplies",
                "amount": "75.25",
                "method": "cash",
                "incurred_on": timezone.localdate().isoformat(),
                "idempotency_key": "expense-key",
            },
            format="json",
        )
        self.assertEqual(duplicate_expense.status_code, 200)
        self.assertEqual(Expense.objects.count(), 1)
        expense_reverse = self.client.post(
            f"{self.base}/expenses/{expense_id}/reverse/", {}, format="json"
        )
        self.assertEqual(expense_reverse.status_code, 200)
        self.assertEqual(expense_reverse.data["status"], Expense.Status.REVERSED)

        invoice_reverse = self.client.post(
            f"{self.base}/invoices/{issued.data['id']}/reverse/", {}, format="json"
        )
        self.assertEqual(invoice_reverse.status_code, 200, invoice_reverse.data)
        self.assertEqual(invoice_reverse.data["outstanding"], "0.00")
        repeated_invoice_reverse = self.client.post(
            f"{self.base}/invoices/{issued.data['id']}/reverse/", {}, format="json"
        )
        self.assertEqual(repeated_invoice_reverse.status_code, 200)
        reconciliation = self.client.get(f"{self.base}/reports/reconciliation/")
        self.assertTrue(reconciliation.data["balanced"])
        self.assertEqual(reconciliation.data["difference"], "0.00")
        self.assertEqual(
            reconciliation.data["receivables_subledger_difference"], "0.00"
        )

    def test_financial_api_rejects_invalid_cross_tenant_and_technician_access(self):
        invoice = self.create_invoice()
        self.assertEqual(invoice.status_code, 201)
        foreign_owner = User.objects.create_user(
            username="finance-foreign@example.com",
            email="finance-foreign@example.com",
            password="Finance-Test-Password-348!",
        )
        foreign_organization = Organization.objects.create(
            name="Foreign Financial Organization", created_by=foreign_owner
        )
        Membership.objects.create(
            user=foreign_owner,
            organization=foreign_organization,
            role=Membership.Role.OWNER,
        )
        foreign_customer = Customer.objects.create(
            organization=foreign_organization, name="Foreign Customer"
        )

        foreign_invoice = self.client.post(
            f"/api/organizations/{foreign_organization.pk}/invoices/",
            {
                "customer": self.customer.pk,
                "tax_mode": "igst",
                "lines": [{
                    "description": "Foreign reference",
                    "quantity": "1.000",
                    "unit_price": "10.00",
                    "gst_rate": "0.00",
                }],
            },
            format="json",
        )
        self.assertEqual(foreign_invoice.status_code, 403)
        self.assertEqual(foreign_customer.invoices.count(), 0)

        technician = User.objects.create_user(
            username="finance-tech@example.com",
            email="finance-tech@example.com",
            password="Finance-Test-Password-348!",
        )
        Membership.objects.create(
            user=technician,
            organization=self.organization,
            role=Membership.Role.TECHNICIAN,
        )
        self.client.force_authenticate(technician)
        denied = self.client.get(f"{self.base}/invoices/")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(
            self.client.get(f"{self.base}/reports/reconciliation/").status_code,
            403,
        )

    def test_payment_requests_reject_foreign_customer_and_invoice_ids(self):
        foreign_owner = User.objects.create_user(
            username="finance-scope-owner@example.com",
            email="finance-scope-owner@example.com",
            password="Finance-Test-Password-482!",
        )
        foreign_organization = Organization.objects.create(
            name="Payment Scope Organization", created_by=foreign_owner
        )
        foreign_customer = Customer.objects.create(
            organization=foreign_organization, name="Foreign Payment Customer"
        )

        foreign_customer_payment = self.client.post(
            f"{self.base}/payments/",
            {
                "customer": foreign_customer.pk,
                "amount": "100.00",
                "method": "cash",
                "received_on": timezone.localdate().isoformat(),
                "idempotency_key": "foreign-customer-payment",
            },
            format="json",
        )
        self.assertEqual(foreign_customer_payment.status_code, 400)

        local_payment = self.create_payment(amount="100.00", key="local-scope-payment")
        self.assertEqual(local_payment.status_code, 201, local_payment.data)
        foreign_invoice = Invoice.objects.create(
            organization=foreign_organization,
            invoice_number="INV-FOREIGN-000001",
            customer=foreign_customer,
            tax_mode=Invoice.TaxMode.INTER_STATE,
            created_by=foreign_owner,
        )
        foreign_invoice_allocation = self.allocate(
            local_payment.data["id"], foreign_invoice.pk
        )
        self.assertEqual(foreign_invoice_allocation.status_code, 400)
        self.assertFalse(PaymentAllocation.objects.exists())

    def test_invoice_amounts_are_bounded_before_journal_posting(self):
        oversized_line = self.create_invoice(
            lines=[
                {
                    "description": "Amount exceeding ledger precision",
                    "quantity": "999999999.999",
                    "unit_price": "9999999999.99",
                    "gst_rate": "0.00",
                }
            ]
        )
        self.assertEqual(oversized_line.status_code, 400, oversized_line.data)

        oversized_invoice_total = self.create_invoice(
            lines=[
                {
                    "description": "First large line",
                    "quantity": "100.000",
                    "unit_price": "6000000000.00",
                    "gst_rate": "0.00",
                },
                {
                    "description": "Second large line",
                    "quantity": "100.000",
                    "unit_price": "6000000000.00",
                    "gst_rate": "0.00",
                },
            ]
        )
        self.assertEqual(oversized_invoice_total.status_code, 400, oversized_invoice_total.data)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_quotation_lifecycle_converts_once_and_exports_documents(self):
        created = self.client.post(
            f"{self.base}/quotations/",
            {
                "customer": self.customer.pk,
                "tax_mode": "cgst_sgst",
                "valid_until": (timezone.localdate() + timedelta(days=14)).isoformat(),
                "notes": "Estimate <please review>",
                "lines": [
                    {
                        "description": "Repair & maintenance",
                        "quantity": "2.000",
                        "unit_price": "250.00",
                        "gst_rate": "18.00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(
            created.data["quotation_number"],
            f"QUO-{self.organization.id:04d}-000001",
        )
        self.assertEqual(created.data["subtotal"], "500.00")
        self.assertEqual(created.data["tax_total"], "90.00")
        self.assertEqual(created.data["total"], "590.00")
        quotation_id = created.data["id"]

        quote_pdf = self.client.get(
            f"{self.base}/quotations/{quotation_id}/document/"
        )
        self.assertEqual(quote_pdf.status_code, 200)
        self.assertEqual(quote_pdf["Content-Type"], "application/pdf")
        self.assertTrue(quote_pdf.content.startswith(b"%PDF-"))
        self.assertIn("attachment;", quote_pdf["Content-Disposition"])

        before_accept = self.client.post(
            f"{self.base}/quotations/{quotation_id}/convert/", {}, format="json"
        )
        self.assertEqual(before_accept.status_code, 400)
        sent = self.client.post(
            f"{self.base}/quotations/{quotation_id}/send/", {}, format="json"
        )
        self.assertEqual(sent.status_code, 200, sent.data)
        self.assertEqual(sent.data["status"], Quotation.Status.SENT)

        locked_edit = self.client.patch(
            f"{self.base}/quotations/{quotation_id}/",
            {"notes": "Cannot change after send"},
            format="json",
        )
        self.assertEqual(locked_edit.status_code, 400)
        accepted = self.client.post(
            f"{self.base}/quotations/{quotation_id}/accept/", {}, format="json"
        )
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(accepted.data["status"], Quotation.Status.ACCEPTED)

        converted = self.client.post(
            f"{self.base}/quotations/{quotation_id}/convert/", {}, format="json"
        )
        self.assertEqual(converted.status_code, 200, converted.data)
        self.assertEqual(converted.data["status"], Quotation.Status.CONVERTED)
        invoice = Invoice.objects.get(pk=converted.data["converted_invoice"])
        self.assertEqual(invoice.status, Invoice.Status.DRAFT)
        self.assertEqual(
            invoice.invoice_number, f"INV-{self.organization.id:04d}-000001"
        )
        self.assertEqual(invoice.lines.count(), 1)
        self.assertEqual(invoice.lines.get().taxable_amount, Decimal("500.00"))
        self.assertEqual(invoice.lines.get().tax_amount, Decimal("90.00"))
        self.assertEqual(JournalEntry.objects.count(), 0)

        repeated_conversion = self.client.post(
            f"{self.base}/quotations/{quotation_id}/convert/", {}, format="json"
        )
        self.assertEqual(repeated_conversion.status_code, 200)
        self.assertEqual(repeated_conversion.data["converted_invoice"], invoice.pk)
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(
            FinancialAuditEvent.objects.filter(
                entity_type="invoice", entity_id=invoice.pk, action="created_from_quotation"
            ).count(),
            1,
        )
        self.assertTrue(
            {
                "created",
                "sent",
                "accepted",
                "converted",
            }.issubset(
                set(
                    FinancialAuditEvent.objects.filter(
                        entity_type="quotation",
                        entity_id=quotation_id,
                    ).values_list("action", flat=True)
                )
            )
        )

        invoice_pdf_response = self.client.get(
            f"{self.base}/invoices/{invoice.pk}/document/"
        )
        self.assertEqual(invoice_pdf_response.status_code, 200)
        self.assertTrue(invoice_pdf_response.content.startswith(b"%PDF-"))
        self.assertIn("nosniff", invoice_pdf_response["X-Content-Type-Options"])
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_quotation_and_invoice_documents_are_tenant_scoped(self):
        quotation_response = self.client.post(
            f"{self.base}/quotations/",
            {
                "customer": self.customer.pk,
                "tax_mode": "igst",
                "valid_until": (timezone.localdate() + timedelta(days=5)).isoformat(),
                "lines": [{
                    "description": "Service",
                    "quantity": "1.000",
                    "unit_price": "100.00",
                    "gst_rate": "18.00",
                }],
            },
            format="json",
        )
        self.assertEqual(quotation_response.status_code, 201, quotation_response.data)
        issued = self.issue_invoice()
        self.assertEqual(issued.status_code, 200, issued.data)
        foreign_owner = User.objects.create_user(
            username="pdf-foreign-owner@example.com",
            email="pdf-foreign-owner@example.com",
            password="Finance-Test-Password-482!",
        )
        foreign_organization = Organization.objects.create(
            name="Foreign Documents", created_by=foreign_owner
        )
        Membership.objects.create(
            user=foreign_owner,
            organization=foreign_organization,
            role=Membership.Role.OWNER,
        )
        self.client.force_authenticate(foreign_owner)
        foreign_path = (
            f"/api/organizations/{foreign_organization.pk}/quotations/"
            f"{quotation_response.data['id']}/document/"
        )
        self.assertEqual(self.client.get(foreign_path).status_code, 404)

        invoice_foreign_path = (
            f"/api/organizations/{foreign_organization.pk}/invoices/"
            f"{issued.data['id']}/document/"
        )
        self.assertEqual(self.client.get(invoice_foreign_path).status_code, 404)

    def test_declined_quotation_cannot_be_accepted_or_converted(self):
        created = self.client.post(
            f"{self.base}/quotations/",
            {
                "customer": self.customer.pk,
                "tax_mode": "igst",
                "valid_until": (timezone.localdate() + timedelta(days=5)).isoformat(),
                "lines": [{
                    "description": "Declined service",
                    "quantity": "1.000",
                    "unit_price": "100.00",
                    "gst_rate": "18.00",
                }],
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        quote_url = f"{self.base}/quotations/{created.data['id']}"
        self.assertEqual(
            self.client.post(f"{quote_url}/send/", {}, format="json").status_code,
            200,
        )
        declined = self.client.post(
            f"{quote_url}/decline/", {}, format="json"
        )
        self.assertEqual(declined.status_code, 200)
        self.assertEqual(declined.data["status"], Quotation.Status.DECLINED)
        self.assertEqual(
            self.client.post(f"{quote_url}/accept/", {}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.client.post(f"{quote_url}/convert/", {}, format="json").status_code,
            400,
        )
        self.assertEqual(Invoice.objects.count(), 0)

    def test_expired_quotation_cannot_be_sent_or_accepted_directly(self):
        quote = Quotation.objects.create(
            organization=self.organization,
            quotation_number="QUO-0001-EXPIRED",
            customer=self.customer,
            tax_mode=Invoice.TaxMode.INTER_STATE,
            valid_until=timezone.localdate() - timedelta(days=1),
            created_by=self.owner,
        )
        QuotationLine.objects.create(
            quotation=quote,
            description="Expired service",
            quantity=Decimal("1.000"),
            unit_price=Decimal("10.00"),
            gst_rate=Decimal("0.00"),
            taxable_amount=Decimal("10.00"),
            tax_amount=Decimal("0.00"),
            igst_amount=Decimal("0.00"),
        )
        send = self.client.post(
            f"{self.base}/quotations/{quote.pk}/send/", {}, format="json"
        )
        accept = self.client.post(
            f"{self.base}/quotations/{quote.pk}/accept/", {}, format="json"
        )
        self.assertEqual(send.status_code, 400)
        self.assertEqual(accept.status_code, 400)

    def test_unbalanced_or_immutable_journals_cannot_be_posted_or_changed(self):
        journal = JournalEntry.objects.create(
            organization=self.organization,
            reference="UNBALANCED-TEST",
            description="Invalid journal",
            entry_date=timezone.localdate(),
        )
        JournalLine.objects.bulk_create([
            JournalLine(
                journal_entry=journal,
                account=JournalLine.Account.CASH,
                debit=Decimal("10.00"),
                credit=Decimal("0.00"),
            ),
            JournalLine(
                journal_entry=journal,
                account=JournalLine.Account.BANK,
                debit=Decimal("0.00"),
                credit=Decimal("9.00"),
            ),
        ])
        journal.posted = True
        with self.assertRaises(DjangoValidationError):
            journal.save(update_fields=["posted"])
        journal.refresh_from_db()
        self.assertFalse(journal.posted)

        invoice = self.issue_invoice()
        self.assertEqual(invoice.status_code, 200)
        posted = Invoice.objects.get(pk=invoice.data["id"]).journal_entry
        posted.description = "Edited posted journal"
        with self.assertRaises(DjangoValidationError):
            posted.save()


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentPaymentIdempotencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner = User.objects.create_user(
            username="finance-concurrent@example.com",
            email="finance-concurrent@example.com",
            password="Finance-Test-Password-348!",
        )
        self.organization = Organization.objects.create(
            name="Concurrent Finance Organization", created_by=self.owner
        )
        Membership.objects.create(
            user=self.owner,
            organization=self.organization,
            role=Membership.Role.OWNER,
        )
        self.customer = Customer.objects.create(
            organization=self.organization, name="Concurrent Customer"
        )

    def test_simultaneous_same_key_payment_creates_one_receipt_journal(self):
        url = f"/api/organizations/{self.organization.pk}/payments/"
        barrier = Barrier(2)

        def send_payment():
            client = APIClient()
            client.force_authenticate(self.owner)
            payload = {
                "customer": self.customer.pk,
                "amount": "100.00",
                "method": "cash",
                "received_on": timezone.localdate().isoformat(),
                "idempotency_key": "concurrent-stable-key",
            }
            barrier.wait(timeout=10)
            return client.post(url, payload, format="json")

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: send_payment(), range(2)))

        self.assertEqual(sorted(response.status_code for response in responses), [200, 201])
        self.assertEqual(Payment.objects.filter(
            organization=self.organization
        ).count(), 1)
        self.assertEqual(JournalEntry.objects.filter(
            organization=self.organization,
            reference__contains="-RECEIPT",
        ).count(), 1)
