// A short instruction the user saves once and that rides along with every
// generation — school, course, or cultural context they would otherwise retype.
//
// Kept deliberately small. The model's context window also has to hold the
// prompt, any attached images, and the generated artifact, so this is capped and
// collapsed to a single line rather than being a second prompt box.

/** Matches the cap the backend enforces in `_normalize_custom_context`. */
export const CUSTOM_CONTEXT_MAX_CHARS = 300;

const STORAGE_PREFIX = "app.customContext";

const storageKey = (email?: string | null) =>
  email ? `${STORAGE_PREFIX}.${email}` : STORAGE_PREFIX;

/** Collapse to one line and cap. Applied on input, not just on save. */
export function normalizeCustomContext(value: string): string {
  return value.replace(/\s+/g, " ").trimStart().slice(0, CUSTOM_CONTEXT_MAX_CHARS);
}

export function loadCustomContext(email?: string | null): string {
  try {
    return localStorage.getItem(storageKey(email)) ?? "";
  } catch {
    // Storage blocked; behave as if nothing was saved.
    return "";
  }
}

export function saveCustomContext(email: string | null | undefined, value: string): void {
  const normalized = normalizeCustomContext(value).trim();
  try {
    if (normalized) localStorage.setItem(storageKey(email), normalized);
    else localStorage.removeItem(storageKey(email));
  } catch {
    // Storage blocked; the value still applies for this session via component state.
  }
}
