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
import {
  clearSecurelyStoredApiKeysForUser,
  isSecureStorageEnabledForUser,
  loadApiKeysForUser,
  persistApiKeysForUser,
  persistApiKeysSecurelyForUser,
} from "@/lib/secureKeys";

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

  const handleProviderChange = (provider: Provider) => {
    const models = provider ? PROVIDER_CONFIG[provider].models : [];
    const defaultModel = models[0] || "";

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
  const modelListId = `provider-models-${selectedProvider || "none"}`;

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
            <label className="text-sm font-medium">Model</label>
            <Input
              list={modelListId}
              value={localKeys.model || ""}
              onChange={(event) =>
                setLocalKeys((previous) => ({
                  ...previous,
                  model: event.target.value,
                }))
              }
              disabled={!selectedProvider}
              placeholder={
                selectedProvider
                  ? "Choose or type exact model ID"
                  : "Select provider first"
              }
            />
            <datalist id={modelListId}>
              {selectedProviderModels.map((model) => (
                <option key={model} value={model} />
              ))}
            </datalist>
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
        </div>
      </Card>
    </div>
  );
};
