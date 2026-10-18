import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  addServiceJobWorkNote,
  createServiceJob,
  deleteServiceJob,
  getContracts,
  getCustomers,
  getEquipment,
  getMembers,
  getServiceJobs,
  updateServiceJob,
  type Customer,
  type Equipment,
  type OrganizationMember,
  type Page,
  type ServiceJob,
  type ServiceJobInput,
  type ServiceJobStatus,
  type ServiceContract,
  type UserProfile,
} from "./api";

interface JobsPageProps {
  organizationId: number;
  user: UserProfile;
}

type JobForm = Omit<ServiceJobInput, "scheduled_for"> & {
  scheduled_for: string;
};

const emptyJob: JobForm = {
  customer: 0,
  equipment: null,
  assigned_technician: null,
  service_contract: null,
  title: "",
  description: "",
  status: "new",
  scheduled_for: "",
  technician_note: "",
  completion_report: "",
};

const statusLabels: Record<ServiceJobStatus, string> = {
  new: "New",
  scheduled: "Scheduled",
  in_progress: "In progress",
  completed: "Completed",
  cancelled: "Cancelled",
};

function JobsPage({ organizationId, user }: JobsPageProps) {
  const membership = user.organizations.find((item) => item.id === organizationId);
  const isTechnician = membership?.role === "technician";
  const canManage = membership?.role === "owner"
    || membership?.role === "admin"
    || membership?.role === "manager";
  const [page, setPage] = useState<Page<ServiceJob>>();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [technicians, setTechnicians] = useState<OrganizationMember[]>([]);
  const [contracts, setContracts] = useState<ServiceContract[]>([]);
  const [form, setForm] = useState<JobForm>(emptyJob);
  const [editing, setEditing] = useState<number>();
  const [showForm, setShowForm] = useState(false);
  const [statusFilter, setStatusFilter] = useState<ServiceJobStatus | "all">("all");
  const [search, setSearch] = useState("");
  const [scheduledFrom, setScheduledFrom] = useState("");
  const [scheduledTo, setScheduledTo] = useState("");
  const [technicianFilter, setTechnicianFilter] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [busy, setBusy] = useState(false);
  const [busyJob, setBusyJob] = useState<number>();
  const [workNoteDrafts, setWorkNoteDrafts] = useState<Record<number, string>>({});
  const [completionJob, setCompletionJob] = useState<number>();
  const [completionReportDraft, setCompletionReportDraft] = useState("");
  const [error, setError] = useState("");

  const loadJobs = useCallback(async () => {
    setPage(
      await getServiceJobs(
        organizationId,
        {
          status: statusFilter === "all" ? undefined : statusFilter,
          search,
          scheduled_from: scheduledFrom || undefined,
          scheduled_to: scheduledTo || undefined,
          technician: technicianFilter || undefined,
          page: pageNumber,
        },
      ),
    );
  }, [
    organizationId,
    pageNumber,
    scheduledFrom,
    scheduledTo,
    search,
    statusFilter,
    technicianFilter,
  ]);

  useEffect(() => {
    let active = true;
    const timeout = window.setTimeout(() => {
    Promise.all([
      getServiceJobs(organizationId, {
        status: statusFilter === "all" ? undefined : statusFilter,
        search,
        scheduled_from: scheduledFrom || undefined,
        scheduled_to: scheduledTo || undefined,
        technician: technicianFilter || undefined,
        page: pageNumber,
      }),
      getCustomers(organizationId),
      getEquipment(organizationId),
      getContracts(organizationId, "active"),
      isTechnician ? Promise.resolve(undefined) : getMembers(organizationId),
    ])
      .then(([jobs, customerPage, equipmentPage, contractPage, memberPage]) => {
        if (!active) return;
        setPage(jobs);
        setCustomers(customerPage.results);
        setEquipment(equipmentPage.results);
        setContracts(contractPage.results);
        setTechnicians(
          memberPage?.results.filter((member) => member.role === "technician") ?? [],
        );
      })
      .catch((reason: unknown) => {
        if (active) setError(messageFor(reason));
      });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [
    isTechnician,
    organizationId,
    pageNumber,
    scheduledFrom,
    scheduledTo,
    search,
    statusFilter,
    technicianFilter,
  ]);

  function startCreate() {
    setEditing(undefined);
    setForm({
      ...emptyJob,
      customer: customers[0]?.id ?? 0,
    });
    setError("");
    setShowForm(true);
  }

  function startEdit(job: ServiceJob) {
    setEditing(job.id);
    setForm({
      customer: job.customer,
      equipment: job.equipment,
      assigned_technician: job.assigned_technician,
      service_contract: job.service_contract,
      title: job.title,
      description: job.description,
      status: job.status,
      scheduled_for: toLocalDateTime(job.scheduled_for),
      technician_note: job.technician_note,
      completion_report: job.completion_report,
    });
    setError("");
    setShowForm(true);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const input: ServiceJobInput = {
        ...form,
        equipment: form.equipment || null,
        assigned_technician: form.assigned_technician || null,
        service_contract: form.service_contract || null,
        scheduled_for: form.scheduled_for
          ? new Date(form.scheduled_for).toISOString()
          : null,
      };
      if (editing === undefined) {
        await createServiceJob(organizationId, input);
      } else {
        await updateServiceJob(organizationId, editing, input);
      }
      setShowForm(false);
      setEditing(undefined);
      setPageNumber(1);
      await loadJobs();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function updateStatus(
    job: ServiceJob,
    status: ServiceJobStatus,
    completionReport = "",
  ): Promise<boolean> {
    setBusyJob(job.id);
    setError("");
    try {
      await updateServiceJob(organizationId, job.id, {
        status,
        technician_note: job.technician_note,
        completion_report: completionReport,
      });
      await loadJobs();
      return true;
    } catch (reason) {
      setError(messageFor(reason));
      return false;
    } finally {
      setBusyJob(undefined);
    }
  }

  async function addWorkNote(job: ServiceJob) {
    const note = workNoteDrafts[job.id]?.trim();
    if (!note) return;
    setBusyJob(job.id);
    setError("");
    try {
      await addServiceJobWorkNote(organizationId, job.id, note);
      setWorkNoteDrafts({ ...workNoteDrafts, [job.id]: "" });
      await loadJobs();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyJob(undefined);
    }
  }

  async function remove(job: ServiceJob) {
    if (!window.confirm(`Delete service job "${job.title}" and all service history?`)) return;
    setBusyJob(job.id);
    setError("");
    try {
      await deleteServiceJob(organizationId, job.id);
      await loadJobs();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyJob(undefined);
    }
  }

  const customerEquipment = equipment.filter(
    (item) => item.customer === form.customer,
  );
  const editingJobStatus = page?.results.find((job) => job.id === editing)?.status;
  const editableStatuses = editing === undefined
    ? ["new", "scheduled"] as const
    : editingJobStatus
      ? allowedTransitions(editingJobStatus, false)
      : ["new", "scheduled"] as const;

  return (
    <section className="workspace-page data-page">
      <div className="data-page-heading">
        <div>
          <div className="eyebrow">SERVICE OPERATIONS</div>
          <h1>Service jobs</h1>
          <p className="welcome-copy">
            Schedule work, assign technicians, and follow job progress.
            {page ? ` ${page.count} job${page.count === 1 ? "" : "s"}.` : ""}
          </p>
        </div>
        {canManage && (
          <button
            className="primary-button"
            disabled={customers.length === 0}
            onClick={startCreate}
            type="button"
          >
            Create service job
          </button>
        )}
      </div>

      {error && <div className="form-error page-alert" role="alert">{error}</div>}
      {canManage && customers.length === 0 && (
        <div className="inline-notice">
          Add a customer before creating a service job.
        </div>
      )}

      {showForm && (
        <form className="panel record-form" onSubmit={save}>
          <div className="panel-form-heading">
            <div>
              <h2>{editing === undefined ? "Create a service job" : "Edit service job"}</h2>
              <p>Schedule and assign the work for this organization.</p>
            </div>
            <button
              className="icon-button"
              onClick={() => setShowForm(false)}
              type="button"
              aria-label="Close service job form"
            >
              ×
            </button>
          </div>
          <div className="form-grid">
            <label className="field-wide">
              Job title
              <input
                maxLength={200}
                onChange={(event) => setForm({ ...form, title: event.target.value })}
                required
                value={form.title}
              />
            </label>
            <label>
              Customer
              <select
                onChange={(event) =>
                  setForm({
                    ...form,
                    customer: Number(event.target.value),
                    equipment: null,
                    service_contract: null,
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
              Equipment
              <select
                onChange={(event) =>
                  setForm({
                    ...form,
                    equipment: event.target.value ? Number(event.target.value) : null,
                  })
                }
                value={form.equipment ?? ""}
              >
                <option value="">No specific equipment</option>
                {customerEquipment.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}{item.serial_number ? ` · ${item.serial_number}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Assign technician
              <select
                onChange={(event) =>
                  setForm({
                    ...form,
                    assigned_technician: event.target.value
                      ? Number(event.target.value)
                      : null,
                  })
                }
                value={form.assigned_technician ?? ""}
              >
                <option value="">Unassigned</option>
                {technicians.map((technician) => (
                  <option key={technician.id} value={technician.id}>
                    {technician.name || technician.email}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Service contract
              <select
                onChange={(event) =>
                  setForm({
                    ...form,
                    service_contract: event.target.value
                      ? Number(event.target.value)
                      : null,
                  })
                }
                value={form.service_contract ?? ""}
              >
                <option value="">No contract coverage</option>
                {contracts
                  .filter((contract) => contract.customer === form.customer)
                  .map((contract) => (
                    <option key={contract.id} value={contract.id}>
                      {contract.contract_number}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Status
              <select
                onChange={(event) => {
                  const status = parseStatus(event.target.value);
                  if (status) setForm({ ...form, status });
                }}
                value={form.status}
              >
                {editableStatuses.map((status) => (
                  <option key={status} value={status}>{statusLabels[status]}</option>
                ))}
              </select>
            </label>
            <label>
              Scheduled for
              <input
                onChange={(event) => setForm({ ...form, scheduled_for: event.target.value })}
                type="datetime-local"
                value={form.scheduled_for}
              />
            </label>
            <label className="field-wide">
              Work description
              <textarea
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                rows={3}
                value={form.description}
              />
            </label>
            <label className="field-wide">
              Work notes
              <textarea
                maxLength={10000}
                onChange={(event) =>
                  setForm({ ...form, technician_note: event.target.value })
                }
                placeholder="Internal work notes"
                rows={2}
                value={form.technician_note}
              />
            </label>
            {form.status === "completed" && (
              <label className="field-wide">
                Completion report
                <textarea
                  maxLength={10000}
                  onChange={(event) =>
                    setForm({ ...form, completion_report: event.target.value })
                  }
                  required
                  rows={3}
                  value={form.completion_report}
                />
              </label>
            )}
          </div>
          <div className="form-actions">
            <button className="secondary-button" onClick={() => setShowForm(false)} type="button">
              Cancel
            </button>
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? "Saving…" : editing === undefined ? "Create job" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      <div className="jobs-toolbar">
        <label>
          Search jobs
          <input
            onChange={(event) => {
              setSearch(event.target.value);
              setPageNumber(1);
            }}
            placeholder="Job, customer, equipment, serial"
            type="search"
            value={search}
          />
        </label>
        <label>
          Status
          <select
            onChange={(event) => {
              const value = event.target.value;
              setStatusFilter(value === "all" ? "all" : parseStatus(value) ?? "all");
              setPageNumber(1);
            }}
            value={statusFilter}
          >
            <option value="all">All jobs</option>
            {(["new", "scheduled", "in_progress", "completed", "cancelled"] as const).map((status) => (
              <option key={status} value={status}>{statusLabels[status]}</option>
            ))}
          </select>
        </label>
        <label>
          Scheduled from
          <input
            onChange={(event) => {
              setScheduledFrom(event.target.value);
              setPageNumber(1);
            }}
            type="date"
            value={scheduledFrom}
          />
        </label>
        <label>
          Scheduled to
          <input
            onChange={(event) => {
              setScheduledTo(event.target.value);
              setPageNumber(1);
            }}
            type="date"
            value={scheduledTo}
          />
        </label>
        {canManage && (
          <label>
            Technician
            <select
              onChange={(event) => {
                setTechnicianFilter(Number(event.target.value));
                setPageNumber(1);
              }}
              value={technicianFilter}
            >
              <option value={0}>All technicians</option>
              {technicians.map((technician) => (
                <option key={technician.id} value={technician.id}>
                  {technician.name || technician.email}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="job-card-list">
        {!page ? (
          <div className="panel empty-state">Loading service jobs…</div>
        ) : page.results.length === 0 ? (
          <div className="panel empty-state">
            <span className="empty-icon" aria-hidden="true">↗</span>
            <strong>No service jobs match these filters</strong>
            <span>Adjust the search or filters, or create a job for this organization.</span>
            {canManage && customers.length > 0 && (
              <button className="secondary-button" onClick={startCreate} type="button">
                Create the first job
              </button>
            )}
          </div>
        ) : page.results.map((job) => {
          const assignedToCurrentUser =
            job.assigned_technician === membership?.membership_id;
          const canUpdate = canManage || (isTechnician && assignedToCurrentUser);
          const timeline = [
            ...job.status_history.map((entry) => ({
              kind: "status" as const,
              id: entry.id,
              timestamp: entry.changed_at,
              heading: entry.previous_status
                ? statusLabels[entry.status]
                : `Created as ${statusLabels[entry.status]}`,
              actor: entry.changed_by_name || "Team member",
              note: entry.note,
            })),
            ...job.work_notes.map((entry) => ({
              kind: "note" as const,
              id: entry.id,
              timestamp: entry.created_at,
              heading: "Work note",
              actor: entry.created_by_name || "Team member",
              note: entry.note,
            })),
          ].sort(
            (left, right) =>
              new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime(),
          );
          return (
            <article className="panel job-card" key={job.id}>
              <div className="job-card-heading">
                <div>
                  <div className="panel-kicker">
                    {job.service_contract_number
                      ? `AMC · ${job.service_contract_number}`
                      : `JOB #${job.id}`}
                  </div>
                  <h2>{job.title}</h2>
                  <p>{job.customer_name}{job.equipment_name ? ` · ${job.equipment_name}` : ""}</p>
                </div>
                {canUpdate ? (
                  <select
                    aria-label={`Status for ${job.title}`}
                    className={`job-status status-${job.status}`}
                    disabled={busyJob === job.id}
                    onChange={(event) => {
                      const nextStatus = parseStatus(event.target.value);
                      if (!nextStatus || nextStatus === job.status) return;
                      if (nextStatus === "completed") {
                        setCompletionJob(job.id);
                        setCompletionReportDraft(job.completion_report);
                        return;
                      }
                      void updateStatus(job, nextStatus);
                    }}
                    value={job.status}
                  >
                    {allowedTransitions(job.status, isTechnician && !canManage).map((status) => (
                      <option key={status} value={status}>{statusLabels[status]}</option>
                    ))}
                  </select>
                ) : (
                  <span className={`job-status-label status-${job.status}`}>
                    {statusLabels[job.status]}
                  </span>
                )}
              </div>
              {job.description && <p className="job-card-description">{job.description}</p>}
              <dl className="job-card-facts">
                <div>
                  <dt>Assigned technician</dt>
                  <dd>{job.assigned_technician_name || job.assigned_technician_email || "Unassigned"}</dd>
                </div>
                <div>
                  <dt>Scheduled</dt>
                  <dd>{formatSchedule(job.scheduled_for)}</dd>
                </div>
              </dl>
              {job.status === "completed" && job.completion_report && (
                <div className="job-report">
                  <strong>Completion report</strong>
                  <p>{job.completion_report}</p>
                </div>
              )}
              {completionJob === job.id && (
                <div className="job-report-editor">
                  <label>
                    Completion report
                    <textarea
                      maxLength={10000}
                      onChange={(event) => setCompletionReportDraft(event.target.value)}
                      required
                      rows={3}
                      value={completionReportDraft}
                    />
                  </label>
                  <div className="form-actions">
                    <button
                      className="secondary-button"
                      onClick={() => setCompletionJob(undefined)}
                      type="button"
                    >
                      Cancel
                    </button>
                    <button
                      className="primary-button"
                      disabled={busyJob === job.id || !completionReportDraft.trim()}
                      onClick={() => {
                        void updateStatus(job, "completed", completionReportDraft.trim())
                          .then((saved) => {
                            if (saved) {
                              setCompletionJob(undefined);
                              setCompletionReportDraft("");
                            }
                          });
                      }}
                      type="button"
                    >
                      {busyJob === job.id ? "Saving…" : "Complete job"}
                    </button>
                  </div>
                </div>
              )}
              {canUpdate && job.status !== "completed" && job.status !== "cancelled" && (
                <form
                  className="job-note-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void addWorkNote(job);
                  }}
                >
                  <label>
                    Add work note
                    <textarea
                      maxLength={5000}
                      onChange={(event) =>
                        setWorkNoteDrafts({
                          ...workNoteDrafts,
                          [job.id]: event.target.value,
                        })
                      }
                      placeholder="Record findings or work performed"
                      rows={2}
                      value={workNoteDrafts[job.id] ?? ""}
                    />
                  </label>
                  <button
                    className="secondary-button"
                    disabled={busyJob === job.id || !workNoteDrafts[job.id]?.trim()}
                    type="submit"
                  >
                    Add note
                  </button>
                </form>
              )}
              <div className="job-card-footer">
                <details className="job-history">
                  <summary>
                    Service history · {job.status_history.length} status update{job.status_history.length === 1 ? "" : "s"} · {job.work_notes.length} work note{job.work_notes.length === 1 ? "" : "s"}
                  </summary>
                  <ol>
                    {timeline.map((entry) => (
                      <li key={`${entry.kind}-${entry.id}`}>
                        <strong>{entry.heading}</strong>
                        <span>{entry.actor} · {new Date(entry.timestamp).toLocaleString("en-IN")}</span>
                        {entry.note && <span>{entry.note}</span>}
                      </li>
                    ))}
                  </ol>
                </details>
                {canManage && (
                  <div className="record-actions">
                    <button className="table-action" onClick={() => startEdit(job)} type="button">
                      Edit
                    </button>
                    <button
                      className="table-action table-danger"
                      disabled={busyJob === job.id}
                      onClick={() => void remove(job)}
                      type="button"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {page && page.count > 50 && (
        <div className="pagination-controls">
          <span>Page {pageNumber} of {Math.ceil(page.count / 50)}</span>
          <div>
            <button
              className="secondary-button"
              disabled={pageNumber <= 1}
              onClick={() => setPageNumber((current) => current - 1)}
              type="button"
            >
              Previous
            </button>
            <button
              className="secondary-button"
              disabled={pageNumber >= Math.ceil(page.count / 50)}
              onClick={() => setPageNumber((current) => current + 1)}
              type="button"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function allowedTransitions(
  current: ServiceJobStatus,
  technician: boolean,
): ServiceJobStatus[] {
  const transitions: Record<ServiceJobStatus, ServiceJobStatus[]> = {
    new: technician ? ["new"] : ["new", "scheduled", "cancelled"],
    scheduled: technician
      ? ["scheduled", "in_progress"]
      : ["scheduled", "in_progress", "cancelled"],
    in_progress: technician
      ? ["in_progress", "completed"]
      : ["in_progress", "completed", "cancelled"],
    completed: ["completed"],
    cancelled: ["cancelled"],
  };
  return transitions[current];
}

function parseStatus(value: string): ServiceJobStatus | undefined {
  if (
    value === "new"
    || value === "scheduled"
    || value === "in_progress"
    || value === "completed"
    || value === "cancelled"
  ) {
    return value;
  }
  return undefined;
}

function toLocalDateTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function formatSchedule(value: string | null): string {
  if (!value) return "Not scheduled";
  return new Date(value).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function messageFor(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return "Could not complete the service job request. Check your connection and try again.";
}

export default JobsPage;
