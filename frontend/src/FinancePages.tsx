import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import {
  allocatePayment,
  ApiError,
  createCashBankTransfer,
  createExpense,
  createInvoice,
  createPayment,
  createQuotation,
  downloadInvoicePdf,
  downloadQuotationPdf,
  getCustomers,
  getCashBankTransfers,
  getCollectionsReport,
  getCustomerLedger,
  getExpenses,
  getExpensesReport,
  getFinancialAuditEvents,
  getInvoices,
  getJournals,
  getOutstandingReport,
  getPayments,
  getQuotations,
  getReconciliationReport,
  getTrialBalance,
  issueInvoice,
  performQuotationAction,
  reverseExpense,
  reverseCashBankTransfer,
  reverseInvoice,
  reversePayment,
  reversePaymentAllocation,
  updateInvoice,
  updateQuotation,
  type Customer,
  type CashBankTransfer,
  type CollectionsReport,
  type CustomerLedger,
  type Expense,
  type ExpenseInput,
  type ExpensesReport,
  type FinancialAuditEvent,
  type Invoice,
  type InvoiceInput,
  type InvoiceLine,
  type JournalEntry,
  type OutstandingReport,
  type Page,
  type Payment,
  type PaymentMethod,
  type Quotation,
  type QuotationAction,
  type QuotationInput,
  type ReconciliationReport,
  type TrialBalanceReport,
} from "./api";

interface FinancePageProps {
  organizationId: number;
  canWrite: boolean;
}

type InvoiceFormState = {
  customer: number;
  tax_mode: "cgst_sgst" | "igst";
  due_date: string;
  notes: string;
  lines: InvoiceLine[];
};

const blankLine = (): InvoiceLine => ({
  description: "",
  quantity: "1.000",
  unit_price: "",
  gst_rate: "18.00",
});

const today = () => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Asia/Kolkata",
    year: "numeric",
  }).formatToParts(new Date());
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
};
const addDaysToDate = (days: number) => {
  const date = new Date(`${today()}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};
const newKey = () => globalThis.crypto.randomUUID();

function messageFor(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return "Could not complete the request. Check the API connection and try again.";
}

function money(value: string | number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function FinanceHeading({
  eyebrow,
  title,
  caption,
  count,
  action,
}: {
  eyebrow: string;
  title: string;
  caption: string;
  count?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="data-page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p className="welcome-copy">
          {caption}{count ? ` ${count}` : ""}
        </p>
      </div>
      {action}
    </div>
  );
}

export function InvoicesPage({ organizationId, canWrite }: FinancePageProps) {
  const [page, setPage] = useState<Page<Invoice>>();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [form, setForm] = useState<InvoiceFormState>({
    customer: 0,
    tax_mode: "cgst_sgst",
    due_date: today(),
    notes: "",
    lines: [blankLine()],
  });
  const [editing, setEditing] = useState<number>();
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busyInvoice, setBusyInvoice] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [invoices, customerPage] = await Promise.all([
        getInvoices(organizationId),
        getCustomers(organizationId),
      ]);
      setPage(invoices);
      setCustomers(customerPage.results);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    void load();
  }, [load]);

  function startCreate() {
    setEditing(undefined);
    setForm({
      customer: customers[0]?.id ?? 0,
      tax_mode: "cgst_sgst",
      due_date: today(),
      notes: "",
      lines: [blankLine()],
    });
    setShowForm(true);
    setError("");
  }

  function startEdit(invoice: Invoice) {
    setEditing(invoice.id);
    setForm({
      customer: invoice.customer,
      tax_mode: invoice.tax_mode,
      due_date: invoice.due_date ?? today(),
      notes: invoice.notes,
      lines: invoice.lines.map((line) => ({
        description: line.description,
        quantity: line.quantity,
        unit_price: line.unit_price,
        gst_rate: line.gst_rate,
      })),
    });
    setShowForm(true);
    setError("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const input: InvoiceInput = form;
      if (editing === undefined) {
        await createInvoice(organizationId, input);
      } else {
        await updateInvoice(organizationId, editing, input);
      }
      setShowForm(false);
      setEditing(undefined);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function performInvoiceAction(invoice: Invoice, action: "issue" | "reverse") {
    const confirmed = action === "reverse"
      ? window.confirm(`Reverse invoice ${invoice.invoice_number}? This posts a permanent reversing journal entry.`)
      : true;
    if (!confirmed) return;
    setBusyInvoice(invoice.id);
    setError("");
    try {
      if (action === "issue") await issueInvoice(organizationId, invoice.id);
      else await reverseInvoice(organizationId, invoice.id);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyInvoice(undefined);
    }
  }

  function updateLine(index: number, patch: Partial<InvoiceLine>) {
    setForm((current) => ({
      ...current,
      lines: current.lines.map((line, lineIndex) =>
        lineIndex === index ? { ...line, ...patch } : line,
      ),
    }));
  }

  return (
    <section className="workspace-page data-page">
      <FinanceHeading
        eyebrow="BILLING"
        title="Invoices"
        caption="Prepare drafts, calculate GST-exclusive line totals, and issue invoices."
        count={page ? `${page.count} total.` : undefined}
        action={canWrite ? (
          <button className="primary-button" disabled={customers.length === 0} onClick={startCreate} type="button">
            Create invoice
          </button>
        ) : undefined}
      />
      {error && <div className="form-error page-alert" role="alert">{error}<button className="table-action" onClick={() => void load()} type="button">Retry</button></div>}
      <div className="inline-notice" role="status">
        GST calculations are provided for operational use. Downloaded invoice
        PDFs are management copies, not statutory GST tax invoices.
      </div>
      {showForm && (
        <form className="panel record-form" onSubmit={save}>
          <div className="panel-form-heading">
            <h2>{editing === undefined ? "Invoice draft" : "Edit invoice draft"}</h2>
            <button className="icon-button" onClick={() => setShowForm(false)} type="button" aria-label="Close invoice form">×</button>
          </div>
          <div className="form-grid">
            <label>
              Customer
              <select required value={form.customer || ""} onChange={(event) => setForm({ ...form, customer: Number(event.target.value) })}>
                <option disabled value="">Choose a customer</option>
                {customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}
              </select>
            </label>
            <label>
              GST treatment
              <select value={form.tax_mode} onChange={(event) => setForm({ ...form, tax_mode: event.target.value as InvoiceFormState["tax_mode"] })}>
                <option value="cgst_sgst">Intra-state · CGST + SGST</option>
                <option value="igst">Inter-state · IGST</option>
              </select>
            </label>
            <label>
              Due date
              <input type="date" required value={form.due_date} onChange={(event) => setForm({ ...form, due_date: event.target.value })} />
            </label>
            <label className="field-wide">
              Notes
              <textarea rows={2} value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} />
            </label>
          </div>
          <div className="finance-lines">
            <div className="finance-lines-heading"><strong>Invoice lines</strong><button className="table-action" onClick={() => setForm({ ...form, lines: [...form.lines, blankLine()] })} type="button">Add line</button></div>
            {form.lines.map((line, index) => (
              <div className="finance-line-form" key={index}>
                <label>Description<input required maxLength={300} value={line.description} onChange={(event) => updateLine(index, { description: event.target.value })} /></label>
                <label>Quantity<input required min="0.001" step="0.001" type="number" value={line.quantity} onChange={(event) => updateLine(index, { quantity: event.target.value })} /></label>
                <label>Unit price<input required min="0" step="0.01" type="number" value={line.unit_price} onChange={(event) => updateLine(index, { unit_price: event.target.value })} /></label>
                <label>GST %<input required min="0" max="100" step="0.01" type="number" value={line.gst_rate} onChange={(event) => updateLine(index, { gst_rate: event.target.value })} /></label>
                {form.lines.length > 1 && <button className="table-action table-danger" onClick={() => setForm({ ...form, lines: form.lines.filter((_, itemIndex) => itemIndex !== index) })} type="button" aria-label={`Remove line ${index + 1}`}>×</button>}
              </div>
            ))}
          </div>
          <div className="form-actions">
            <button className="secondary-button" onClick={() => setShowForm(false)} type="button">Cancel</button>
            <button className="primary-button" disabled={busy} type="submit">{busy ? "Saving…" : "Save draft"}</button>
          </div>
        </form>
      )}
      <div className="panel records-panel">
        {loading ? <p className="empty-state">Loading invoices…</p> : !page?.results.length ? (
          <div className="empty-state"><strong>No invoices yet</strong><span>Invoices created through this workspace will appear here.</span></div>
        ) : (
          <div className="table-scroll"><table className="records-table">
            <thead><tr><th>Invoice</th><th>Customer</th><th>Due date</th><th>Total</th><th>Received</th><th>Balance</th><th>Status</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>{page.results.map((invoice) => (
              <tr key={invoice.id}>
                <td><span className="record-primary">{invoice.invoice_number}</span><span className="record-secondary">{invoice.tax_mode === "igst" ? "IGST" : "CGST + SGST"} · tax {money(invoice.tax_total)}</span></td>
                <td>{invoice.customer_name}</td><td>{invoice.due_date ?? "—"}</td>
                <td>{money(invoice.total)}</td><td>{money(invoice.allocated_total)}</td><td>{money(invoice.outstanding)}</td>
                <td><span className={`contract-status status-${invoice.status}`}>{invoice.status}</span></td>
                <td className="record-actions">
                  <button
                    className="table-action"
                    disabled={busyInvoice === invoice.id}
                    onClick={() => {
                      setBusyInvoice(invoice.id);
                      setError("");
                      void downloadInvoicePdf(
                        organizationId,
                        invoice.id,
                        invoice.invoice_number,
                      )
                        .catch((reason: unknown) => setError(messageFor(reason)))
                        .finally(() => setBusyInvoice(undefined));
                    }}
                    type="button"
                  >
                    PDF
                  </button>
                  {canWrite && invoice.status === "draft" && <>
                    <button className="table-action" disabled={busyInvoice === invoice.id} onClick={() => startEdit(invoice)} type="button">Edit</button>
                    <button className="table-action" disabled={busyInvoice === invoice.id} onClick={() => void performInvoiceAction(invoice, "issue")} type="button">Issue</button>
                  </>}
                  {canWrite && invoice.status === "issued" && Number(invoice.allocated_total) === 0 && (
                    <button className="table-action table-danger" disabled={busyInvoice === invoice.id} onClick={() => void performInvoiceAction(invoice, "reverse")} type="button">Reverse</button>
                  )}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      <QuotationsPanel
        canWrite={canWrite}
        customers={customers}
        organizationId={organizationId}
      />
    </section>
  );
}

function QuotationsPanel({
  organizationId,
  customers,
  canWrite,
}: {
  organizationId: number;
  customers: Customer[];
  canWrite: boolean;
}) {
  const [page, setPage] = useState<Page<Quotation>>();
  const [form, setForm] = useState<QuotationInput>({
    customer: customers[0]?.id ?? 0,
    tax_mode: "cgst_sgst",
    valid_until: addDaysToDate(14),
    notes: "",
    lines: [blankLine()],
  });
  const [editing, setEditing] = useState<number>();
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<number>();
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPage(await getQuotations(organizationId));
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    void load();
  }, [load]);

  function startCreate() {
    setEditing(undefined);
    setForm({
      customer: customers[0]?.id ?? 0,
      tax_mode: "cgst_sgst",
      valid_until: addDaysToDate(14),
      notes: "",
      lines: [blankLine()],
    });
    setShowForm(true);
    setError("");
  }

  function startEdit(quotation: Quotation) {
    setEditing(quotation.id);
    setForm({
      customer: quotation.customer,
      tax_mode: quotation.tax_mode,
      valid_until: quotation.valid_until,
      notes: quotation.notes,
      lines: quotation.lines.map(({ description, quantity, unit_price, gst_rate }) => ({
        description,
        quantity,
        unit_price,
        gst_rate,
      })),
    });
    setShowForm(true);
    setError("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (editing === undefined) {
        await createQuotation(organizationId, form);
      } else {
        await updateQuotation(organizationId, editing, form);
      }
      setShowForm(false);
      setEditing(undefined);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function performAction(quotation: Quotation, action: QuotationAction) {
    if (action === "decline" && !window.confirm(
      `Record ${quotation.quotation_number} as declined?`,
    )) return;
    setBusyId(quotation.id);
    setError("");
    try {
      await performQuotationAction(organizationId, quotation.id, action);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyId(undefined);
    }
  }

  async function download(quotation: Quotation) {
    setBusyId(quotation.id);
    setError("");
    try {
      await downloadQuotationPdf(
        organizationId,
        quotation.id,
        quotation.quotation_number,
      );
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyId(undefined);
    }
  }

  function updateLine(index: number, patch: Partial<InvoiceLine>) {
    setForm((current) => ({
      ...current,
      lines: current.lines.map((line, lineIndex) =>
        lineIndex === index ? { ...line, ...patch } : line,
      ),
    }));
  }

  return (
    <>
      <FinanceHeading
        eyebrow="ESTIMATES"
        title="Quotations"
        caption="Create estimates, record sent/accepted status, and convert accepted quotes to invoice drafts."
        count={page ? `${page.count} total.` : undefined}
        action={canWrite ? (
          <button
            className="primary-button"
            disabled={customers.length === 0}
            onClick={startCreate}
            type="button"
          >
            Create quotation
          </button>
        ) : undefined}
      />
      <div className="inline-notice" role="status">
        “Mark sent” and “Record acceptance” update internal records only; they do
        not email the customer or collect a customer signature. PDFs are estimates,
        not statutory GST invoices.
      </div>
      {error && (
        <div className="form-error page-alert" role="alert">
          {error}<button className="table-action" onClick={() => void load()} type="button">Retry</button>
        </div>
      )}
      {showForm && (
        <form className="panel record-form" onSubmit={save}>
          <div className="panel-form-heading">
            <h2>{editing === undefined ? "Quotation draft" : "Edit quotation draft"}</h2>
            <button
              className="icon-button"
              onClick={() => setShowForm(false)}
              type="button"
              aria-label="Close quotation form"
            >
              ×
            </button>
          </div>
          <div className="form-grid">
            <label>
              Customer
              <select
                required
                value={form.customer || ""}
                onChange={(event) => setForm({ ...form, customer: Number(event.target.value) })}
              >
                <option disabled value="">Choose a customer</option>
                {customers.map((customer) => (
                  <option key={customer.id} value={customer.id}>{customer.name}</option>
                ))}
              </select>
            </label>
            <label>
              GST treatment
              <select
                value={form.tax_mode}
                onChange={(event) => setForm({
                  ...form,
                  tax_mode: event.target.value as QuotationInput["tax_mode"],
                })}
              >
                <option value="cgst_sgst">Intra-state · CGST + SGST</option>
                <option value="igst">Inter-state · IGST</option>
              </select>
            </label>
            <label>
              Valid until
              <input
                type="date"
                required
                value={form.valid_until}
                onChange={(event) => setForm({ ...form, valid_until: event.target.value })}
              />
            </label>
            <label className="field-wide">
              Notes
              <textarea
                rows={2}
                value={form.notes}
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
              />
            </label>
          </div>
          <div className="finance-lines">
            <div className="finance-lines-heading">
              <strong>Quotation lines</strong>
              <button
                className="table-action"
                onClick={() => setForm({ ...form, lines: [...form.lines, blankLine()] })}
                type="button"
              >
                Add line
              </button>
            </div>
            {form.lines.map((line, index) => (
              <div className="finance-line-form" key={index}>
                <label>
                  Description
                  <input
                    required
                    maxLength={300}
                    value={line.description}
                    onChange={(event) => updateLine(index, { description: event.target.value })}
                  />
                </label>
                <label>
                  Quantity
                  <input
                    required
                    min="0.001"
                    step="0.001"
                    type="number"
                    value={line.quantity}
                    onChange={(event) => updateLine(index, { quantity: event.target.value })}
                  />
                </label>
                <label>
                  Unit price
                  <input
                    required
                    min="0"
                    step="0.01"
                    type="number"
                    value={line.unit_price}
                    onChange={(event) => updateLine(index, { unit_price: event.target.value })}
                  />
                </label>
                <label>
                  GST %
                  <input
                    required
                    min="0"
                    max="100"
                    step="0.01"
                    type="number"
                    value={line.gst_rate}
                    onChange={(event) => updateLine(index, { gst_rate: event.target.value })}
                  />
                </label>
                {form.lines.length > 1 && (
                  <button
                    className="table-action table-danger"
                    onClick={() => setForm({
                      ...form,
                      lines: form.lines.filter((_, lineIndex) => lineIndex !== index),
                    })}
                    type="button"
                    aria-label={`Remove quotation line ${index + 1}`}
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
          <div className="form-actions">
            <button className="secondary-button" onClick={() => setShowForm(false)} type="button">
              Cancel
            </button>
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? "Saving…" : "Save quotation draft"}
            </button>
          </div>
        </form>
      )}
      <div className="panel records-panel">
        {loading ? <p className="empty-state">Loading quotations…</p> : !page?.results.length ? (
          <div className="empty-state">
            <strong>No quotations yet</strong>
            <span>Saved quotation drafts will appear here.</span>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="records-table">
              <thead>
                <tr>
                  <th>Quotation</th><th>Customer</th><th>Valid until</th>
                  <th>Total</th><th>Status</th><th><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {page.results.map((quotation) => (
                  <tr key={quotation.id}>
                    <td>
                      <span className="record-primary">{quotation.quotation_number}</span>
                      <span className="record-secondary">
                        {quotation.tax_mode === "igst" ? "IGST" : "CGST + SGST"} · GST {money(quotation.tax_total)}
                      </span>
                    </td>
                    <td>{quotation.customer_name}</td>
                    <td>{quotation.valid_until}</td>
                    <td>{money(quotation.total)}</td>
                    <td><span className={`contract-status status-${quotation.status}`}>{quotation.status}</span></td>
                    <td className="record-actions">
                      <button
                        className="table-action"
                        disabled={busyId === quotation.id}
                        onClick={() => void download(quotation)}
                        type="button"
                      >
                        PDF
                      </button>
                      {canWrite && quotation.status === "draft" && <>
                        <button className="table-action" disabled={busyId === quotation.id} onClick={() => startEdit(quotation)} type="button">Edit</button>
                        <button className="table-action" disabled={busyId === quotation.id} onClick={() => void performAction(quotation, "send")} type="button">Mark sent</button>
                      </>}
                      {canWrite && quotation.status === "sent" && <>
                        <button className="table-action" disabled={busyId === quotation.id} onClick={() => void performAction(quotation, "accept")} type="button">Record acceptance</button>
                        <button className="table-action table-danger" disabled={busyId === quotation.id} onClick={() => void performAction(quotation, "decline")} type="button">Record decline</button>
                      </>}
                      {canWrite && quotation.status === "accepted" && (
                        <button className="table-action" disabled={busyId === quotation.id} onClick={() => void performAction(quotation, "convert")} type="button">Create invoice draft</button>
                      )}
                      {quotation.converted_invoice_number && (
                        <span className="record-secondary">{quotation.converted_invoice_number}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

export function PaymentsPage({ organizationId, canWrite }: FinancePageProps) {
  const [payments, setPayments] = useState<Page<Payment>>();
  const [transfers, setTransfers] = useState<Page<CashBankTransfer>>();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customer, setCustomer] = useState(0);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [receivedOn, setReceivedOn] = useState(today());
  const [reference, setReference] = useState("");
  const [transferAmount, setTransferAmount] = useState("");
  const [transferDate, setTransferDate] = useState(today());
  const [transferReference, setTransferReference] = useState("");
  const [allocationTarget, setAllocationTarget] = useState<Payment>();
  const [allocationInvoice, setAllocationInvoice] = useState(0);
  const [allocationAmount, setAllocationAmount] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [paymentPage, transferPage, invoicePage, customerPage] = await Promise.all([
        getPayments(organizationId),
        getCashBankTransfers(organizationId),
        getInvoices(organizationId),
        getCustomers(organizationId),
      ]);
      setPayments(paymentPage);
      setTransfers(transferPage);
      setInvoices(invoicePage.results);
      setCustomers(customerPage.results);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => { void load(); }, [load]);

  const allocationOptions = useMemo(
    () => invoices.filter(
      (invoice) =>
        invoice.status === "issued"
        && invoice.customer === allocationTarget?.customer
        && Number(invoice.outstanding) > 0,
    ),
    [allocationTarget?.customer, invoices],
  );

  async function submitPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await createPayment(organizationId, {
        customer,
        amount,
        method,
        received_on: receivedOn,
        reference,
        idempotency_key: newKey(),
      });
      setAmount("");
      setReference("");
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function submitAllocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!allocationTarget) return;
    setBusy(true);
    setError("");
    try {
      await allocatePayment(organizationId, allocationTarget.id, {
        invoice: allocationInvoice,
        amount: allocationAmount,
        idempotency_key: newKey(),
      });
      setAllocationTarget(undefined);
      setAllocationAmount("");
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function submitTransfer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await createCashBankTransfer(organizationId, {
        amount: transferAmount,
        transferred_on: transferDate,
        reference: transferReference,
        idempotency_key: newKey(),
      });
      setTransferAmount("");
      setTransferReference("");
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function reverseTransfer(transfer: CashBankTransfer) {
    if (!window.confirm(`Reverse cash-to-bank transfer ${transfer.transfer_number}?`)) return;
    setBusy(true);
    setError("");
    try {
      await reverseCashBankTransfer(organizationId, transfer.id);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function reverseAllocation(payment: Payment, allocationId: number) {
    if (!window.confirm("Reverse this allocation? The invoice balance will be restored.")) return;
    setBusy(true);
    setError("");
    try {
      await reversePaymentAllocation(organizationId, payment.id, allocationId);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function reverseReceipt(payment: Payment) {
    if (!window.confirm("Reverse this receipt? Reverse its allocations first.")) return;
    setBusy(true);
    setError("");
    try {
      await reversePayment(organizationId, payment.id);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workspace-page data-page">
      <FinanceHeading eyebrow="CASH FLOW" title="Payments" caption="Record cash, UPI, and bank receipts; allocate them against issued invoices." count={payments ? `${payments.count} recorded.` : undefined} />
      {error && <div className="form-error page-alert" role="alert">{error}<button className="table-action" onClick={() => void load()} type="button">Retry</button></div>}
      {canWrite && (
        <form className="panel record-form" onSubmit={submitPayment}>
          <div className="panel-form-heading"><div><h2>Record a receipt</h2><p>Unallocated amounts remain visible as customer advances.</p></div></div>
          <div className="form-grid finance-form-grid">
            <label>Customer<select required value={customer || ""} onChange={(event) => setCustomer(Number(event.target.value))}><option disabled value="">Choose customer</option>{customers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label>Amount (INR)<input required min="0.01" step="0.01" type="number" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
            <label>Method<select value={method} onChange={(event) => setMethod(event.target.value as PaymentMethod)}><option value="cash">Cash</option><option value="upi">UPI</option><option value="bank">Bank transfer</option></select></label>
            <label>Received on<input required type="date" value={receivedOn} onChange={(event) => setReceivedOn(event.target.value)} /></label>
            <label className="field-wide">Transaction reference<input maxLength={120} value={reference} onChange={(event) => setReference(event.target.value)} /></label>
          </div>
          <div className="form-actions"><button className="primary-button" disabled={busy || customers.length === 0} type="submit">{busy ? "Recording…" : "Record payment"}</button></div>
        </form>
      )}
      {canWrite && (
        <form className="panel record-form" onSubmit={submitTransfer}>
          <div className="panel-form-heading"><div><h2>Cash-to-bank transfer</h2><p>Post a balanced cash credit and bank debit without changing customer balances.</p></div></div>
          <div className="form-grid finance-form-grid">
            <label>Amount (INR)<input required min="0.01" step="0.01" type="number" value={transferAmount} onChange={(event) => setTransferAmount(event.target.value)} /></label>
            <label>Transfer date<input required type="date" value={transferDate} onChange={(event) => setTransferDate(event.target.value)} /></label>
            <label className="field-wide">Bank reference<input maxLength={120} value={transferReference} onChange={(event) => setTransferReference(event.target.value)} /></label>
          </div>
          <div className="form-actions"><button className="primary-button" disabled={busy} type="submit">{busy ? "Posting…" : "Post transfer"}</button></div>
        </form>
      )}
      <div className="panel records-panel">
        <div className="panel-form-heading"><div><h2>Cash-to-bank transfers</h2><p>Transfers are recorded in the journal and can only be corrected by reversal.</p></div></div>
        {loading ? <p className="empty-state">Loading transfers…</p> : !transfers?.results.length ? <div className="empty-state"><strong>No transfers recorded</strong><span>Cash deposits to a bank account will appear here.</span></div> : (
          <div className="table-scroll"><table className="records-table">
            <thead><tr><th>Transfer</th><th>Date</th><th>Bank reference</th><th>Amount</th><th>Status</th><th>Action</th></tr></thead>
            <tbody>{transfers.results.map((transfer) => (
              <tr key={transfer.id}>
                <td><span className="record-primary">{transfer.transfer_number}</span><span className="record-secondary">{transfer.journal_reference}</span></td>
                <td>{transfer.transferred_on}</td><td>{transfer.reference || "—"}</td><td>{money(transfer.amount)}</td>
                <td><span className={`contract-status status-${transfer.status === "posted" ? "active" : "expired"}`}>{transfer.status}</span></td>
                <td>{canWrite && transfer.status === "posted" ? <button className="table-action danger-action" disabled={busy} onClick={() => void reverseTransfer(transfer)} type="button">Reverse</button> : "—"}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {allocationTarget && (
        <form className="panel record-form" onSubmit={submitAllocation}>
          <div className="panel-form-heading"><h2>Allocate receipt · {allocationTarget.customer_name}</h2><button className="icon-button" onClick={() => setAllocationTarget(undefined)} type="button" aria-label="Close allocation form">×</button></div>
          <div className="form-grid">
            <label>Issued invoice<select required value={allocationInvoice || ""} onChange={(event) => setAllocationInvoice(Number(event.target.value))}><option disabled value="">Choose invoice</option>{allocationOptions.map((invoice) => <option key={invoice.id} value={invoice.id}>{invoice.invoice_number} · balance {money(invoice.outstanding)}</option>)}</select></label>
            <label>Amount (INR)<input required max={allocationTarget.unallocated_amount} min="0.01" step="0.01" type="number" value={allocationAmount} onChange={(event) => setAllocationAmount(event.target.value)} /></label>
          </div>
          {allocationOptions.length === 0 && <p className="field-hint">This customer has no issued invoices with an outstanding balance.</p>}
          <div className="form-actions"><button className="secondary-button" onClick={() => setAllocationTarget(undefined)} type="button">Cancel</button><button className="primary-button" disabled={busy || allocationOptions.length === 0} type="submit">{busy ? "Allocating…" : "Allocate payment"}</button></div>
        </form>
      )}
      <div className="panel records-panel">
        {loading ? <p className="empty-state">Loading payments…</p> : !payments?.results.length ? <div className="empty-state"><strong>No payments recorded</strong><span>Receipts from this organization will appear here.</span></div> : (
          <div className="table-scroll"><table className="records-table">
            <thead><tr><th>Receipt</th><th>Customer</th><th>Method</th><th>Date</th><th>Amount</th><th>Unallocated</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>{payments.results.map((payment) => (
              <tr key={payment.id}>
                <td><span className="record-primary">{payment.journal_reference}</span><span className="record-secondary">{payment.reference || "No transaction reference"}</span>
                  {payment.allocations.length > 0 && <ul className="allocation-list">{payment.allocations.map((allocation) => <li key={allocation.id}>{allocation.invoice_number} · {money(allocation.amount)}{allocation.reversed_at ? " · reversed" : canWrite && payment.status === "received" && <button className="table-action table-danger" disabled={busy} onClick={() => void reverseAllocation(payment, allocation.id)} type="button">Reverse allocation</button>}</li>)}</ul>}
                </td>
                <td>{payment.customer_name}</td><td>{payment.method.toUpperCase()}</td><td>{payment.received_on}</td><td>{money(payment.amount)}</td><td>{money(payment.unallocated_amount)}</td>
                <td><span className={`contract-status status-${payment.status === "received" ? "active" : "cancelled"}`}>{payment.status}</span></td>
                <td className="record-actions">{canWrite && payment.status === "received" && <>
                  {Number(payment.unallocated_amount) > 0 && <button className="table-action" disabled={busy} onClick={() => { setAllocationTarget(payment); setAllocationInvoice(0); setAllocationAmount(""); }} type="button">Allocate</button>}
                  {payment.allocations.every((item) => item.reversed_at !== null) && <button className="table-action table-danger" disabled={busy} onClick={() => void reverseReceipt(payment)} type="button">Reverse receipt</button>}
                </>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
    </section>
  );
}

export function ExpensesPage({ organizationId, canWrite }: FinancePageProps) {
  const [page, setPage] = useState<Page<Expense>>();
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("bank");
  const [incurredOn, setIncurredOn] = useState(today());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPage(await getExpenses(organizationId));
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => { void load(); }, [load]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const input: ExpenseInput = {
        description,
        category,
        amount,
        method,
        incurred_on: incurredOn,
        idempotency_key: newKey(),
      };
      await createExpense(organizationId, input);
      setDescription("");
      setCategory("");
      setAmount("");
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function reverse(expense: Expense) {
    if (!window.confirm(`Reverse expense ${expense.expense_number}?`)) return;
    setBusy(true);
    setError("");
    try {
      await reverseExpense(organizationId, expense.id);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workspace-page data-page">
      <FinanceHeading eyebrow="CASH FLOW" title="Expenses" caption="Record organizational expenses with a balanced cash, UPI, or bank journal entry." count={page ? `${page.count} recorded.` : undefined} />
      {error && <div className="form-error page-alert" role="alert">{error}<button className="table-action" onClick={() => void load()} type="button">Retry</button></div>}
      {canWrite && <form className="panel record-form" onSubmit={submit}>
        <div className="panel-form-heading"><h2>Record an expense</h2></div>
        <div className="form-grid finance-form-grid">
          <label>Description<input required maxLength={300} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <label>Category<input required maxLength={100} value={category} onChange={(event) => setCategory(event.target.value)} /></label>
          <label>Amount (INR)<input required min="0.01" step="0.01" type="number" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
          <label>Paid by<select value={method} onChange={(event) => setMethod(event.target.value as PaymentMethod)}><option value="cash">Cash</option><option value="bank">Bank transfer</option><option value="upi">UPI</option></select></label>
          <label>Date<input required type="date" value={incurredOn} onChange={(event) => setIncurredOn(event.target.value)} /></label>
        </div>
        <div className="form-actions"><button className="primary-button" disabled={busy} type="submit">{busy ? "Saving…" : "Record expense"}</button></div>
      </form>}
      <div className="panel records-panel">
        {loading ? <p className="empty-state">Loading expenses…</p> : !page?.results.length ? <div className="empty-state"><strong>No expenses recorded</strong><span>Expense entries saved through this workspace will appear here.</span></div> : (
          <div className="table-scroll"><table className="records-table">
            <thead><tr><th>Expense</th><th>Category</th><th>Paid by</th><th>Date</th><th>Amount</th><th>Status</th><th><span className="visually-hidden">Actions</span></th></tr></thead>
            <tbody>{page.results.map((expense) => <tr key={expense.id}>
              <td><span className="record-primary">{expense.description}</span><span className="record-secondary">{expense.expense_number} · {expense.journal_reference}</span></td><td>{expense.category}</td><td>{expense.method.toUpperCase()}</td><td>{expense.incurred_on}</td><td>{money(expense.amount)}</td>
              <td><span className={`contract-status status-${expense.status === "posted" ? "active" : "cancelled"}`}>{expense.status}</span></td>
              <td className="record-actions">{canWrite && expense.status === "posted" && <button className="table-action table-danger" disabled={busy} onClick={() => void reverse(expense)} type="button">Reverse</button>}</td>
            </tr>)}</tbody>
          </table></div>
        )}
      </div>
    </section>
  );
}

export function ReportsPage({ organizationId }: FinancePageProps) {
  const [outstanding, setOutstanding] = useState<OutstandingReport>();
  const [reconciliation, setReconciliation] = useState<ReconciliationReport>();
  const [trialBalance, setTrialBalance] = useState<TrialBalanceReport>();
  const [collections, setCollections] = useState<CollectionsReport>();
  const [expenses, setExpenses] = useState<ExpensesReport>();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState(0);
  const [customerLedger, setCustomerLedger] = useState<CustomerLedger>();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [appliedRange, setAppliedRange] = useState({ date_from: "", date_to: "" });
  const [journals, setJournals] = useState<Page<JournalEntry>>();
  const [auditEvents, setAuditEvents] = useState<Page<FinancialAuditEvent>>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [outstandingReport, reconciliationReport, trialBalanceReport, collectionsReport, expensesReport, customerPage, journalPage, auditPage, ledger] = await Promise.all([
        getOutstandingReport(organizationId),
        getReconciliationReport(organizationId),
        getTrialBalance(organizationId, appliedRange.date_to || undefined),
        getCollectionsReport(organizationId, appliedRange),
        getExpensesReport(organizationId, appliedRange),
        getCustomers(organizationId),
        getJournals(organizationId),
        getFinancialAuditEvents(organizationId),
        selectedCustomer
          ? getCustomerLedger(organizationId, selectedCustomer, appliedRange)
          : Promise.resolve(undefined),
      ]);
      setOutstanding(outstandingReport);
      setReconciliation(reconciliationReport);
      setTrialBalance(trialBalanceReport);
      setCollections(collectionsReport);
      setExpenses(expensesReport);
      setCustomers(customerPage.results);
      setCustomerLedger(ledger);
      setJournals(journalPage);
      setAuditEvents(auditPage);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setLoading(false);
    }
  }, [appliedRange, organizationId, selectedCustomer]);

  useEffect(() => { void load(); }, [load]);

  return (
    <section className="workspace-page data-page">
      <FinanceHeading eyebrow="FINANCIAL CONTROL" title="Reports & journals" caption="Live balances and posted ledger entries from this organization." />
      {error && <div className="form-error page-alert" role="alert">{error}<button className="table-action" onClick={() => void load()} type="button">Retry</button></div>}
      <form className="panel record-form" onSubmit={(event) => {
        event.preventDefault();
        setAppliedRange({ date_from: dateFrom, date_to: dateTo });
      }}>
        <div className="panel-form-heading"><div><h2>Report period</h2><p>Collections, expenses, and customer ledger use inclusive dates. Trial balance is as of the end date.</p></div></div>
        <div className="form-grid finance-form-grid">
          <label>From<input type="date" value={dateFrom} max={dateTo || undefined} onChange={(event) => setDateFrom(event.target.value)} /></label>
          <label>To<input type="date" value={dateTo} min={dateFrom || undefined} onChange={(event) => setDateTo(event.target.value)} /></label>
          <label>Customer ledger<select value={selectedCustomer || ""} onChange={(event) => setSelectedCustomer(Number(event.target.value))}><option value="">Choose a customer</option>{customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.name}</option>)}</select></label>
        </div>
        <div className="form-actions"><button className="primary-button" disabled={loading} type="submit">{loading ? "Refreshing…" : "Apply period"}</button></div>
      </form>
      {loading ? <div className="panel records-panel"><p className="empty-state">Loading financial reports…</p></div> : outstanding && reconciliation && trialBalance && collections && expenses && (
        <>
          <section className="finance-report-grid" aria-label="Outstanding balances">
            <article className="finance-report-card"><span>Issued invoices</span><strong>{outstanding.invoice_count}</strong><small>{outstanding.open_invoice_count} with balance</small></article>
            <article className="finance-report-card"><span>Invoiced</span><strong>{money(outstanding.invoiced_total)}</strong><small>Issued invoice totals</small></article>
            <article className="finance-report-card"><span>Allocated</span><strong>{money(outstanding.allocated_total)}</strong><small>Active allocations</small></article>
            <article className="finance-report-card"><span>Outstanding</span><strong>{money(outstanding.outstanding_total)}</strong><small>Invoice balances due</small></article>
            <article className="finance-report-card"><span>Customer advances</span><strong>{money(outstanding.customer_advances_total)}</strong><small>Unallocated receipts</small></article>
          </section>
          <section className="panel reconciliation-panel">
            <div className="reconciliation-heading">
              <div><div className="panel-kicker">DOUBLE-ENTRY RECONCILIATION</div><h2>{reconciliation.balanced && reconciliation.receivables_reconciled ? "Ledger and receivables are reconciled" : "Ledger or receivables discrepancy detected"}</h2><p>{reconciliation.posted_journal_count} posted journal entries · journal difference {money(reconciliation.difference)}</p></div>
              <span className={`contract-status status-${reconciliation.balanced && reconciliation.receivables_reconciled ? "active" : "expired"}`}>{reconciliation.balanced && reconciliation.receivables_reconciled ? "Reconciled" : "Investigate"}</span>
            </div>
            <div className="account-balance-list">{reconciliation.accounts.map((account) => <div key={account.account}><span>{account.account_name}</span><strong>{money(account.balance)}</strong><small>Dr {money(account.debits)} · Cr {money(account.credits)}</small></div>)}</div>
            <div className={reconciliation.receivables_reconciled ? "inline-notice" : "form-error page-alert"} role={reconciliation.receivables_reconciled ? "status" : "alert"}>Accounts receivable control balance: {money(reconciliation.accounts_receivable_balance)} · Customer subledger: {money(reconciliation.customer_receivables_balance)} · Difference: {money(reconciliation.receivables_subledger_difference)}</div>
          </section>
          <section className="panel reconciliation-panel">
            <div className="panel-form-heading"><div><div className="panel-kicker">TRIAL BALANCE</div><h2>As of {trialBalance.as_of ?? "all posted dates"}</h2><p>Debit balances {money(trialBalance.debit_balance_total)} · Credit balances {money(trialBalance.credit_balance_total)}</p></div><span className={`contract-status status-${trialBalance.balanced ? "active" : "expired"}`}>{trialBalance.balanced ? "Balanced" : "Out of balance"}</span></div>
            <div className="account-balance-list">{trialBalance.accounts.filter((account) => Number(account.debits) || Number(account.credits)).map((account) => <div key={account.account}><span>{account.account_name}</span><strong>Dr {money(account.debit_balance)} · Cr {money(account.credit_balance)}</strong><small>Movement: Dr {money(account.debits)} · Cr {money(account.credits)}</small></div>)}</div>
          </section>
          <section className="finance-report-grid" aria-label="Collections and expenses">
            <article className="finance-report-card"><span>Collections</span><strong>{money(collections.total)}</strong><small>{collections.receipt_count} receipts in the selected period</small></article>
            <article className="finance-report-card"><span>Expenses</span><strong>{money(expenses.total)}</strong><small>{expenses.expense_count} posted expenses in the selected period</small></article>
          </section>
          <div className="panel records-panel">
            <div className="panel-form-heading"><div><h2>Collections by method and customer</h2><p>Reversed receipts are excluded.</p></div></div>
            <div className="account-balance-list">
              {collections.by_method.map((row) => <div key={`method-${row.method}`}><span>{row.method.toUpperCase()}</span><strong>{money(row.amount)}</strong><small>{row.count} receipts</small></div>)}
              {collections.by_customer.map((row) => <div key={`customer-${row.customer}`}><span>{row.customer_name}</span><strong>{money(row.amount)}</strong><small>{row.count} receipts</small></div>)}
              {!collections.by_method.length && !collections.by_customer.length && <p className="empty-state">No collections in the selected period.</p>}
            </div>
          </div>
          <div className="panel records-panel">
            <div className="panel-form-heading"><div><h2>Expenses by category and method</h2><p>Reversed expenses are excluded.</p></div></div>
            <div className="account-balance-list">
              {expenses.by_category.map((row) => <div key={`category-${row.category}`}><span>{row.category}</span><strong>{money(row.amount)}</strong><small>{row.count} expenses</small></div>)}
              {expenses.by_method.map((row) => <div key={`expense-method-${row.method}`}><span>{row.method.toUpperCase()}</span><strong>{money(row.amount)}</strong><small>{row.count} expenses</small></div>)}
              {!expenses.by_category.length && !expenses.by_method.length && <p className="empty-state">No expenses in the selected period.</p>}
            </div>
          </div>
          {selectedCustomer > 0 && (
            <div className="panel records-panel">
              <div className="panel-form-heading"><div><h2>Customer ledger{customerLedger ? ` · ${customerLedger.customer.name}` : ""}</h2><p>Opening balance {money(customerLedger?.opening_balance ?? "0")} · Closing balance {money(customerLedger?.closing_balance ?? "0")}</p></div></div>
              {!customerLedger?.results.length ? <div className="empty-state"><strong>No customer ledger entries</strong><span>Posted invoices, receipts, and allocations for this customer appear here.</span></div> : (
                <div className="table-scroll"><table className="records-table"><thead><tr><th>Date</th><th>Journal</th><th>Description</th><th>Account</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead><tbody>{customerLedger.results.map((line) => <tr key={line.id}><td>{line.date}</td><td>{line.journal_reference}</td><td>{line.description}</td><td>{line.account_name}</td><td>{money(line.debit)}</td><td>{money(line.credit)}</td><td>{money(line.running_balance)}</td></tr>)}</tbody></table></div>
              )}
            </div>
          )}
          <div className="panel records-panel">
            <div className="panel-form-heading"><div><h2>Posted journals</h2><p>Immutable entries and their balanced debit/credit lines.</p></div></div>
            {!journals?.results.length ? <div className="empty-state"><strong>No posted journal entries</strong><span>Invoices, receipts, allocations, and expenses post their journal entries here.</span></div> : <div className="journal-list">{journals.results.map((entry) => <details className="journal-entry" key={entry.id}>
              <summary><span><strong>{entry.reference}</strong><small>{entry.entry_date} · {entry.description}{entry.reverses ? " · Reversal" : ""}</small></span><span>Dr {money(entry.debit_total)} · Cr {money(entry.credit_total)}</span></summary>
              <div className="table-scroll"><table className="records-table"><thead><tr><th>Account</th><th>Debit</th><th>Credit</th></tr></thead><tbody>{entry.lines.map((line) => <tr key={line.id}><td>{line.account_name}</td><td>{line.debit !== "0.00" ? money(line.debit) : "—"}</td><td>{line.credit !== "0.00" ? money(line.credit) : "—"}</td></tr>)}</tbody></table></div>
            </details>)}</div>}
          </div>
          <div className="panel records-panel">
            <div className="panel-form-heading">
              <div><h2>Financial audit log</h2><p>Immutable transaction events for this organization.</p></div>
            </div>
            {!auditEvents?.results.length ? (
              <div className="empty-state"><strong>No financial events recorded</strong><span>Quotation, invoice, receipt, allocation, and expense actions will appear here.</span></div>
            ) : (
              <div className="table-scroll">
                <table className="records-table">
                  <thead><tr><th>When</th><th>Action</th><th>Record</th><th>Actor</th><th>Details</th></tr></thead>
                  <tbody>{auditEvents.results.map((event) => (
                    <tr key={event.id}>
                      <td>{new Date(event.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" })}</td>
                      <td>{event.action}</td>
                      <td>{event.reference}<span className="record-secondary">{event.entity_type} · #{event.entity_id}</span></td>
                      <td>{event.actor_name || event.actor_email}</td>
                      <td>{Object.keys(event.details).length ? JSON.stringify(event.details) : "—"}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
