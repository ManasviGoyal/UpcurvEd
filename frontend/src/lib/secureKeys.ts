import type { ApiKeys } from "@/types";
import { isDesktopLocalMode } from "@/lib/runtime";

export const EMPTY_KEYS: ApiKeys = {
  claude: "",
  gemini: "",
  provider: "",
  model: "",
};

function settingsKey(email: string): string {
  return `app.settings.${email}`;
}

function secureOptInKey(email: string): string {
  return `app.secureKeysOptIn.${email}`;
}

function normalizeKeys(raw: any, fallback: ApiKeys = EMPTY_KEYS): ApiKeys {
  return {
    claude: String(raw?.claude ?? fallback.claude ?? ""),
    gemini: String(raw?.gemini ?? fallback.gemini ?? ""),
    provider: (String(raw?.provider ?? fallback.provider ?? "") as ApiKeys["provider"]) || "",
    model: String(raw?.model ?? fallback.model ?? ""),
  };
}

function localMetadataOnly(keys: ApiKeys): ApiKeys {
  const normalized = normalizeKeys(keys);
  return {
    ...normalized,
    claude: "",
    gemini: "",
  };
}

function readLocalSettings(email: string, fallback: ApiKeys = EMPTY_KEYS): ApiKeys {
  try {
    const raw = localStorage.getItem(settingsKey(email));
    if (!raw) return normalizeKeys({}, fallback);
    return normalizeKeys(JSON.parse(raw), fallback);
  } catch {
    return normalizeKeys({}, fallback);
  }
}

function writeLocalSettings(email: string, keys: ApiKeys): void {
  try {
    localStorage.setItem(settingsKey(email), JSON.stringify(normalizeKeys(keys)));
  } catch {}
}

function hasDesktopSecureStore(): boolean {
  return Boolean(window.desktop?.secureStore);
}

export function isSecureStorageEnabledForUser(email: string): boolean {
  try {
    return localStorage.getItem(secureOptInKey(email)) === "1";
  } catch {
    return false;
  }
}

function setSecureStorageEnabledForUser(email: string, enabled: boolean): void {
  try {
    if (enabled) {
      localStorage.setItem(secureOptInKey(email), "1");
    } else {
      localStorage.removeItem(secureOptInKey(email));
    }
  } catch {}
}

export async function loadApiKeysForUser(
  email: string,
  fallback: ApiKeys = EMPTY_KEYS
): Promise<ApiKeys> {
  const local = readLocalSettings(email, fallback);

  // Never touch secure storage unless the user explicitly opted in.
  if (!isDesktopLocalMode() || !hasDesktopSecureStore() || !isSecureStorageEnabledForUser(email)) {
    return local;
  }

  try {
    const secure = await window.desktop!.secureStore!.getApiKeys(email);
    if (!secure) return local;

    const normalizedSecure = normalizeKeys(secure, local);
    return {
      ...local,
      ...normalizedSecure,
      claude: normalizedSecure.claude || "",
      gemini: normalizedSecure.gemini || "",
    };
  } catch {
    return local;
  }
}

// Local-only save. If secure storage had previously been enabled, disable it.
export async function persistApiKeysForUser(email: string, keys: ApiKeys): Promise<void> {
  writeLocalSettings(email, normalizeKeys(keys));

  if (!isDesktopLocalMode() || !hasDesktopSecureStore()) {
    setSecureStorageEnabledForUser(email, false);
    return;
  }

  if (!isSecureStorageEnabledForUser(email)) {
    setSecureStorageEnabledForUser(email, false);
    return;
  }

  try {
    await window.desktop!.secureStore!.clearApiKeys(email);
  } catch {
    // Keep local save even if secure clear fails.
  }

  setSecureStorageEnabledForUser(email, false);
}

// Explicit opt-in secure save.
export async function persistApiKeysSecurelyForUser(
  email: string,
  keys: ApiKeys
): Promise<{ ok: boolean; reason?: string }> {
  const normalized = normalizeKeys(keys);

  if (!isDesktopLocalMode() || !hasDesktopSecureStore()) {
    // Fall back to local save only.
    writeLocalSettings(email, normalized);
    setSecureStorageEnabledForUser(email, false);
    return { ok: false, reason: "secure_store_unavailable" };
  }

  try {
    const result = await window.desktop!.secureStore!.setApiKeys(email, normalized);
    if (!result?.ok) {
      throw new Error(result?.reason || "secure_store_unavailable");
    }

    // Keep only non-secret metadata locally. Actual keys live in secure storage.
    writeLocalSettings(email, localMetadataOnly(normalized));
    setSecureStorageEnabledForUser(email, true);
    return { ok: true };
  } catch {
    // If secure save fails, keep the user from losing data by saving locally instead.
    writeLocalSettings(email, normalized);
    setSecureStorageEnabledForUser(email, false);
    return { ok: false, reason: "secure_store_unavailable" };
  }
}

// Clears only the secure-store copy and disables secure loading.
// It does not remove the local settings entry.
export async function clearSecurelyStoredApiKeysForUser(email: string): Promise<void> {
  setSecureStorageEnabledForUser(email, false);

  if (!isDesktopLocalMode() || !hasDesktopSecureStore()) return;

  try {
    await window.desktop!.secureStore!.clearApiKeys(email);
  } catch {}
}

export async function clearApiKeysForUser(email: string): Promise<void> {
  try {
    localStorage.removeItem(settingsKey(email));
  } catch {}

  await clearSecurelyStoredApiKeysForUser(email);
}