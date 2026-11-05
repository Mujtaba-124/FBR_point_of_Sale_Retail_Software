import type { EncryptionMode, SaveEmailSettingsRequest, SmtpSettings } from "@/lib/api/types";

/** Client-side checks mirroring the backend; the backend remains the authority. */

export type SmtpFormValues = {
  smtp_host: string;
  smtp_port: string;
  encryption_mode: EncryptionMode;
  smtp_username: string;
  smtp_password: string;
  sender_email: string;
  sender_name: string;
};

export type SmtpFormErrors = Partial<Record<keyof SmtpFormValues, string>>;

export const DEFAULT_PORT: Record<EncryptionMode, number> = { starttls: 587, ssl: 465 };
export const GMAIL_HOST = "smtp.gmail.com";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const LABEL_RE = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;
const CONTROL_RE = /[\u0000-\u001f\u007f]/;

export function emptyValues(): SmtpFormValues {
  return {
    smtp_host: "",
    smtp_port: "587",
    encryption_mode: "starttls",
    smtp_username: "",
    smtp_password: "",
    sender_email: "",
    sender_name: "Cheena FBR POS",
  };
}

export function valuesFrom(settings: SmtpSettings | null): SmtpFormValues {
  if (!settings) return emptyValues();
  return {
    smtp_host: settings.smtp_host,
    smtp_port: String(settings.smtp_port),
    encryption_mode: settings.encryption_mode,
    smtp_username: settings.smtp_username ?? "",
    smtp_password: "",
    sender_email: settings.sender_email,
    sender_name: settings.sender_name,
  };
}

export function isValidEmail(value: string): boolean {
  const email = value.trim();
  return email.length <= 320 && EMAIL_RE.test(email) && !CONTROL_RE.test(email);
}

export function hostProblem(raw: string): string | null {
  const host = raw.trim().replace(/\.$/, "").toLowerCase();
  if (!host) return "Enter the SMTP host.";
  if (host.length > 253) return "The SMTP host is too long.";
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local")) {
    return "This SMTP host is not allowed. Use a public mail server such as smtp.gmail.com.";
  }
  if (/^[\d.]+$/.test(host) || host.includes(":")) return null; // IP literal: checked by the server
  const labels = host.split(".");
  if (labels.length < 2 || !labels.every((l) => LABEL_RE.test(l))) {
    return "Enter a valid host name, for example smtp.gmail.com.";
  }
  return null;
}

export function validateSmtpForm(
  values: SmtpFormValues,
  opts: { allowedPorts: number[]; passwordStored: boolean },
): SmtpFormErrors {
  const errors: SmtpFormErrors = {};
  const host = hostProblem(values.smtp_host);
  if (host) errors.smtp_host = host;

  const port = Number(values.smtp_port);
  if (!Number.isInteger(port) || !opts.allowedPorts.includes(port)) {
    errors.smtp_port = "Use port 587 (STARTTLS) or 465 (SSL/TLS).";
  }

  const username = values.smtp_username.trim();
  if (username.length > 320 || CONTROL_RE.test(username)) {
    errors.smtp_username = "The SMTP username is not valid.";
  }
  if (username && !values.smtp_password && !opts.passwordStored) {
    errors.smtp_password = "Enter the SMTP password.";
  } else if (values.smtp_password.length > 256) {
    errors.smtp_password = "The SMTP password must be at most 256 characters.";
  } else if (CONTROL_RE.test(values.smtp_password)) {
    errors.smtp_password = "The SMTP password contains characters that are not allowed.";
  }

  if (!isValidEmail(values.sender_email)) errors.sender_email = "Enter a valid sender email address.";

  const name = values.sender_name.trim();
  if (!name) errors.sender_name = "Enter the sender name.";
  else if (name.length > 100) errors.sender_name = "The sender name must be at most 100 characters.";
  else if (CONTROL_RE.test(values.sender_name)) {
    errors.sender_name = "The sender name contains characters that are not allowed.";
  }
  return errors;
}

export function toRequest(
  values: SmtpFormValues,
  expectedVersion: number | null,
): SaveEmailSettingsRequest {
  const username = values.smtp_username.trim();
  return {
    smtp_host: values.smtp_host.trim(),
    smtp_port: Number(values.smtp_port),
    encryption_mode: values.encryption_mode,
    smtp_username: username || null,
    smtp_password: values.smtp_password || null,
    sender_email: values.sender_email.trim(),
    sender_name: values.sender_name.trim(),
    expected_version: expectedVersion,
  };
}

export function isDirty(values: SmtpFormValues, settings: SmtpSettings | null): boolean {
  const saved = valuesFrom(settings);
  return (Object.keys(saved) as (keyof SmtpFormValues)[]).some((k) =>
    k === "smtp_password" ? values.smtp_password !== "" : values[k].trim() !== saved[k].trim(),
  );
}
