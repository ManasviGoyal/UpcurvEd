// frontend/src/pages/Settings.tsx
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import type { ApiKeys, Provider, User } from "@/types";
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

const PROVIDER_LABELS: Record<Provider, string> = {
  "": "Auto (by available key)",
  claude: "Claude (Anthropic)",
  gemini: "Gemini (Google)",
};

const PROVIDER_MODELS: Record<Provider, string[]> = {
  "": [],
  "claude": ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-7"],
  "gemini": ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite-preview"],
};

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
  const [localKeys, setLocalKeys] = useState<ApiKeys>({
    claude: apiKeys.claude || "",
    gemini: apiKeys.gemini || "",
    provider: apiKeys.provider || "",
    model: apiKeys.model || "",
  });
  const [secureStorageEnabled, setSecureStorageEnabled] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      const loaded = await loadApiKeysForUser(user.email);
      if (!cancelled) {
        setLocalKeys(loaded);
        setSecureStorageEnabled(desktopLocal ? isSecureStorageEnabledForUser(user.email) : false);
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
      await persistApiKeysForUser(user.email, localKeys);
      setApiKeys(localKeys);
      setSecureStorageEnabled(false);
      setView("chat");
    } finally {
      setBusy(false);
    }
  };

  const handleSaveSecurely = async () => {
    const trimmedName = displayName.trim();
    if (trimmedName && trimmedName !== user.name && onUpdateName) {
      onUpdateName(trimmedName);
    }

    setBusy(true);
    setStatusMessage("");
    try {
      const result = await persistApiKeysSecurelyForUser(user.email, localKeys);
      setApiKeys(localKeys);

      if (result.ok) {
        setSecureStorageEnabled(true);
        setView("chat");
        return;
      }

      setSecureStorageEnabled(false);
      setStatusMessage(
        "Secure storage was unavailable, so the keys were saved locally on this device instead."
      );
    } finally {
      setBusy(false);
    }
  };

  const handleRemoveSecure = async () => {
    setBusy(true);
    setStatusMessage("");
    try {
      await clearSecurelyStoredApiKeysForUser(user.email);
      await persistApiKeysForUser(user.email, localKeys);
      setApiKeys(localKeys);
      setSecureStorageEnabled(false);
      setStatusMessage("Securely saved keys were removed. Current values are now stored locally only.");
    } finally {
      setBusy(false);
    }
  };

  const handleProviderChange = (provider: Provider) => {
    const defaultModel = PROVIDER_MODELS[provider][0] || "";
    setLocalKeys((prev) => ({
      ...prev,
      provider,
      model: provider ? (prev.model || defaultModel) : "",
    }));
  };

  return (
    <div className={`flex items-center justify-center min-h-screen ${asDialog ? "bg-transparent" : "bg-secondary"}`}>
      <Card className="w-full max-w-md p-8">
        <h2 className="text-2xl font-bold mb-6">Settings</h2>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium">Your Name</label>
            <Input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Enter your display name"
            />
          </div>

          <div>
            <label className="text-sm font-medium">Gemini API Key</label>
            <Input
              type="password"
              value={localKeys.gemini}
              onChange={(e) => setLocalKeys({ ...localKeys, gemini: e.target.value })}
              placeholder="Enter your Gemini API key"
            />
          </div>

          <div>
            <label className="text-sm font-medium">Claude API Key</label>
            <Input
              type="password"
              value={localKeys.claude}
              onChange={(e) => setLocalKeys({ ...localKeys, claude: e.target.value })}
              placeholder="Enter your Claude API key"
            />
          </div>

          <div className="grid grid-cols-1 gap-2">
            <label className="text-sm font-medium">Provider</label>
            <select
              className="border rounded px-3 py-2 bg-background"
              value={localKeys.provider || ""}
              onChange={(e) => handleProviderChange(e.target.value as Provider)}
            >
              {Object.entries(PROVIDER_LABELS).map(([val, label]) => (
                <option key={val} value={val}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-1 gap-2">
            <label className="text-sm font-medium">Model (optional)</label>
            <select
              className="border rounded px-3 py-2 bg-background"
              value={localKeys.model || ""}
              onChange={(e) => setLocalKeys({ ...localKeys, model: e.target.value })}
              disabled={!localKeys.provider}
            >
              <option value="">{localKeys.provider ? "Choose…" : "Select provider first"}</option>
              {(PROVIDER_MODELS[localKeys.provider || ""] || []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>

          {desktopLocal && (
            <div className="rounded border p-3 text-sm">
              <p className="font-medium mb-1">Secure storage</p>
              <p className="text-muted-foreground mb-2">
                “Save” stores your API keys locally on this device.
                “Save API Keys Securely” stores them in your OS keychain and may show a system prompt.
              </p>
              <p className="text-muted-foreground">
                Status: {secureStorageEnabled ? "Using secure storage" : "Using local storage only"}
              </p>
            </div>
          )}

          {statusMessage && <p className="text-sm text-muted-foreground">{statusMessage}</p>}
        </div>

        <div className="mt-6 flex flex-col gap-3">
          <div className="flex gap-4">
            <Button onClick={handleSave} className="flex-1" disabled={busy}>
              Save
            </Button>
            <Button onClick={() => setView("chat")} variant="outline" className="flex-1" disabled={busy}>
              Cancel
            </Button>
          </div>

          {desktopLocal && (
            <>
              <Button onClick={handleSaveSecurely} variant="secondary" className="w-full" disabled={busy}>
                Save API Keys Securely
              </Button>

              {secureStorageEnabled && (
                <Button onClick={handleRemoveSecure} variant="outline" className="w-full" disabled={busy}>
                  Remove Securely Saved Keys
                </Button>
              )}
            </>
          )}

          {desktopLocal && onResetLocalData && (
            <Button onClick={onResetLocalData} variant="destructive" className="w-full" disabled={busy}>
              Reset local data
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
};