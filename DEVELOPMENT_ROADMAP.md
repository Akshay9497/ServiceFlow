# ServiceFlow Development Roadmap

## Product and architecture

ServiceFlow is a multi-tenant SaaS platform for Indian service businesses. The
React application communicates with a Django REST Framework API over JSON/HTTPS.
Django owns authentication, authorization, business rules, and PostgreSQL
persistence. PostgreSQL is the source of truth; credentials and signing keys
are supplied through environment variables, never committed to the repository.

The intended tenancy boundary is an organization. A user's membership and role
in an organization determine access to that organization's customers, equipment,
jobs, contracts, financial records, and reports. Enforce that boundary in API
permissions and querysets, not just in the UI. Store money as decimal amounts
with an explicit INR currency, use Asia/Kolkata for business-facing dates, and
record payment method and status explicitly. Do not treat a browser-supplied
organization ID or role as authorization.

### Folder structure

```text
ServiceFlow/
├── DEVELOPMENT_ROADMAP.md
├── README.md
├── .gitignore
├── backend/
│   ├── .env.example
│   ├── requirements.txt
│   ├── manage.py
│   ├── config/                  # Django settings and URL/ASGI/WSGI entry points
│   └── api/                     # Auth, tenancy, customers, equipment, jobs, AMCs
│       └── migrations/          # Additive schema migrations
├── frontend/
│   ├── .env.example
│   ├── package.json
│   ├── index.html
│   └── src/                     # React application, API client, and dashboard
└── docs/
    └── README.md                # Documentation index and architecture notes
```

As the product grows, add focused Django apps under `backend/` for
`organizations`, `accounts`, `customers`, `equipment`, `jobs`, `contracts`,
`billing`, `expenses`, `reports`, and `subscriptions`. Keep shared API routing,
settings, and deployment configuration in `config`; keep feature-specific
models, serializers, permissions, services, URLs, and tests with their app.
Organize larger frontend features under `frontend/src/features/` and shared
networking, layout, and UI under `frontend/src/`.

## Implementation phases

1. **Project foundation (complete):** Initialize Django and React independently;
   configure environment-based PostgreSQL settings and local CORS; add a
   database-independent health-check API; build a responsive dashboard shell
   that reports API availability without fabricated business records.
2. **Identity and organizations (implemented):** Email-based registration,
   JWT login/refresh/logout, organization creation, membership/role management,
   and role-based organization permissions. Logout blacklists the refresh
   token; existing access tokens remain valid until expiry. Password recovery
   remains future work.
3. **Customers and equipment (implemented):** Tenant-scoped records, related
   customer/date validation, searchable paginated endpoints, and responsive
   CRUD management screens.
4. **Service operations (implemented and verified):** Tenant-scoped service
   jobs, status transitions and history, technician assignment, scheduling,
   assigned-job technician workflows, searchable and date-filtered job lists,
   append-only work notes, and required, locked completion reports. The API
   tests currently run against in-memory SQLite; PostgreSQL integration has
   not been exercised in this environment.
5. **Annual Maintenance Contracts (implemented and tested):** Tenant-scoped
   contracts, covered equipment, inclusive India-business-timezone coverage
   dates, visit tracking and limits, explicit renewal drafts, boundary-tested
   upcoming renewal filters, configurable idempotent reminders, and immutable
   per-attempt notification history. API tests use in-memory SQLite; email
   transport and live PostgreSQL behavior still require external configuration
   and verification.
6. **Invoices and quotations (implemented and tested):** Organization-scoped
   drafts with Decimal GST-exclusive CGST/SGST or IGST calculation,
   state-checked quote lifecycle, accepted-quote conversion, safe
   organization-serialized numbering, downloadable management PDFs, and
   tenant-isolated APIs and screens. PDFs are not statutory GST tax invoices;
   customer delivery/signature collection and compliant GST document
   generation remain unimplemented.
7. **Payments and expenses (implemented and tested):** Cash, UPI, and bank
   receipts, partial/idempotent allocations, customer advances, expenses,
   atomic balanced journals, safe reversals, idempotent cash-to-bank transfers,
   and organization-scoped mutation audit events exposed in the finance UI.
8. **Financial reports (core reports implemented and tested):** Customer
   ledgers with opening/running/closing balances, an as-of trial balance,
   inclusive date-filtered collections and expense summaries, invoice
   outstanding/advance totals, and reconciliation of customer receivables to
   the accounts-receivable control account. Immutable transaction audit history
   and the report UI are implemented. Export formats and more advanced
   visualizations remain future work. API tests use in-memory SQLite; real
   PostgreSQL behavior still requires verification.
9. **SaaS subscriptions (manual pilot workflow implemented and tested):**
   configurable plans, organization activation and plan-change requests,
   staff-approved pilot activation, subscription status/cancellation,
   subscription invoices, and transactional member/customer/equipment/job
   usage caps. Online payment gateway checkout and webhooks are intentionally
   not implemented: provider credentials and official integration/webhook
   documentation have not been supplied. Automatic renewals, proration,
   subscription invoice tax compliance, and automated payment reconciliation
   remain pending.
10. **Production readiness (incomplete):** Controlled-pilot deployment and
    restore guidance are documented; a PostgreSQL dump/archive-verification
    helper, safer closed-registration default outside debug mode, auth
    throttling, and environment-driven production settings are implemented.
    Real PostgreSQL validation, provider-managed/scheduled off-site backups and
    a     witnessed restore drill, centralized log aggregation/alerting, audit
    coverage beyond the implemented financial mutation history, deployment
    automation, accessibility, performance, and browser end-to-end coverage
    remain outstanding.

Each phase adds real API-backed behavior, authorization, validation, and tests
before presenting business records in the UI. Integrations and reminders must
surface failures rather than claim success when delivery has not occurred.

## Phase 1 completion criteria

- Backend configuration reads the Django secret and PostgreSQL connection
  values from environment variables (with an uncommitted local `.env`).
- `GET /api/health/` returns a small JSON response without querying PostgreSQL.
- The frontend builds independently and shows the actual API health state.
- Dashboard modules not yet implemented are presented as planned, not as
  working controls or fabricated records.
- Backend checks and focused tests pass; the frontend production build succeeds.

## Phase 2 completion criteria

- Registration creates an account, an organization, and its owner membership
  atomically; password login issues short-lived access and refresh tokens.
- Authenticated accounts can create additional organizations atomically and
  become their owners; logout revokes the account's refresh token.
- Organization routes verify active membership, scope every customer/equipment
  queryset to that organization, and prevent cross-tenant equipment links.
- Customer and equipment lists support tenant-scoped search and pagination;
  create/update validation rejects blank names, invalid contact data, and
  equipment warranty dates before installation.
- Owners/admins manage memberships with role limits; owners/admins/managers can
  write customer/equipment records; technicians have read-only access.
- The React application uses authenticated REST calls for dashboard counts,
  customer/equipment CRUD, and membership management.
- Automated tests verify authentication, role permissions, and cross-tenant
  access denial. PostgreSQL credentials remain external to source control.

## Phase 4 completion criteria

- Service jobs link to organization-scoped customers, optional customer
  equipment, and an active technician membership in the same organization.
- Jobs support scheduling, assignment, tenant-filtered list/detail, status
  filtering, and append-only status-change history.
- Technicians see only their assigned jobs and can advance them from scheduled
  to in progress and from in progress to completed; they cannot create, delete,
  reassign, or edit job details.
- Completion reports are required to complete work and are locked after
  completion; work notes are append-only and author-attributed.
- Job lists support tenant-scoped text search, status/technician/date filters,
  date-range validation, and the standard paginated response.
- Owners, administrators, and managers can manage jobs; cross-organization job,
  customer, equipment, and technician references are rejected.
- Dashboard counts and the responsive service-jobs screen use real API records.
- The additive migration is clean against model state; authorization/workflow
  tests, the full API test suite, and the frontend production build pass.

## Phase 5 completion criteria

- Contracts are organization-scoped and validate that customers and covered
  equipment belong to that organization.
- Contract dates, values, status, visit allowances, and reminder offsets are
  validated; completed contracted jobs consume at most one included visit.
- Renewal creates a draft linked to its source contract and never silently
  activates or auto-renews it.
- Upcoming expiries, contract visit history, and reminder delivery records are
  exposed through tenant-scoped APIs; a persistent unique reminder identity
  prevents duplicate sends for the same expiry and offset.
- Reminder delivery is configurable by environment, reports failures, and can
  retry failed deliveries. The contracts and jobs screens use the real API.
- The additive schema migration, backend tests, Django checks, migration-drift
  check, and frontend production build pass.

## Phase 6 completion criteria

- Tenant-scoped quotations use the invoice GST calculation and validate
  organization-owned customers; only drafts are editable.
- Sent, accepted, and declined transitions validate lifecycle and expiry.
  Status recording is an internal action, not customer delivery or signature.
- Accepted quotations convert repeat-safely into invoice drafts without
  issuing them or posting accounting entries.
- Tenant-scoped invoice and quotation PDFs are generated as management
  documents and clearly disclaim statutory GST invoice status.
- Tests cover GST mode changes, quotation lifecycle/conversion, PDF responses,
  and cross-tenant document isolation; migration checks, API tests, and the
  frontend production build pass.

The manual Phase 9 subscription and pilot workflows are implemented. The next
incomplete work is online payment integration after a provider is selected and
its credentials and official documentation are supplied, followed by
production readiness. Report exports and additional visualizations also remain
pending within Phase 8.
