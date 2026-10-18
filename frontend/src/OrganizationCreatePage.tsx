import { useState, type FormEvent } from "react";

import {
  ApiError,
  createOrganization,
  getCurrentUser,
  type UserProfile,
} from "./api";

interface OrganizationCreatePageProps {
  onCancel: () => void;
  onCreated: (user: UserProfile, organizationId: number) => void;
}

function OrganizationCreatePage({
  onCancel,
  onCreated,
}: OrganizationCreatePageProps) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    let organizationCreated = false;
    try {
      const organization = await createOrganization(name.trim());
      organizationCreated = true;
      const profile = await getCurrentUser();
      onCreated(profile, organization.id);
    } catch (reason) {
      setError(
        organizationCreated
          ? "The organization was created, but your organization list could not be refreshed. Reload the page to continue."
          : reason instanceof ApiError
          ? reason.message
          : "Could not create the organization. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workspace-page data-page">
      <div className="data-page-heading">
        <div>
          <div className="eyebrow">WORKSPACE SETUP</div>
          <h1>Create an organization</h1>
          <p className="welcome-copy">
            Your account will be the owner of this organization.
          </p>
        </div>
      </div>
      {error && <div className="form-error page-alert" role="alert">{error}</div>}
      <form className="panel member-form" onSubmit={submit}>
        <div className="panel-form-heading">
          <div>
            <h2>Organization details</h2>
            <p>Each organization has its own isolated workspace and team.</p>
          </div>
        </div>
        <div className="member-add-row organization-create-row">
          <label>
            Organization name
            <input
              autoComplete="organization"
              maxLength={200}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </label>
          <button className="primary-button" disabled={busy} type="submit">
            {busy ? "Creating…" : "Create organization"}
          </button>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={onCancel}
            type="button"
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

export default OrganizationCreatePage;
