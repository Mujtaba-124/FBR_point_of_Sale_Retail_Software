/**
 * Shop inputs hold business identifiers and integration secrets, never sign-in
 * credentials. Browser password managers decide what to fill from page
 * structure (a password-type field plus the text field before it, or any
 * formless inputs on the page), and Chrome ignores autocomplete="off" for
 * them. So these fields:
 *   - are never type="password" (the FBR token is masked with CSS instead),
 *   - always live inside a <form> of their own,
 *   - have neutral, non-credential names,
 *   - carry the opt-out hints honoured by common password managers.
 */
export const NO_CREDENTIAL_AUTOFILL = {
  autoComplete: "off",
  autoCorrect: "off",
  autoCapitalize: "none",
  spellCheck: false,
  "data-1p-ignore": "true", // 1Password
  "data-lpignore": "true", // LastPass
  "data-bwignore": "true", // Bitwarden
  "data-form-type": "other", // Dashlane
} as const;

/** Masks a text input like a password field without making it one. */
export const MASKED_TEXT = "[-webkit-text-security:disc] [text-security:disc]";
