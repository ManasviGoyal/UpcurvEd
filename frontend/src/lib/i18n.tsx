// Deterministic UI translations.
//
// Every string comes from src/lib/translations.json — a plain lookup table keyed by
// string id, then by language code. No model call, no network request, so the same
// language always renders exactly the same words, offline included. A key with no
// entry for the active language falls back to English, and an unknown key renders
// itself so a typo is visible rather than blank.
import {
  Fragment,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// One file per surface so no single table becomes unmanageable. They are merged
// into one lookup at import time; a key must live in exactly one file.
import appStrings from "./translations/app.json";
import homeStrings from "./translations/home.json";
import setupStrings from "./translations/setup.json";

export type LanguageCode =
  | "en"
  | "es"
  | "pt"
  | "fr"
  | "it"
  | "hi"
  | "zh-Hans"
  | "id"
  | "ja";

export type Language = {
  code: LanguageCode;
  /** Shown in the picker — always in the language itself, as is conventional. */
  label: string;
  /** For screen readers and `title` text on the trigger button. */
  englishName: string;
};

// Order follows the picker mock: English first, then the rest as designed.
export const LANGUAGES: Language[] = [
  { code: "en", label: "English", englishName: "English" },
  { code: "es", label: "Español", englishName: "Spanish" },
  { code: "pt", label: "Português", englishName: "Portuguese" },
  { code: "fr", label: "Français", englishName: "French" },
  { code: "it", label: "Italiano", englishName: "Italian" },
  { code: "hi", label: "हिन्दी", englishName: "Hindi" },
  { code: "zh-Hans", label: "简体中文", englishName: "Chinese (Simplified)" },
  { code: "id", label: "Bahasa Indonesia", englishName: "Indonesian" },
  { code: "ja", label: "日本語", englishName: "Japanese" },
];

export const DEFAULT_LANGUAGE: LanguageCode = "en";

// Not scoped per user: the picker is on the signed-out landing page too, and someone
// who reads Hindi reads Hindi before and after signing in.
const LANGUAGE_STORAGE_KEY = "app.language";

// `strings` keeps each table one level down so the files can carry a `_comment`
// note (JSON has no comments) without it looking like a translatable key.
const SOURCES: Record<string, Record<string, Record<string, string>>> = {
  home: homeStrings.strings,
  app: appStrings.strings,
  setup: setupStrings.strings,
};

function buildTable(): Record<string, Record<string, string>> {
  const merged: Record<string, Record<string, string>> = {};
  const origin: Record<string, string> = {};

  for (const [file, entries] of Object.entries(SOURCES)) {
    for (const [key, values] of Object.entries(entries)) {
      // A key defined twice would resolve by file order, which is invisible at the
      // call site and a nightmare to debug — surface it while editing instead.
      if (import.meta.env.DEV && origin[key]) {
        console.error(`[i18n] duplicate key "${key}" in ${origin[key]}.json and ${file}.json`);
      }
      origin[key] = file;
      merged[key] = values;
    }
  }

  return merged;
}

const TABLE = buildTable();

const isLanguageCode = (value: unknown): value is LanguageCode =>
  typeof value === "string" && LANGUAGES.some((language) => language.code === value);

/**
 * Closest supported language for a BCP-47 tag from the browser.
 * `zh-CN`/`zh-SG`/`zh-Hans-*` map to Simplified Chinese; `zh-TW`/`zh-HK` do not,
 * because we ship no Traditional translation and English beats wrong-script text.
 */
export function matchLanguage(tag: string | undefined | null): LanguageCode | null {
  if (!tag) return null;
  const normalized = tag.toLowerCase();

  if (normalized.startsWith("zh")) {
    const simplified =
      normalized.includes("hans") ||
      normalized === "zh" ||
      normalized.startsWith("zh-cn") ||
      normalized.startsWith("zh-sg") ||
      normalized.startsWith("zh-my");
    return simplified ? "zh-Hans" : null;
  }

  // Indonesian was renamed from `in`, which some older platforms still report.
  const base = normalized.split("-")[0];
  if (base === "in") return "id";
  // Hebrew/Yiddish had the same rename treatment; not supported, but keep the guard
  // from mapping them onto something wrong.
  if (base === "iw" || base === "ji") return null;

  const match = LANGUAGES.find((language) => language.code.split("-")[0] === base);
  return match ? match.code : null;
}

/** First run only: honour the browser's preferred languages, in order. */
function detectLanguage(): LanguageCode {
  if (typeof navigator === "undefined") return DEFAULT_LANGUAGE;

  const candidates = [...(navigator.languages || []), navigator.language];
  for (const candidate of candidates) {
    const matched = matchLanguage(candidate);
    if (matched) return matched;
  }
  return DEFAULT_LANGUAGE;
}

export function readStoredLanguage(): LanguageCode | null {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return isLanguageCode(stored) ? stored : null;
  } catch {
    return null;
  }
}

/** Substitutes `{name}` placeholders; unknown placeholders are left alone. */
function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole
  );
}

export function translate(
  key: string,
  language: LanguageCode,
  vars?: Record<string, string | number>
): string {
  const entry = TABLE[key];
  if (!entry) {
    if (import.meta.env.DEV) console.warn(`[i18n] missing key: ${key}`);
    return key;
  }
  const value = entry[language] ?? entry[DEFAULT_LANGUAGE] ?? key;
  return interpolate(value, vars);
}

export type Translate = (key: string, vars?: Record<string, string | number>) => string;

type LanguageContextValue = {
  language: LanguageCode;
  setLanguage: (next: LanguageCode) => void;
  t: Translate;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  // Stored choice wins over browser detection, and both are read before first paint
  // so the UI never flashes English and then swaps.
  const [language, setLanguageState] = useState<LanguageCode>(
    () => readStoredLanguage() ?? detectLanguage()
  );

  useEffect(() => {
    // Screen readers and hyphenation both key off this.
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = useCallback((next: LanguageCode) => {
    setLanguageState(next);
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
    } catch {
      // Private browsing or a blocked storage quota; the choice still applies for this session.
    }
  }, []);

  const value = useMemo<LanguageContextValue>(
    () => ({
      language,
      setLanguage,
      t: (key, vars) => translate(key, language, vars),
    }),
    [language, setLanguage]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

/**
 * Renders a translated string that contains inline markup, e.g.
 * `"Follow the {guide} to get started."` with `components={{ guide: <Link ... /> }}`.
 *
 * Splitting such a sentence into "before" and "after" keys would force every language
 * into English word order; keeping it whole lets each translation put the link where
 * its own grammar wants it. Placeholders with no matching component fall back to
 * `vars`, then to the literal token.
 */
export function Trans({
  k,
  vars,
  components,
}: {
  k: string;
  vars?: Record<string, string | number>;
  components?: Record<string, ReactNode>;
}) {
  const { language } = useLanguage();
  const text = translate(k, language, vars);

  if (!components) return <>{text}</>;

  const pieces = text.split(/(\{\w+\})/g).filter((piece) => piece !== "");

  return (
    <>
      {pieces.map((piece, index) => {
        const token = /^\{(\w+)\}$/.exec(piece);
        const node = token ? components[token[1]] : undefined;
        return node !== undefined ? (
          <Fragment key={index}>{node}</Fragment>
        ) : (
          <Fragment key={index}>{piece}</Fragment>
        );
      })}
    </>
  );
}

/**
 * Works outside the provider too — it falls back to the stored/detected language and
 * a no-op setter, so a component can be rendered in isolation (tests, storybook-style
 * previews) without being wrapped.
 */
export function useLanguage(): LanguageContextValue {
  const context = useContext(LanguageContext);
  const fallbackLanguage = readStoredLanguage() ?? DEFAULT_LANGUAGE;

  return (
    context ?? {
      language: fallbackLanguage,
      setLanguage: () => {},
      t: (key, vars) => translate(key, fallbackLanguage, vars),
    }
  );
}
