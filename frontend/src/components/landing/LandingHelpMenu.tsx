import { useEffect, useRef, useState } from "react";
import { BookOpenText, ChevronDown, HelpCircle, MessageSquareText, ShieldCheck } from "lucide-react";

import { useLanguage } from "@/lib/i18n";

type LandingHelpMenuProps = {
  isDark: boolean;
  buttonClassName?: string;
  onOpenFaq: () => void;
  onOpenFeedback: () => void;
  onOpenPrivacyTerms: () => void;
};

const PRIVACY_TERMS_LABELS: Record<string, string> = {
  en: "Privacy & Terms",
  id: "Privasi & Ketentuan",
  es: "Privacidad y términos",
  pt: "Privacidade e termos",
  fr: "Confidentialité et conditions",
  it: "Privacy e termini",
  hi: "गोपनीयता और शर्तें",
  zh: "隐私与条款",
  ja: "プライバシーと利用規約",
};

export default function LandingHelpMenu({
  isDark,
  buttonClassName = "",
  onOpenFaq,
  onOpenFeedback,
  onOpenPrivacyTerms,
}: LandingHelpMenuProps) {
  const { t, language } = useLanguage();
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
  const hoverClass = isDark ? "hover:bg-slate-800" : "hover:bg-slate-100";
  const mutedClass = isDark ? "text-slate-400" : "text-slate-500";

  const choose = (action: () => void) => {
    setIsOpen(false);
    action();
  };

  const privacyTermsLabel = PRIVACY_TERMS_LABELS[language] ?? PRIVACY_TERMS_LABELS.en;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={t("nav.help.aria")}
        className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-semibold shadow-sm backdrop-blur-md transition-colors sm:px-4 ${buttonClassName}`}
      >
        <HelpCircle className="h-4 w-4" aria-hidden="true" />
        <span>{t("nav.help")}</span>
        <ChevronDown
          className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {isOpen && (
        <div
          role="menu"
          className={`absolute right-0 z-50 mt-2 w-64 rounded-xl border p-1.5 shadow-2xl backdrop-blur-md ${panelClass}`}
        >
          <p className={`px-3 pb-1.5 pt-1 text-xs font-semibold uppercase tracking-wide ${mutedClass}`}>
            {t("nav.help")}
          </p>

          <button
            type="button"
            role="menuitem"
            onClick={() => choose(onOpenFaq)}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${hoverClass}`}
          >
            <BookOpenText className="h-4 w-4 shrink-0 text-teal-500" aria-hidden="true" />
            <span>{t("help.faq.heading")}</span>
          </button>

          <button
            type="button"
            role="menuitem"
            onClick={() => choose(onOpenFeedback)}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${hoverClass}`}
          >
            <MessageSquareText className="h-4 w-4 shrink-0 text-teal-500" aria-hidden="true" />
            <span>{t("feedback.title")}</span>
          </button>

          <button
            type="button"
            role="menuitem"
            onClick={() => choose(onOpenPrivacyTerms)}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${hoverClass}`}
          >
            <ShieldCheck className="h-4 w-4 shrink-0 text-teal-500" aria-hidden="true" />
            <span>{privacyTermsLabel}</span>
          </button>
        </div>
      )}
    </div>
  );
}
