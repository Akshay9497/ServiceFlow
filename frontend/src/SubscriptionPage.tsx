import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  cancelOrganizationSubscription,
  getOrganizationSubscription,
  getSubscriptionInvoices,
  getSubscriptionPlans,
  requestSubscriptionPlan,
  type OrganizationSubscription,
  type SubscriptionChangeRequest,
  type SubscriptionInvoice,
  type SubscriptionOverview,
  type SubscriptionPlan,
} from "./api";

function errorMessage(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return "Could not complete the request. Check the API connection and try again.";
}

function formatMoney(amount: string | number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(Number(amount));
}

function usageLabel(
  used: number,
  limit: number | null,
): string {
  return limit === null ? `${used} used · no configured cap` : `${used} of ${limit} used`;
}

interface SubscriptionPageProps {
  organizationId: number;
  canManage: boolean;
}

export default function SubscriptionPage({
  organizationId,
  canManage,
}: SubscriptionPageProps) {
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [overview, setOverview] = useState<SubscriptionOverview>();
  const [invoices, setInvoices] = useState<SubscriptionInvoice[]>([]);
  const [selectedPlan, setSelectedPlan] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [availablePlans, subscriptionOverview, invoicePage] = await Promise.all([
        getSubscriptionPlans(),
        getOrganizationSubscription(organizationId),
        getSubscriptionInvoices(organizationId),
      ]);
      setPlans(availablePlans);
      setOverview(subscriptionOverview);
      setInvoices(invoicePage.results);
      const recommended = availablePlans.find(
        (plan) => plan.id !== subscriptionOverview.subscription?.plan.id,
      ) ?? availablePlans[0];
      setSelectedPlan(recommended ? String(recommended.id) : "");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [organizationId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submitPlanRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedPlan) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const request: SubscriptionChangeRequest = await requestSubscriptionPlan(
        organizationId,
        Number(selectedPlan),
      );
      setNotice(
        `Your ${request.request_type === "activate" ? "activation" : "plan change"} request for ${request.plan_name} is awaiting ServiceFlow review.`,
      );
      await load();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function cancelSubscription() {
    if (!window.confirm("Cancel this subscription now? This is effective immediately.")) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const subscription: OrganizationSubscription =
        await cancelOrganizationSubscription(organizationId);
      setNotice(`Subscription cancelled on ${subscription.cancelled_at?.slice(0, 10) ?? "today"}.`);
      await load();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  const subscription = overview?.subscription;
  const limitEntries = overview ? Object.entries(overview.usage) : [];

  return (
    <section className="workspace-page data-page">
      <div className="data-page-heading">
        <div>
          <div className="eyebrow">ACCOUNT & BILLING</div>
          <h1>Subscription</h1>
          <p className="welcome-copy">Review plan status, usage, invoices, and request a plan change.</p>
        </div>
      </div>
      {error && <div className="form-error page-alert" role="alert">{error}<button className="table-action" onClick={() => void load()} type="button">Retry</button></div>}
      {notice && <div className="inline-notice" role="status">{notice}</div>}
      {loading ? <div className="panel records-panel"><p className="empty-state">Loading subscription details…</p></div> : overview && (
        <>
          <section className="finance-report-grid" aria-label="Subscription status">
            <article className="finance-report-card">
              <span>Current plan</span>
              <strong>{subscription?.plan.name ?? "No plan activated"}</strong>
              <small>{subscription ? `${formatMoney(subscription.plan.price)} / ${subscription.plan.billing_period}` : "Submit an activation request for review"}</small>
            </article>
            <article className="finance-report-card">
              <span>Status</span>
              <strong>{subscription?.status ?? "Not activated"}</strong>
              <small>{subscription ? `${subscription.starts_on} – ${subscription.ends_on}` : "No subscription record exists yet"}</small>
            </article>
            <article className="finance-report-card">
              <span>Activation</span>
              <strong>{subscription?.manual_pilot ? "Manual pilot" : subscription ? "Standard" : "Pending setup"}</strong>
              <small>{subscription?.manual_pilot ? "Pilot access was approved by ServiceFlow" : "Payments are recorded manually during the pilot"}</small>
            </article>
          </section>

          {overview.pending_request && (
            <div className="inline-notice" role="status">
              {overview.pending_request.request_type === "activate" ? "Activation" : "Plan change"} request for {overview.pending_request.plan_name} is awaiting ServiceFlow review since {new Date(overview.pending_request.created_at).toLocaleDateString("en-IN")}.
            </div>
          )}

          <section className="panel reconciliation-panel">
            <div className="panel-form-heading"><div><div className="panel-kicker">PLAN USAGE</div><h2>Current usage against configured limits</h2><p>Limits apply to new records. Existing data is preserved if a plan has a lower cap.</p></div></div>
            <div className="account-balance-list">
              {limitEntries.map(([resource, usage]) => (
                <div key={resource}><span>{resource}</span><strong>{usageLabel(usage.used, usage.limit)}</strong><small>{usage.unlimited ? "Unlimited" : "Plan limit"}</small></div>
              ))}
            </div>
          </section>

          {canManage && (
            <form className="panel record-form" onSubmit={submitPlanRequest}>
              <div className="panel-form-heading"><div><div className="panel-kicker">PLAN REQUEST</div><h2>{subscription?.status === "active" ? "Request a plan change" : "Request activation"}</h2><p>Activation and plan changes are reviewed and applied manually by a ServiceFlow administrator. No online payment is initiated.</p></div></div>
              {plans.length === 0 ? <p className="empty-state">No subscription plans are configured. Contact your ServiceFlow administrator.</p> : (
                <>
                  <div className="form-grid finance-form-grid">
                    <label>Available plan
                      <select disabled={Boolean(overview.pending_request)} required value={selectedPlan} onChange={(event) => setSelectedPlan(event.target.value)}>
                        {plans.map((plan) => <option key={plan.id} value={plan.id}>{plan.name} · {formatMoney(plan.price)} / {plan.billing_period}</option>)}
                      </select>
                    </label>
                  </div>
                  {plans.find((plan) => String(plan.id) === selectedPlan) && (
                    <div className="inline-notice">
                      {plans.find((plan) => String(plan.id) === selectedPlan)?.description || "Plan details are maintained by ServiceFlow."}
                      {plans.find((plan) => String(plan.id) === selectedPlan)?.features.length
                        ? ` Includes: ${plans.find((plan) => String(plan.id) === selectedPlan)?.features.join(", ")}.`
                        : ""}
                    </div>
                  )}
                  <div className="form-actions">
                    {subscription?.status === "active" && <button className="secondary-button" disabled={busy} onClick={() => void cancelSubscription()} type="button">Cancel subscription</button>}
                    <button className="primary-button" disabled={busy || !selectedPlan || Boolean(overview.pending_request)} type="submit">{busy ? "Submitting…" : subscription?.status === "active" ? "Request plan change" : "Request activation"}</button>
                  </div>
                </>
              )}
            </form>
          )}

          <div className="panel records-panel">
            <div className="panel-form-heading"><div><h2>Subscription invoices</h2><p>Issued by ServiceFlow when a request is approved. Pilot invoices may have a zero balance.</p></div></div>
            {!invoices.length ? <div className="empty-state"><strong>No subscription invoices</strong><span>Invoices appear here after activation or a plan change is approved.</span></div> : (
              <div className="table-scroll"><table className="records-table">
                <thead><tr><th>Invoice</th><th>Plan</th><th>Period</th><th>Due</th><th>Amount</th><th>Status</th><th>Payment reference</th></tr></thead>
                <tbody>{invoices.map((invoice) => (
                  <tr key={invoice.id}><td>{invoice.invoice_number}</td><td>{invoice.plan_name}</td><td>{invoice.period_start} – {invoice.period_end}</td><td>{invoice.due_on}</td><td>{formatMoney(invoice.amount)}</td><td>{invoice.status}</td><td>{invoice.payment_reference || "Recorded by ServiceFlow during pilot"}</td></tr>
                ))}</tbody>
              </table></div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
