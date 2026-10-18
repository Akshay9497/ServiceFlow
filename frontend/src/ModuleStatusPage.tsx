interface ModuleStatusPageProps {
  title: string;
  description: string;
  onNavigate: (page: "customers" | "equipment" | "jobs" | "contracts") => void;
}

function ModuleStatusPage({
  title,
  description,
  onNavigate,
}: ModuleStatusPageProps) {
  return (
    <section className="workspace-page data-page">
      <div className="data-page-heading">
        <div>
          <div className="eyebrow">MODULE NOT AVAILABLE YET</div>
          <h1>{title}</h1>
          <p className="welcome-copy">{description}</p>
        </div>
        <span className="phase-badge">
          <span className="phase-badge-dot" aria-hidden="true" />
          No connected API
        </span>
      </div>

      <section className="panel module-status-panel" aria-labelledby="module-status-heading">
        <span className="module-status-icon" aria-hidden="true">↗</span>
        <div>
          <div className="panel-kicker">NOT CONNECTED</div>
          <h2 id="module-status-heading">This workspace module is not live.</h2>
          <p>
            ServiceFlow does not currently provide an API for {title.toLowerCase()}.
            This screen does not show sample records or accept changes. The module
            will become functional when its backend workflows are implemented.
          </p>
        </div>
      </section>

      <section className="module-available-section" aria-labelledby="available-heading">
        <div className="panel-kicker" id="available-heading">AVAILABLE WORKSPACE AREAS</div>
        <div className="module-available-links">
          <button className="secondary-button" onClick={() => onNavigate("customers")} type="button">
            Customers
          </button>
          <button className="secondary-button" onClick={() => onNavigate("equipment")} type="button">
            Equipment
          </button>
          <button className="secondary-button" onClick={() => onNavigate("jobs")} type="button">
            Service jobs
          </button>
          <button className="secondary-button" onClick={() => onNavigate("contracts")} type="button">
            AMC contracts
          </button>
        </div>
      </section>
    </section>
  );
}

export default ModuleStatusPage;
