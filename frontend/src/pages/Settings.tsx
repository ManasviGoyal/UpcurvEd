import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import type { ApiKeys, Provider, User } from "@/types";
import { loadApiKeysForUser, persistApiKeysForUser } from "@/lib/secureKeys";

interface SettingsPageProps {
  setView: (view: string) => void;
  user: User;
  apiKeys: ApiKeys;
  setApiKeys: (keys: ApiKeys) => void;
  asDialog?: boolean; // when true, render without full-page background so it can be used in an overlay
}

const PROVIDER_LABELS: Record<Provider, string> = {
  "": "Auto (by available key)",
  "claude": "Claude (Anthropic)",
  "gemini": "Gemini (Google)",
};

const PROVIDER_MODELS: Record<Provider, string[]> = {
  "": [],
  "claude": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-20241022", "claude-sonnet-4-5-20250929"],
  "gemini": ["gemini-2.5-pro"],
};

export const SettingsPage = ({ setView, user, apiKeys, setApiKeys, asDialog }: SettingsPageProps) => {
  const [localKeys, setLocalKeys] = useState<ApiKeys>({
    claude: apiKeys.claude || "",
    gemini: apiKeys.gemini || "",
    provider: apiKeys.provider || "",
    model: apiKeys.model || "",
  });

  useEffect(() => {
    let cancelled = false;
    async function hydrate() {
      const loaded = await loadApiKeysForUser(user.email, apiKeys);
      if (!cancelled) {
        setLocalKeys(loaded);
      }
    }
    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [user.email, apiKeys]);

  const handleSave = async () => {
    setApiKeys(localKeys);
    await persistApiKeysForUser(user.email, localKeys);
    setView("chat");
  };

  const handleProviderChange = (provider: Provider) => {
    const defaultModel = PROVIDER_MODELS[provider][0] || "";
    setLocalKeys(prev => ({ ...prev, provider, model: provider ? (prev.model || defaultModel) : "" }));
  };


  return (
    <div className={`flex items-center justify-center min-h-screen ${asDialog ? 'bg-transparent' : 'bg-secondary'}`}>
      <Card className="w-full max-w-md p-8">
        <h2 className="text-2xl font-bold mb-6">Settings</h2>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium">Gemini API Key</label>
            <Input
              type="password"
              value={localKeys.gemini}
              onChange={e => setLocalKeys({ ...localKeys, gemini: e.target.value })}
              placeholder="Enter your Gemini API key"
            />
          </div>

          <div>
            <label className="text-sm font-medium">Claude API Key</label>
            <Input
              type="password"
              value={localKeys.claude}
              onChange={e => setLocalKeys({ ...localKeys, claude: e.target.value })}
              placeholder="Enter your Claude API key"
            />
          </div>

          <div className="grid grid-cols-1 gap-2">
            <label className="text-sm font-medium">Provider</label>
            <select
              className="border rounded px-3 py-2 bg-background"
              value={localKeys.provider || ""}
              onChange={e => handleProviderChange(e.target.value as Provider)}
            >
              {Object.entries(PROVIDER_LABELS).map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-1 gap-2">
            <label className="text-sm font-medium">Model (optional)</label>
            <select
              className="border rounded px-3 py-2 bg-background"
              value={localKeys.model || ""}
              onChange={e => setLocalKeys({ ...localKeys, model: e.target.value })}
              disabled={!localKeys.provider}
            >
              <option value="">{localKeys.provider ? "Choose…" : "Select provider first"}</option>
              {(PROVIDER_MODELS[localKeys.provider || ""] || []).map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-6 flex flex-col gap-4">
          <div className="flex gap-4">
            <Button onClick={handleSave} className="flex-1">Save</Button>
            <Button onClick={() => setView("chat")} variant="outline" className="flex-1">Cancel</Button>
          </div>
        </div>
      </Card>
    </div>
  );
};
