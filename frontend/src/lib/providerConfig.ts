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
  /** Bare product name, interpolated into translated strings ("{provider} API Key").
   *  Not translated: these are proper nouns that stay identical in every language. */
  shortName: string;
  models: readonly string[];
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
    shortName: "Gemini",
    models: [
      "gemini-3-flash-preview",
      "gemini-3.7-flash",
      "gemini-3.1-pro-preview",
      "gemini-3.1-flash-lite",
      "gemini-2.5-flash",
      "gemini-2.5-pro",
    ],
  },
  claude: {
    label: "Claude (Anthropic)",
    shortName: "Claude",
    models: [
      "claude-haiku-4-5",
      "claude-sonnet-5",
      "claude-sonnet-4-6",
      "claude-opus-5",
      "claude-opus-4-8",
      "claude-opus-4-7",
    ],
  },
  openai: {
    label: "OpenAI",
    shortName: "OpenAI",
    models: [
      "gpt-5.6",
      "gpt-5.6-sol",
      "gpt-5.6-terra",
      "gpt-5.6-luna",
    ],
  },
  openrouter: {
    label: "OpenRouter",
    shortName: "OpenRouter",
    models: [
      "nvidia/nemotron-3-ultra-550b-a55b:free",
      "openai/gpt-oss-20b:free",
      "openrouter/free",
      "nvidia/nemotron-3.5-lightning:free",
      "nvidia/nemotron-3-super-120b-a12b:free",
      "google/gemma-4-31b-it:free",
    ],
  },
};


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
