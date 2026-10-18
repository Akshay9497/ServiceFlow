# ServiceFlow frontend

React 19, TypeScript, and Vite frontend. From `frontend\` in PowerShell:

```powershell
npm install
npm run dev
```

Set `VITE_API_BASE_URL` in `frontend\.env` to the Django API root if it differs
from `http://127.0.0.1:8000/api`. Build and type-check with:

```powershell
npm run build
```

The login flow uses the Django JWT API. Registration availability is loaded
from the backend's public configuration endpoint; when the backend disables
self-service signup, the API and frontend both enforce that setting.
Customer, equipment, member, service-job, AMC, quotation, invoice/PDF, payment,
expense, and financial-report screens use organization-scoped DRF endpoints.
Dashboard metrics are loaded from real record, renewal, and (for
finance-authorized roles) outstanding-balance endpoints. Quotation status actions record internal
business-entered states; they do not send email or capture customer signatures.
Broad operational reporting and subscription management remain unavailable
because their backend APIs are not implemented; the UI identifies these gaps
and does not show sample records or pretend write actions. Downloaded PDFs are
management copies, not statutory GST invoices.
Before connecting pilot data, review the
[controlled pilot deployment checklist](../docs/PILOT_DEPLOYMENT.md).
