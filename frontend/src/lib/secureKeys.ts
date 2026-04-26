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
  if (!isDesktopLocalMode() || !hasDesktopSecureStore()) {
    writeLocalSettings(email, normalizeKeys(keys));
    return;
  }
  // Keep non-sensitive provider/model in local settings.
  writeLocalSettings(email, {
    claude: "",
    gemini: "",
    provider: keys.provider || "",
    model: keys.model || "",
  });
  try {
    await window.desktop!.secureStore!.setApiKeys(email, normalizeKeys(keys));
  } catch {
    // Fallback: if secure store fails, keep prior behavior so user is not blocked.
    writeLocalSettings(email, normalizeKeys(keys));
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
