import { useEffect } from "react";

import { useLanguage } from "@/lib/i18n";

interface NoticeOfConsentModalProps {
  isDark: boolean;
  onClose: () => void;
}

export default function NoticeOfConsentModal({ isDark, onClose }: NoticeOfConsentModalProps) {
  const { t, language } = useLanguage();

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  const surfaceClass = isDark
    ? "bg-slate-900 text-white border-slate-700"
    : "bg-white text-slate-900 border-slate-200";
  const mutedTextClass = isDark ? "text-slate-300" : "text-slate-600";
  const accentClass = isDark ? "text-teal-300" : "text-teal-700";
  const sectionClass = isDark ? "border-slate-700" : "border-slate-200";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="upcurved-consent-title"
        className={`max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-2xl border shadow-2xl ${surfaceClass}`}
      >
        <div
          className={`flex items-center justify-between border-b px-5 py-4 sm:px-6 ${
            isDark ? "border-slate-700" : "border-slate-200"
          }`}
        >
          <h2 id="upcurved-consent-title" className="text-2xl font-bold">
            {t("nav.consent")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("consent.close")}
            className={`flex h-10 w-10 items-center justify-center rounded-full border transition-colors ${
              isDark
                ? "border-slate-700 bg-slate-800 hover:bg-slate-700"
                : "border-slate-200 bg-slate-100 hover:bg-slate-200"
            }`}
          >
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                d="M6 6l12 12M18 6L6 18"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <div className="max-h-[calc(90vh-88px)] space-y-6 overflow-y-auto px-5 py-5 sm:px-8 sm:py-8">
          <div className="text-center">
            <img
              src="/upcurved-logo.png"
              alt=""
              aria-hidden="true"
              className="mx-auto mb-4 h-20 w-20"
            />
            <h3 className={`text-2xl font-bold ${accentClass}`}>
              {t("consent.heading")}
            </h3>
            <p className={`mt-2 text-sm ${mutedTextClass}`}>{t("common.date.2026-08-16")}</p>
            {/* The English wording is what this notice is written against. */}
            {language !== "en" && (
              <p className={`mt-2 text-xs italic ${mutedTextClass}`}>
                {t("legal.translationNote")}
              </p>
            )}
          </div>

          <div className="space-y-6">
            <section className={`rounded-xl border p-5 ${sectionClass}`}>
              <h4 className="mb-3 text-lg font-bold">{t("consent.note.heading")}</h4>
              <p className={`leading-relaxed ${mutedTextClass}`}>{t("consent.note.body")}</p>
            </section>

            <section className={`rounded-xl border p-5 ${sectionClass}`}>
              <h4 className="mb-3 text-lg font-bold">{t("consent.disclaimer.heading")}</h4>
              <p className={`leading-relaxed ${mutedTextClass}`}>{t("consent.disclaimer.body")}</p>
            </section>
          </div>

          <div className="pt-3 text-center">
            <p className={`mb-3 text-base font-medium ${mutedTextClass}`}>
              {t("consent.thanks")} <span className="inline-block -translate-y-0.5">🖍️</span>
            </p>
            <p className={`text-base ${mutedTextClass}`}>
              🍎 📚 {t("consent.closing")}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}