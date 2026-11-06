/** Client checks mirroring the backend (the backend stays the authority). */

const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$/;
const POS_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$/;
const CONTROL_RE = /[\u0000-\u001f\u007f]/;

export type ShopValues = { name: string; branch_name: string; code: string; pos_id: string };
export type ShopErrors = Partial<Record<keyof ShopValues | "fbr_token", string>>;

export const normalize = (value: string) => value.trim().replace(/\s+/g, " ");

function textProblem(raw: string, label: string): string | null {
  if (CONTROL_RE.test(raw)) return `${label} contains characters that are not allowed.`;
  const value = normalize(raw);
  if (!value) return `Enter the ${label.toLowerCase()}.`;
  if (value.length > 120) return `${label} must be at most 120 characters.`;
  return null;
}

export function validateShop(values: ShopValues): ShopErrors {
  const errors: ShopErrors = {};
  const name = textProblem(values.name, "Shop Name");
  if (name) errors.name = name;
  const branch = textProblem(values.branch_name, "Branch Name");
  if (branch) errors.branch_name = branch;
  if (!CODE_RE.test(values.code.trim())) {
    errors.code =
      "Use 1-20 letters, digits, hyphens or underscores, starting with a letter or digit.";
  }
  if (!POS_ID_RE.test(values.pos_id.trim())) {
    errors.pos_id =
      "Use 1-50 letters, digits, hyphens or underscores, starting with a letter or digit.";
  }
  return errors;
}

export function tokenProblem(raw: string): string | null {
  const value = raw.trim();
  if (!value) return "Enter the FBR token.";
  if (value.length < 8 || value.length > 2048) return "The FBR token must be 8-2048 characters.";
  if (/[^\x21-\x7e]/.test(value)) {
    return "The FBR token may contain only printable characters without spaces.";
  }
  return null;
}

/** Backend conflict/validation codes mapped to the field they belong to. */
export const FIELD_FOR_CODE: Record<string, keyof ShopErrors> = {
  shop_code_taken: "code",
  pos_id_taken: "pos_id",
  invalid_name: "name",
  invalid_branch_name: "branch_name",
  invalid_code: "code",
  invalid_pos_id: "pos_id",
  invalid_fbr_token: "fbr_token",
};
