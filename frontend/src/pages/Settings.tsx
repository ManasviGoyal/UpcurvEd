import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import type { ApiKeys, Provider, User } from "@/types";
import {
  AUTO_PROVIDER_LABEL,
  NO_PROVIDER_MODEL_HELP,
  PROVIDER_CONFIG,
  PROVIDER_IDS,
  normalizeApiKeys,
} from "@/lib/providerConfig";
import { apiFetch } from "@/lib/api";
import {
  clearSecurelyStoredApiKeysForUser,
  isSecureStorageEnabledForUser,
  loadApiKeysForUser,
  persistApiKeysForUser,
  persistApiKeysSecurelyForUser,
} from "@/lib/secureKeys";

// Sentinel for the "type your own model ID" entry. Prefixed so it can never
// collide with a real provider model ID.
const CUSTOM_MODEL_OPTION = "__custom_model__";

interface SettingsPageProps {
  setView: (view: string) => void;
  user: User;
  apiKeys: ApiKeys;
  setApiKeys: (keys: ApiKeys) => void;
  asDialog?: boolean;
  onUpdateName?: (name: string) => void;
  desktopLocal?: boolean;
  onResetLocalData?: () => void;
}

export const SettingsPage = ({
  setView,
  user,
  apiKeys,
  setApiKeys,
  asDialog,
  onUpdateName,
  desktopLocal = false,
  onResetLocalData,
}: SettingsPageProps) => {
  const [displayName, setDisplayName] = useState<string>(user.name || "");
  const [localKeys, setLocalKeys] = useState<ApiKeys>(() => normalizeApiKeys(apiKeys));
  const [secureStorageEnabled, setSecureStorageEnabled] = useState<boolean>(false);
  const [useSecureStorage, setUseSecureStorage] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [exportBusy, setExportBusy] = useState<boolean>(false);
  const [exportStatus, setExportStatus] = useState<string>("");
  const [customModelSelected, setCustomModelSelected] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      const loaded = await loadApiKeysForUser(user.email);
      if (!cancelled) {
        const secureEnabled = desktopLocal
          ? isSecureStorageEnabledForUser(user.email)
          : false;
        setLocalKeys(normalizeApiKeys(loaded));
        setSecureStorageEnabled(secureEnabled);
        setUseSecureStorage(secureEnabled);
      }
    }

    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [user.email, desktopLocal]);

  const handleSave = async () => {
    const trimmedName = displayName.trim();
    if (trimmedName && trimmedName !== user.name && onUpdateName) {
      onUpdateName(trimmedName);
    }

    setBusy(true);
    setStatusMessage("");

    try {
      const keysToSave = normalizeApiKeys(localKeys);

      if (desktopLocal && useSecureStorage) {
        const result = await persistApiKeysSecurelyForUser(user.email, keysToSave);
        setApiKeys(keysToSave);

        if (result.ok) {
          setSecureStorageEnabled(true);
          setUseSecureStorage(true);
          setView("chat");
          return;
        }

        setSecureStorageEnabled(false);
        setUseSecureStorage(false);
        setStatusMessage(
          "Secure storage is unavailable on this device, so keys were saved locally instead."
        );
        setView("chat");
        return;
      }

      await clearSecurelyStoredApiKeysForUser(user.email);
      await persistApiKeysForUser(user.email, keysToSave);
      setApiKeys(keysToSave);
      setSecureStorageEnabled(false);
      setUseSecureStorage(false);
      setView("chat");
    } finally {
      setBusy(false);
    }
  };

  const handleExportDiagnostics = async () => {
    if (!desktopLocal || exportBusy) return;
    setExportBusy(true);
    setExportStatus("");

    try {
      const response = await apiFetch("/diagnostics/generation-export", {
        method: "GET",
      });
      if (!response.ok) {
        let detail = "Could not export generation diagnostics.";
        try {
          const payload = await response.json();
          detail = String(payload?.detail || detail);
        } catch {}
        throw new Error(detail);
      }

      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const filenameMatch = disposition.match(/filename\*?=(?:UTF-8''|["']?)([^"';\n]+)/i);
      const filename = filenameMatch?.[1]
        ? decodeURIComponent(filenameMatch[1].trim())
        : "upcurved_generation_diagnostics.zip";
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      setExportStatus("Generation diagnostics exported.");
    } catch (error: any) {
      setExportStatus(
        error?.message || "Could not export generation diagnostics."
      );
    } finally {
      setExportBusy(false);
    }
  };

  const handleProviderChange = (provider: Provider) => {
    const models = provider ? PROVIDER_CONFIG[provider].models : [];
    const defaultModel = models[0] || "";

    // The new provider's presets are unrelated to the old one's, so drop back to
    // the preset dropdown instead of leaving the custom-ID input open.
    setCustomModelSelected(false);

    setLocalKeys((previous) => ({
      ...previous,
      provider,
      model: provider
        ? models.includes(previous.model || "")
          ? previous.model
          : defaultModel
        : "",
    }));
  };

  const selectedProvider = localKeys.provider || "";
  const selectedProviderConfig = selectedProvider
    ? PROVIDER_CONFIG[selectedProvider]
    : null;
  const selectedProviderModels = selectedProviderConfig?.models || [];
  const modelSelectId = `provider-model-${selectedProvider || "none"}`;

  // A saved model that isn't one of the listed presets (e.g. typed by hand, or a
  // preset that has since been removed) must still show as the current selection.
  const isCustomModel =
    Boolean(selectedProvider) &&
    (customModelSelected || (Boolean(localKeys.model) && !selectedProviderModels.includes(localKeys.model || "")));

  return (
    <div
      className={`flex min-h-0 items-start justify-center overflow-hidden p-3 sm:items-center sm:p-6 ${
        asDialog ? "bg-transparent" : "min-h-screen bg-secondary"
      }`}
    >
      <Card
        className="
          w-full max-w-md
          max-h-[calc(100dvh-1.5rem)]
          overflow-y-auto
          overscroll-contain
          p-5 sm:max-h-[calc(100dvh-3rem)] sm:p-8
        "
      >
        <h2 className="text-2xl font-bold mb-6">Settings</h2>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium">Your Name</label>
            <Input
              type="text"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Enter your display name"
            />
          </div>

          {PROVIDER_IDS.map((provider) => {
            const config = PROVIDER_CONFIG[provider];
            return (
              <div key={provider}>
                <label className="text-sm font-medium">{config.keyLabel}</label>
                <Input
                  type="password"
                  value={localKeys[provider]}
                  onChange={(event) =>
                    setLocalKeys((previous) => ({
                      ...previous,
                      [provider]: event.target.value,
                    }))
                  }
                  placeholder={config.keyPlaceholder}
                />
              </div>
            );
          })}

          <div className="grid grid-cols-1 gap-2">
            <label className="text-sm font-medium">Provider</label>
            <select
              className="border rounded px-3 py-2 bg-background"
              value={selectedProvider}
              onChange={(event) => handleProviderChange(event.target.value as Provider)}
            >
              <option value="">{AUTO_PROVIDER_LABEL}</option>
              {PROVIDER_IDS.map((provider) => (
                <option key={provider} value={provider}>
                  {PROVIDER_CONFIG[provider].label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-1 gap-2">
            <label className="text-sm font-medium" htmlFor={modelSelectId}>
              Model
            </label>
            <select
              id={modelSelectId}
              className="border rounded px-3 py-2 bg-background"
              value={isCustomModel ? CUSTOM_MODEL_OPTION : localKeys.model || ""}
              disabled={!selectedProvider}
              onChange={(event) => {
                const next = event.target.value;
                // Switching to "custom" clears the field so the text input starts empty
                // rather than inheriting the model that was selected a moment ago.
                setCustomModelSelected(next === CUSTOM_MODEL_OPTION);
                setLocalKeys((previous) => ({
                  ...previous,
                  model: next === CUSTOM_MODEL_OPTION ? "" : next,
                }));
              }}
            >
              {!selectedProvider && <option value="">Select provider first</option>}
              {selectedProviderModels.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
              {selectedProvider && (
                <option value={CUSTOM_MODEL_OPTION}>Other — enter a model ID…</option>
              )}
            </select>

            {isCustomModel && (
              <Input
                autoFocus
                value={localKeys.model || ""}
                onChange={(event) =>
                  setLocalKeys((previous) => ({
                    ...previous,
                    model: event.target.value,
                  }))
                }
                placeholder="Exact model ID"
              />
            )}

            <p className="text-xs text-muted-foreground">
              {selectedProviderConfig?.help || NO_PROVIDER_MODEL_HELP}
            </p>
          </div>

          {desktopLocal && (
            <div className="rounded border p-3">
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium">Secure key storage</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Store API keys in your OS keychain when available. Saving may show a system
                    prompt.
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Currently: {secureStorageEnabled ? "Secure OS storage" : "Local storage"}
                  </p>
                </div>
                <Switch
                  checked={useSecureStorage}
                  onCheckedChange={setUseSecureStorage}
                  disabled={busy}
                />
              </div>
            </div>
          )}

          {statusMessage && (
            <p className="text-sm text-muted-foreground">{statusMessage}</p>
          )}
        </div>

        <div className="mt-6 flex flex-col gap-4">
          <div className="flex gap-4">
            <Button onClick={handleSave} className="flex-1" disabled={busy}>
              Save
            </Button>
            <Button
              onClick={() => setView("chat")}
              variant="outline"
              className="flex-1"
              disabled={busy}
            >
              Cancel
            </Button>
          </div>

          {desktopLocal && onResetLocalData && (
            <div className="pt-2 border-t">
              <Button
                onClick={onResetLocalData}
                variant="destructive"
                className="w-full"
                disabled={busy}
              >
                Reset local data
              </Button>
            </div>
          )}

          {desktopLocal && (
            <div className="pt-4 border-t space-y-3">
              <div>
                <p className="text-sm font-medium">Export generation diagnostics</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Download a privacy-safe summary of video generation performance.
                </p>
              </div>
              <Button
                onClick={handleExportDiagnostics}
                variant="outline"
                className="w-full"
                disabled={busy || exportBusy}
              >
                {exportBusy ? "Preparing export..." : "Export generation diagnostics"}
              </Button>
              {exportStatus && (
                <p className="text-xs text-muted-foreground">{exportStatus}</p>
              )}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
};
