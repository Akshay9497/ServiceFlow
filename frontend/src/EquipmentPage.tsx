import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  createEquipment,
  deleteEquipment,
  getCustomers,
  getEquipment,
  updateEquipment,
  type Customer,
  type Equipment,
  type Page,
} from "./api";

interface EquipmentPageProps {
  organizationId: number;
  canWrite: boolean;
  onManageCustomers: () => void;
}

type EquipmentInput = Pick<
  Equipment,
  | "customer"
  | "name"
  | "manufacturer"
  | "model_number"
  | "serial_number"
  | "installed_at"
  | "warranty_expires_at"
  | "notes"
>;

const emptyEquipment: EquipmentInput = {
  customer: 0,
  name: "",
  manufacturer: "",
  model_number: "",
  serial_number: "",
  installed_at: null,
  warranty_expires_at: null,
  notes: "",
};

function EquipmentPage({
  organizationId,
  canWrite,
  onManageCustomers,
}: EquipmentPageProps) {
  const [page, setPage] = useState<Page<Equipment>>();
  const [pageNumber, setPageNumber] = useState(1);
  const [search, setSearch] = useState("");
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerCount, setCustomerCount] = useState(0);
  const [customerLoading, setCustomerLoading] = useState(true);
  const [customerSearch, setCustomerSearch] = useState("");
  const [selectedCustomer, setSelectedCustomer] = useState<{
    id: number;
    name: string;
  }>();
  const [form, setForm] = useState<EquipmentInput>(emptyEquipment);
  const [editing, setEditing] = useState<number>();
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadEquipment = useCallback(async (targetPage = pageNumber) => {
    setPage(await getEquipment(organizationId, { page: targetPage, search }));
  }, [organizationId, pageNumber, search]);

  useEffect(() => {
    let active = true;
    const timeout = window.setTimeout(() => {
      getEquipment(organizationId, { page: pageNumber, search })
        .then((equipment) => {
          if (!active) return;
          setPage(equipment);
        })
        .catch((reason: unknown) => {
          if (active) setError(messageFor(reason));
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [organizationId, pageNumber, search]);

  useEffect(() => {
    let active = true;
    setCustomerLoading(true);
    const timeout = window.setTimeout(() => {
      getCustomers(organizationId, { search: customerSearch })
        .then((customerPage) => {
          if (!active) return;
          setCustomers(customerPage.results);
          if (!customerSearch.trim()) setCustomerCount(customerPage.count);
        })
        .catch((reason: unknown) => {
          if (active) setError(messageFor(reason));
        })
        .finally(() => {
          if (active) setCustomerLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [organizationId, customerSearch]);

  function startCreate() {
    setEditing(undefined);
    setSelectedCustomer(undefined);
    setForm({
      ...emptyEquipment,
      customer: 0,
    });
    setCustomerSearch("");
    setError("");
    setShowForm(true);
  }

  function startEdit(equipment: Equipment) {
    setEditing(equipment.id);
    setSelectedCustomer({
      id: equipment.customer,
      name: equipment.customer_name,
    });
    setForm({
      customer: equipment.customer,
      name: equipment.name,
      manufacturer: equipment.manufacturer,
      model_number: equipment.model_number,
      serial_number: equipment.serial_number,
      installed_at: equipment.installed_at,
      warranty_expires_at: equipment.warranty_expires_at,
      notes: equipment.notes,
    });
    setCustomerSearch("");
    setError("");
    setShowForm(true);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const input = {
        ...form,
        installed_at: form.installed_at || null,
        warranty_expires_at: form.warranty_expires_at || null,
      };
      if (editing === undefined) {
        await createEquipment(organizationId, input);
      } else {
        await updateEquipment(organizationId, editing, input);
      }
      setShowForm(false);
      setEditing(undefined);
      setPageNumber(1);
      await loadEquipment(1);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function remove(equipment: Equipment) {
    if (!window.confirm(`Delete ${equipment.name}?`)) return;
    setError("");
    try {
      await deleteEquipment(organizationId, equipment.id);
      setPageNumber(1);
      await loadEquipment(1);
    } catch (reason) {
      setError(messageFor(reason));
    }
  }

  return (
    <section className="workspace-page data-page">
      <div className="data-page-heading">
        <div>
          <div className="eyebrow">ASSETS UNDER YOUR CARE</div>
          <h1>Equipment</h1>
          <p className="welcome-copy">
            Equipment records linked to customers.
            {page
              ? ` ${page.count} ${search ? "matching" : "total"}.`
              : ""}
          </p>
        </div>
        <div className="data-page-actions">
          <label className="record-search-label">
            <span className="visually-hidden">Search equipment</span>
            <input
              aria-label="Search equipment"
              className="record-search"
              onChange={(event) => {
                setSearch(event.target.value);
                setPageNumber(1);
                setError("");
              }}
              placeholder="Search equipment"
              type="search"
              value={search}
            />
          </label>
          {canWrite && (
            <button
              className="primary-button"
              disabled={customerLoading || customerCount === 0}
              onClick={startCreate}
              type="button"
            >
              Add equipment
            </button>
          )}
        </div>
      </div>

      {error && <div className="form-error page-alert" role="alert">{error}</div>}
      {customerLoading && page && (
        <div className="inline-notice">Checking customer records…</div>
      )}
      {!customerLoading && customerCount === 0 && page && (
        <div className="inline-notice">
          Add a customer before registering their equipment.{" "}
          <button className="text-button" onClick={onManageCustomers} type="button">
            Go to customers
          </button>
        </div>
      )}

      {showForm && (
        <form className="panel record-form" onSubmit={save}>
          <div className="panel-form-heading">
            <h2>{editing === undefined ? "Add equipment" : "Edit equipment"}</h2>
            <button
              className="icon-button"
              onClick={() => setShowForm(false)}
              type="button"
              aria-label="Close equipment form"
            >
              ×
            </button>
          </div>
          <div className="form-grid">
            <label className="field-wide">
              Search customers
              <input
                autoComplete="off"
                onChange={(event) => setCustomerSearch(event.target.value)}
                placeholder="Search by customer name, phone, or email"
                value={customerSearch}
              />
            </label>
            <label className="field-wide">
              Customer
              <select
                onChange={(event) => {
                  const customerId = Number(event.target.value);
                  const customer = customers.find((item) => item.id === customerId);
                  setForm({ ...form, customer: customerId });
                  if (customer) {
                    setSelectedCustomer({ id: customer.id, name: customer.name });
                  }
                }}
                required
                value={form.customer || ""}
              >
                <option disabled value="">Choose a customer</option>
                {selectedCustomer
                  && !customers.some((item) => item.id === selectedCustomer.id) && (
                  <option value={selectedCustomer.id}>
                    {selectedCustomer.name}
                  </option>
                )}
                {customers.map((customer) => (
                  <option key={customer.id} value={customer.id}>{customer.name}</option>
                ))}
              </select>
              {customers.length === 0 && customerSearch && (
                <span className="field-hint">No matching customers. Adjust your search.</span>
              )}
              {customers.length > 0 && customerCount > customers.length && (
                <span className="field-hint">
                  Showing up to 50 matches. Refine your search to find another customer.
                </span>
              )}
            </label>
            <label>
              Equipment name
              <input
                maxLength={200}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                required
                value={form.name}
              />
            </label>
            <label>
              Manufacturer
              <input
                maxLength={120}
                onChange={(event) =>
                  setForm({ ...form, manufacturer: event.target.value })
                }
                value={form.manufacturer}
              />
            </label>
            <label>
              Model number
              <input
                maxLength={120}
                onChange={(event) => setForm({ ...form, model_number: event.target.value })}
                value={form.model_number}
              />
            </label>
            <label>
              Serial number
              <input
                maxLength={120}
                onChange={(event) => setForm({ ...form, serial_number: event.target.value })}
                value={form.serial_number}
              />
            </label>
            <label>
              Installed on
              <input
                onChange={(event) => setForm({ ...form, installed_at: event.target.value || null })}
                type="date"
                value={form.installed_at ?? ""}
              />
            </label>
            <label>
              Warranty expires
              <input
                onChange={(event) =>
                  setForm({ ...form, warranty_expires_at: event.target.value || null })
                }
                type="date"
                value={form.warranty_expires_at ?? ""}
              />
            </label>
            <label className="field-wide">
              Notes
              <textarea
                onChange={(event) => setForm({ ...form, notes: event.target.value })}
                rows={2}
                value={form.notes}
              />
            </label>
          </div>
          <div className="form-actions">
            <button className="secondary-button" onClick={() => setShowForm(false)} type="button">
              Cancel
            </button>
            <button className="primary-button" disabled={busy} type="submit">
              {busy ? "Saving…" : editing === undefined ? "Save equipment" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      <div className="panel records-panel">
        {!page ? (
          <p className="empty-state">Loading equipment records…</p>
        ) : page.results.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon" aria-hidden="true">⌂</span>
            <strong>{search ? "No matching equipment" : "No equipment yet"}</strong>
            <span>
              {search
                ? "Try a different equipment, model, serial, or customer search."
                : "Equipment registered for your customers will appear here."}
            </span>
            {canWrite && customerCount > 0 && !search && (
              <button className="secondary-button" onClick={startCreate} type="button">
                Add your first equipment record
              </button>
            )}
          </div>
        ) : (
          <div className="table-scroll">
            <table className="records-table">
              <thead>
                <tr>
                  <th>Equipment</th>
                  <th>Customer</th>
                  <th>Model / serial</th>
                  <th>Warranty expires</th>
                  {canWrite && <th><span className="visually-hidden">Actions</span></th>}
                </tr>
              </thead>
              <tbody>
                {page.results.map((equipment) => (
                  <tr key={equipment.id}>
                    <td>
                      <span className="record-primary">{equipment.name}</span>
                      {equipment.manufacturer && (
                        <span className="record-secondary">{equipment.manufacturer}</span>
                      )}
                    </td>
                    <td>{equipment.customer_name}</td>
                    <td>{[equipment.model_number, equipment.serial_number].filter(Boolean).join(" · ") || "—"}</td>
                    <td>{equipment.warranty_expires_at || "—"}</td>
                    {canWrite && (
                      <td className="record-actions">
                        <button className="table-action" onClick={() => startEdit(equipment)} type="button">
                          Edit
                        </button>
                        <button className="table-action table-danger" onClick={() => void remove(equipment)} type="button">
                          Delete
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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
      </div>
    </section>
  );
}

function messageFor(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return "Could not complete the equipment request. Check your connection and try again.";
}

export default EquipmentPage;
