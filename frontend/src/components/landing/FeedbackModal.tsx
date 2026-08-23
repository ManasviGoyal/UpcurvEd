import { useEffect } from "react";

import { Trans, useLanguage } from "@/lib/i18n";

const FORM_ID = "1FAIpQLSemR4uuVdmnGVFjcGRc3bSGsZ1zcNRLgQuSXZuYSVw-CkI68g";

// Not embedded in an iframe: the form redirects to a Google sign-in page, which
// sends `X-Frame-Options: DENY` and would render blank inside the modal.
export const FEEDBACK_FORM_URL = `https://docs.google.com/forms/d/e/${FORM_ID}/viewform?usp=header`;

const DIAGNOSTICS_SCREENSHOT = "/feedback/export-diagnostics-settings.png";

interface FeedbackModalProps {
  isDark: boolean;
  onClose: () => void;
}

export default function FeedbackModal({ isDark, onClose }: FeedbackModalProps) {
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
  const linkClass = `font-semibold underline underline-offset-4 transition-colors ${
    isDark ? "text-teal-300 hover:text-teal-200" : "text-teal-700 hover:text-teal-800"
  }`;

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
        aria-labelledby="upcurved-feedback-title"
        className={`max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-2xl border shadow-2xl ${surfaceClass}`}
      >
        <div
          className={`flex items-center justify-between border-b px-5 py-4 sm:px-6 ${
            isDark ? "border-slate-700" : "border-slate-200"
          }`}
        >
          <h2 id="upcurved-feedback-title" className="text-2xl font-bold">
            {t("feedback.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("feedback.close")}
            className={`flex h-10 w-10 items-center justify-center rounded-full border transition-colors ${
              isDark
                ? "border-slate-700 bg-slate-800 hover:bg-slate-700"
                : "border-slate-200 bg-slate-100 hover:bg-slate-200"
            }`}
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" strokeWidth="2" strokeLinecap="round" />
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
              {t("feedback.heading")}
            </h3>
            <p className={`mt-2 text-sm ${mutedTextClass}`}>{t("common.date.2026-08-16")}</p>
            {/* The English wording is what these terms are written against. */}
            {language !== "en" && (
              <p className={`mt-2 text-xs italic ${mutedTextClass}`}>
                {t("legal.translationNote")}
              </p>
            )}
          </div>

          <section className={`rounded-xl border p-5 ${sectionClass}`}>
            <h4 className="mb-3 text-lg font-bold">{t("feedback.disclaimer.heading")}</h4>
            <p className={`leading-relaxed ${mutedTextClass}`}>{t("feedback.disclaimer.body")}</p>
          </section>

          <section className={`rounded-xl border p-5 ${sectionClass}`}>
            <h4 className="mb-3 text-lg font-bold">{t("feedback.data.heading")}</h4>
            <p className={`leading-relaxed ${mutedTextClass}`}>{t("feedback.data.body")}</p>
          </section>

          <section className={`rounded-xl border p-5 ${sectionClass}`}>
            <h4 className="mb-3 text-lg font-bold">{t("feedback.how.heading")}</h4>
            <p className={`leading-relaxed ${mutedTextClass}`}>{t("feedback.how.body")}</p>
            <img
              src={DIAGNOSTICS_SCREENSHOT}
              alt={t("feedback.how.imageAlt")}
              loading="lazy"
              className="mt-4 w-full max-w-xs rounded-xl border border-slate-600 shadow-lg"
            />
          </section>

          <section className={`rounded-xl border p-5 ${sectionClass}`}>
            <h4 className="mb-3 text-lg font-bold">{t("feedback.where.heading")}</h4>
            <p className={`leading-relaxed ${mutedTextClass}`}>
              <Trans
                k="feedback.where.body"
                components={{
                  form: (
                    <a className={linkClass} href={FEEDBACK_FORM_URL} target="_blank" rel="noopener noreferrer">
                      {t("feedback.formLink")}
                    </a>
                  ),
                }}
              />
            </p>
          </section>

          <section className={`rounded-xl border p-5 ${sectionClass}`}>
            <h4 className="mb-3 text-lg font-bold">{t("feedback.ask.heading")}</h4>
            <p className={`leading-relaxed ${mutedTextClass}`}>{t("feedback.ask.body")}</p>

            <a
              href={FEEDBACK_FORM_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-flex items-center gap-2 rounded-full bg-teal-500 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-teal-600"
            >
              {t("feedback.openForm")}
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" aria-hidden="true">
                <path
                  d="M14 5h5v5M19 5l-8 8M18 14v4a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h4"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </a>

            <p className={`mt-3 text-sm ${mutedTextClass}`}>{t("feedback.newTab")}</p>
          </section>

          <div className="pt-1 text-center">
            <p className={`text-base ${mutedTextClass}`}>
              🍎 📚 {t("feedback.thanks")}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
