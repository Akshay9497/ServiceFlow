# ServiceFlow backend

## Setup

Requires Python 3.12+ and a PostgreSQL 14+ database. From `backend\` in
PowerShell, create a local environment file, edit its secret and database
credentials, and install the dependencies:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create the PostgreSQL database and role using your PostgreSQL administration
tool, then set `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGHOST`, and `PGPORT` in
`.env` to match. Set a unique random `DJANGO_SECRET_KEY`; do not use the
placeholder in `.env.example` outside local setup. `.env` is ignored by Git.

Apply the initial Django migrations and start the development server:

```powershell
python manage.py migrate
python manage.py runserver
```

`GET http://127.0.0.1:8000/api/health/` returns the API health status and does
not require a database connection. Local frontend CORS origins are configured
by `CORS_ALLOWED_ORIGINS`.
`GET /api/public-config/` reports whether public registration is enabled.
For a controlled pilot, set `PUBLIC_REGISTRATION_ENABLED=false`; the API
enforces this setting and the frontend hides its registration action.
Registration defaults to the value of `DJANGO_DEBUG` (enabled for debug
development and disabled when debug is off). Set it explicitly in deployed
environments. The example environment file keeps registration disabled.

See the [API reference](../docs/API.md) for authentication, memberships, role
permissions, and tenant-scoped customer/equipment endpoints.
See [pilot deployment guidance](../docs/PILOT_DEPLOYMENT.md) before connecting
real business data.

## API overview

- `POST /api/auth/register/` creates a user, organization, and owner membership.
- `POST /api/auth/token/` accepts `username` (the account email) and `password`;
  `POST /api/auth/token/refresh/` refreshes an access token.
- Authenticated `POST /api/auth/logout/` blacklists that account's refresh
  token. Already-issued access tokens remain valid until their short expiry.
- `GET /api/auth/me/` and `GET /api/organizations/` return the authenticated
  user's profile and organization memberships.
- Authenticated `POST /api/organizations/` creates an organization and owner
  membership for the current account.
- `/api/organizations/{organization_id}/members/` lists members and lets
  organization owners/admins add existing accounts, change roles, and remove
  memberships. Owners control administrator and owner roles; administrators
  can grant manager and technician roles.
- `/api/organizations/{organization_id}/customers/` and
  `/api/organizations/{organization_id}/equipment/` provide tenant-scoped CRUD.
  Both support case-insensitive `search` and page-number pagination (50 per
  page). Customer search includes contact details; equipment search includes
  customer and asset identifiers. Owners, administrators, and managers can
  write; technicians can read. Equipment links and dates are validated within
  the selected organization.
- `/api/organizations/{organization_id}/jobs/` supports tenant-scoped job CRUD,
  scheduling, technician assignment, searchable status/technician/date filters,
  paginated results, status history, append-only work notes, and technician
  status progression. Completion requires a report, which is locked once the
  job is completed. Technicians only see their assigned jobs.
- `/api/organizations/{organization_id}/contracts/` supports tenant-scoped AMC
  CRUD, customer/equipment coverage, visit history, renewal drafts, and
  reminder records. Contract visit coverage dates are inclusive in the
  `Asia/Kolkata` timezone, and completed linked jobs consume at most one
  included visit. `upcoming-renewals/?days=30` filters active contracts
  expiring today through the inclusive end of the requested 1–365 day window.
  Contract `history/`, `reminders/`, and `renew/` actions provide visit history,
  per-attempt notification history, and an explicit draft renewal respectively.
- `/api/organizations/{organization_id}/invoices/` supports GST-exclusive
  invoice drafts, issuing, and reversal. Tax mode is selected as intra-state
  `cgst_sgst` or inter-state `igst`.
- `/api/organizations/{organization_id}/payments/` supports cash, UPI, and bank
  receipts, idempotency-protected customer advances, invoice allocations, and
  reversals. `/expenses/`, `/journals/`, and `/reports/outstanding/` and
  `/reports/reconciliation/` provide balanced expense entries, read-only
  journals, and financial reports.
- `/api/organizations/{organization_id}/financial-audit/` is a read-only,
  tenant-scoped, paginated log of financial mutations. Events are immutable and
  created in the same database transaction as their business operation.
- `/api/subscription/plans/` lists active administrator-configured plans.
  Organization owners/admins request activation or plan changes through
  `/api/organizations/{organization_id}/subscription/`; platform staff review
  requests through `/api/platform/subscription-requests/`. Approved pilot
  activations, subscription invoices, immediate cancellation, and member,
  customer, equipment, and job usage limits are supported.
- Send the access token in `Authorization: Bearer <access-token>`. API lists are
  paginated (50 records per page).

Configure subscription plans in Django admin at `/admin/` before asking an
organization to request activation. Plan setup is intentionally not seeded
with sample pricing. Pilot activation is a manual staff decision and creates a
zero-value invoice; standard activation/plan changes issue the configured plan
price as a subscription billing record. Owners/admins can cancel immediately;
existing business data remains available and configured usage caps continue to
apply.

Online payment gateway processing is disabled. No gateway credentials or
provider-specific official documentation are configured, so ServiceFlow does
not expose payment checkout or webhook routes. Staff can record a confirmed
manual invoice payment with a reference; repeating the same reference is
idempotent. Do not configure webhooks until provider signature verification,
event identity/deduplication, retries, and failure handling are implemented
and tested against the selected provider's official documentation.

Service-job status transitions are `new → scheduled → in_progress → completed`;
active jobs may also be cancelled. Scheduling or starting work requires both an
assigned technician and a scheduled time. Completing work requires a non-blank
completion report. `POST /jobs/{job_id}/notes/` adds an attributed, append-only
work note; `GET` on the same route lists notes. List filters include `status`,
`technician`, `scheduled_from`, `scheduled_to`, and standard DRF `search`
(`title`, description, customer, equipment, serial number, or technician email).
The scheduled date range must be valid and ordered. Job history is preserved
when customers have jobs or contracts, so the API prevents deletion of those
customer records.

## AMC renewal reminders

The `send_contract_renewal_reminders` management command processes due email
reminders for active contracts with enabled reminder offsets. Missing customer
email addresses and email-backend errors are recorded as failures for review
and retry. Schedule it once daily using Windows Task Scheduler or cron:

```powershell
python manage.py send_contract_renewal_reminders
```

The default email backend writes messages to the console for local development.
The login screen's **Forgot password?** action emails a one-time code to the
current account email. After verifying it, the user chooses a new login email
and password, then verifies a second code sent to the new email. Codes expire
after ten minutes, allow at most five attempts, and reset requests do not reveal
whether an account exists. For local testing, codes are printed in the backend
console; configure SMTP for real inbox delivery. Configure
`EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `EMAIL_USE_TLS` through environment
variables. Do not put SMTP credentials in source control. A reminder is uniquely
tracked per contract, expiry date, and
offset; failed sends remain visible and are retried on a later command run.
Each send attempt retains its attempt number, timestamp, recipient snapshot,
outcome, and safe delivery detail. Review the command output and reminder
records when it exits with a delivery error. Renewal reminders do not
automatically renew contracts; the API creates a draft for explicit review.
Reminder due dates and contract expiry calculations use `Asia/Kolkata`, not the
host machine's timezone.

For environments without a local PostgreSQL server, run the automated tests
against a temporary in-memory SQLite database (this does not change application
database configuration):

```powershell
$env:DJANGO_SECRET_KEY = "a-random-local-test-key-at-least-32-characters"
python manage.py check --settings=config.test_settings
python manage.py test api --settings=config.test_settings
```

## Database backups and restore drills

PowerShell helpers in `scripts/` automate PostgreSQL backup creation, integrity
validation, and restore drills:

- `.\scripts\backup-postgres.ps1` runs `pg_dump` with custom-format output into
  an external directory defined by `$env:SERVICEFLOW_BACKUP_DIR`, verifies the
  archive list table of contents using `pg_restore --list`, promotes the archive
  from `.partial` to `.dump`, and writes a SHA-256 checksum sidecar.
- `.\scripts\restore-postgres.ps1 -BackupFile <file.dump> -TargetDatabase <db>`
  verifies SHA-256 sidecar integrity, prevents accidental execution against the
  live `PGDATABASE`, and runs `pg_restore --no-owner` into an isolated target
  database for scheduled recovery drills.

Both scripts automatically discover `pg_dump` and `pg_restore` binaries in
standard PostgreSQL installation directories when not present in `$env:PATH`.

## Checks

```powershell
python manage.py check
python manage.py test api
```
