# ServiceFlow

ServiceFlow is a SaaS application for Indian service businesses. The project
currently implements the Django foundation and tenant-scoped operational and
financial workflows: an independently runnable Django REST API,
PostgreSQL environment configuration, multi-tenant organizations, customers,
equipment, service jobs, AMC contracts, renewal reminders, and a
React/TypeScript dashboard.

See [DEVELOPMENT_ROADMAP.md](./DEVELOPMENT_ROADMAP.md) for the architecture and
implementation phases. Backend and frontend setup notes are in
[backend/README.md](./backend/README.md) and
[frontend/README.md](./frontend/README.md).

## Prerequisites

- Python 3.12 or newer
- Node.js 20.19+ or 22.12+ and npm
- PostgreSQL 14 or newer, running locally or remotely

## Run the backend

From the repository root in PowerShell:

```powershell
cd backend
Copy-Item .env.example .env
```

Edit `backend\.env`: set a new `DJANGO_SECRET_KEY`, and set `PGDATABASE`,
`PGUSER`, and `PGPASSWORD` to credentials for a PostgreSQL database you have
created. Do not commit `.env`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The API health endpoint is `http://127.0.0.1:8000/api/health/`. Features include
registration, bearer-token login, organizations and memberships,
organization-scoped customer and equipment CRUD with search and pagination,
service jobs with technician assignments, AMC contracts with renewal reminders,
GST invoices, customer receipts and advances, expenses, balanced journals,
quotations, downloadable
management PDFs, and outstanding and reconciliation reports. Subscriptions
and broad operational reporting are not yet implemented. The PDFs are not
statutory GST invoices.
See
[backend/README.md](./backend/README.md) for the API routes and test commands.
Before connecting real pilot data, review the
[controlled pilot deployment checklist](./docs/PILOT_DEPLOYMENT.md). It
documents important gaps including absent subscription limits, automated
backups, email verification, password recovery, MFA, and statutory invoice
documents. This software has not been certified as production-ready.

## Run the frontend

In a second PowerShell terminal, from the repository root:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`). Set
`VITE_API_BASE_URL` in `frontend\.env` if the backend API is not at
`http://127.0.0.1:8000/api`.

## Checks

Run from `backend\` with the virtual environment active and `DJANGO_SECRET_KEY`
set in `.env`:

```powershell
python manage.py check
python manage.py test api
```

Run from `frontend\`:

```powershell
npm run build
```

No database reset or destructive database commands are needed. `migrate`
applies Django's normal schema migrations to the configured database.
