# ServiceFlow API reference

This reference describes implemented routes only. The API is rooted at
`/api/`, returns JSON, and uses trailing slashes. Organization IDs in URLs
select a tenant context; they are not authorization credentials. The API
checks the authenticated user's membership and scopes data to that organization.

## Local setup and migrations

Configure `DJANGO_SECRET_KEY`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGHOST`,
and `PGPORT` in `backend\.env` (copy `backend\.env.example`). The configured
runtime database is PostgreSQL. Create the database and role separately, then
apply the project's additive migrations from `backend\`:

```powershell
python manage.py migrate
python manage.py runserver
```

The health endpoint does not access the database:

```http
GET /api/health/
```

```json
{"status": "ok", "service": "ServiceFlow API"}
```

This endpoint is a liveness check, not a database-readiness check.

The public frontend configuration endpoint reports whether self-service
registration is enabled. It contains no organization or user data:

```http
GET /api/public-config/
```

Set `PUBLIC_REGISTRATION_ENABLED=false` to reject signup server-side and hide
the registration control in the frontend. It defaults to the value of
`DJANGO_DEBUG`: enabled in debug development and disabled when debug is off.
Set it explicitly for every deployed environment; controlled pilots should
keep registration closed.

## Authentication

### Register a business

```http
POST /api/auth/register/
Content-Type: application/json
```

```json
{
  "name": "Asha Sharma",
  "email": "asha@example.in",
  "password": "A-long-unique-password",
  "organization_name": "Asha Cooling Services"
}
```

A successful response is `201 Created` and returns the new user and
organization. Registration creates the user, organization, and owner
membership atomically. Password policy validators apply; duplicate emails are
rejected without creating another organization. Registration, login, and token
refresh endpoints are subject to configurable IP-based rate limits.

```json
{
  "user": {
    "id": 1,
    "email": "asha@example.in",
    "name": "Asha Sharma"
  },
  "organization": {
    "id": 1,
    "name": "Asha Cooling Services",
    "role": "owner"
  }
}
```

### Obtain and refresh a JWT

```http
POST /api/auth/token/
Content-Type: application/json
```

Provide the account email as `username`:

```json
{"username": "asha@example.in", "password": "A-long-unique-password"}
```

The response includes `access` and `refresh` tokens. Send the access token on
protected routes:

```http
Authorization: Bearer <access-token>
```

### Reset a forgotten password

Request a six-digit recovery code using the current account email:

```http
POST /api/auth/password-reset/
Content-Type: application/json
```

```json
{"email": "asha@example.in"}
```

The endpoint always returns the same `200 OK` response to avoid revealing
whether an account exists. If an active account with a usable password matches,
ServiceFlow emails a code. Codes expire after ten minutes and allow at most five
verification attempts.

Verify the code sent to the current email:

```http
POST /api/auth/password-reset/verify/
Content-Type: application/json
```

```json
{"email": "asha@example.in", "otp": "123456"}
```

Use the returned `verification_token` to request a second code for the new
login email:

```http
POST /api/auth/password-reset/new-email/
Content-Type: application/json
```

```json
{
  "verification_token": "<verification-token>",
  "new_email": "asha.new@example.in"
}
```

Complete the change with the second code and new password:

```http
POST /api/auth/password-reset/complete/
Content-Type: application/json
```

```json
{
  "verification_token": "<verification-token>",
  "new_email": "asha.new@example.in",
  "otp": "654321",
  "new_password": "A-new-long-unique-password",
  "confirm_password": "A-new-long-unique-password"
}
```

Password policy validators apply. Successful recovery changes both the account
email and login username, resets its password, invalidates the codes, and
blacklists existing refresh tokens. Verification tokens expire after ten
minutes. In local development, the console email backend prints codes in the
backend terminal; configure SMTP for real inbox delivery.

Refresh an access token with:

```http
POST /api/auth/token/refresh/
Content-Type: application/json
```

```json
{"refresh": "<refresh-token>"}
```

Log out by sending the current refresh token with an authenticated request:

```http
POST /api/auth/logout/
Authorization: Bearer <access-token>
Content-Type: application/json
```

```json
{"refresh": "<refresh-token>"}
```

The response is `205 Reset Content`. The refresh token must belong to the
authenticated user and is blacklisted. Already-issued access tokens remain
valid until their 20-minute expiry; the frontend clears both tokens
immediately. Refresh tokens last one day. Apply migrations after enabling the
Simple JWT token blacklist app so blacklist and outstanding-token tables exist.

### Current user and organizations

```http
GET /api/auth/me/
GET /api/organizations/
POST /api/organizations/
```

These routes require authentication. The current-user response contains the
user's organizations and their membership roles. `GET /api/organizations/`
returns only the authenticated user's memberships, using the standard
paginated-list envelope. `POST /api/organizations/` accepts `{"name":
"Business name"}` and atomically creates a new organization with the requester
as its owner. Organization creation is rate-limited.

## Organization memberships and roles

```http
GET    /api/organizations/{organization_id}/members/
POST   /api/organizations/{organization_id}/members/
GET    /api/organizations/{organization_id}/members/{membership_id}/
PATCH  /api/organizations/{organization_id}/members/{membership_id}/
DELETE /api/organizations/{organization_id}/members/{membership_id}/
```

Owners and administrators can manage memberships. Managers can list them but
cannot change them; technicians cannot access membership management. Add an
already registered user by email:

```json
{"user_email": "technician@example.in", "role": "technician"}
```

Administrators can grant `manager` and `technician` roles only. Owners can
manage administrator and owner roles as well, subject to protection of the
last owner: an owner cannot remove their own membership, and an owner
membership cannot be removed while it is the organization's only owner.

## Tenant-scoped customer and equipment records

Customer routes:

```http
GET    /api/organizations/{organization_id}/customers/
POST   /api/organizations/{organization_id}/customers/
GET    /api/organizations/{organization_id}/customers/{customer_id}/
PUT    /api/organizations/{organization_id}/customers/{customer_id}/
PATCH  /api/organizations/{organization_id}/customers/{customer_id}/
DELETE /api/organizations/{organization_id}/customers/{customer_id}/
```

Equipment routes:

```http
GET    /api/organizations/{organization_id}/equipment/
POST   /api/organizations/{organization_id}/equipment/
GET    /api/organizations/{organization_id}/equipment/{equipment_id}/
PUT    /api/organizations/{organization_id}/equipment/{equipment_id}/
PATCH  /api/organizations/{organization_id}/equipment/{equipment_id}/
DELETE /api/organizations/{organization_id}/equipment/{equipment_id}/
```

Owners, administrators, and managers can create or modify these records.
Technicians have read access only. Equipment must reference a customer in the
same organization. A record from another tenant is not returned by a detail
queryset, and cross-tenant related-object IDs are rejected. Customers with
service history or contracts and equipment covered by contracts are protected
from deletion.

List routes use page-number pagination (50 records per page by default):

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": []
}
```

Customer and equipment lists accept the standard `page` parameter and a
case-insensitive `search` parameter:

```http
GET /api/organizations/{organization_id}/customers/?search=asha&page=2
GET /api/organizations/{organization_id}/equipment/?search=serial-123&page=1
```

Customer search covers name, phone, email, and address. Equipment search covers
asset name, manufacturer, model number, serial number, and the associated
customer name. Search remains constrained to the authenticated member's
organization and returns the same paginated envelope.

Customer and equipment create/update requests require a non-blank name and
validate field lengths and email/date formats. Equipment must reference a
customer in the same organization; warranty expiry cannot precede the
installation date. Owners, administrators, and managers can create/update
records; technicians are read-only. Historical customers and contract-covered
equipment cannot be deleted.

## Other implemented organization routes

The same organization-membership boundary applies to these implemented APIs:

- `/api/organizations/{organization_id}/jobs/` — service jobs and technician
  workflows.
- `/api/organizations/{organization_id}/contracts/` — AMCs, renewals, visits,
  and renewal reminders.
- `/api/organizations/{organization_id}/invoices/` — invoice drafts, GST
  calculations, issue, reversal, and PDF management-document export.
- `/api/organizations/{organization_id}/quotations/` — GST estimates, internal
  sent/accepted/declined status recording, invoice-draft conversion, and PDF
  management-document export.
- `/api/organizations/{organization_id}/payments/` — cash, UPI, and bank
  receipts, idempotent allocation, advances, and reversal.
- `/api/organizations/{organization_id}/cash-bank-transfers/` — idempotent
  cash-to-bank transfers and their balanced journal reversals.
- `/api/organizations/{organization_id}/expenses/` — cash, UPI, or bank
  expenses and reversal.
- `/api/organizations/{organization_id}/journals/` — read-only posted journal
  entries.
- `/api/organizations/{organization_id}/reports/outstanding/` and
  `/api/organizations/{organization_id}/reports/reconciliation/` — financial
  balances, control-account/subledger reconciliation, and per-account balances.
- `/api/organizations/{organization_id}/reports/customers/{customer_id}/ledger/`
  — customer-specific posted ledger lines and opening, running, and closing
  balances; accepts inclusive `date_from` and `date_to` ISO dates.
- `/api/organizations/{organization_id}/reports/trial-balance/` — per-account
  debit and credit balances as of optional `as_of=YYYY-MM-DD`.
- `/api/organizations/{organization_id}/reports/collections/` and
  `/api/organizations/{organization_id}/reports/expenses/` — date-filtered
  totals and summaries by method/customer or category.
- `/api/organizations/{organization_id}/financial-audit/` — read-only,
  organization-scoped audit events for quotation, invoice, receipt, allocation,
  expense, and cash-to-bank transfer mutations.
- `/api/organizations/{organization_id}/subscription/` — current subscription,
  plan usage, activation/plan-change requests, and cancellation.
- `/api/organizations/{organization_id}/subscription/invoices/` — paginated
  subscription invoices visible to organization finance roles.

## Subscription plans and manual pilot activation

Subscription plans are configured by a ServiceFlow administrator in Django
admin at `/admin/` (`Subscription plans`). The catalog starts empty on purpose:
operators must configure names, INR price, billing period and duration, limits,
and features before organizations can request a plan. `null` limits are
unlimited. Limits currently cover organization members (including the owner),
customers, equipment, and service jobs. Existing organizations without an
assigned subscription remain uncapped until explicitly activated.

Authenticated organization members can read active plans:

```http
GET /api/subscription/plans/
```

Owners and administrators can read current subscription/usage and request
activation or a plan change:

```http
GET  /api/organizations/{organization_id}/subscription/
POST /api/organizations/{organization_id}/subscription/
```

```json
{"plan": 1}
```

Only one pending request is allowed per organization. Requests do not change
the plan or access until approved by a ServiceFlow platform staff account.
`GET /api/organizations/{organization_id}/subscription/` returns the assigned
plan and status, configured usage/limits, and any pending request. Plan limits
are checked transactionally when creating a member, customer, equipment item,
or service job. Reducing limits below current usage preserves existing data but
blocks further creation of that resource.

ServiceFlow staff review pending requests using a staff-authenticated session
or JWT:

```http
GET  /api/platform/subscription-requests/
POST /api/platform/subscription-requests/{request_id}/decision/
```

Approve a controlled pilot activation by explicitly setting `manual_pilot`:

```json
{
  "decision": "approve",
  "manual_pilot": true,
  "note": "Approved for the October controlled pilot"
}
```

Setting `manual_pilot` to `true` is permitted only for initial activation. It
activates the requested plan for the configured `period_days` and creates a
zero-value paid subscription invoice. A standard activation or approved plan
change creates an invoice for the configured plan price; plan changes take
effect on approval, start a new full plan period, and are billed at the full
price (no proration). Subscription invoices are operational billing records,
not representations of statutory GST invoices. There is no automatic renewal.
Active subscriptions become expired when their end date has passed and the
subscription is next read.

Owners and administrators cancel immediately:

```http
DELETE /api/organizations/{organization_id}/subscription/
```

Cancellation changes subscription status immediately and preserves existing
organization data and access; the assigned plan's usage caps continue to be
applied. ServiceFlow staff can record a manually confirmed payment against an
issued subscription invoice:

```http
POST /api/platform/subscription-invoices/{invoice_id}/mark-paid/
```

```json
{"payment_reference": "bank transfer reference"}
```

Repeating settlement with the same reference is idempotent; a conflicting
reference cannot settle an already-paid invoice. Online payment processing is
not enabled. No gateway credentials or provider documentation are configured,
so no provider checkout, webhook endpoint, signature verification, or
provider-event processing is claimed or implemented. Provider-specific webhook
verification and duplicate-event handling must be added and tested against the
selected provider's official documentation before online payments are enabled.

Financial write actions use decimal amounts, transaction-bound journal posting,
organization-serialized numbering, and idempotency keys for receipts,
allocations, expenses, and cash-to-bank transfers. The audit endpoint is
paginated and read-only;
immutable event entries identify the actor, action, record reference, and
relevant transaction details. Financial reports and transaction screens use
the same tenant-scoped endpoints.

### Service jobs

`GET /api/organizations/{organization_id}/jobs/` returns tenant-scoped,
paginated jobs. It supports `status`, `technician`, `scheduled_from`,
`scheduled_to`, and DRF `search` query parameters. Search covers job title and
description, customer name, equipment name or serial number, and technician
email. The date range accepts ISO dates (`YYYY-MM-DD`) and rejects invalid or
reversed ranges. Technician accounts are restricted to jobs assigned to their
membership, regardless of query parameters.

Jobs may be created as new or scheduled. Scheduling and starting work requires
an assigned technician and a scheduled date/time. Technicians can progress an
assigned job from scheduled to in progress and then completed. Active jobs may
also be cancelled by an owner, administrator, or manager. Completion requires
a non-blank report; the report becomes immutable once the job is completed.
Status history records the completion report on completion.

Assigned technicians and organization managers can add notes; technicians can
only access notes on their assigned jobs. Notes are append-only and include the
author and timestamp:

```http
GET  /api/organizations/{organization_id}/jobs/{job_id}/notes/
POST /api/organizations/{organization_id}/jobs/{job_id}/notes/
```

```json
{ "note": "Replaced the filter and confirmed normal operating pressure." }
```

### Annual maintenance contracts

Contracts, covered equipment, and visits are organization-scoped. A completed
job linked to an active contract records one protected visit; the contract's
start and end dates are inclusive in the `Asia/Kolkata` business timezone.
Completion is rejected outside that coverage window or after the included visit
allowance is used. Visit count and visit history are included in contract
responses; `GET /api/organizations/{organization_id}/contracts/{contract_id}/history/`
returns the contract, any renewal draft, and visit records.

Renewal reminders are configurable per contract with up to ten unique offsets
from 1 to 365 days before expiry. Upcoming-renewal filters include contracts
expiring today and on the final requested day, using the India business date.
Run `python manage.py send_contract_renewal_reminders` daily to deliver due
emails. The database uniquely keys each reminder by contract, expiry date, and
offset, so reruns do not duplicate successful notifications; failed sends can
be retried.

`GET /api/organizations/{organization_id}/contracts/{contract_id}/reminders/`
returns each reminder and its immutable attempt history, including attempt
number, outcome, attempted timestamp, recipient snapshot, and a safe delivery
result detail. Renewal creates an explicit draft contract; reminders do not
automatically renew coverage.

### Invoices

Create a draft using an organization-scoped customer and GST-exclusive lines:

```http
POST /api/organizations/{organization_id}/invoices/
```

```json
{
  "customer": 12,
  "tax_mode": "cgst_sgst",
  "due_date": "2026-11-12",
  "notes": "Service visit",
  "lines": [
    {
      "description": "Repair and parts",
      "quantity": "2.000",
      "unit_price": "250.00",
      "gst_rate": "18.00"
    }
  ]
}
```

`tax_mode` is `cgst_sgst` for intra-state invoices or `igst` for inter-state
invoices. Line taxable amounts and GST are rounded to paise using
round-half-up; for CGST/SGST, any odd paise is assigned to SGST. Invoice
numbers are generated per organization. Drafts can be edited; issuing posts an
immutable balanced journal entry. Issued invoices cannot be edited. An invoice
can be reversed only after its active payment allocations have been reversed.

```http
POST /api/organizations/{organization_id}/invoices/{invoice_id}/issue/
POST /api/organizations/{organization_id}/invoices/{invoice_id}/reverse/
```

The invoice representation returns computed `subtotal`, `tax_total`, `total`,
`allocated_total`, and `outstanding` as decimal strings. Download an invoice
management PDF with
`GET /api/organizations/{organization_id}/invoices/{invoice_id}/document/`.
It includes organization/customer names, line items, tax calculation, issue
and due dates, and current payment balance. It is explicitly marked as not
being a statutory GST tax invoice.

### Quotations

Create a tenant-scoped quotation draft with the same GST-exclusive line format
as an invoice and a required `valid_until` date:

```http
POST /api/organizations/{organization_id}/quotations/
```

Quotations are editable only while draft. The `send/` action records that the
business marked the estimate as sent; it does not send email. The `accept/` and
`decline/` actions record a status entered by an authorized organization
finance user; this is not a customer login, signature, or proof-of-acceptance
workflow. Expired drafts cannot be sent or accepted. Only sent quotations can
be accepted or declined.

```http
POST /api/organizations/{organization_id}/quotations/{quotation_id}/send/
POST /api/organizations/{organization_id}/quotations/{quotation_id}/accept/
POST /api/organizations/{organization_id}/quotations/{quotation_id}/decline/
POST /api/organizations/{organization_id}/quotations/{quotation_id}/convert/
GET  /api/organizations/{organization_id}/quotations/{quotation_id}/document/
```

The quotation PDF includes the estimate lines, GST calculation, and validity
date.

Conversion is limited to accepted quotations and is repeat-safe: the same
invoice draft is returned on repeat requests. Conversion copies the customer,
GST treatment, notes, and calculated lines into a new invoice draft. It does
not issue that invoice or post accounting journals. A quotation PDF is an
estimate, not an invoice or statutory tax document.

### Payments, allocations, advances, and expenses

Record a receipt with a unique client-provided `idempotency_key`:

```http
POST /api/organizations/{organization_id}/payments/
```

```json
{
  "customer": 12,
  "amount": "700.00",
  "method": "bank",
  "received_on": "2026-10-13",
  "reference": "UTR-optional",
  "idempotency_key": "client-generated-unique-key"
}
```

`method` is `cash`, `upi`, or `bank`. Repeating the same key with the same
request returns the original receipt without posting another journal; reusing
the key with different request data returns `409 Conflict`. Receipts are
initially customer advances (debit Cash/Bank/UPI clearing, credit Customer
Advances).

Allocate part of a receipt to an issued invoice for the same customer:

```http
POST /api/organizations/{organization_id}/payments/{payment_id}/allocations/
```

```json
{
  "invoice": 34,
  "amount": "250.00",
  "idempotency_key": "client-generated-allocation-key"
}
```

The allocation cannot exceed the invoice balance or unapplied receipt. It posts
debit Customer Advances and credit Accounts Receivable. The endpoint for an
allocation reversal is
`POST /api/organizations/{organization_id}/payments/{payment_id}/allocations/{allocation_id}/reverse/`.
Reverse allocations before reversing their payment:
`POST /api/organizations/{organization_id}/payments/{payment_id}/reverse/`.
Reversal entries are new balanced journal entries; posted entries are not
edited or deleted.

Record and reverse an expense:

```http
POST /api/organizations/{organization_id}/expenses/
POST /api/organizations/{organization_id}/expenses/{expense_id}/reverse/
```

Expense creation requires `description`, `category`, `amount`, `method`
(`cash`, `upi`, or `bank`), `incurred_on`, and a unique `idempotency_key`.
Expenses debit Operating Expense and credit the selected cash/bank/UPI account.

Transfer physical cash into a bank account:

```http
POST /api/organizations/{organization_id}/cash-bank-transfers/
POST /api/organizations/{organization_id}/cash-bank-transfers/{transfer_id}/reverse/
```

The create request requires `amount`, `transferred_on`, and
`idempotency_key`; `reference` is optional. It posts a debit to Bank and credit
to Cash. Repeating the same key and request returns the existing transfer;
reusing that key with different data returns `409 Conflict`. Reversal posts a
new balanced journal and does not edit the original.

### Journals and reports

`GET /api/organizations/{organization_id}/journals/` returns posted journal
entries with debit and credit lines. Financial endpoints and reports are
available only to organization owners, administrators, and managers.

`GET /api/organizations/{organization_id}/reports/outstanding/` returns issued
invoice totals, active allocations, outstanding balance, and unallocated
customer advances. The customer ledger, trial balance, collections, and expense
report routes listed above are also available. Date-filtered reports accept
inclusive `date_from` and `date_to` in `YYYY-MM-DD` format and reject invalid
or reversed ranges. Trial balance accepts optional `as_of=YYYY-MM-DD`.
`GET /api/organizations/{organization_id}/reports/reconciliation/` returns
posted debit/credit totals, per-account balances, the accounts-receivable
control balance, customer-tagged receivables, and their difference. Historical
invoice, receipt, allocation, and reversal journal lines are assigned their
customer dimension by additive migration `0009`; the report separately flags
an accounts-receivable subledger mismatch even when all journals balance.
Every journal is checked for at least two lines, positive totals, and equal
debits/credits before posting; posted journal and line records are immutable
through model saves and the API.

## Errors and access control

Validation errors return `400 Bad Request` with field-specific JSON errors.
Unauthenticated protected requests return `401 Unauthorized`; an authenticated
user who is not a member of the requested organization is denied, and
organization-scoped detail querysets do not reveal records from other tenants.
The browsable DRF renderer is available in development; no API documentation
route is implied by this reference.
