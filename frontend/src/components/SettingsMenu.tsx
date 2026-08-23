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
  const { mode, setMode } = useAppearance();
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
          {/* One line: label on the left, a three-way segmented control on the right.
              The buttons are icon-only because the words for "Automatic" vary enough
              in length across languages to wrap the row otherwise; each carries the
              translated name as its accessible name and tooltip. */}
          <div className="flex items-center justify-between gap-3 px-2 py-1.5">
            <span className={`text-xs font-semibold uppercase tracking-wide ${sectionLabelClass}`}>
              {t("settings.appearance")}
            </span>
            <div
              role="radiogroup"
              aria-label={t("settings.appearance")}
              className={`inline-flex shrink-0 rounded-full border p-0.5 ${
                isDark ? "border-slate-700" : "border-slate-200"
              }`}
            >
              {modes.map((value) => {
                const Icon = MODE_ICONS[value];
                const selected = mode === value;
                const label = t(`settings.appearance.${value}`);
                return (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    aria-label={label}
                    title={label}
                    onClick={() => setMode(value)}
                    className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
                      selected
                        ? "bg-teal-500 text-white"
                        : isDark
                          ? "text-slate-300 hover:bg-slate-800"
                          : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </button>
                );
              })}
            </div>
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
                    <span className="min-w-0 flex-1">
                      <span className="language-label block truncate">{entry.label}</span>
                      {/* Identifies the row when the machine has no font for the
                          script; without it a missing Hangul font is just boxes. */}
                      {entry.englishName !== entry.label && (
                        <span className={`block truncate text-xs ${sectionLabelClass}`}>
                          {entry.englishName}
                        </span>
                      )}
                    </span>
                    {selected && <Check className="h-4 w-4 shrink-0 text-teal-500" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default SettingsMenu;
