import { useEffect } from "react";

const OPENROUTER_HOME_URL = "https://openrouter.ai/";
const OPENROUTER_KEYS_URL = "https://openrouter.ai/settings/keys";

interface DocsModalProps {
  isDark: boolean;
  onClose: () => void;
}

function ExternalLink({
  href,
  children,
  isDark,
}: {
  href: string;
  children: React.ReactNode;
  isDark: boolean;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={`font-semibold underline underline-offset-4 transition-colors ${
        isDark
          ? "text-teal-300 hover:text-teal-200"
          : "text-teal-700 hover:text-teal-800"
      }`}
    >
      {children}
    </a>
  );
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
  const sectionClass = isDark
    ? "border-slate-700 bg-slate-800/65"
    : "border-slate-200 bg-slate-50";
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
          <div>
            <p className={`text-sm font-medium ${mutedTextClass}`}>UpcurvEd Help</p>
            <h2 id="upcurved-docs-title" className="text-2xl font-bold">
              Docs & FAQ
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Docs"
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

        <div className="max-h-[calc(90vh-88px)] space-y-5 overflow-y-auto px-5 py-5 sm:px-6 sm:py-6">
          <section className={`rounded-xl border p-4 sm:p-5 ${sectionClass}`}>
            <h3 className="mb-3 text-lg font-bold">Getting started</h3>
            <ol className={`list-decimal space-y-2 pl-5 ${mutedTextClass}`}>
              <li>Download and install UpcurvEd Desktop.</li>
              <li>Open <strong>Settings</strong> in UpcurvEd.</li>
              <li>Select a model provider and add its API key.</li>
              <li>Choose a model, return to the chat, and describe what you want to create.</li>
            </ol>
          </section>

          <section className={`rounded-xl border p-4 sm:p-5 ${sectionClass}`}>
            <h3 className="mb-2 text-lg font-bold">Opening UpcurvEd on macOS</h3>
            <p className={`mb-3 ${mutedTextClass}`}>
              Because the current Mac build is not yet certified by Apple, macOS may say the
              developer cannot be verified or that the app cannot be opened.
            </p>
            <ol className={`list-decimal space-y-2 pl-5 ${mutedTextClass}`}>
              <li>
                In Finder, right-click or Control-click <strong>UpcurvEd</strong>, choose
                <strong> Open</strong>, and confirm.
              </li>
              <li>
                If it is still blocked, try opening it once, then go to
                <strong> System Settings → Privacy & Security</strong>.
              </li>
              <li>
                Scroll to the Security section, select <strong>Open Anyway</strong>, and confirm
                by selecting <strong>Open</strong>.
              </li>
            </ol>
            <p className={`mt-3 text-sm ${mutedTextClass}`}>
              Only override this warning when UpcurvEd was downloaded from the official
              UpcurvEd page.
            </p>
          </section>

          <section className={`rounded-xl border p-4 sm:p-5 ${sectionClass}`}>
            <h3 className="mb-2 text-lg font-bold">Use UpcurvEd for free with OpenRouter</h3>
            <ol className={`list-decimal space-y-3 pl-5 ${mutedTextClass}`}>
              <li>
                Visit <ExternalLink href={OPENROUTER_HOME_URL} isDark={isDark}>OpenRouter</ExternalLink>
                {" "}and create an account or sign in.
              </li>
              <li>
                Open the <ExternalLink href={OPENROUTER_KEYS_URL} isDark={isDark}>API Keys page</ExternalLink>,
                select <strong>Create Key</strong>, and give it a recognizable name such as
                <strong> UpcurvEd</strong>.
              </li>
              <li>Copy the new key when OpenRouter shows it.</li>
              <li>
                In UpcurvEd, open <strong>Settings</strong>, select <strong>OpenRouter</strong>,
                paste the key, and save it.
              </li>
              <li>
                Choose <strong>OpenRouter Free</strong> or another model marked as free, then
                start generating.
              </li>
            </ol>
            <div
              className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
                isDark
                  ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
                  : "border-amber-300 bg-amber-50 text-amber-900"
              }`}
            >
              Free models do not charge for model requests, but availability, speed, and usage
              limits can vary. During busy periods, try again or select a different free model.
            </div>
          </section>

          <section className={`rounded-xl border p-4 sm:p-5 ${sectionClass}`}>
            <h3 className="mb-2 text-lg font-bold">Example prompt</h3>
            <div className={`rounded-lg border p-4 font-mono text-sm ${codeClass}`}>
              Explain how to add fractions.
            </div>
          </section>

          <section className={`rounded-xl border p-4 sm:p-5 ${sectionClass}`}>
            <h3 className="mb-4 text-lg font-bold">Frequently asked questions</h3>
            <div className="space-y-5">
              <div>
                <h4 className="font-semibold">Do I need an API key?</h4>
                <p className={`mt-1 ${mutedTextClass}`}>
                  Yes. UpcurvEd connects to the model provider selected in Settings using the
                  API key you provide.
                </p>
              </div>

              <div>
                <h4 className="font-semibold">Can I use UpcurvEd without paying for AI usage?</h4>
                <p className={`mt-1 ${mutedTextClass}`}>
                  Yes. Select OpenRouter Free or another currently available free model. Free
                  model availability and limits may change.
                </p>
              </div>

              <div>
                <h4 className="font-semibold">Why did a free model fail or take longer?</h4>
                <p className={`mt-1 ${mutedTextClass}`}>
                  Free providers may be busy or temporarily unavailable. Try again or select a
                  different free model.
                </p>
              </div>

              <div>
                <h4 className="font-semibold">Where do I change providers or models?</h4>
                <p className={`mt-1 ${mutedTextClass}`}>
                  Open Settings inside UpcurvEd, then choose the provider and model you want to
                  use.
                </p>
              </div>

              <div>
                <h4 className="font-semibold">What can UpcurvEd create?</h4>
                <p className={`mt-1 ${mutedTextClass}`}>
                  Educational animations, stories, quizzes, podcasts, and interactive visuals.
                </p>
              </div>

              <div>
                <h4 className="font-semibold">Is my API key shown publicly?</h4>
                <p className={`mt-1 ${mutedTextClass}`}>
                  No. UpcurvEd Desktop stores your chats, settings, and generated files locally
                  on your computer. Your API key is used only to connect to the AI provider you
                  select.
                </p>
                <p className={`mt-2 ${mutedTextClass}`}>
                  Some features require an internet connection, including AI generation, voice
                  generation, software downloads, and the feedback form.
                </p>
                <p className={`mt-2 ${mutedTextClass}`}>
                  If you are participating in a pilot or troubleshooting with the UpcurvEd team,
                  you may voluntarily export and share optional diagnostic files. These exports
                  do not include API keys, prompts, chat messages, names, email addresses, or
                  generated scripts.
                </p>
                <p className={`mt-2 font-medium ${mutedTextClass}`}>
                  As always, never paste an API key into prompts, feedback forms, screenshots,
                  or shared content.
                </p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
