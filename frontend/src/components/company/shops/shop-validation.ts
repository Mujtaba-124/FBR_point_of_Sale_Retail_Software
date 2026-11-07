/** Client checks mirroring the backend (the backend stays the authority). */

const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$/;
const POS_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$/;
const CONTROL_RE = /[\u0000-\u001f\u007f]/;

export type ShopValues = { name: string; branch_name: string; code: string; pos_id: string; sales_tax_rate: string };
export type ShopErrors = Partial<Record<keyof ShopValues | "fbr_token", string>>;

export const normalize = (value: string) => value.trim().replace(/\s+/g, " ");

function textProblem(raw: string, label: string): string | null {
  if (CONTROL_RE.test(raw)) return `${label} contains characters that are not allowed.`;
  const value = normalize(raw);
  if (!value) return `Enter the ${label.toLowerCase()}.`;
  if (value.length > 120) return `${label} must be at most 120 characters.`;
  return null;
}

const TAX_RATE_RE = /^\d{1,3}(\.\d{1,2})?$/;

/** Sales Tax %: 0-100, at most 2 decimals, digits only ("18", "17.5", "0"). */
export function taxRateProblem(raw: string): string | null {
  const value = raw.trim().replace(/%$/, "").trim();
  if (!value) return "Enter the Sales Tax %.";
  if (!TAX_RATE_RE.test(value)) return "Use a number from 0 to 100 with at most 2 decimal places.";
  if (toHundredths(value) > BigInt(10000)) return "Sales Tax % cannot be more than 100.";
  return null;
}

/** Exact comparison of rate strings without floats: "18" and "18.00" are equal. */
export function toHundredths(value: string): bigint {
  const [whole, fraction = ""] = value.trim().replace(/%$/, "").trim().split(".");
  return BigInt(whole || "0") * BigInt(100) + BigInt((fraction + "00").slice(0, 2));
}

/** "18.00" -> "18%", "17.50" -> "17.5%", null -> "Not configured". */
export function formatTaxRate(rate: string | null | undefined): string {
  if (rate === null || rate === undefined || rate === "") return "Not configured";
  const text = rate.includes(".") ? rate.replace(/0+$/, "").replace(/\.$/, "") : rate;
  return `${text}%`;
}

export function validateShop(
  values: ShopValues,
  { taxRateRequired }: { taxRateRequired: boolean } = { taxRateRequired: true },
): ShopErrors {
  const errors: ShopErrors = {};
  if (taxRateRequired || values.sales_tax_rate.trim()) {
    const tax = taxRateProblem(values.sales_tax_rate);
    if (tax) errors.sales_tax_rate = tax;
  }
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
  invalid_sales_tax_rate: "sales_tax_rate",
};
