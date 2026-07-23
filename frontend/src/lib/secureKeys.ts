import type { ApiKeys } from "@/types";
import {
  EMPTY_API_KEYS,
  PROVIDER_IDS,
  normalizeApiKeys,
} from "@/lib/providerConfig";
import { isDesktopLocalMode } from "@/lib/runtime";

export const EMPTY_KEYS: ApiKeys = { ...EMPTY_API_KEYS };

function settingsKey(email: string): string {
  return `app.settings.${email}`;
}

function secureOptInKey(email: string): string {
  return `app.secureKeysOptIn.${email}`;
}

function normalizeKeys(raw: any, fallback: ApiKeys = EMPTY_KEYS): ApiKeys {
  return normalizeApiKeys(raw, fallback);
}

function localMetadataOnly(keys: ApiKeys): ApiKeys {
  const normalized = normalizeKeys(keys);
  for (const provider of PROVIDER_IDS) {
    normalized[provider] = "";
  }
  return normalized;
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

  if (
    !isDesktopLocalMode() ||
    !hasDesktopSecureStore() ||
    !isSecureStorageEnabledForUser(email)
  ) {
    return local;
  }

  try {
    const secure = await window.desktop!.secureStore!.getApiKeys(email);
    if (!secure) return local;

    const normalizedSecure = normalizeKeys(secure, local);
    const merged = { ...local, ...normalizedSecure } as ApiKeys;
    for (const provider of PROVIDER_IDS) {
      merged[provider] = normalizedSecure[provider] || "";
    }
    return merged;
  } catch {
    return local;
  }
}

export async function persistApiKeysForUser(
  email: string,
  keys: ApiKeys
): Promise<void> {
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
  } catch {}

  setSecureStorageEnabledForUser(email, false);
}

export async function persistApiKeysSecurelyForUser(
  email: string,
  keys: ApiKeys
): Promise<{ ok: boolean; reason?: string }> {
  const normalized = normalizeKeys(keys);

  if (!isDesktopLocalMode() || !hasDesktopSecureStore()) {
    writeLocalSettings(email, normalized);
    setSecureStorageEnabledForUser(email, false);
    return { ok: false, reason: "secure_store_unavailable" };
  }

  try {
    const result = await window.desktop!.secureStore!.setApiKeys(email, normalized);
    if (!result?.ok) {
      throw new Error(result?.reason || "secure_store_unavailable");
    }

    writeLocalSettings(email, localMetadataOnly(normalized));
    setSecureStorageEnabledForUser(email, true);
    return { ok: true };
  } catch {
    writeLocalSettings(email, normalized);
    setSecureStorageEnabledForUser(email, false);
    return { ok: false, reason: "secure_store_unavailable" };
  }
}

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
