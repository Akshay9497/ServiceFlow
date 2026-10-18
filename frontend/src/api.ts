export interface HealthStatus {
  status: string;
  service: string;
}

export interface OrganizationMembership {
  id: number;
  membership_id: number;
  name: string;
  role: "owner" | "admin" | "manager" | "technician";
}

export type OrganizationSummary = OrganizationMembership;

export interface UserProfile {
  id: number;
  email: string;
  name: string;
  organizations: OrganizationMembership[];
  is_superuser?: boolean;
}

export interface Customer {
  id: number;
  name: string;
  phone: string;
  email: string;
  address: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface Equipment {
  id: number;
  customer: number;
  customer_name: string;
  name: string;
  manufacturer: string;
  model_number: string;
  serial_number: string;
  installed_at: string | null;
  warranty_expires_at: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface OrganizationMember {
  id: number;
  user_id: number;
  email: string;
  name: string;
  role: OrganizationMembership["role"];
  joined_at: string;
}

export interface SubscriptionPlan {
  id: number;
  code: string;
  name: string;
  description: string;
  price: string;
  billing_period: "monthly" | "yearly";
  period_days: number;
  max_members: number | null;
  max_customers: number | null;
  max_equipment: number | null;
  max_jobs: number | null;
  features: string[];
}

export interface SubscriptionInvoice {
  id: number;
  invoice_number: string;
  plan_name: string;
  period_start: string;
  period_end: string;
  amount: string;
  status: "issued" | "paid" | "void";
  issued_at: string;
  due_on: string;
  paid_at: string | null;
  payment_reference: string;
}

export interface SubscriptionChangeRequest {
  id: number;
  request_type: "activate" | "change_plan";
  status: "pending" | "approved" | "rejected" | "cancelled";
  requested_plan: number;
  plan_name: string;
  requested_by_name: string;
  decided_by_name: string | null;
  manual_pilot: boolean;
  decision_note: string;
  created_at: string;
  decided_at: string | null;
}

export interface OrganizationSubscription {
  id: number;
  plan: SubscriptionPlan;
  status: "active" | "cancelled" | "expired" | "suspended";
  starts_on: string;
  ends_on: string;
  manual_pilot: boolean;
  activated_at: string;
  cancelled_at: string | null;
  invoices: SubscriptionInvoice[];
}

export interface SubscriptionOverview {
  subscription: OrganizationSubscription | null;
  usage: Record<string, { used: number; limit: number | null; unlimited: boolean }>;
  pending_request: SubscriptionChangeRequest | null;
}

export type ServiceJobStatus =
  | "new"
  | "scheduled"
  | "in_progress"
  | "completed"
  | "cancelled";

export interface ServiceJobHistoryEntry {
  id: number;
  previous_status: string;
  status: ServiceJobStatus;
  note: string;
  changed_by_name: string;
  changed_at: string;
}

export interface ServiceJobWorkNote {
  id: number;
  note: string;
  created_by_name: string;
  created_at: string;
}

export interface ServiceJob {
  id: number;
  customer: number;
  customer_name: string;
  equipment: number | null;
  equipment_name: string | null;
  assigned_technician: number | null;
  assigned_technician_name: string | null;
  assigned_technician_email: string | null;
  service_contract: number | null;
  service_contract_number: string | null;
  title: string;
  description: string;
  status: ServiceJobStatus;
  scheduled_for: string | null;
  technician_note: string;
  completion_report: string;
  status_history: ServiceJobHistoryEntry[];
  work_notes: ServiceJobWorkNote[];
  created_at: string;
  updated_at: string;
}

export type ServiceContractStatus = "draft" | "active" | "expired" | "cancelled";
export type ServiceContractType =
  | "comprehensive"
  | "non_comprehensive"
  | "labour_only"
  | "custom";
export type VisitFrequency =
  | "monthly"
  | "quarterly"
  | "half_yearly"
  | "annual"
  | "custom";

export interface ContractVisit {
  id: number;
  job: number;
  job_title: string;
  job_status: ServiceJobStatus;
  recorded_by_name: string;
  recorded_at: string;
}

export interface ServiceContract {
  id: number;
  contract_number: string;
  customer: number;
  customer_name: string;
  covered_equipment: number[];
  covered_equipment_names: string[];
  contract_type: ServiceContractType;
  start_date: string;
  end_date: string;
  contract_value: string;
  currency: string;
  included_visits: number;
  visits_consumed: number;
  visits_remaining: number;
  visit_history: ContractVisit[];
  visit_frequency: VisitFrequency;
  payment_terms: string;
  terms_and_conditions: string;
  renewal_reminders_enabled: boolean;
  reminder_days: number[];
  status: ServiceContractStatus;
  renewed_from: number | null;
  renewed_from_number: string | null;
  renewal_contract_number: string | null;
  days_until_expiry: number;
  created_at: string;
  updated_at: string;
}

export type ServiceContractInput = Pick<
  ServiceContract,
  | "customer"
  | "covered_equipment"
  | "contract_type"
  | "start_date"
  | "end_date"
  | "contract_value"
  | "included_visits"
  | "visit_frequency"
  | "payment_terms"
  | "terms_and_conditions"
  | "renewal_reminders_enabled"
  | "reminder_days"
  | "status"
>;

export interface ContractRenewalReminder {
  id: number;
  contract_number: string;
  customer_name: string;
  customer_email: string;
  contract_end_date: string;
  days_before_expiry: number;
  status: "pending" | "sent" | "failed";
  attempts: number;
  sent_at: string | null;
  updated_at: string;
  attempt_history: ContractRenewalReminderAttempt[];
}

export interface ContractRenewalReminderAttempt {
  attempt_number: number;
  recipient: string;
  status: "sent" | "failed";
  detail: string;
  attempted_at: string;
}

export type InvoiceStatus = "draft" | "issued" | "reversed";
export type InvoiceTaxMode = "cgst_sgst" | "igst";
export type QuotationStatus = "draft" | "sent" | "accepted" | "declined" | "converted";

export interface InvoiceLine {
  id?: number;
  description: string;
  quantity: string;
  unit_price: string;
  gst_rate: string;
  taxable_amount?: string;
  tax_amount?: string;
  cgst_amount?: string;
  sgst_amount?: string;
  igst_amount?: string;
}

export interface Invoice {
  id: number;
  invoice_number: string;
  customer: number;
  customer_name: string;
  tax_mode: InvoiceTaxMode;
  status: InvoiceStatus;
  issue_date: string | null;
  due_date: string | null;
  notes: string;
  lines: InvoiceLine[];
  subtotal: string;
  tax_total: string;
  total: string;
  allocated_total: string;
  outstanding: string;
  journal_reference: string | null;
  created_at: string;
  updated_at: string;
}

export type InvoiceInput = Pick<
  Invoice,
  "customer" | "tax_mode" | "due_date" | "notes" | "lines"
>;

export interface Quotation {
  id: number;
  quotation_number: string;
  customer: number;
  customer_name: string;
  tax_mode: InvoiceTaxMode;
  valid_until: string;
  notes: string;
  status: QuotationStatus;
  sent_at: string | null;
  accepted_at: string | null;
  declined_at: string | null;
  converted_invoice: number | null;
  converted_invoice_number: string | null;
  lines: InvoiceLine[];
  subtotal: string;
  tax_total: string;
  total: string;
  created_at: string;
  updated_at: string;
}

export type QuotationInput = Pick<
  Quotation,
  "customer" | "tax_mode" | "valid_until" | "notes" | "lines"
>;

export type PaymentMethod = "cash" | "upi" | "bank";
export type PaymentStatus = "received" | "reversed";

export interface PaymentAllocation {
  id: number;
  invoice: number;
  invoice_number: string;
  amount: string;
  idempotency_key: string;
  created_at: string;
  reversed_at: string | null;
}

export interface Payment {
  id: number;
  customer: number;
  customer_name: string;
  amount: string;
  method: PaymentMethod;
  received_on: string;
  reference: string;
  idempotency_key: string;
  status: PaymentStatus;
  allocations: PaymentAllocation[];
  unallocated_amount: string;
  journal_reference: string;
  created_at: string;
  reversed_at: string | null;
}

export interface PaymentInput {
  customer: number;
  amount: string;
  method: PaymentMethod;
  received_on: string;
  reference: string;
  idempotency_key: string;
}

export interface Expense {
  id: number;
  expense_number: string;
  description: string;
  category: string;
  amount: string;
  method: PaymentMethod;
  incurred_on: string;
  idempotency_key: string;
  status: "posted" | "reversed";
  journal_reference: string;
  created_at: string;
  reversed_at: string | null;
}

export interface CashBankTransfer {
  id: number;
  transfer_number: string;
  amount: string;
  transferred_on: string;
  reference: string;
  idempotency_key: string;
  status: "posted" | "reversed";
  journal_reference: string;
  created_at: string;
  reversed_at: string | null;
}

export interface CashBankTransferInput {
  amount: string;
  transferred_on: string;
  reference: string;
  idempotency_key: string;
}

export interface DatedReportOptions {
  date_from?: string;
  date_to?: string;
}

export interface CustomerLedger {
  customer: { id: number; name: string };
  opening_balance: string;
  closing_balance: string;
  count: number;
  next: string | null;
  previous: string | null;
  results: Array<{
    id: number;
    date: string;
    journal_reference: string;
    description: string;
    account: string;
    account_name: string;
    debit: string;
    credit: string;
    running_balance: string;
  }>;
}

export interface TrialBalanceReport {
  as_of: string | null;
  debit_balance_total: string;
  credit_balance_total: string;
  balanced: boolean;
  accounts: Array<{
    account: string;
    account_name: string;
    debits: string;
    credits: string;
    debit_balance: string;
    credit_balance: string;
  }>;
}

export interface CollectionsReport {
  date_from: string | null;
  date_to: string | null;
  receipt_count: number;
  total: string;
  by_method: Array<{ method: PaymentMethod; count: number; amount: string }>;
  by_customer: Array<{
    customer: number;
    customer_name: string;
    count: number;
    amount: string;
  }>;
}

export interface ExpensesReport {
  date_from: string | null;
  date_to: string | null;
  expense_count: number;
  total: string;
  by_category: Array<{ category: string; count: number; amount: string }>;
  by_method: Array<{ method: PaymentMethod; count: number; amount: string }>;
}

export type ExpenseInput = Pick<
  Expense,
  "description" | "category" | "amount" | "method" | "incurred_on" | "idempotency_key"
>;

export interface JournalLine {
  id: number;
  account: string;
  account_name: string;
  debit: string;
  credit: string;
}

export interface JournalEntry {
  id: number;
  reference: string;
  description: string;
  entry_date: string;
  posted: boolean;
  posted_at: string | null;
  reverses: number | null;
  lines: JournalLine[];
  debit_total: string;
  credit_total: string;
}

export interface FinancialAuditEvent {
  id: number;
  action: string;
  entity_type: string;
  entity_id: number;
  reference: string;
  actor_name: string;
  actor_email: string;
  details: Record<string, string | number | boolean | null | string[]>;
  created_at: string;
}

export interface OutstandingReport {
  invoice_count: number;
  open_invoice_count: number;
  invoiced_total: string;
  allocated_total: string;
  outstanding_total: string;
  customer_advances_total: string;
}

export interface ReconciliationReport {
  posted_journal_count: number;
  debit_total: string;
  credit_total: string;
  difference: string;
  balanced: boolean;
  receivables_reconciled: boolean;
  accounts_receivable_balance: string;
  customer_receivables_balance: string;
  receivables_subledger_difference: string;
  accounts: Array<{
    account: string;
    account_name: string;
    debits: string;
    credits: string;
    balance: string;
  }>;
}

export type ServiceJobInput = Pick<
  ServiceJob,
  | "customer"
  | "equipment"
  | "assigned_technician"
  | "service_contract"
  | "title"
  | "description"
  | "status"
  | "scheduled_for"
  | "technician_note"
  | "completion_report"
>;

export interface ServiceJobListOptions {
  status?: ServiceJobStatus;
  page?: number;
  search?: string;
  technician?: number;
  scheduled_from?: string;
  scheduled_to?: string;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

interface TokenPair {
  access: string;
  refresh: string;
}

const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api"
).replace(/\/+$/, "");

const ACCESS_TOKEN_KEY = "serviceflow.access";
const REFRESH_TOKEN_KEY = "serviceflow.refresh";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function errorMessage(data: unknown, status: number): string {
  if (typeof data === "object" && data !== null && "detail" in data) {
    const detail = data.detail;
    if (typeof detail === "string") return detail;
  }
  const messages = validationMessages(data);
  if (messages.length) return messages.join(" ");
  return `The request failed (HTTP ${status}).`;
}

function validationMessages(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(validationMessages);
  if (typeof value === "object" && value !== null) {
    return Object.values(value).flatMap(validationMessages);
  }
  return [];
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204 || response.status === 205) return undefined as T;

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError(
      `The server returned an unreadable response (HTTP ${response.status}).`,
      response.status,
    );
  }

  if (!response.ok) {
    throw new ApiError(errorMessage(data, response.status), response.status);
  }
  return data as T;
}

async function publicRequest<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${apiBaseUrl}/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseResponse<T>(response);
}

async function refreshAccessToken(): Promise<string> {
  const refresh = sessionStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refresh) throw new ApiError("Your session has expired. Please sign in again.", 401);

  const response = await fetch(`${apiBaseUrl}/auth/token/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  try {
    const tokens = await parseResponse<{ access: string }>(response);
    sessionStorage.setItem(ACCESS_TOKEN_KEY, tokens.access);
    return tokens.access;
  } catch (error) {
    clearSession();
    throw error;
  }
}

async function authorizedResponse(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let access = sessionStorage.getItem(ACCESS_TOKEN_KEY);
  if (!access && sessionStorage.getItem(REFRESH_TOKEN_KEY)) {
    access = await refreshAccessToken();
  }
  if (access) headers.set("Authorization", `Bearer ${access}`);

  let response = await fetch(`${apiBaseUrl}/${path}`, { ...init, headers });
  if (response.status === 401 && sessionStorage.getItem(REFRESH_TOKEN_KEY)) {
    access = await refreshAccessToken();
    headers.set("Authorization", `Bearer ${access}`);
    response = await fetch(`${apiBaseUrl}/${path}`, { ...init, headers });
  }

  return response;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  return parseResponse<T>(await authorizedResponse(path, init));
}

async function downloadDocument(path: string, fileName: string): Promise<void> {
  const response = await authorizedResponse(path);
  if (!response.ok) {
    return parseResponse<void>(response);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fileName;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export function hasSession(): boolean {
  return Boolean(
    sessionStorage.getItem(ACCESS_TOKEN_KEY) ||
      sessionStorage.getItem(REFRESH_TOKEN_KEY),
  );
}

export function clearSession(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  sessionStorage.removeItem("serviceflow.organization");
}

export async function getHealthStatus(
  signal?: AbortSignal,
): Promise<HealthStatus> {
  const response = await fetch(`${apiBaseUrl}/health/`, { signal });
  return parseResponse<HealthStatus>(response);
}

export async function getPublicConfiguration(): Promise<{
  registration_enabled: boolean;
}> {
  const response = await fetch(`${apiBaseUrl}/public-config/`);
  return parseResponse<{ registration_enabled: boolean }>(response);
}

export async function register(input: {
  name: string;
  email: string;
  password: string;
  organization_name: string;
}): Promise<void> {
  await publicRequest("auth/register/", input);
}

export async function login(email: string, password: string): Promise<void> {
  const tokens = await publicRequest<TokenPair>("auth/token/", {
    username: email,
    password,
  });
  sessionStorage.setItem(ACCESS_TOKEN_KEY, tokens.access);
  sessionStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh);
}

export async function requestPasswordReset(email: string): Promise<void> {
  await publicRequest<{ detail: string }>("auth/password-reset/", { email });
}

export async function verifyPasswordResetOTP(
  email: string,
  otp: string,
): Promise<{ verification_token: string }> {
  return publicRequest("auth/password-reset/verify/", { email, otp });
}

export async function requestPasswordResetEmailChange(input: {
  verification_token: string;
  new_email: string;
}): Promise<void> {
  await publicRequest<{ detail: string }>("auth/password-reset/new-email/", input);
}

export async function completePasswordReset(input: {
  verification_token: string;
  new_email: string;
  otp: string;
  new_password: string;
  confirm_password: string;
}): Promise<void> {
  await publicRequest<{ detail: string }>("auth/password-reset/complete/", input);
}

export async function logout(): Promise<void> {
  const refresh = sessionStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refresh) {
    clearSession();
    return;
  }
  try {
    await request<void>("auth/logout/", {
      method: "POST",
      body: JSON.stringify({ refresh }),
    });
  } finally {
    clearSession();
  }
}

export function getCurrentUser(): Promise<UserProfile> {
  return request("auth/me/");
}

export function createOrganization(name: string): Promise<OrganizationSummary> {
  return request("organizations/", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

function organizationPath(organizationId: number, resource: string): string {
  return `organizations/${organizationId}/${resource}/`;
}

export interface ListOptions {
  page?: number;
  search?: string;
}

function listQuery(options: ListOptions = {}): string {
  const query = new URLSearchParams();
  if (options.page && options.page > 1) query.set("page", String(options.page));
  if (options.search?.trim()) query.set("search", options.search.trim());
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

export function getCustomers(
  organizationId: number,
  options: ListOptions = {},
): Promise<Page<Customer>> {
  return request(`${organizationPath(organizationId, "customers")}${listQuery(options)}`);
}

export function getSubscriptionPlans(): Promise<SubscriptionPlan[]> {
  return request("subscription/plans/");
}

export function getOrganizationSubscription(
  organizationId: number,
): Promise<SubscriptionOverview> {
  return request(organizationPath(organizationId, "subscription"));
}

export function requestSubscriptionPlan(
  organizationId: number,
  plan: number,
): Promise<SubscriptionChangeRequest> {
  return request(organizationPath(organizationId, "subscription"), {
    method: "POST",
    body: JSON.stringify({ plan }),
  });
}

export function cancelOrganizationSubscription(
  organizationId: number,
): Promise<OrganizationSubscription> {
  return request(organizationPath(organizationId, "subscription"), {
    method: "DELETE",
  });
}

export function getSubscriptionInvoices(
  organizationId: number,
): Promise<Page<SubscriptionInvoice>> {
  return request(`${organizationPath(organizationId, "subscription")}invoices/`);
}

export function createCustomer(
  organizationId: number,
  input: Omit<Customer, "id" | "created_at" | "updated_at">,
): Promise<Customer> {
  return request(organizationPath(organizationId, "customers"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateCustomer(
  organizationId: number,
  customerId: number,
  input: Omit<Customer, "id" | "created_at" | "updated_at">,
): Promise<Customer> {
  return request(`${organizationPath(organizationId, "customers")}${customerId}/`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteCustomer(
  organizationId: number,
  customerId: number,
): Promise<void> {
  return request(`${organizationPath(organizationId, "customers")}${customerId}/`, {
    method: "DELETE",
  });
}

export function getEquipment(
  organizationId: number,
  options: ListOptions = {},
): Promise<Page<Equipment>> {
  return request(`${organizationPath(organizationId, "equipment")}${listQuery(options)}`);
}

export function createEquipment(
  organizationId: number,
  input: Omit<Equipment, "id" | "customer_name" | "created_at" | "updated_at">,
): Promise<Equipment> {
  return request(organizationPath(organizationId, "equipment"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateEquipment(
  organizationId: number,
  equipmentId: number,
  input: Omit<Equipment, "id" | "customer_name" | "created_at" | "updated_at">,
): Promise<Equipment> {
  return request(`${organizationPath(organizationId, "equipment")}${equipmentId}/`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteEquipment(
  organizationId: number,
  equipmentId: number,
): Promise<void> {
  return request(`${organizationPath(organizationId, "equipment")}${equipmentId}/`, {
    method: "DELETE",
  });
}

export function getMembers(
  organizationId: number,
): Promise<Page<OrganizationMember>> {
  return request(organizationPath(organizationId, "members"));
}

export function addMember(
  organizationId: number,
  user_email: string,
  role: OrganizationMember["role"],
): Promise<OrganizationMember> {
  return request(organizationPath(organizationId, "members"), {
    method: "POST",
    body: JSON.stringify({ user_email, role }),
  });
}

export function updateMemberRole(
  organizationId: number,
  memberId: number,
  role: OrganizationMember["role"],
): Promise<OrganizationMember> {
  return request(`${organizationPath(organizationId, "members")}${memberId}/`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeMember(
  organizationId: number,
  memberId: number,
): Promise<void> {
  return request(`${organizationPath(organizationId, "members")}${memberId}/`, {
    method: "DELETE",
  });
}

export function getServiceJobs(
  organizationId: number,
  options: ServiceJobListOptions = {},
): Promise<Page<ServiceJob>> {
  const query = new URLSearchParams();
  if (options.status) query.set("status", options.status);
  if (options.page && options.page > 1) query.set("page", String(options.page));
  if (options.search?.trim()) query.set("search", options.search.trim());
  if (options.technician) query.set("technician", String(options.technician));
  if (options.scheduled_from) query.set("scheduled_from", options.scheduled_from);
  if (options.scheduled_to) query.set("scheduled_to", options.scheduled_to);
  const serialized = query.toString();
  return request(
    `${organizationPath(organizationId, "jobs")}${serialized ? `?${serialized}` : ""}`,
  );
}

export function createServiceJob(
  organizationId: number,
  input: ServiceJobInput,
): Promise<ServiceJob> {
  return request(organizationPath(organizationId, "jobs"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateServiceJob(
  organizationId: number,
  jobId: number,
  input: Partial<ServiceJobInput>,
): Promise<ServiceJob> {
  return request(`${organizationPath(organizationId, "jobs")}${jobId}/`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteServiceJob(organizationId: number, jobId: number): Promise<void> {
  return request(`${organizationPath(organizationId, "jobs")}${jobId}/`, {
    method: "DELETE",
  });
}

export function addServiceJobWorkNote(
  organizationId: number,
  jobId: number,
  note: string,
): Promise<ServiceJobWorkNote> {
  return request(
    `${organizationPath(organizationId, "jobs")}${jobId}/notes/`,
    { method: "POST", body: JSON.stringify({ note }) },
  );
}

export function getContracts(
  organizationId: number,
  status?: ServiceContractStatus,
): Promise<Page<ServiceContract>> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request(`${organizationPath(organizationId, "contracts")}${query}`);
}

export function createContract(
  organizationId: number,
  input: ServiceContractInput,
): Promise<ServiceContract> {
  return request(organizationPath(organizationId, "contracts"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateContract(
  organizationId: number,
  contractId: number,
  input: Partial<ServiceContractInput>,
): Promise<ServiceContract> {
  return request(
    `${organizationPath(organizationId, "contracts")}${contractId}/`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export function renewContract(
  organizationId: number,
  contractId: number,
  input: { start_date: string; end_date: string; contract_value: string },
): Promise<ServiceContract> {
  return request(
    `${organizationPath(organizationId, "contracts")}${contractId}/renew/`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function getUpcomingRenewals(
  organizationId: number,
  days = 30,
): Promise<Page<ServiceContract>> {
  return request(
    `${organizationPath(organizationId, "contracts")}upcoming-renewals/?days=${days}`,
  );
}

export function getContractReminders(
  organizationId: number,
  contractId: number,
): Promise<ContractRenewalReminder[]> {
  return request(
    `${organizationPath(organizationId, "contracts")}${contractId}/reminders/`,
  );
}

export function getInvoices(
  organizationId: number,
  status?: InvoiceStatus,
): Promise<Page<Invoice>> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request(`${organizationPath(organizationId, "invoices")}${query}`);
}

export function createInvoice(
  organizationId: number,
  input: InvoiceInput,
): Promise<Invoice> {
  return request(organizationPath(organizationId, "invoices"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateInvoice(
  organizationId: number,
  invoiceId: number,
  input: Partial<InvoiceInput>,
): Promise<Invoice> {
  return request(`${organizationPath(organizationId, "invoices")}${invoiceId}/`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function issueInvoice(
  organizationId: number,
  invoiceId: number,
): Promise<Invoice> {
  return request(
    `${organizationPath(organizationId, "invoices")}${invoiceId}/issue/`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function reverseInvoice(
  organizationId: number,
  invoiceId: number,
): Promise<Invoice> {
  return request(
    `${organizationPath(organizationId, "invoices")}${invoiceId}/reverse/`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function downloadInvoicePdf(
  organizationId: number,
  invoiceId: number,
  invoiceNumber: string,
): Promise<void> {
  return downloadDocument(
    `${organizationPath(organizationId, "invoices")}${invoiceId}/document/`,
    `${invoiceNumber}.pdf`,
  );
}

export function getQuotations(organizationId: number): Promise<Page<Quotation>> {
  return request(organizationPath(organizationId, "quotations"));
}

export function createQuotation(
  organizationId: number,
  input: QuotationInput,
): Promise<Quotation> {
  return request(organizationPath(organizationId, "quotations"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateQuotation(
  organizationId: number,
  quotationId: number,
  input: Partial<QuotationInput>,
): Promise<Quotation> {
  return request(
    `${organizationPath(organizationId, "quotations")}${quotationId}/`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

export type QuotationAction = "send" | "accept" | "decline" | "convert";

export function performQuotationAction(
  organizationId: number,
  quotationId: number,
  action: QuotationAction,
): Promise<Quotation> {
  return request(
    `${organizationPath(organizationId, "quotations")}${quotationId}/${action}/`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function downloadQuotationPdf(
  organizationId: number,
  quotationId: number,
  quotationNumber: string,
): Promise<void> {
  return downloadDocument(
    `${organizationPath(organizationId, "quotations")}${quotationId}/document/`,
    `${quotationNumber}.pdf`,
  );
}

export function getPayments(organizationId: number): Promise<Page<Payment>> {
  return request(organizationPath(organizationId, "payments"));
}

export function getCashBankTransfers(
  organizationId: number,
): Promise<Page<CashBankTransfer>> {
  return request(organizationPath(organizationId, "cash-bank-transfers"));
}

export function createCashBankTransfer(
  organizationId: number,
  input: CashBankTransferInput,
): Promise<CashBankTransfer> {
  return request(organizationPath(organizationId, "cash-bank-transfers"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function reverseCashBankTransfer(
  organizationId: number,
  transferId: number,
): Promise<CashBankTransfer> {
  return request(
    `${organizationPath(organizationId, "cash-bank-transfers")}${transferId}/reverse/`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function createPayment(
  organizationId: number,
  input: PaymentInput,
): Promise<Payment> {
  return request(organizationPath(organizationId, "payments"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function allocatePayment(
  organizationId: number,
  paymentId: number,
  input: { invoice: number; amount: string; idempotency_key: string },
): Promise<PaymentAllocation> {
  return request(
    `${organizationPath(organizationId, "payments")}${paymentId}/allocations/`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export function reversePayment(
  organizationId: number,
  paymentId: number,
): Promise<Payment> {
  return request(`${organizationPath(organizationId, "payments")}${paymentId}/reverse/`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function reversePaymentAllocation(
  organizationId: number,
  paymentId: number,
  allocationId: number,
): Promise<PaymentAllocation> {
  return request(
    `${organizationPath(organizationId, "payments")}${paymentId}/allocations/${allocationId}/reverse/`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function getExpenses(organizationId: number): Promise<Page<Expense>> {
  return request(organizationPath(organizationId, "expenses"));
}

export function createExpense(
  organizationId: number,
  input: ExpenseInput,
): Promise<Expense> {
  return request(organizationPath(organizationId, "expenses"), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function reverseExpense(
  organizationId: number,
  expenseId: number,
): Promise<Expense> {
  return request(`${organizationPath(organizationId, "expenses")}${expenseId}/reverse/`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function getJournals(organizationId: number): Promise<Page<JournalEntry>> {
  return request(organizationPath(organizationId, "journals"));
}

export function getFinancialAuditEvents(
  organizationId: number,
): Promise<Page<FinancialAuditEvent>> {
  return request(organizationPath(organizationId, "financial-audit"));
}

export function getOutstandingReport(
  organizationId: number,
): Promise<OutstandingReport> {
  return request(`${organizationPath(organizationId, "reports")}outstanding/`);
}

function datedReportQuery(options: DatedReportOptions = {}): string {
  const query = new URLSearchParams();
  if (options.date_from) query.set("date_from", options.date_from);
  if (options.date_to) query.set("date_to", options.date_to);
  const serialized = query.toString();
  return serialized ? `?${serialized}` : "";
}

export function getCustomerLedger(
  organizationId: number,
  customerId: number,
  options: DatedReportOptions = {},
): Promise<CustomerLedger> {
  return request(
    `${organizationPath(organizationId, "reports")}customers/${customerId}/ledger/${datedReportQuery(options)}`,
  );
}

export function getTrialBalance(
  organizationId: number,
  asOf?: string,
): Promise<TrialBalanceReport> {
  const query = asOf ? `?${new URLSearchParams({ as_of: asOf })}` : "";
  return request(`${organizationPath(organizationId, "reports")}trial-balance/${query}`);
}

export function getCollectionsReport(
  organizationId: number,
  options: DatedReportOptions = {},
): Promise<CollectionsReport> {
  return request(
    `${organizationPath(organizationId, "reports")}collections/${datedReportQuery(options)}`,
  );
}

export function getExpensesReport(
  organizationId: number,
  options: DatedReportOptions = {},
): Promise<ExpensesReport> {
  return request(
    `${organizationPath(organizationId, "reports")}expenses/${datedReportQuery(options)}`,
  );
}

export function getReconciliationReport(
  organizationId: number,
): Promise<ReconciliationReport> {
  return request(`${organizationPath(organizationId, "reports")}reconciliation/`);
}
