import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  getContracts,
  getCustomers,
  getEquipment,
  getOutstandingReport,
  getServiceJobs,
  getUpcomingRenewals,
} from "./api";

interface DashboardPageProps {
  organizationId: number;
  canViewFinance: boolean;
  onNavigate: (
    page: "customers" | "equipment" | "jobs" | "contracts" | "invoices" | "payments" | "expenses" | "reports" | "subscription",
  ) => void;
}

function DashboardPage({ organizationId, canViewFinance, onNavigate }: DashboardPageProps) {
  const [counts, setCounts] = useState<{
    customers: number;
    equipment: number;
    jobs: number;
    contracts: number;
    upcomingRenewals: number;
    invoiceCount?: number;
    outstandingTotal?: string;
  }>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [customers, equipment, jobs, contracts, upcomingRenewals] =
        await Promise.all([
          getCustomers(organizationId),
          getEquipment(organizationId),
          getServiceJobs(organizationId),
          getContracts(organizationId, "active"),
          getUpcomingRenewals(organizationId, 30),
        ]);
      const finance = canViewFinance
        ? await getOutstandingReport(organizationId)
        : undefined;
      setCounts({
        customers: customers.count,
        equipment: equipment.count,
        jobs: jobs.count,
        contracts: contracts.count,
        upcomingRenewals: upcomingRenewals.count,
        invoiceCount: finance?.invoice_count,
        outstandingTotal: finance?.outstanding_total,
      });
    } catch (reason: unknown) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not load organization records.",
      );
    } finally {
      setLoading(false);
    }
  }, [canViewFinance, organizationId]);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  return (
    <div className="workspace-page">
      <section className="welcome-row">
        <div>
          <div className="eyebrow">YOUR SERVICE OPERATIONS, IN ONE PLACE</div>
          <h1>Your business at a glance.</h1>
          <p className="welcome-copy">Live records from your organization workspace.</p>
        </div>
        <span className="phase-badge">
          <span className="phase-badge-dot" aria-hidden="true" />
          Phase 5 · Service operations
        </span>
      </section>

      {error && (
        <div className="form-error page-alert" role="alert">
          {error}
          <button className="table-action" onClick={() => void loadDashboard()} type="button">
            Retry
          </button>
        </div>
      )}

      <section className="metric-grid" aria-label="Organization records" aria-busy={loading}>
        <button className="metric-card" onClick={() => onNavigate("customers")} type="button">
          <span className="metric-icon metric-purple" aria-hidden="true">◎</span>
          <span className="metric-label">Customers</span>
          <strong>{counts ? counts.customers : loading ? "…" : "—"}</strong>
          <span className="metric-caption">Organization records</span>
        </button>
        <button className="metric-card" onClick={() => onNavigate("equipment")} type="button">
          <span className="metric-icon metric-blue" aria-hidden="true">⌂</span>
          <span className="metric-label">Equipment</span>
          <strong>{counts ? counts.equipment : loading ? "…" : "—"}</strong>
          <span className="metric-caption">Registered equipment</span>
        </button>
        <button className="metric-card" onClick={() => onNavigate("jobs")} type="button">
          <span className="metric-icon metric-amber" aria-hidden="true">↗</span>
          <span className="metric-label">Service jobs</span>
          <strong>{counts ? counts.jobs : loading ? "…" : "—"}</strong>
          <span className="metric-caption">Organization work orders</span>
        </button>
        <button className="metric-card" onClick={() => onNavigate("contracts")} type="button">
          <span className="metric-icon metric-green" aria-hidden="true">◷</span>
          <span className="metric-label">Active contracts</span>
          <strong>{counts ? counts.contracts : loading ? "…" : "—"}</strong>
          <span className="metric-caption">
            {counts ? `${counts.upcomingRenewals} renewing in 30 days` : "Renewal tracking"}
          </span>
        </button>
      </section>
      {canViewFinance && (
        <section className="metric-grid finance-dashboard-grid" aria-label="Financial records">
          <button className="metric-card" onClick={() => onNavigate("invoices")} type="button">
            <span className="metric-icon metric-purple" aria-hidden="true">▤</span>
            <span className="metric-label">Issued invoices</span>
            <strong>{loading ? "…" : counts?.invoiceCount ?? "—"}</strong>
            <span className="metric-caption">From the organization invoice API</span>
          </button>
          <button className="metric-card" onClick={() => onNavigate("reports")} type="button">
            <span className="metric-icon metric-amber" aria-hidden="true">₹</span>
            <span className="metric-label">Outstanding balance</span>
            <strong>{loading ? "…" : counts?.outstandingTotal !== undefined
              ? new Intl.NumberFormat("en-IN", {
                style: "currency",
                currency: "INR",
                maximumFractionDigits: 2,
              }).format(Number(counts.outstandingTotal))
              : "—"}</strong>
            <span className="metric-caption">Issued invoices, net of allocations</span>
          </button>
        </section>
      )}

      <section className="panel dashboard-welcome">
        <div className="panel-kicker">YOUR WORKSPACE IS LIVE</div>
        <h2>Build your service records as you go.</h2>
        <p>
          Add customers, register equipment, and coordinate real service jobs.
          Counts above reflect records saved in this organization, not sample data.
        </p>
        <div className="dashboard-actions">
          <button
            className="primary-button"
            onClick={() => onNavigate("customers")}
            type="button"
          >
            Manage customers
          </button>
          <button
            className="secondary-button"
            onClick={() => onNavigate("equipment")}
            type="button"
          >
            Manage equipment
          </button>
          <button
            className="secondary-button"
            onClick={() => onNavigate("jobs")}
            type="button"
          >
            View service jobs
          </button>
          <button
            className="secondary-button"
            onClick={() => onNavigate("contracts")}
            type="button"
          >
            Manage contracts
          </button>
        </div>
      </section>

      <div className="phase-grid" aria-label="ServiceFlow modules">
        <button className="phase-tile phase-tile-active" onClick={() => onNavigate("jobs")} type="button">
          <span>Jobs & technicians</span><small>Available now · View jobs</small>
        </button>
        <button className="phase-tile phase-tile-active" onClick={() => onNavigate("contracts")} type="button">
          <span>AMCs & renewals</span><small>Available now · View contracts</small>
        </button>
        <button className="phase-tile phase-tile-active" onClick={() => onNavigate("invoices")} type="button">
          <span>Invoices & quotations</span><small>Available now · View billing</small>
        </button>
        <button className="phase-tile phase-tile-active" onClick={() => onNavigate("reports")} type="button">
          <span>Financial reports</span><small>Available now · View reports</small>
        </button>
      </div>
    </div>
  );
}

export default DashboardPage;
