/** Client checks mirroring the backend (the backend stays the authority). */

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const CONTROL_RE = /[\u0000-\u001f\u007f]/;

export type NewUserValues = { full_name: string; email: string; role_id: string };
export type NewUserErrors = Partial<Record<keyof NewUserValues, string>>;

export function validateFullName(raw: string): string | null {
  const name = raw.trim();
  if (!name) return "Enter the full name.";
  if (name.length > 200) return "The full name must be at most 200 characters.";
  if (CONTROL_RE.test(raw)) return "The full name contains characters that are not allowed.";
  return null;
}

export function validateNewUser(values: NewUserValues): NewUserErrors {
  const errors: NewUserErrors = {};
  const name = validateFullName(values.full_name);
  if (name) errors.full_name = name;
  const email = values.email.trim();
  if (!email || email.length > 320 || !EMAIL_RE.test(email) || CONTROL_RE.test(email)) {
    errors.email = "Enter a valid email address.";
  }
  if (!values.role_id) errors.role_id = "Choose a role.";
  return errors;
}

export function setupLinkFor(token: string, origin: string): string {
  return `${origin}/set-password#token=${encodeURIComponent(token)}`;
}
