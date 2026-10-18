import { useEffect, useState } from "react";

import AuthPage from "./AuthPage";
import CustomersPage from "./CustomersPage";
import ContractsPage from "./ContractsPage";
import DashboardPage from "./DashboardPage";
import EquipmentPage from "./EquipmentPage";
import { ExpensesPage, InvoicesPage, PaymentsPage, ReportsPage } from "./FinancePages";
import JobsPage from "./JobsPage";
import MembersPage from "./MembersPage";
import SubscriptionPage from "./SubscriptionPage";
import {
  clearSession,
  getCurrentUser,
  hasSession,
  logout,
  type UserProfile,
} from "./api";
import "./App.css";

type PageName =
  | "overview"
  | "customers"
  | "equipment"
  | "jobs"
  | "contracts"
  | "members"
  | "invoices"
  | "payments"
  | "expenses"
  | "reports"
  | "subscription";

function App() {
  const [user, setUser] = useState<UserProfile>();
  const [organizationId, setOrganizationId] = useState<number>();
  const [page, setPage] = useState<PageName>("overview");
  const [checkingSession, setCheckingSession] = useState(hasSession);
  const [sessionError, setSessionError] = useState("");

  useEffect(() => {
    if (!hasSession()) return;
    let active = true;
    getCurrentUser()
      .then((profile) => {
        if (active) acceptUser(profile);
      })
      .catch(() => {
        if (!active) return;
        clearSession();
        setSessionError("Your session has expired. Sign in to continue.");
      })
      .finally(() => {
        if (active) setCheckingSession(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function acceptUser(profile: UserProfile, preferredOrganizationId?: number) {
    setUser(profile);
    const savedId = Number(sessionStorage.getItem("serviceflow.organization"));
    const selected = profile.organizations.find(
      (organization) => organization.id === preferredOrganizationId,
    ) ?? profile.organizations.find((organization) => organization.id === savedId)
      ?? profile.organizations[0];
    setOrganizationId(selected?.id);
    if (selected) {
      sessionStorage.setItem("serviceflow.organization", String(selected.id));
    }
    setSessionError("");
  }

  function selectOrganization(value: string) {
    const nextId = Number(value);
    if (!Number.isInteger(nextId) || !user?.organizations.some((org) => org.id === nextId)) {
      return;
    }
    setOrganizationId(nextId);
    sessionStorage.setItem("serviceflow.organization", String(nextId));
    setPage("overview");
  }

  async function signOut() {
    let notice = "";
    try {
      await logout();
    } catch {
      notice = "Signed out locally, but the server could not revoke the refresh token. Sign out again when the connection is available.";
    }
    clearSession();
    setUser(undefined);
    setOrganizationId(undefined);
    setPage("overview");
    setSessionError(notice);
  }

  if (checkingSession) {
    return (
      <main className="auth-shell">
        <div className="session-loading-box">
          <div className="spinner" aria-hidden="true" />
          <p className="session-loading">Restoring your workspace session…</p>
        </div>
      </main>
    );
  }

  if (!user) {
    return (
      <AuthPage
        initialNotice={sessionError}
        onAuthenticated={acceptUser}
      />
    );
  }

  if (!organizationId) {
    return (
      <main className="auth-shell">
        <section className="auth-card no-org-card">
          <div className="no-org-icon-badge" aria-hidden="true">
            🏢
          </div>
          <h1>Organization Access Required</h1>
          <p className="auth-intro">
            This account is not assigned to any organization yet. Organizations and
            memberships are provisioned by platform administrators in the Django Superadmin.
          </p>

          {user.is_superuser ? (
            <div className="admin-cta-box">
              <span className="admin-status-badge">Platform Superuser Detected</span>
              <p className="admin-cta-note">
                You have administrative access. Open the Django admin to create an organization
                and assign your account as the owner.
              </p>
              <a
                className="primary-button auth-submit admin-launch-btn"
                href="/admin/api/organization/add/"
                rel="noreferrer"
                target="_blank"
              >
                Create Organization in Django Admin ↗
              </a>
            </div>
          ) : (
            <div className="contact-admin-notice">
              Please contact your platform administrator or organization owner to assign your account.
            </div>
          )}

          <button className="secondary-button" onClick={signOut} type="button">
            Sign out
          </button>
        </section>
      </main>
    );
  }

  const organization = user.organizations.find((item) => item.id === organizationId);
  const isAdministrator = organization?.role === "owner" || organization?.role === "admin";
  const canWriteRecords = isAdministrator || organization?.role === "manager";
  const currentPageTitle: Record<PageName, string> = {
    overview: "Overview",
    customers: "Customers",
    equipment: "Equipment",
    jobs: "Service jobs",
    contracts: "Service contracts",
    members: "Team members",
    invoices: "Invoices & quotations",
    payments: "Payments",
    expenses: "Expenses",
    reports: "Reports",
    subscription: "Subscription",
  };

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Main navigation">
        <a className="brand" href="#overview" aria-label="ServiceFlow overview">
          <span className="brand-mark" aria-hidden="true">
            <span /><span /><span /><span />
          </span>
          <span className="brand-name">ServiceFlow</span>
        </a>

        <div className="sidebar-label">WORKSPACE</div>
        <nav>
          <NavButton active={page === "overview"} icon="▦" onClick={() => setPage("overview")}>
            Overview
          </NavButton>
          <NavButton active={page === "customers"} icon="◎" onClick={() => setPage("customers")}>
            Customers
          </NavButton>
          <NavButton active={page === "equipment"} icon="⌂" onClick={() => setPage("equipment")}>
            Equipment
          </NavButton>
          <NavButton active={page === "jobs"} icon="↗" onClick={() => setPage("jobs")}>
            Service jobs
          </NavButton>
          <NavButton active={page === "contracts"} icon="◷" onClick={() => setPage("contracts")}>
            Service contracts
          </NavButton>
          {isAdministrator && (
            <NavButton active={page === "members"} icon="♧" onClick={() => setPage("members")}>
              Team members
            </NavButton>
          )}
          {canWriteRecords && (
            <>
              <div className="sidebar-label sidebar-label-secondary">FINANCE & BILLING</div>
              <NavButton active={page === "invoices"} icon="▤" onClick={() => setPage("invoices")}>
                Invoices & quotations
              </NavButton>
              <NavButton active={page === "payments"} icon="₹" onClick={() => setPage("payments")}>
                Payments
              </NavButton>
              <NavButton active={page === "expenses"} icon="↘" onClick={() => setPage("expenses")}>
                Expenses
              </NavButton>
              <NavButton active={page === "reports"} icon="▥" onClick={() => setPage("reports")}>
                Financial reports
              </NavButton>
            </>
          )}
          <div className="sidebar-label sidebar-label-secondary">SETTINGS</div>
          {canWriteRecords && (
            <NavButton active={page === "subscription"} icon="◇" onClick={() => setPage("subscription")}>
              Subscription & plan
            </NavButton>
          )}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-bottom-mark" aria-hidden="true">
            {organization?.name.slice(0, 1).toUpperCase() ?? "S"}
          </div>
          <div className="sidebar-workspace">
            <label className="sidebar-bottom-title" htmlFor="organization-switcher">
              Active Organization
            </label>
            <select
              className="organization-switcher"
              id="organization-switcher"
              onChange={(event) => selectOrganization(event.target.value)}
              value={organizationId}
            >
              {user.organizations.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
            <div className="sidebar-bottom-caption">
              <span className="role-pill">{organization?.role ?? "Member"}</span>
            </div>
            {user.is_superuser && (
              <a
                className="sidebar-admin-link"
                href="/admin/api/organization/"
                rel="noreferrer"
                target="_blank"
                title="Manage organizations in Django Superadmin"
              >
                <span className="admin-link-icon">⚙</span> Django Admin ↗
              </a>
            )}
          </div>
        </div>
      </aside>

      <main className="main-content" id="overview">
        <header className="topbar">
          <div className="breadcrumb">
            <span className="breadcrumb-org">{organization?.name ?? "Workspace"}</span>
            <span className="breadcrumb-divider" aria-hidden="true">/</span>
            <strong className="breadcrumb-page">{currentPageTitle[page]}</strong>
          </div>
          <div className="account-controls">
            {user.is_superuser && (
              <a
                className="superuser-badge-link"
                href="/admin/"
                rel="noreferrer"
                target="_blank"
                title="Open Django Superadmin Console"
              >
                <span className="superuser-badge-dot" />
                <span>Superadmin</span>
                <span className="arrow-external">↗</span>
              </a>
            )}
            <div className="user-pill">
              <span className="user-avatar-dot" aria-hidden="true">
                {user.email.slice(0, 1).toUpperCase()}
              </span>
              <span className="account-email">{user.email}</span>
            </div>
            <button className="signout-button" onClick={signOut} type="button">
              Sign out
            </button>
          </div>
        </header>

        {page === "overview" && (
          <DashboardPage
            key={`overview-${organizationId}`}
            canViewFinance={Boolean(canWriteRecords)}
            onNavigate={setPage}
            organizationId={organizationId}
          />
        )}
        {page === "customers" && (
          <CustomersPage
            key={`customers-${organizationId}`}
            canWrite={Boolean(canWriteRecords)}
            organizationId={organizationId}
          />
        )}
        {page === "equipment" && (
          <EquipmentPage
            key={`equipment-${organizationId}`}
            canWrite={Boolean(canWriteRecords)}
            onManageCustomers={() => setPage("customers")}
            organizationId={organizationId}
          />
        )}
        {page === "jobs" && (
          <JobsPage
            key={`jobs-${organizationId}`}
            organizationId={organizationId}
            user={user}
          />
        )}
        {page === "contracts" && (
          <ContractsPage
            key={`contracts-${organizationId}`}
            canRenew={Boolean(canWriteRecords)}
            canWrite={Boolean(canWriteRecords)}
            organizationId={organizationId}
          />
        )}
        {page === "members" && isAdministrator && (
          <MembersPage
            key={`members-${organizationId}`}
            organizationId={organizationId}
            user={user}
          />
        )}
        {page === "invoices" && (
          <InvoicesPage
            key={`invoices-${organizationId}`}
            canWrite={Boolean(canWriteRecords)}
            organizationId={organizationId}
          />
        )}
        {page === "payments" && (
          <PaymentsPage
            key={`payments-${organizationId}`}
            canWrite={Boolean(canWriteRecords)}
            organizationId={organizationId}
          />
        )}
        {page === "expenses" && (
          <ExpensesPage
            key={`expenses-${organizationId}`}
            canWrite={Boolean(canWriteRecords)}
            organizationId={organizationId}
          />
        )}
        {page === "reports" && (
          <ReportsPage
            key={`reports-${organizationId}`}
            canWrite={Boolean(canWriteRecords)}
            organizationId={organizationId}
          />
        )}
        {page === "subscription" && (
          <SubscriptionPage
            key={`subscription-${organizationId}`}
            canManage={Boolean(isAdministrator)}
            organizationId={organizationId}
          />
        )}
      </main>
    </div>
  );
}

interface NavButtonProps {
  active: boolean;
  icon: string;
  onClick: () => void;
  children: string;
}

function NavButton({ active, icon, onClick, children }: NavButtonProps) {
  return (
    <button
      aria-current={active ? "page" : undefined}
      className={`nav-link nav-button${active ? " nav-link-active" : ""}`}
      onClick={onClick}
      type="button"
    >
      <span className="nav-icon" aria-hidden="true">{icon}</span>
      <span className="nav-text">{children}</span>
    </button>
  );
}

export default App;
