import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  addMember,
  ApiError,
  getMembers,
  removeMember,
  updateMemberRole,
  type OrganizationMember,
  type Page,
  type UserProfile,
} from "./api";

interface MembersPageProps {
  organizationId: number;
  user: UserProfile;
}

function MembersPage({ organizationId, user }: MembersPageProps) {
  const actor = user.organizations.find((organization) => organization.id === organizationId);
  const [page, setPage] = useState<Page<OrganizationMember>>();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrganizationMember["role"]>("technician");
  const [busy, setBusy] = useState(false);
  const [busyMember, setBusyMember] = useState<number>();
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setPage(await getMembers(organizationId));
  }, [organizationId]);

  useEffect(() => {
    let active = true;
    getMembers(organizationId)
      .then((result) => {
        if (active) setPage(result);
      })
      .catch((reason: unknown) => {
        if (active) setError(messageFor(reason));
      });
    return () => {
      active = false;
    };
  }, [organizationId]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await addMember(organizationId, email, role);
      setEmail("");
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(
    member: OrganizationMember,
    nextRole: OrganizationMember["role"],
  ) {
    setBusyMember(member.id);
    setError("");
    try {
      await updateMemberRole(
        organizationId,
        member.id,
        nextRole,
      );
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyMember(undefined);
    }
  }

  async function remove(member: OrganizationMember) {
    if (!window.confirm(`Remove ${member.email} from this organization?`)) return;
    setBusyMember(member.id);
    setError("");
    try {
      await removeMember(organizationId, member.id);
      await load();
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setBusyMember(undefined);
    }
  }

  if (actor?.role !== "owner" && actor?.role !== "admin") {
    return (
      <section className="workspace-page data-page">
        <div className="data-page-heading">
          <div>
            <div className="eyebrow">WORKSPACE ACCESS</div>
            <h1>Team members</h1>
          </div>
        </div>
        <div className="form-error page-alert" role="alert">
          Only organization owners and administrators can view or manage memberships.
        </div>
      </section>
    );
  }

  return (
    <section className="workspace-page data-page">
      <div className="data-page-heading">
        <div>
          <div className="eyebrow">WORKSPACE ACCESS</div>
          <h1>Team members</h1>
          <p className="welcome-copy">
            Add existing ServiceFlow accounts and assign organization roles.
          </p>
        </div>
      </div>

      {error && <div className="form-error page-alert" role="alert">{error}</div>}
      <form className="panel member-form" onSubmit={submit}>
        <div className="panel-form-heading">
          <div>
            <h2>Add a member</h2>
            <p>They must already have a ServiceFlow account.</p>
          </div>
        </div>
        <div className="member-add-row">
          <label>
            Account email
            <input
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label>
            Organization role
            <select onChange={(event) => setRole(event.target.value as OrganizationMember["role"])} value={role}>
              <option value="technician">Technician</option>
              <option value="manager">Manager</option>
              {actor.role === "owner" && (
                <>
                  <option value="admin">Administrator</option>
                  <option value="owner">Owner</option>
                </>
              )}
            </select>
          </label>
          <button className="primary-button" disabled={busy} type="submit">
            {busy ? "Adding…" : "Add member"}
          </button>
        </div>
      </form>

      <div className="panel records-panel">
        {!page ? (
          <p className="empty-state">Loading team members…</p>
        ) : (
          <div className="table-scroll">
            <table className="records-table">
              <thead>
                <tr><th>Member</th><th>Role</th><th>Joined</th><th><span className="visually-hidden">Actions</span></th></tr>
              </thead>
              <tbody>
                {page.results.map((member) => {
                  const isOwner = member.role === "owner";
                  const isCurrentUser = user.id === member.user_id;
                  return (
                    <tr key={member.id}>
                      <td>
                        <span className="record-primary">{member.name || member.email}</span>
                        <span className="record-secondary">{member.email}</span>
                      </td>
                      <td>
                        <select
                          aria-label={`Role for ${member.email}`}
                          disabled={isOwner || isCurrentUser || busyMember === member.id}
                          onChange={(event) => {
                            const nextRole = parseRole(event.target.value);
                            if (nextRole) void changeRole(member, nextRole);
                          }}
                          value={member.role}
                        >
                          <option value="owner">Owner</option>
                          <option value="admin">Administrator</option>
                          <option value="manager">Manager</option>
                          <option value="technician">Technician</option>
                        </select>
                      </td>
                      <td>{new Date(member.joined_at).toLocaleDateString("en-IN")}</td>
                      <td className="record-actions">
                        {!isOwner && !isCurrentUser && (
                          <button
                            className="table-action table-danger"
                            disabled={busyMember === member.id}
                            onClick={() => void remove(member)}
                            type="button"
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="field-hint member-hint">
        Owners and administrators control workspace access. Administrators can
        assign manager and technician roles; only owners can assign owner or
        administrator roles.
      </p>
    </section>
  );
}

function messageFor(reason: unknown): string {
  if (reason instanceof ApiError) return reason.message;
  return "Could not complete the membership request. Check your connection and try again.";
}

function parseRole(value: string): OrganizationMember["role"] | undefined {
  if (value === "owner" || value === "admin" || value === "manager" || value === "technician") {
    return value;
  }
  return undefined;
}

export default MembersPage;
