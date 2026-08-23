// Icon-only settings menu for the public pages (landing + setup guide).
//
// Holds the choices that used to be either invisible (appearance was decided by the
// clock) or spread across separate buttons: appearance, language, and motion.
import { useEffect, useRef, useState } from "react";
import { Check, Monitor, Moon, Settings2, Sun } from "lucide-react";

import { LANGUAGES, useLanguage, type LanguageCode } from "@/lib/i18n";
import { useAppearance, type AppearanceMode } from "@/lib/appearance";

type SettingsMenuProps = {
  /** Landing-page palette; these pages do not follow the signed-in app theme. */
  isDark: boolean;
  /** Shared pill styling from the page's other utility buttons. */
  buttonClassName?: string;
};

const MODE_ICONS: Record<AppearanceMode, typeof Sun> = {
  auto: Monitor,
  light: Sun,
  dark: Moon,
};

export function SettingsMenu({ isDark, buttonClassName = "" }: SettingsMenuProps) {
  const { t } = useLanguage();
  const { language, setLanguage } = useLanguage();
  const { mode, setMode, reduceMotion, setReduceMotion } = useAppearance();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const onPointerDown = (event: MouseEvent | TouchEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setIsOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  const panelClass = isDark
    ? "border-slate-700 bg-slate-900/95 text-slate-100"
    : "border-slate-200 bg-white/95 text-slate-900";
  const rowHoverClass = isDark ? "hover:bg-slate-800" : "hover:bg-slate-100";
  const sectionLabelClass = isDark ? "text-slate-400" : "text-slate-500";
  const dividerClass = isDark ? "border-slate-800" : "border-slate-200";

  const modes: AppearanceMode[] = ["auto", "light", "dark"];

  const chooseLanguage = (code: LanguageCode) => {
    setLanguage(code);
    // Left open on purpose: appearance and language often get changed together.
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-haspopup="true"
        aria-expanded={isOpen}
        aria-label={t("settings.open")}
        title={t("settings.title")}
        className={`inline-flex h-10 w-10 items-center justify-center rounded-full border shadow-sm backdrop-blur-md transition-colors ${buttonClassName}`}
      >
        <Settings2 className="h-4 w-4" aria-hidden="true" />
      </button>

      {isOpen && (
        <div
          role="dialog"
          aria-label={t("settings.title")}
          className={`absolute right-0 z-50 mt-2 max-h-[75vh] w-64 overflow-y-auto rounded-xl border p-2 shadow-2xl backdrop-blur-md ${panelClass}`}
        >
          <div role="radiogroup" aria-label={t("settings.appearance")}>
            <p className={`px-2 pb-1 pt-1 text-xs font-semibold uppercase tracking-wide ${sectionLabelClass}`}>
              {t("settings.appearance")}
            </p>
            {modes.map((value) => {
              const Icon = MODE_ICONS[value];
              const selected = mode === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setMode(value)}
                  className={`flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left text-sm transition-colors ${rowHoverClass} ${
                    selected ? "font-semibold" : ""
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  <span className="flex-1 truncate">{t(`settings.appearance.${value}`)}</span>
                  {selected && <Check className="h-4 w-4 shrink-0 text-teal-500" aria-hidden="true" />}
                </button>
              );
            })}
            <p className={`px-2 pb-2 pt-1 text-xs ${sectionLabelClass}`}>
              {t("settings.appearance.autoHint")}
            </p>
          </div>

          <div className={`mt-1 border-t pt-2 ${dividerClass}`}>
            <p className={`px-2 pb-1 text-xs font-semibold uppercase tracking-wide ${sectionLabelClass}`}>
              {t("language.label")}
            </p>
            <div role="radiogroup" aria-label={t("language.choose")}>
              {LANGUAGES.map((entry) => {
                const selected = entry.code === language;
                return (
                  <button
                    key={entry.code}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    lang={entry.code}
                    onClick={() => chooseLanguage(entry.code)}
                    className={`flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2 text-left text-sm transition-colors ${rowHoverClass} ${
                      selected ? "font-semibold" : ""
                    }`}
                  >
                    <span className="truncate">{entry.label}</span>
                    {selected && <Check className="h-4 w-4 shrink-0 text-teal-500" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          </div>

          <div className={`mt-1 border-t pt-2 ${dividerClass}`}>
            <button
              type="button"
              role="switch"
              aria-checked={reduceMotion}
              onClick={() => setReduceMotion(!reduceMotion)}
              className={`flex w-full items-start gap-3 rounded-lg px-2 py-2 text-left text-sm transition-colors ${rowHoverClass}`}
            >
              <span className="flex-1">
                <span className="block">{t("settings.reduceMotion")}</span>
                <span className={`mt-0.5 block text-xs ${sectionLabelClass}`}>
                  {t("settings.reduceMotion.hint")}
                </span>
              </span>
              {/* Plain markup rather than the app's Switch: this page has its own palette. */}
              <span
                aria-hidden="true"
                className={`mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors ${
                  reduceMotion ? "bg-teal-500" : isDark ? "bg-slate-700" : "bg-slate-300"
                }`}
              >
                <span
                  className={`h-4 w-4 rounded-full bg-white transition-transform ${
                    reduceMotion ? "translate-x-4" : ""
                  }`}
                />
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default SettingsMenu;
