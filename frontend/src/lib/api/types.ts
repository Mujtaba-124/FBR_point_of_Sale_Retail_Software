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

export type WorkspaceResponse = { workspace: Workspace; user: CurrentUser };

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
