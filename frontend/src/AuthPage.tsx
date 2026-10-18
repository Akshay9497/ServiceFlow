import { useEffect, useState, type FormEvent } from "react";

import {
  ApiError,
  completePasswordReset,
  getCurrentUser,
  getPublicConfiguration,
  login,
  requestPasswordReset,
  requestPasswordResetEmailChange,
  register,
  type UserProfile,
  verifyPasswordResetOTP,
} from "./api";

type AuthMode =
  | "login"
  | "register"
  | "forgot"
  | "verify-otp"
  | "credentials"
  | "verify-new-email";

interface AuthPageProps {
  onAuthenticated: (user: UserProfile) => void;
  initialNotice?: string;
}

function AuthPage({ onAuthenticated, initialNotice = "" }: AuthPageProps) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [name, setName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [email, setEmail] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [verificationToken, setVerificationToken] = useState("");
  const [error, setError] = useState(initialNotice);
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);
  const [registrationStatus, setRegistrationStatus] = useState<
    "loading" | "enabled" | "disabled" | "unavailable"
  >("loading");

  useEffect(() => {
    let active = true;
    getPublicConfiguration()
      .then(({ registration_enabled }) => {
        if (active) {
          setRegistrationStatus(registration_enabled ? "enabled" : "disabled");
        }
      })
      .catch(() => {
        if (active) setRegistrationStatus("unavailable");
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccess("");
    setBusy(true);
    try {
      if (mode === "forgot") {
        await requestPasswordReset(email);
        setMode("verify-otp");
        setSuccess("If an account exists, a verification code has been sent to its email.");
        return;
      }
      if (mode === "verify-otp") {
        const result = await verifyPasswordResetOTP(email, otp);
        setVerificationToken(result.verification_token);
        setOtp("");
        setMode("credentials");
        setSuccess("Email verified. Enter your new login email and password.");
        return;
      }
      if (mode === "credentials") {
        await requestPasswordResetEmailChange({
          verification_token: verificationToken,
          new_email: newEmail,
        });
        setOtp("");
        setMode("verify-new-email");
        setSuccess("A verification code has been sent to your new email address.");
        return;
      }
      if (mode === "verify-new-email") {
        await completePasswordReset({
          verification_token: verificationToken,
          new_email: newEmail,
          otp,
          new_password: password,
          confirm_password: confirmPassword,
        });
        setPassword("");
        setConfirmPassword("");
        setOtp("");
        setVerificationToken("");
        setEmail(newEmail);
        setMode("login");
        setSuccess("Email and password updated. Sign in with your new email.");
        return;
      }
      if (mode === "register") {
        await register({
          name,
          email,
          password,
          organization_name: organizationName,
        });
      }
      await login(email, password);
      onAuthenticated(await getCurrentUser());
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Could not connect to ServiceFlow. Check that the API is running.",
      );
    } finally {
      setBusy(false);
    }
  }

  function changeMode(nextMode: AuthMode) {
    if (nextMode === "register" && registrationStatus !== "enabled") return;
    setMode(nextMode);
    setError("");
    setSuccess("");
  }

  return (
    <main className="auth-shell">
      <section className="auth-card" aria-labelledby="auth-heading">
        <a className="brand auth-brand" href="/" aria-label="ServiceFlow home">
          <span className="brand-mark" aria-hidden="true">
            <span /><span /><span /><span />
          </span>
          <span className="brand-name">serviceflow</span>
        </a>
        <div className="eyebrow">SERVICE BUSINESS, IN CONTROL</div>
        <h1 id="auth-heading">
          {mode === "register"
            ? "Start your workspace"
            : mode === "forgot"
              ? "Reset your password"
              : mode === "verify-otp"
                ? "Verify your email"
                : mode === "credentials"
                  ? "Choose new login details"
                  : mode === "verify-new-email"
                    ? "Verify your new email"
                    : "Welcome back"}
        </h1>
        <p className="auth-intro">
          {mode === "register"
            ? "Create your business account and organization."
            : mode === "forgot"
              ? "Enter the email on your account to receive a verification code."
              : mode === "verify-otp"
                ? `Enter the six-digit code sent to ${email}.`
                : mode === "credentials"
                  ? "Choose a new email address and password for signing in."
                  : mode === "verify-new-email"
                    ? `Enter the six-digit code sent to ${newEmail} to finish updating your account.`
                    : "Sign in to continue to your service workspace."}
        </p>

        <form className="form-stack" onSubmit={handleSubmit}>
          {mode === "register" && (
            <>
              <label>
                Your name
                <input
                  autoComplete="name"
                  maxLength={150}
                  onChange={(event) => setName(event.target.value)}
                  required
                  value={name}
                />
              </label>
              <label>
                Business name
                <input
                  autoComplete="organization"
                  maxLength={200}
                  onChange={(event) => setOrganizationName(event.target.value)}
                  required
                  value={organizationName}
                />
              </label>
            </>
          )}
          {["login", "register", "forgot"].includes(mode) && (
            <label>
              {mode === "login" ? "Username (email address)" : "Email address"}
              <input
                autoComplete="email"
                maxLength={150}
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
              />
            </label>
          )}
          {["login", "register"].includes(mode) && (
            <label>
              Password
              <input
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
              {mode === "register" && (
                <span className="field-hint">Use at least 8 characters.</span>
              )}
            </label>
          )}
          {mode === "verify-otp" && (
            <label>
              Email verification code
              <input
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={6}
                onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))}
                pattern="\d{6}"
                required
                value={otp}
              />
            </label>
          )}
          {mode === "credentials" && (
            <>
              <label>
                New login email
                <input
                  autoComplete="email"
                  maxLength={150}
                  onChange={(event) => setNewEmail(event.target.value)}
                  required
                  type="email"
                  value={newEmail}
                />
              </label>
              <label>
                New password
                <input
                  autoComplete="new-password"
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  type="password"
                  value={password}
                />
                <span className="field-hint">Use at least 8 characters.</span>
              </label>
              <label>
                Confirm new password
                <input
                  autoComplete="new-password"
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  required
                  type="password"
                  value={confirmPassword}
                />
              </label>
            </>
          )}
          {mode === "verify-new-email" && (
            <label>
              Code sent to new email
              <input
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={6}
                onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))}
                pattern="\d{6}"
                required
                value={otp}
              />
            </label>
          )}
          {error && <div className="form-error" role="alert">{error}</div>}
          {success && <div className="form-success" role="status">{success}</div>}
          <button className="primary-button auth-submit" disabled={busy} type="submit">
            {busy
              ? "Please wait…"
              : mode === "register"
                ? "Create business account"
                : mode === "forgot"
                  ? "Send verification code"
                  : mode === "verify-otp"
                    ? "Verify code"
                    : mode === "credentials"
                      ? "Verify new email"
                      : mode === "verify-new-email"
                        ? "Verify & update account"
                        : "Sign in"}
          </button>
        </form>
        {mode === "login" && (
          <p className="auth-forgot">
            <button className="text-button" onClick={() => changeMode("forgot")} type="button">
              Forgot password?
            </button>
          </p>
        )}
        <p className="auth-switch">
          {mode === "register" ? (
            <>
              Already have an account?{" "}
              <button className="text-button" onClick={() => changeMode("login")} type="button">
                Sign in
              </button>
            </>
          ) : ["forgot", "verify-otp", "credentials", "verify-new-email"].includes(mode) ? (
            <button className="text-button" onClick={() => changeMode("login")} type="button">
              Back to sign in
            </button>
          ) : registrationStatus === "enabled" ? (
            <>
              New to ServiceFlow?{" "}
              <button
                className="text-button"
                onClick={() => changeMode("register")}
                type="button"
              >
                Create an account
              </button>
            </>
          ) : (
            <span>
              {registrationStatus === "loading"
                ? "Checking account availability…"
                : registrationStatus === "disabled"
                  ? "Account creation is limited during this pilot. Contact your ServiceFlow administrator."
                  : "Account availability could not be checked. Contact your ServiceFlow administrator."}
            </span>
          )}
        </p>
      </section>
      <p className="auth-footnote">A clearer day starts here.</p>
    </main>
  );
}

export default AuthPage;
