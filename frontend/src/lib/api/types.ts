/** API response types shared by client and server code. */

export type AccessCategory = "super_admin" | "company_admin" | "company_user";
export type Workspace = "super_admin" | "company";

export type CurrentUser = {
  id: string;
  email: string;
  full_name: string;
  access_category: AccessCategory;
  workspace: Workspace;
  /** From /auth/me only. null for the Super Admin. */
  company_access?: { allowed: boolean; code: SubscriptionErrorCode | null } | null;
};

/** Backend codes for Company access refused by the subscription. */
export type SubscriptionErrorCode =
  | "subscription_expired"
  | "subscription_not_started"
  | "subscription_not_configured";

export const SUBSCRIPTION_ERROR_CODES: readonly SubscriptionErrorCode[] = [
  "subscription_expired",
  "subscription_not_started",
  "subscription_not_configured",
];

export type LoginResponse = { user: CurrentUser };

/** `permissions` are display hints only: the backend re-checks every request. */
export type WorkspaceResponse = {
  workspace: Workspace;
  user: CurrentUser;
  permissions?: string[];
  /** Company Workspace: this account uses the All Shops / shop selector. */
  shop_context_enabled?: boolean;
};

export type ApiErrorBody = { error: { code: string; message: string } };

/** Computed by the backend in Asia/Karachi calendar days; the UI only displays it. */
export type SubscriptionStatus =
  | "not_configured"
  | "invalid"
  | "scheduled"
  | "active"
  | "expiring_soon"
  | "expired";

export type Subscription = {
  status: SubscriptionStatus;
  start_date: string | null; // YYYY-MM-DD
  expiry_date: string | null;
  last_renewed_on: string | null;
  total_days: number | null;
  days_used: number | null;
  days_remaining: number | null;
  days_until_start: number | null;
  progress_percent: number | null;
  expiring_soon_threshold_days: number;
};

export type CompanyAdminContact = {
  status: "available" | "not_found" | "multiple";
  count: number;
  full_name: string | null;
  email: string | null;
  is_active: boolean | null;
};

export type RenewalRules = {
  can_renew: boolean;
  min_new_expiry_date: string | null;
  max_new_expiry_date: string | null;
};

export type SubscriptionManagement = {
  today: string;
  timezone: "Asia/Karachi";
  company: { name: string | null; account_type: "single_company" };
  subscription: Subscription;
  renewal: RenewalRules;
};

export type Renewal = {
  id: string;
  renewed_at: string; // ISO timestamp (UTC)
  previous_expiry_date: string;
  new_expiry_date: string;
  renewal_note: string | null;
  renewed_by: { full_name: string; email: string };
};

export type RenewalPage = { items: Renewal[]; total: number; limit: number; offset: number };

export type RenewRequest = {
  new_expiry_date: string;
  expected_expiry_date: string;
  idempotency_key: string;
  renewal_note: string | null;
};

export type RenewResponse = { renewal: Renewal; subscription: Subscription; replayed: boolean };

export type SuperAdminDashboard = {
  today: string;
  timezone: "Asia/Karachi";
  company: { name: string | null; account_type: "single_company" };
  company_admin: CompanyAdminContact;
  subscription: Subscription;
};

// --- Email settings ----------------------------------------------------------

export type EmailSettingsStatus = "not_configured" | "configured" | "disabled";
export type EncryptionMode = "starttls" | "ssl";

/** The SMTP password is write-only: the API reports only whether one is stored. */
export type SmtpSettings = {
  smtp_host: string;
  smtp_port: number;
  encryption_mode: EncryptionMode;
  smtp_username: string | null;
  password_set: boolean;
  password_readable: boolean;
  sender_email: string;
  sender_name: string;
  is_enabled: boolean;
  version: number;
  updated_at: string;
};

export type EmailTestHistory = {
  last_test_status: "success" | "failure" | null;
  last_test_kind: "connection" | "email" | null;
  last_test_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_failure_code: string | null;
  last_failure_message: string | null;
};

export type EmailSettings = {
  status: EmailSettingsStatus;
  encryption_ready: boolean;
  allowed_ports: number[];
  settings: SmtpSettings | null;
  history: EmailTestHistory | null;
};

export type SaveEmailSettingsRequest = {
  smtp_host: string;
  smtp_port: number;
  encryption_mode: EncryptionMode;
  smtp_username: string | null;
  /** Blank keeps the stored password. */
  smtp_password: string | null;
  sender_email: string;
  sender_name: string;
  expected_version: number | null;
};

export type EmailCheckResult = {
  kind: "connection" | "email";
  ok: boolean;
  code: string | null;
  message: string;
  tested_at: string;
  replayed: boolean;
  email_settings: EmailSettings;
};

// --- Subscription expiry reminders --------------------------------------------

export type ReminderSettings = {
  is_enabled: boolean;
  notify_super_admin: boolean;
  notify_company_admin: boolean;
  version: number;
  updated_at: string;
};

export type ReminderOverview = {
  settings: ReminderSettings;
  schedule: {
    days_before: number;
    days_after: number;
    send_time: string; // "09:00" PKT
    timezone: "Asia/Karachi";
    expiry_date: string | null;
    window_start: string | null;
    window_end: string | null;
    today: string;
    today_stage: string | null;
    next_reminder_date: string | null;
  };
  /** Emails are masked by the backend. */
  recipients: {
    super_admin_status: "selected" | "none" | "ambiguous" | "invalid" | "disabled";
    super_admin_email: string | null;
    company_admin_emails: string[];
    company_admins_without_valid_email: number;
  };
  readiness: { email_configured: boolean; email_enabled: boolean };
  last_run: {
    at: string | null;
    business_date: string | null;
    result: string | null;
    queued: number | null;
    already_queued: number | null;
  };
};

export type OutboxStatus =
  | "pending"
  | "processing"
  | "retry_scheduled"
  | "accepted"
  | "failed_permanent"
  | "cancelled_obsolete"
  | "cancelled";

export type ReminderHistoryItem = {
  id: string;
  scheduled_date: string;
  expiry_date: string;
  days_offset: number;
  stage: string;
  recipient_categories: ("super_admin" | "company_admin")[];
  recipient: string; // masked
  status: OutboxStatus;
  attempt_count: number;
  max_attempts: number;
  last_attempt_at: string | null;
  next_attempt_at: string | null;
  accepted_at: string | null;
  reason_code: string | null;
  reason: string | null;
};

export type ReminderHistoryPage = {
  items: ReminderHistoryItem[];
  total: number;
  limit: number;
  offset: number;
  counts: Record<OutboxStatus, number>;
};

export const WORKSPACE_PATHS: Record<Workspace, string> = {
  super_admin: "/super-admin",
  company: "/company",
};

/** Session cookie names (secure production name and local HTTP name). */
export const SESSION_COOKIE_NAMES = ["__Host-cheena_session", "cheena_session"] as const;
export const CSRF_COOKIE_NAMES = ["__Host-cheena_csrf", "cheena_csrf"] as const;

// --- Company dashboard ----------------------------------------------------------

/** `available: false` means the module is not built yet: `value` is null, not zero. */
export type DashboardMetric = {
  available: boolean;
  value: number | null;
  unavailable_reason: string | null;
};

export type CompanyDashboard = {
  company: { name: string | null };
  metrics: {
    total_shops: DashboardMetric;
    active_shops: DashboardMetric;
    active_users: DashboardMetric;
    pending_approvals: DashboardMetric;
    pending_fbr_sync: DashboardMetric;
  };
  sales_overview: { available: false; unavailable_reason: string };
  recent_uploads: { available: false; unavailable_reason: string };
  shop_allowance: ShopAllowanceSummary;
  /** The shop context the response was built for. */
  context: ShopContextInfo;
  /** "company" = always company-wide; "context" = follows the selected shop. */
  metric_scopes: Record<string, "company" | "context">;
};

// --- Company User Management + Roles & Permissions --------------------------------

export type UserCapacity = { active: number; limit: number; available: number; inactive: number };

export type RoleRef = { id: string; name: string; is_system: boolean; is_active: boolean };

export type CompanyUser = {
  id: string;
  full_name: string;
  email: string;
  tier: "company_admin" | "company_user";
  is_protected: boolean;
  status: "active" | "inactive";
  role: RoleRef | null;
  setup_pending: boolean;
  setup_link_expires_at: string | null;
  last_login_at: string | null;
  created_at: string;
  shop_access: ShopAccessSummary;
};

// --- User shop access (Phase 3.3) ----------------------------------------------------

/** "company" = the protected Company Admin: every shop, not editable. */
export type ShopScopeMode = "company" | "all" | "selected" | "none";
export type ShopAccessMode = Exclude<ShopScopeMode, "company">;

export type ShopAccessSummary = { mode: ShopScopeMode; shop_count: number | null };

export type AssignableShop = { id: string; name: string; code: string; status: "active" | "inactive" };

export type ShopAccessDetail = ShopAccessSummary & {
  shops: AssignableShop[];
  editable: boolean;
  version: number | null;
  updated_at: string | null;
};

export type ShopAccessUpdate = { access: ShopAccessDetail; changed: boolean };

export type AssignableShops = { items: AssignableShop[]; total: number };

export type CompanyUserPage = {
  items: CompanyUser[];
  total: number;
  limit: number;
  offset: number;
  capacity: UserCapacity;
};

/** The raw token appears once; the link is /set-password#token=<token>. */
export type SetupLinkIssued = {
  user: CompanyUser;
  setup_token: string;
  setup_expires_at: string;
  capacity: UserCapacity;
};

export type UserActionResult = { user: CompanyUser; capacity: UserCapacity };

export type CompanyRoleItem = {
  id: string;
  name: string;
  description: string | null;
  system_key: "company_admin" | "company_user" | null;
  is_system: boolean;
  is_active: boolean;
  permissions: string[];
  active_users: number;
  total_users: number;
  version: number;
  updated_at: string;
};

export type CapabilityColumn = "view" | "create" | "edit" | "delete" | "special";

export type PermissionModule = {
  key: string;
  label: string;
  available: boolean;
  admin_only: boolean;
  capabilities: { key: string; label: string; column: CapabilityColumn }[];
};

export type PermissionCatalog = { modules: PermissionModule[]; baseline: string[] };

export type RoleListPayload = { items: CompanyRoleItem[] };

// --- Shop Management ----------------------------------------------------------------

/** The FBR token itself is never sent to the browser; only its status. */
export type Shop = {
  id: string;
  name: string;
  branch_name: string;
  code: string;
  pos_id: string;
  status: "active" | "inactive";
  fbr_token_status: "configured" | "not_configured" | "unreadable";
  fbr_token_updated_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type ShopSummary = { total: number; active: number; inactive: number };

export type ShopPage = {
  items: Shop[];
  total: number;
  limit: number;
  offset: number;
  summary: ShopSummary;
  allowance: ShopAllowanceSummary;
};

// --- Shop Allowance (set by the Super Admin; aggregate counts only) ------------------

/** Unlimited has `max_shops: null` and `available_slots: null`, never a sentinel number.
 *  `registered_shops` counts active and inactive shops. */
export type ShopAllowanceSummary = {
  mode: "limited" | "unlimited";
  max_shops: number | null;
  registered_shops: number;
  available_slots: number | null;
  at_capacity: boolean;
  over_limit: boolean;
};

export type ShopAllowance = ShopAllowanceSummary & { version: number; last_updated_at: string | null };

export type ShopAllowanceUpdate = { allowance: ShopAllowance; changed: boolean };

// --- Shop context (All Shops / one shop) ------------------------------------------------

/** Selector option: immutable ID, display name and code only (no POS ID, no token). */
export type ShopOption = { id: string; name: string; code: string };

export type ShopSelectionStatus = "all" | "active" | "inactive" | "not_found" | "invalid";

export type ShopOptions = {
  items: ShopOption[];
  total: number;
  truncated: boolean;
  selection: { status: ShopSelectionStatus; shop: ShopOption | null };
  /** The account's shop scope and what its "All" option means. */
  access: { mode: ShopScopeMode; all_label: string };
};

export type ShopContextInfo = { scope: "all" | "shop"; shop: ShopOption | null };
