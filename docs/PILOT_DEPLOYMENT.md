# Controlled pilot deployment and operations

This is a deployment checklist for a **small, invite-managed pilot**, not a
production-readiness certification. Run the API and frontend over HTTPS and
use a managed PostgreSQL service with encrypted connections. Keep all runtime
credentials in the hosting provider's secret manager; do not deploy either
`.env.example` file as a populated secret file.

## Implemented safeguards and known limits

- API resources are scoped to the authenticated user's organization membership.
  Finance writes are restricted to owners, administrators, and managers.
- Registration, login, and token refresh have IP-based DRF throttles. Their
  default cache is process-local; the documented pilot command uses one web
  worker. Multi-worker or multi-instance deployments need a shared cache before
  relying on these limits. Configure `DRF_NUM_PROXIES` to the exact trusted
  proxy count only after the edge sanitizes/appends `X-Forwarded-For`; otherwise
  keep it `0` and apply rate controls at the trusted edge.
- Non-debug deployments return JSON only, and production security headers,
  HTTPS redirects, secure cookies, HSTS, proxy trust, database TLS, allowed
  hosts, CORS origins, and trusted CSRF origins are configurable separately.
- Django request/security logs are written to standard output. They are not an
  audit trail and no centralized log storage, alerting, or request correlation
  service is configured.
- Signup does not verify email addresses, password recovery, and MFA are absent.
- Logout blacklists refresh tokens; already-issued access tokens remain valid
  until their short expiry.
- Subscription plans are configured manually in Django admin. Staff approve
  activations and plan changes, pilot activations may be explicitly zero-priced,
  and limits apply to new members, customers, equipment, and jobs. Subscription
  expiry/cancellation does not revoke organization access; it is not a complete
  suspension/collections workflow. Automatic renewals, proration, online
  gateway checkout, and webhooks are not implemented.
- Invoices calculate GST but are not statutory GST documents: supplier/customer
  GSTINs, place of supply, HSN/SAC, e-invoice IRN/QR, and compliant document
  numbering/export are not implemented. Have an Indian tax professional verify
  the workflow before using these records for tax filing or issuing them to
  customers.
- Passwords and JWTs have no MFA protection. The frontend keeps JWTs in
  `sessionStorage`; XSS prevention and HTTPS are therefore essential.

## Configure the backend

Provision a PostgreSQL database and a least-privilege application role through
the database provider. Require TLS and a verified server certificate when the
provider supports it. Inject these environment variables through the host:

```text
DJANGO_SECRET_KEY=<unique, randomly generated secret>
DJANGO_DEBUG=false
# Omit PUBLIC_REGISTRATION_ENABLED to default to closed when DEBUG=false.
PUBLIC_REGISTRATION_ENABLED=false
DJANGO_ALLOWED_HOSTS=<api hostname, without scheme>
CORS_ALLOWED_ORIGINS=https://<frontend hostname>
DJANGO_CSRF_TRUSTED_ORIGINS=https://<api hostname>
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SESSION_COOKIE_SECURE=true
DJANGO_CSRF_COOKIE_SECURE=true
DJANGO_SECURE_HSTS_SECONDS=3600
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=false
DJANGO_SECURE_HSTS_PRELOAD=false
DJANGO_TRUST_PROXY_SSL_HEADER=true
DRF_BROWSABLE_API_ENABLED=false
DRF_NUM_PROXIES=<trusted proxy count>
PGDATABASE=<database name>
PGUSER=<application role>
PGPASSWORD=<database password>
PGHOST=<database host>
PGPORT=5432
PGSSLMODE=verify-full
PGSSLROOTCERT=<path to provider CA certificate>
```

Use `DJANGO_TRUST_PROXY_SSL_HEADER=true` only when the trusted reverse proxy
removes client-supplied `X-Forwarded-Proto` headers and sets its own. Confirm
that HTTPS works end to end before enabling the redirect or HSTS. Increase
HSTS duration only after validating the domain and all subdomains. Add only
the real HTTPS origins and hostnames; do not use wildcards. Configure
`EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` using the
chosen email provider's credentials before sending renewal reminders. The
console email backend is for local development only.

Run deployment checks from `backend\` with the release environment:

```powershell
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
```

Review all deployment-check warnings instead of suppressing them. Apply
approved additive migrations as a separately controlled release step:

```powershell
python manage.py migrate
```

During the image build, install requirements and collect Django admin static
assets:

```text
python -m pip install -r requirements.txt
python manage.py collectstatic --noinput
```

Run automated tests in CI or against a dedicated disposable database; never
run `manage.py test` with production database credentials. PostgreSQL test
roles need permission to create a separate test database.

Run the WSGI application with a supported production server (for a small
single-instance pilot, one worker keeps the default in-memory throttle cache
effective). Do not use Django `runserver` in the pilot:

```text
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 1
```

Gunicorn and WhiteNoise are listed in `requirements.txt`; Gunicorn is intended
for the target Linux host. No hosting provider, TLS termination, firewall, outbound email policy, or
centralized logging/alerting is configured in this repository.

With public signup disabled, create only approved pilot owner accounts through
a restricted operator session. Run the following from `backend\`; the password
is entered with terminal echo disabled and should be delivered to the owner
over a separate approved channel:

```powershell
python manage.py shell
```

```python
from getpass import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from api.models import Membership, Organization

email = input("Owner email: ").strip().lower()
name = input("Owner name: ").strip()
organization_name = input("Business name: ").strip()
password = getpass("Temporary password: ")
validate_password(password)
User = get_user_model()
user = User.objects.create_user(
    username=email, email=email, first_name=name, password=password
)
organization = Organization.objects.create(name=organization_name, created_by=user)
Membership.objects.create(
    organization=organization, user=user, role=Membership.Role.OWNER
)
```

This is a manual provisioning path, not an invitation workflow; verify the
owner's email address out of band and securely communicate the temporary
password. There is no password reset flow if that password is lost.

## Build and host the frontend

Set `VITE_API_BASE_URL` to the public HTTPS API base ending in `/api` in the
frontend build environment, then from `frontend\` run:

```powershell
npm ci
npm run build
```

Publish `frontend\dist\` to a static host with HTTPS. Configure a single-page
application fallback to `index.html`, restrict the API CORS allowlist to this
origin, and do not place credentials in `VITE_*` variables (they are bundled
into public assets). Confirm the built frontend is using the production API
origin rather than localhost.

## Backups and restore drill

No hosting provider, backup destination, retention policy, or scheduler
credentials are configured in this repository. Configure encrypted,
access-restricted, off-site PostgreSQL backups with the database provider (or
a separately secured operations host) before live use. Set and communicate
retention and recovery-point/recovery-time objectives with the pilot businesses.
The repository includes a PowerShell helper that creates and validates a
custom-format PostgreSQL archive and SHA-256 checksum; operators must still
schedule it and deliver the archive to an approved encrypted/off-site
destination.

From `backend\`, install PostgreSQL client utilities and inject `PGHOST`,
`PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, and
`SERVICEFLOW_BACKUP_DIR` into the process environment from a secret manager.
The backup directory must be encrypted, access-restricted, off-site or synced
to an approved off-site destination, and outside the repository. Do not echo
the password or put it in a command line:

```powershell
$env:SERVICEFLOW_BACKUP_DIR = "E:\ServiceFlowBackups"
.\scripts\backup-postgres.ps1
Get-ChildItem $env:SERVICEFLOW_BACKUP_DIR -Filter "serviceflow-*.dump.sha256"
```

The helper runs `pg_dump`, checks readability with `pg_restore --list`, only
then promotes the `.partial` archive to `.dump`, and writes the SHA-256 sidecar.
It does not delete old archives, schedule itself, encrypt the destination, or
copy files off-site. Transfer using the approved encrypted backup system and
verify the checksum after transfer. Run and document a restore drill before
storing live customer or financial data, and repeat it regularly. A backup is
not verified until an actual isolated restore and application checks succeed.

To drill a restore, provision a **separate, empty temporary database** and role
first, set `PGHOST`, `PGPORT`, `PGUSER`, and `PGPASSWORD` for it, and run the
restore helper (which validates SHA-256 checksum integrity and prevents
overwriting the live `PGDATABASE`):

```powershell
$env:RESTORE_PGDATABASE = "serviceflow_restore_drill"
.\scripts\restore-postgres.ps1 -BackupFile $backupFile -TargetDatabase $env:RESTORE_PGDATABASE
```

Alternatively, invoke `pg_restore` directly:

```powershell
pg_restore --no-owner --dbname $env:RESTORE_PGDATABASE $backupFile
```

Do not target the live database and do not use `pg_restore --clean` for this
procedure. Point a temporary ServiceFlow deployment at the restored database,
then verify migrations, login, tenant access, record counts, invoice balances,
and the reconciliation report. Delete the temporary database only through
the provider's reviewed process after preserving the drill evidence.

## Pilot acceptance checklist

- [ ] HTTPS, DNS, host allowlists, CORS/CSRF origins, trusted proxy, HSTS, and
      secure cookies are verified on the actual host.
- [ ] PostgreSQL TLS, restricted roles, encrypted backups, retention, and a
      successful isolated restore drill are recorded.
- [ ] Authentication throttles and logs are observed on the chosen runtime;
      shared caching is configured before adding workers or instances.
- [ ] The production secret, closed public registration, database TLS, and
      HTTPS security settings are verified using the actual hosting values.
- [ ] Cross-organization access tests and financial reconciliation pass against
      PostgreSQL, not just SQLite.
- [ ] SMTP delivery and retry monitoring are verified using pilot-owned test
      mailboxes.
- [ ] A CA/business owner has approved the GST and invoice workflow for its
      intended use; otherwise use another compliant invoicing system.
- [ ] Pilot users understand subscriptions/limits, email verification,
      password recovery, MFA, quotations, exports, and statutory invoice
      documents are not implemented.

## External credentials and manual decisions still required

PostgreSQL provider/credentials and CA bundle; domain/DNS and HTTPS certificate;
production host and secret manager; email/SMTP provider credentials and sender
domain setup; encrypted off-site backup destination, schedule, retention policy,
and restore evidence;
centralized log/alert destination; frontend static host and API URL; pilot
user invitation process; shared cache if scaling beyond one worker; selected
payment provider and official documentation if online billing is required; and
accountant approval of Indian GST treatment. This repository does not provide
email verification, password reset, MFA, automated subscription renewal,
subscription suspension/collections, gateway checkout/webhooks, financial
report exports, statutory GST/e-invoice integration, or automated backup
scheduling and off-site transfer.
