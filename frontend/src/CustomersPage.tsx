import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  createCustomer,
  deleteCustomer,
  getCustomers,
  updateCustomer,
  type Customer,
  type Page,
} from "./api";

interface CustomersPageProps {
  organizationId: number;
  canWrite: boolean;
}

type CustomerInput = Pick<
  Customer,
  "name" | "phone" | "email" | "address" | "notes"
>;

const emptyCustomer: CustomerInput = {
  name: "",
  phone: "",
  email: "",
  address: "",
  notes: "",
};

function CustomersPage({ organizationId, canWrite }: CustomersPageProps) {
  const [page, setPage] = useState<Page<Customer>>();
  const [pageNumber, setPageNumber] = useState(1);
  const [search, setSearch] = useState("");
  const [form, setForm] = useState<CustomerInput>(emptyCustomer);
  const [editing, setEditing] = useState<number>();
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (targetPage = pageNumber) => {
    const result = await getCustomers(organizationId, { page: targetPage, search });
    setPage(result);
  }, [organizationId, pageNumber, search]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    const timeout = window.setTimeout(() => {
      getCustomers(organizationId, { page: pageNumber, search })
        .then((result) => {
          if (active) setPage(result);
        })
        .catch((reason: unknown) => {
          if (active) setError(messageFor(reason));
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [organizationId, pageNumber, search]);

  function startCreate() {
    setEditing(undefined);
    setForm(emptyCustomer);
    setError("");
    setShowForm(true);
  }

  function startEdit(customer: Customer) {
    setEditing(customer.id);
    setForm({
      name: customer.name,
      phone: customer.phone,
      email: customer.email,
      address: customer.address,
      notes: customer.notes,
    });
    setError("");
    setShowForm(true);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (editing === undefined) {
        await createCustomer(organizationId, form);
      } else {
        await updateCustomer(organizationId, editing, form);
      }
      setShowForm(false);
      setForm(emptyCustomer);
      setEditing(undefined);
      setPageNumber(1);
      await load(1);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function remove(customer: Customer) {
    if (!window.confirm(`Delete ${customer.name}? Its equipment records will also be deleted.`)) {
      return;
    }
    setError("");
    try {
      await deleteCustomer(organizationId, customer.id);
      setPageNumber(1);
      await load(1);
    } catch (reason) {
      setError(messageFor(reason));
    }
  }

  return (
    <section className="workspace-page data-page">
      <div className="data-page-heading">
        <div>
          <div className="eyebrow">CUSTOMER DIRECTORY</div>
          <h1>Customers</h1>
          <p className="welcome-copy">
            Customer records for this organization.
            {page
              ? ` ${page.count} ${search ? "matching" : "total"}.`
              : ""}
          </p>
        </div>
        <div className="data-page-actions">
          <label className="record-search-label">
            <span className="visually-hidden">Search customers</span>
            <input
              aria-label="Search customers"
              className="record-search"
              onChange={(event) => {
                setSearch(event.target.value);
                setPageNumber(1);
                setError("");
              }}
              placeholder="Search customers"
              type="search"
              value={search}
            />
          </label>
          {canWrite && (
            <button className="primary-button" onClick={startCreate} type="button">
              Add customer
            </button>
          )}
        </div>
      </div>

      {error && <div className="form-error page-alert" role="alert">{error}</div>}
      {showForm && (
        <form className="panel record-form" onSubmit={save}>
          <div className="panel-form-heading">
            <h2>{editing === undefined ? "Add a customer" : "Edit customer"}</h2>
            <button
              className="icon-button"
              onClick={() => setShowForm(false)}
              type="button"
              aria-label="Close customer form"
            >
              ×
            </button>
          </div>
          <div className="form-grid">
            <label className="field-wide">
              Customer name
              <input
                maxLength={200}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                required
                value={form.name}
              />
            </label>
            <label>
              Phone
              <input
                maxLength={30}
                onChange={(event) => setForm({ ...form, phone: event.target.value })}
                value={form.phone}
              />
            </label>
            <label>
              Email
              <input
                onChange={(event) => setForm({ ...form, email: event.target.value })}
                type="email"
                value={form.email}
              />
            </label>
            <label className="field-wide">
              Address
              <textarea
                onChange={(event) => setForm({ ...form, address: event.target.value })}
                rows={2}
                value={form.address}
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
              {busy ? "Saving…" : editing === undefined ? "Save customer" : "Save changes"}
            </button>
          </div>
        </form>
      )}

      <div className="panel records-panel">
        {loading && !page ? (
          <p className="empty-state">Loading customer records…</p>
        ) : !page ? (
          <p className="empty-state">Customer records are unavailable.</p>
        ) : page.results.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon" aria-hidden="true">◎</span>
            <strong>{search ? "No matching customers" : "No customers yet"}</strong>
            <span>
              {search
                ? "Try another customer name, phone, email, or address."
                : "Customers you add to this organization will appear here."}
            </span>
            {canWrite && !search && (
              <button className="secondary-button" onClick={startCreate} type="button">
                Add your first customer
              </button>
            )}
          </div>
        ) : (
          <div className="table-scroll">
            <table className="records-table">
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Phone</th>
                  <th>Email</th>
                  <th>Address</th>
                  {canWrite && <th><span className="visually-hidden">Actions</span></th>}
                </tr>
              </thead>
              <tbody>
                {page.results.map((customer) => (
                  <tr key={customer.id}>
                    <td className="record-primary">{customer.name}</td>
                    <td>{customer.phone || "—"}</td>
                    <td>{customer.email || "—"}</td>
                    <td className="record-address">{customer.address || "—"}</td>
                    {canWrite && (
                      <td className="record-actions">
                        <button className="table-action" onClick={() => startEdit(customer)} type="button">
                          Edit
                        </button>
                        <button className="table-action table-danger" onClick={() => void remove(customer)} type="button">
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
            <span>
              Page {pageNumber} of {Math.ceil(page.count / 50)}
            </span>
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
  return "Could not complete the customer request. Check your connection and try again.";
}

export default CustomersPage;
