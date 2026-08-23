// The language picker used on the landing page and inside the app.
//
// Deliberately not built on the shadcn dropdown: the landing page runs its own
// light/dark palette (chosen by time of day) that is independent of the app theme,
// so the menu takes its colours from props there and from theme tokens in the app.
import { useEffect, useRef, useState } from "react";
import { Check, Globe } from "lucide-react";

import { LANGUAGES, useLanguage, type LanguageCode } from "@/lib/i18n";

type Variant = "pill" | "sidebar";

type LanguageMenuProps = {
  variant?: Variant;
  /** `pill` only — landing-page palette, which does not follow the app theme. */
  isDark?: boolean;
  /** `sidebar` only — icon-only trigger when the sidebar is narrow. */
  collapsed?: boolean;
  /** Extra classes for the trigger, e.g. the landing page's shared button styling. */
  buttonClassName?: string;
  /** Which corner the panel grows from. */
  align?: "start" | "end";
};

export function LanguageMenu({
  variant = "pill",
  isDark = true,
  collapsed = false,
  buttonClassName = "",
  align = "end",
}: LanguageMenuProps) {
  const { language, setLanguage, t } = useLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const active = LANGUAGES.find((entry) => entry.code === language) ?? LANGUAGES[0];

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

  const choose = (code: LanguageCode) => {
    setLanguage(code);
    setIsOpen(false);
  };

  const panelClass =
    variant === "pill"
      ? isDark
        ? "border-slate-700 bg-slate-900/95 text-slate-100"
        : "border-slate-200 bg-white/95 text-slate-900"
      : "border-border bg-popover text-popover-foreground";

  const optionHoverClass =
    variant === "pill"
      ? isDark
        ? "hover:bg-slate-800"
        : "hover:bg-slate-100"
      : "hover:bg-accent hover:text-accent-foreground";

  const triggerClass =
    variant === "pill"
      ? `inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-semibold shadow-sm backdrop-blur-md transition-colors sm:px-4 ${buttonClassName}`
      : `w-full text-left flex items-center gap-3 px-3 py-2 rounded-md text-sm hover:bg-accent ${
          collapsed ? "justify-center" : ""
        } ${buttonClassName}`;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-haspopup="true"
        aria-expanded={isOpen}
        aria-label={`${t("language.change")}: ${active.label}`}
        title={`${t("language.label")}: ${active.label}`}
        className={triggerClass}
      >
        <Globe className={variant === "pill" ? "h-4 w-4" : "w-5 h-5"} aria-hidden="true" />
        {variant === "pill" ? (
          <span className="language-label">{active.label}</span>
        ) : (
          !collapsed && (
            <span className="flex-1 truncate">
              {t("language.label")}
              <span className="language-label ml-2 text-xs text-muted-foreground">{active.label}</span>
            </span>
          )
        )}
      </button>

      {isOpen && (
        <div
          role="radiogroup"
          aria-label={t("language.choose")}
          className={`absolute z-50 mt-2 max-h-[70vh] w-56 overflow-y-auto rounded-xl border p-1 shadow-2xl backdrop-blur-md ${panelClass} ${
            align === "end" ? "right-0" : "left-0"
          } ${variant === "sidebar" ? "bottom-full mb-2 mt-0" : ""}`}
        >
          {LANGUAGES.map((entry) => {
            const selected = entry.code === language;
            return (
              <button
                key={entry.code}
                type="button"
                role="radio"
                aria-checked={selected}
                lang={entry.code}
                onClick={() => choose(entry.code)}
                className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors ${optionHoverClass} ${
                  selected ? "font-semibold" : ""
                }`}
              >
                <span className="min-w-0 flex-1">
                  <span className="language-label block truncate">{entry.label}</span>
                  {/* Identifies the row when the machine has no font for the script
                      and the native label renders as tofu boxes. */}
                  {entry.englishName !== entry.label && (
                    <span className="block truncate text-xs opacity-60">{entry.englishName}</span>
                  )}
                </span>
                {selected && <Check className="h-4 w-4 shrink-0 text-teal-500" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default LanguageMenu;
