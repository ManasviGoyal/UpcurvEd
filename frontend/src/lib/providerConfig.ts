export const PROVIDER_IDS = [
  "gemini",
  "claude",
  "openai",
  "openrouter",
] as const;

export type ProviderId = (typeof PROVIDER_IDS)[number];
export type Provider = ProviderId | "";

export interface ApiKeys extends Record<ProviderId, string> {
  provider?: Provider;
  model?: string;
}

export interface ProviderUiConfig {
  label: string;
  keyLabel: string;
  keyPlaceholder: string;
  models: readonly string[];
  help: string;
}

export const PROVIDER_PRIORITY: readonly ProviderId[] = [
  "gemini",
  "claude",
  "openai",
  "openrouter",
];

export const PROVIDER_CONFIG: Record<ProviderId, ProviderUiConfig> = {
  gemini: {
    label: "Gemini (Google)",
    keyLabel: "Gemini API Key",
    keyPlaceholder: "Enter your Gemini API key",
    models: [
      "gemini-3-flash-preview",
      "gemini-3.1-pro-preview",
      "gemini-3.1-flash-lite-preview",
    ],
    help: "Choose a Gemini model, or type another exact Google model ID.",
  },
  claude: {
    label: "Claude (Anthropic)",
    keyLabel: "Claude API Key",
    keyPlaceholder: "Enter your Claude API key",
    models: [
      "claude-haiku-4-5",
      "claude-sonnet-4-6",
      "claude-opus-4-7",
    ],
    help: "Choose a Claude model, or type another exact Anthropic model ID.",
  },
  openai: {
    label: "OpenAI",
    keyLabel: "OpenAI API Key",
    keyPlaceholder: "Enter your OpenAI API key",
    models: ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6"],
    help: "Choose an OpenAI model, or type another exact OpenAI model ID.",
  },
  openrouter: {
    label: "OpenRouter",
    keyLabel: "OpenRouter API Key",
    keyPlaceholder: "Enter your OpenRouter API key",
    models: [
      "nvidia/nemotron-3-ultra-550b-a55b:free",
      "openai/gpt-oss-20b:free",
      "openrouter/free",
    ],
    help:
      "Choose a specific OpenRouter model, or type any exact OpenRouter model ID.",
  },
};

export const AUTO_PROVIDER_LABEL = "Auto (by available key)";
export const NO_PROVIDER_MODEL_HELP = "Select a provider first.";

export const EMPTY_API_KEYS: ApiKeys = {
  gemini: "",
  claude: "",
  openai: "",
  openrouter: "",
  provider: "",
  model: "",
};

export function normalizeApiKeys(
  raw?: Partial<ApiKeys> | null,
  fallback: Partial<ApiKeys> = EMPTY_API_KEYS
): ApiKeys {
  const result = { ...EMPTY_API_KEYS } as ApiKeys;
  for (const provider of PROVIDER_IDS) {
    result[provider] = String(raw?.[provider] ?? fallback?.[provider] ?? "");
  }
  result.provider = (String(raw?.provider ?? fallback?.provider ?? "") as Provider) || "";
  result.model = String(raw?.model ?? fallback?.model ?? "");
  return result;
}

export function providerKeysFromApiKeys(
  keys?: Partial<ApiKeys> | null
): Record<ProviderId, string> {
  const normalized = normalizeApiKeys(keys);
  return Object.fromEntries(
    PROVIDER_IDS.map((provider) => [provider, normalized[provider]])
  ) as Record<ProviderId, string>;
}

export function inferProvider(keys?: Partial<ApiKeys> | null): Provider {
  const normalized = normalizeApiKeys(keys);
  for (const provider of PROVIDER_PRIORITY) {
    if (normalized[provider]) return provider;
  }
  return "";
}

export function selectedProvider(keys?: Partial<ApiKeys> | null): Provider {
  const normalized = normalizeApiKeys(keys);
  return normalized.provider || inferProvider(normalized);
}

export function hasSelectedProviderKey(keys?: Partial<ApiKeys> | null): boolean {
  const normalized = normalizeApiKeys(keys);
  const provider = selectedProvider(normalized);
  return Boolean(provider && normalized[provider]);
}

export function providerDisplayName(provider?: Provider | null): string {
  return provider ? PROVIDER_CONFIG[provider].label : "an LLM provider";
}

export function apiKeysChanged(
  before?: Partial<ApiKeys> | null,
  after?: Partial<ApiKeys> | null
): boolean {
  const a = normalizeApiKeys(before);
  const b = normalizeApiKeys(after);
  return (
    a.provider !== b.provider ||
    a.model !== b.model ||
    PROVIDER_IDS.some((provider) => a[provider] !== b[provider])
  );
}

export function apiKeysFingerprint(keys?: Partial<ApiKeys> | null): string {
  const normalized = normalizeApiKeys(keys);
  return JSON.stringify([
    normalized.provider || "",
    normalized.model || "",
    ...PROVIDER_IDS.map((provider) => normalized[provider]),
  ]);
}

export function buildLlmRequestConfig(keys?: Partial<ApiKeys> | null): {
  keys: Record<ProviderId, string>;
  provider: ProviderId | undefined;
  model: string | undefined;
} {
  const normalized = normalizeApiKeys(keys);
  const provider = selectedProvider(normalized) || undefined;
  return {
    keys: providerKeysFromApiKeys(normalized),
    provider,
    model: normalized.model || undefined,
  };
}
