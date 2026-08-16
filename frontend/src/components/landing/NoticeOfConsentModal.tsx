import { useEffect } from "react";

interface NoticeOfConsentModalProps {
  isDark: boolean;
  onClose: () => void;
}

export default function NoticeOfConsentModal({ isDark, onClose }: NoticeOfConsentModalProps) {
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
            Notice of Consent
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Notice of Consent"
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
            <h3 className={`text-2xl font-bold ${accentClass}`}>
              UpcurvEd Notice of Consent
            </h3>
            <p className={`mt-2 text-sm ${mutedTextClass}`}>August 16, 2026</p>
          </div>

          <div className="space-y-6">
            <section className={`rounded-xl border p-5 ${sectionClass}`}>
              <h4 className="mb-3 text-lg font-bold">Note</h4>
              <p className={`leading-relaxed ${mutedTextClass}`}>
                The goal of UpcurvEd is to serve as a non-conversational AI tool for creating
                educational content with natural language. The platform supports open-source free
                models with the intention of improving access to these tools towards the benefit of
                students and teachers. The product is currently open-source and free to use by the
                same intention.
              </p>
            </section>

            <section className={`rounded-xl border p-5 ${sectionClass}`}>
              <h4 className="mb-3 text-lg font-bold">Disclaimer</h4>
              <p className={`leading-relaxed ${mutedTextClass}`}>
                By agreeing to use UpcurvEd, you consent and assume full risk of the use of
                UpcurvEd. UpcurvEd (meaning Isabela Yepes, and Manasvi Goyal) will not be held
                liable for any damages caused or associated with use of UpcurvEd.
              </p>
            </section>
          </div>

          <div className="pt-3 text-center">
            <p className={`mb-3 text-base font-medium ${mutedTextClass}`}>
              Thank you <span className="inline-block -translate-y-0.5">🖍️</span>
            </p>
            <p className={`text-base ${mutedTextClass}`}>
              🍎 📚 We hope the tool helps you with your learning or teaching.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}