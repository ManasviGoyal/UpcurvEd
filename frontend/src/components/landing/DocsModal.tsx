import { useEffect } from "react";
import { Link } from "react-router-dom";

import { Trans, useLanguage } from "@/lib/i18n";

interface DocsModalProps {
  isDark: boolean;
  onClose: () => void;
}

export default function DocsModal({ isDark, onClose }: DocsModalProps) {
  const { t } = useLanguage();

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
  const dividerClass = isDark ? "border-slate-800" : "border-slate-200";
  const linkClass = `font-semibold underline underline-offset-4 transition-colors ${
    isDark ? "text-teal-300 hover:text-teal-200" : "text-teal-700 hover:text-teal-800"
  }`;
  // Rendered inside translated sentences via <Trans>, so each language can place it
  // wherever its own grammar wants.
  const setupGuideLink = (
    <Link to="/setup-guide" className={linkClass} onClick={onClose}>
      {t("docs.setupGuideLink")}
    </Link>
  );

  const codeClass = isDark
    ? "border-slate-700 bg-slate-950 text-slate-100"
    : "border-slate-200 bg-white text-slate-800";

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
        aria-labelledby="upcurved-docs-title"
        className={`max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-2xl border shadow-2xl ${surfaceClass}`}
      >
        <div
          className={`flex items-center justify-between border-b px-5 py-4 sm:px-6 ${
            isDark ? "border-slate-700" : "border-slate-200"
          }`}
        >
          <h2 id="upcurved-docs-title" className="text-2xl font-bold">
            {t("docs.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("docs.close")}
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

        <div className="max-h-[calc(90vh-88px)] overflow-y-auto px-5 py-5 sm:px-6 sm:py-6">
          <img
            src="/upcurved-logo.png"
            alt=""
            aria-hidden="true"
            className="mx-auto mb-6 h-20 w-20"
          />

          <dl className="space-y-6">
            <div>
              <dt className="font-semibold">{t("docs.q.install")}</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                <Trans k="docs.a.install" components={{ setupGuide: setupGuideLink }} />
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">{t("docs.q.apiKey")}</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>{t("docs.a.apiKey")}</dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">{t("docs.q.free")}</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                <Trans k="docs.a.free" components={{ setupGuide: setupGuideLink }} />
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">{t("docs.q.freeFailed")}</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>{t("docs.a.freeFailed")}</dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">{t("docs.q.changeProvider")}</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>{t("docs.a.changeProvider")}</dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">{t("docs.q.whatCreate")}</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>{t("docs.a.whatCreate")}</dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">{t("docs.q.getStarted")}</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                {t("docs.a.getStarted")}
                <span className={`mt-2 block rounded-lg border p-3 font-mono text-sm ${codeClass}`}>
                  {t("docs.example.prompt")}
                </span>
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">{t("docs.q.keyPublic")}</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>{t("docs.a.keyPublic.1")}</dd>
              <dd className={`mt-2 ${mutedTextClass}`}>{t("docs.a.keyPublic.2")}</dd>
              <dd className={`mt-2 ${mutedTextClass}`}>{t("docs.a.keyPublic.3")}</dd>
              <dd className={`mt-2 font-medium ${mutedTextClass}`}>{t("docs.a.keyPublic.4")}</dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}
