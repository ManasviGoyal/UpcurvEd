import { useEffect } from "react";
import { Link } from "react-router-dom";

interface DocsModalProps {
  isDark: boolean;
  onClose: () => void;
}

export default function DocsModal({ isDark, onClose }: DocsModalProps) {
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
            Help &amp; FAQ
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Help"
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
              <dt className="font-semibold">How do I install and set up UpcurvEd?</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                Follow the{" "}
                <Link to="/setup-guide" className={linkClass} onClick={onClose}>
                  Setup Guide
                </Link>
                . It walks through downloading the app, installing it on macOS or Windows, and adding your API key in
                Settings.
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">Do I need an API key?</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                Yes. UpcurvEd connects to the model provider selected in Settings using the API key you provide.
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">Can I use UpcurvEd without paying for AI usage?</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                Yes. Select OpenRouter Free or another currently available free model. The{" "}
                <Link to="/setup-guide" className={linkClass} onClick={onClose}>
                  Setup Guide
                </Link>{" "}
                has step-by-step instructions for getting a free OpenRouter key. Free model availability and limits may
                change.
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">Why did a free model fail or take longer?</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                Free providers may be busy or temporarily unavailable. Try again or select a different free model.
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">Where do I change providers or models?</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                Open Settings inside UpcurvEd, then choose the provider and model you want to use.
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">What can UpcurvEd create?</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                Educational animations, stories, quizzes, podcasts, and interactive visuals.
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">What should I type to get started?</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                Describe what you want to create in plain language. For example:
                <span className={`mt-2 block rounded-lg border p-3 font-mono text-sm ${codeClass}`}>
                  Explain how to add fractions.
                </span>
              </dd>
            </div>

            <div className={`border-t pt-6 ${dividerClass}`}>
              <dt className="font-semibold">Is my API key shown publicly?</dt>
              <dd className={`mt-1 ${mutedTextClass}`}>
                No. UpcurvEd Desktop stores your chats, settings, and generated files locally on your computer. Your API
                key is used only to connect to the AI provider you select.
              </dd>
              <dd className={`mt-2 ${mutedTextClass}`}>
                Some features require an internet connection, including AI generation, voice generation, software
                downloads, and the feedback form.
              </dd>
              <dd className={`mt-2 ${mutedTextClass}`}>
                If you are participating in a pilot or troubleshooting with the UpcurvEd team, you may voluntarily
                export and share optional diagnostic files. These exports do not include API keys, prompts, chat
                messages, names, email addresses, or generated scripts.
              </dd>
              <dd className={`mt-2 font-medium ${mutedTextClass}`}>
                As always, never paste an API key into prompts, feedback forms, screenshots, or shared content.
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}
