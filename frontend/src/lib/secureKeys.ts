import type { ApiKeys } from "@/types";
import { isDesktopLocalMode } from "@/lib/runtime";

const EMPTY_KEYS: ApiKeys = {
  claude: "",
  gemini: "",
  provider: "",
  model: "",
};

function settingsKey(email: string): string {
  return `app.settings.${email}`;
}

function normalizeKeys(raw: any, fallback: ApiKeys = EMPTY_KEYS): ApiKeys {
  return {
    claude: String(raw?.claude ?? fallback.claude ?? ""),
    gemini: String(raw?.gemini ?? fallback.gemini ?? ""),
    provider: (String(raw?.provider ?? fallback.provider ?? "") as ApiKeys["provider"]) || "",
    model: String(raw?.model ?? fallback.model ?? ""),
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
    localStorage.setItem(settingsKey(email), JSON.stringify(keys));
  } catch {}
}

function hasDesktopSecureStore(): boolean {
  return Boolean(window.desktop?.secureStore);
}

export async function loadApiKeysForUser(
  email: string,
  fallback: ApiKeys = EMPTY_KEYS
): Promise<ApiKeys> {
  const local = readLocalSettings(email, fallback);
  if (!isDesktopLocalMode() || !hasDesktopSecureStore()) {
    return local;
  }
  try {
    const secure = await window.desktop!.secureStore!.getApiKeys(email);
    if (!secure) return local;
    const normalizedSecure = normalizeKeys(secure, local);
    return {
      ...local,
      ...normalizedSecure,
      claude: normalizedSecure.claude || local.claude || "",
      gemini: normalizedSecure.gemini || local.gemini || "",
    };
  } catch {
    return local;
  }
}

export async function persistApiKeysForUser(email: string, keys: ApiKeys): Promise<void> {
  // Always keep a local copy in desktop mode so restarts never lose keys,
  // even when keytar/secret service is unavailable.
  writeLocalSettings(email, normalizeKeys(keys));
  if (!isDesktopLocalMode() || !hasDesktopSecureStore()) {
    return;
  }
  try {
    const result = await window.desktop!.secureStore!.setApiKeys(email, normalizeKeys(keys));
    // `setApiKeys` can resolve with `{ ok: false }` when secure storage is unavailable
    // (for example keytar not installed). Treat that as failure and fall back.
    if (!result?.ok) {
      throw new Error(result?.reason || "secure_store_unavailable");
    }
  } catch {
    // Local copy is already written above.
  }
}

export async function clearApiKeysForUser(email: string): Promise<void> {
  try {
    localStorage.removeItem(settingsKey(email));
  } catch {}
  if (!isDesktopLocalMode() || !hasDesktopSecureStore()) return;
  try {
    await window.desktop!.secureStore!.clearApiKeys(email);
  } catch {}
}
