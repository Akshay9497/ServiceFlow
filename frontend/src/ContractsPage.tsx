import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  createContract,
  getContractReminders,
  getContracts,
  getCustomers,
  getEquipment,
  getUpcomingRenewals,
  renewContract,
  updateContract,
  type ContractRenewalReminder,
  type Customer,
  type Equipment,
  type Page,
  type ServiceContract,
  type ServiceContractInput,
  type ServiceContractStatus,
} from "./api";

interface ContractsPageProps {
  organizationId: number;
  canWrite: boolean;
  canRenew: boolean;
}

type ContractForm = Omit<ServiceContractInput, "reminder_days"> & {
  reminder_days: string;
};

const emptyForm: ContractForm = {
  customer: 0,
  covered_equipment: [],
  contract_type: "comprehensive",
  start_date: "",
  end_date: "",
  contract_value: "",
  included_visits: 4,
  visit_frequency: "quarterly",
  payment_terms: "",
  terms_and_conditions: "",
  renewal_reminders_enabled: true,
  reminder_days: "30, 7, 1",
  status: "draft",
};

const statusLabels: Record<ServiceContractStatus, string> = {
  draft: "Draft",
  active: "Active",
  expired: "Expired",
  cancelled: "Cancelled",
};

const typeLabels: Record<ServiceContractInput["contract_type"], string> = {
  comprehensive: "Comprehensive",
  non_comprehensive: "Non-comprehensive",
  labour_only: "Labour only",
  custom: "Custom",
};

function ContractsPage({
  organizationId,
  canWrite,
  canRenew,
}: ContractsPageProps) {
  const [page, setPage] = useState<Page<ServiceContract>>();
  const [upcoming, setUpcoming] = useState<ServiceContract[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [filter, setFilter] = useState<ServiceContractStatus | "all">("all");
  const [form, setForm] = useState<ContractForm>(emptyForm);
  const [editing, setEditing] = useState<number>();
  const [renewing, setRenewing] = useState<ServiceContract>();
  const [renewalDates, setRenewalDates] = useState({ start_date: "", end_date: "", contract_value: "" });
  const [reminders, setReminders] = useState<Record<number, ContractRenewalReminder[]>>({});
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadContracts = useCallback(async () => {
    const result = await getContracts(
      organizationId,
      filter === "all" ? undefined : filter,
    );
    setPage(result);
  }, [filter, organizationId]);

  useEffect(() => {
    let active = true;
    Promise.all([
      getContracts(organizationId, filter === "all" ? undefined : filter),
      getUpcomingRenewals(organizationId, 30),
      getCustomers(organizationId),
      getEquipment(organizationId),
    ])
      .then(([contracts, due, customerPage, equipmentPage]) => {
        if (!active) return;
        setPage(contracts);
        setUpcoming(due.results);
        setCustomers(customerPage.results);
        setEquipment(equipmentPage.results);
      })
      .catch((reason: unknown) => {
        if (active) setError(messageFor(reason));
      });
    return () => {
      active = false;
    };
  }, [filter, organizationId]);

  function startCreate() {
    setEditing(undefined);
    setRenewing(undefined);
    setForm({
      ...emptyForm,
      customer: customers[0]?.id ?? 0,
      start_date: currentBusinessDate(),
      end_date: "",
    });
    setError("");
    setShowForm(true);
  }

  function startEdit(contract: ServiceContract) {
    setEditing(contract.id);
    setRenewing(undefined);
    setForm({
      customer: contract.customer,
      covered_equipment: contract.covered_equipment,
      contract_type: contract.contract_type,
      start_date: contract.start_date,
      end_date: contract.end_date,
      contract_value: contract.contract_value,
      included_visits: contract.included_visits,
      visit_frequency: contract.visit_frequency,
      payment_terms: contract.payment_terms,
      terms_and_conditions: contract.terms_and_conditions,
      renewal_reminders_enabled: contract.renewal_reminders_enabled,
      reminder_days: contract.reminder_days.join(", "),
      status: contract.status,
    });
    setError("");
    setShowForm(true);
  }

  function startRenewal(contract: ServiceContract) {
    const startDate = addDays(contract.end_date, 1);
    setRenewing(contract);
    setEditing(undefined);
    setRenewalDates({
      start_date: startDate,
      end_date: addYears(startDate, 1),
      contract_value: contract.contract_value,
    });
    setError("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const reminderDays = form.reminder_days
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean)
      .map(Number);
    if (reminderDays.some((value) => !Number.isInteger(value))) {
      setError("Enter reminder intervals as whole numbers separated by commas.");
      setBusy(false);
      return;
    }

    const input: ServiceContractInput = {
      ...form,
      reminder_days: reminderDays,
      contract_value: form.contract_value,
    };
    try {
      if (editing === undefined) {
        await createContract(organizationId, input);
      } else {
        await updateContract(organizationId, editing, input);
      }
      setShowForm(false);
      setEditing(undefined);
      await loadContracts();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function saveRenewal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!renewing) return;
    setBusy(true);
    setError("");
    try {
      await renewContract(organizationId, renewing.id, renewalDates);
      setRenewing(undefined);
      await loadContracts();
      setUpcoming((await getUpcomingRenewals(organizationId)).results);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(contract: ServiceContract, status: ServiceContractStatus) {
    setBusy(true);
    setError("");
    try {
      await updateContract(organizationId, contract.id, { status });
      await loadContracts();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function toggleReminders(contract: ServiceContract) {
    setBusy(true);
    setError("");
    try {
      const days = contract.reminder_days.length ? contract.reminder_days : [30, 7, 1];
      await updateContract(organizationId, contract.id, {
        renewal_reminders_enabled: !contract.renewal_reminders_enabled,
        reminder_days: days,
      });
      await loadContracts();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function toggleReminderHistory(contractId: number) {
    if (reminders[contractId]) {
      setReminders((current) => {
        const next = { ...current };
        delete next[contractId];
        return next;
      });
      return;
    }
    setError("");
    try {
      const history = await getContractReminders(organizationId, contractId);
      setReminders((current) => ({ ...current, [contractId]: history }));
    } catch (reason) {
      setError(messageFor(reason));
    }
  }

  const customerEquipment = equipment.filter((item) => item.customer === form.customer);
  const expiredCount = page?.results.filter(
    (contract) => contract.status === "active" && contract.days_until_expiry < 0,
  ).length ?? 0;

  return (
    <section className="workspace-page data-page">
      <div className="data-page-heading">
        <div>
          <div className="eyebrow">RECURRING SERVICE COVERAGE</div>
          <h1>Service contracts</h1>
          <p className="welcome-copy">
            Manage AMCs, covered equipment, included visits, and renewals.
          </p>
        </div>
        {canWrite && (
          <button
            className="primary-button"
            disabled={customers.length === 0}
            onClick={startCreate}
            type="button"
          >
            Add contract
          </button>
        )}
      </div>

      {error && <div className="form-error page-alert" role="alert">{error}</div>}
      {upcoming.length > 0 && (
        <div className="renewal-notice" role="status">
          <strong>{upcoming.length} upcoming renewal{upcoming.length === 1 ? "" : "s"}</strong>
          <span> within the next 30 days.</span>
          {expiredCount > 0 && <span> {expiredCount} active contract{expiredCount === 1 ? "" : "s"} past its end date need review.</span>}
        </div>
      )}
      {upcoming.length === 0 && expiredCount > 0 && (
        <div className="renewal-notice renewal-warning" role="status">
          <strong>{expiredCount} active contract{expiredCount === 1 ? "" : "s"} past its end date need review.</strong>
        </div>
      )}

      {showForm && (
        <form className="panel record-form" onSubmit={save}>
          <div className="panel-form-heading">
            <div>
              <h2>{editing === undefined ? "Create service contract" : "Edit service contract"}</h2>
              <p>Contract numbers are assigned by the organization.</p>
            </div>
            <button className="icon-button" onClick={() => setShowForm(false)} type="button" aria-label="Close form">×</button>
          </div>
          <div className="form-grid">
            <label>
              Customer
              <select
                onChange={(event) =>
                  setForm({
                    ...form,
                    customer: Number(event.target.value),
                    covered_equipment: [],
                  })
                }
                required
                value={form.customer || ""}
              >
                <option disabled value="">Choose a customer</option>
                {customers.map((customer) => (
                  <option key={customer.id} value={customer.id}>{customer.name}</option>
                ))}
              </select>
            </label>
            <label>
              Contract type
              <select
                onChange={(event) => {
                  const value = parseContractType(event.target.value);
                  if (value) setForm({ ...form, contract_type: value });
                }}
                value={form.contract_type}
              >
                {Object.entries(typeLabels).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="field-wide">
              Covered equipment
              <select
                multiple
                onChange={(event) =>
                  setForm({
                    ...form,
                    covered_equipment: Array.from(
                      event.target.selectedOptions,
                      (option) => Number(option.value),
                    ),
                  })
                }
                size={Math.min(4, Math.max(2, customerEquipment.length))}
                value={form.covered_equipment.map(String)}
              >
                {customerEquipment.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}{item.serial_number ? ` · ${item.serial_number}` : ""}
                  </option>
                ))}
              </select>
              <span className="field-hint">
                Leave all unselected to cover all of this customer's equipment.
              </span>
            </label>
            <label>
              Start date
              <input
                onChange={(event) => setForm({ ...form, start_date: event.target.value })}
                required
                type="date"
                value={form.start_date}
              />
            </label>
            <label>
              End date
              <input
                onChange={(event) => setForm({ ...form, end_date: event.target.value })}
                required
                type="date"
                value={form.end_date}
              />
            </label>
            <label>
              Contract value (INR)
              <input
                min="0.01"
                onChange={(event) => setForm({ ...form, contract_value: event.target.value })}
                required
                step="0.01"
                type="number"
                value={form.contract_value}
              />
            </label>
            <label>
              Included visits
              <input
                max="999"
                min="1"
                onChange={(event) =>
                  setForm({ ...form, included_visits: Number(event.target.value) })
                }
                required
                type="number"
                value={form.included_visits}
              />
            </label>
            <label>
              Visit frequency
              <select
                onChange={(event) => {
                  const value = parseVisitFrequency(event.target.value);
                  if (value) setForm({ ...form, visit_frequency: value });
                }}
                value={form.visit_frequency}
              >
                <option value="monthly">Monthly</option>
                <option value="quarterly">Quarterly</option>
                <option value="half_yearly">Half-yearly</option>
                <option value="annual">Annual</option>
                <option value="custom">Custom</option>
              </select>
            </label>
            <label>
              Payment terms
              <input
                maxLength={500}
                onChange={(event) => setForm({ ...form, payment_terms: event.target.value })}
                value={form.payment_terms}
              />
            </label>
            <label className="field-wide">
              Terms and conditions
              <textarea
                onChange={(event) =>
                  setForm({ ...form, terms_and_conditions: event.target.value })
                }
                rows={3}
                value={form.terms_and_conditions}
              />
            </label>
            <label>
              Renewal reminders (days before end)
              <input
                onChange={(event) => setForm({ ...form, reminder_days: event.target.value })}
                placeholder="30, 7, 1"
                value={form.reminder_days}
              />
            </label>
            <label className="checkbox-label">
              <input
                checked={form.renewal_reminders_enabled}
                onChange={(event) =>
                  setForm({ ...form, renewal_reminders_enabled: event.target.checked })
                }
                type="checkbox"
              />
              Send renewal reminders to customer email
            </label>
            <label>
              Contract status
              <select
                onChange={(event) => {
                  const value = parseStatus(event.target.value);
                  if (value) setForm({ ...form, status: value });
                }}
                value={form.status}
              >
                <option value="draft">Draft</option>
                <option value="active">Active</option>
              </select>
            </label>
          </div>
          <div className="form-actions">
            <button className="secondary-button" onClick={() => setShowForm(false)} type="button">Cancel</button>
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? "Saving…" : editing === undefined ? "Create contract" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      {renewing && (
        <form className="panel record-form" onSubmit={saveRenewal}>
          <div className="panel-form-heading">
            <div>
              <h2>Prepare renewal for {renewing.contract_number}</h2>
              <p>This creates a draft renewal. The existing contract is not automatically extended.</p>
            </div>
            <button className="icon-button" onClick={() => setRenewing(undefined)} type="button" aria-label="Close renewal form">×</button>
          </div>
          <div className="form-grid">
            <label>
              Renewal start
              <input
                onChange={(event) => setRenewalDates({ ...renewalDates, start_date: event.target.value })}
                required
                type="date"
                value={renewalDates.start_date}
              />
            </label>
            <label>
              Renewal end
              <input
                onChange={(event) => setRenewalDates({ ...renewalDates, end_date: event.target.value })}
                required
                type="date"
                value={renewalDates.end_date}
              />
            </label>
            <label>
              Renewal value (INR)
              <input
                min="0.01"
                onChange={(event) =>
                  setRenewalDates({ ...renewalDates, contract_value: event.target.value })
                }
                required
                step="0.01"
                type="number"
                value={renewalDates.contract_value}
              />
            </label>
          </div>
          <div className="form-actions">
            <button className="secondary-button" onClick={() => setRenewing(undefined)} type="button">Cancel</button>
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? "Preparing…" : "Create draft renewal"}
            </button>
          </div>
        </form>
      )}

      <div className="contracts-toolbar">
        <span>{page ? `${page.count} contract${page.count === 1 ? "" : "s"}` : "Loading contracts…"}</span>
        <label>
          Status
          <select
            onChange={(event) => {
              const value = event.target.value;
              setFilter(value === "all" ? "all" : parseStatus(value) ?? "all");
            }}
            value={filter}
          >
            <option value="all">All contracts</option>
            {Object.entries(statusLabels).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
      </div>

      {!page ? (
        <div className="panel records-panel"><p className="empty-state">Loading service contracts…</p></div>
      ) : page.results.length === 0 ? (
        <div className="panel records-panel">
          <div className="empty-state">
            <span className="empty-icon" aria-hidden="true">◷</span>
            <strong>No service contracts {filter === "all" ? "yet" : `with ${statusLabels[filter].toLowerCase()} status`}</strong>
            <span>Create a contract to track coverage, included visits, and renewal dates.</span>
            {canWrite && customers.length > 0 && (
              <button className="secondary-button" onClick={startCreate} type="button">Create your first contract</button>
            )}
          </div>
        </div>
      ) : (
        <div className="contract-list">
          {page.results.map((contract) => {
            const expired = contract.status === "active" && contract.days_until_expiry < 0;
            const daysText = contract.days_until_expiry < 0
              ? `Expired ${Math.abs(contract.days_until_expiry)} days ago`
              : contract.days_until_expiry === 0
                ? "Expires today"
                : `Expires in ${contract.days_until_expiry} days`;
            const canEditTerms = canWrite && contract.status === "draft";
            return (
              <article className="panel contract-card" key={contract.id}>
                <div className="contract-main">
                  <div className="contract-heading">
                    <div>
                      <span className="contract-number">{contract.contract_number}</span>
                      <h2>{contract.customer_name}</h2>
                    </div>
                    <span className={`contract-status status-${contract.status}`}>
                      {statusLabels[contract.status]}
                    </span>
                  </div>
                  <div className="contract-type">{typeLabels[contract.contract_type]}</div>
                  <div className="contract-details-grid">
                    <div><span>Coverage</span><strong>{contract.covered_equipment_names.length ? contract.covered_equipment_names.join(", ") : "All customer equipment"}</strong></div>
                    <div><span>Contract period</span><strong>{formatDate(contract.start_date)} – {formatDate(contract.end_date)}</strong></div>
                    <div><span>Contract value</span><strong>{formatINR(contract.contract_value)}</strong></div>
                    <div>
                      <span>Included visits</span>
                      <strong>{contract.visits_consumed} used · {contract.visits_remaining} remaining of {contract.included_visits}</strong>
                    </div>
                  </div>
                  <div className={`contract-expiry${expired ? " contract-expired" : ""}`}>
                    {daysText}
                    {contract.renewal_contract_number && (
                      <span> · Renewal draft {contract.renewal_contract_number}</span>
                    )}
                    {contract.renewed_from_number && (
                      <span> · Renewed from {contract.renewed_from_number}</span>
                    )}
                  </div>
                  {contract.visit_history.length > 0 && (
                    <details className="contract-visit-history">
                      <summary>Visit history ({contract.visit_history.length})</summary>
                      <ul>
                        {contract.visit_history.map((visit) => (
                          <li key={visit.id}>
                            {visit.job_title} · {visit.job_status} · {formatDateTime(visit.recorded_at)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {reminders[contract.id] && (
                    <div className="contract-reminder-history">
                      <strong>Reminder delivery history</strong>
                      {reminders[contract.id].length === 0 ? (
                        <span>No reminders attempted.</span>
                      ) : reminders[contract.id].map((reminder) => (
                        <div className="contract-reminder-entry" key={reminder.id}>
                          {reminder.days_before_expiry} days before expiry · {reminder.status}
                          {reminder.sent_at ? ` · ${formatDateTime(reminder.sent_at)}` : ""}
                          <ul>
                            {reminder.attempt_history.map((attempt) => (
                              <li key={attempt.attempt_number}>
                                Attempt {attempt.attempt_number} · {attempt.status}
                                {attempt.attempted_at ? ` · ${formatDateTime(attempt.attempted_at)}` : ""}
                                {attempt.recipient ? ` · ${attempt.recipient}` : ""}
                                {attempt.detail ? ` · ${attempt.detail}` : ""}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="contract-actions">
                  {canEditTerms && (
                    <button className="table-action" onClick={() => startEdit(contract)} type="button">Edit</button>
                  )}
                  {canWrite && contract.status === "draft" && (
                    <button className="table-action" disabled={busy} onClick={() => void changeStatus(contract, "active")} type="button">Activate</button>
                  )}
                  {canWrite && contract.status === "active" && (
                    <button className="table-action table-danger" disabled={busy} onClick={() => void changeStatus(contract, "cancelled")} type="button">Cancel</button>
                  )}
                  {canRenew && (contract.status === "active" || contract.status === "expired") && !contract.renewal_contract_number && (
                    <button className="secondary-button" onClick={() => startRenewal(contract)} type="button">Prepare renewal</button>
                  )}
                  <button className="table-action" onClick={() => void toggleReminders(contract)} type="button">
                    {contract.renewal_reminders_enabled ? "Pause reminders" : "Enable reminders"}
                  </button>
                  <button className="table-action" onClick={() => void toggleReminderHistory(contract.id)} type="button">
                    {reminders[contract.id] ? "Hide reminders" : "Reminder history"}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function parseStatus(value: string): ServiceContractStatus | undefined {
  if (value === "draft" || value === "active" || value === "expired" || value === "cancelled") {
    return value;
  }
  return undefined;
}

function parseContractType(value: string): ServiceContractInput["contract_type"] | undefined {
  if (value === "comprehensive" || value === "non_comprehensive" || value === "labour_only" || value === "custom") {
    return value;
  }
  return undefined;
}

function parseVisitFrequency(value: string): ServiceContractInput["visit_frequency"] | undefined {
  if (value === "monthly" || value === "quarterly" || value === "half_yearly" || value === "annual" || value === "custom") {
    return value;
  }
  return undefined;
}

function addDays(dateValue: string, days: number): string {
  const date = parseDateOnly(dateValue);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function addYears(dateValue: string, years: number): string {
  const date = parseDateOnly(dateValue);
  const month = date.getUTCMonth();
  date.setUTCFullYear(date.getUTCFullYear() + years);
  if (date.getUTCMonth() !== month) date.setUTCDate(0);
  return date.toISOString().slice(0, 10);
}

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-IN", {
    dateStyle: "medium",
    timeZone: "Asia/Kolkata",
  });
}

function parseDateOnly(value: string): Date {
  return new Date(`${value}T00:00:00Z`);
}

function currentBusinessDate(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Asia/Kolkata",
    year: "numeric",
  }).formatToParts(new Date());
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  });
}

function formatINR(value: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function messageFor(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return "Could not complete the contract request. Check your connection and try again.";
}

export default ContractsPage;
