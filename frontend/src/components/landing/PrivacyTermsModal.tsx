import { useEffect } from "react";

import { useLanguage } from "@/lib/i18n";

interface PrivacyTermsModalProps {
  isDark: boolean;
  onClose: () => void;
}

const POLICY_LINKS = {
  anthropicRetention:
    "https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data",
  anthropicApiData:
    "https://privacy.claude.com/en/articles/7996875-can-you-delete-data-that-i-sent-via-api",
  openrouterCollection: "https://openrouter.ai/docs/guides/privacy/data-collection",
  openrouterProviders: "https://openrouter.ai/docs/guides/privacy/provider-logging",
  openaiData: "https://developers.openai.com/api/docs/guides/your-data",
  geminiTerms: "https://ai.google.dev/gemini-api/terms",
} as const;

export default function PrivacyTermsModal({ isDark, onClose }: PrivacyTermsModalProps) {
  const { t, language } = useLanguage();

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  const surfaceClass = isDark
    ? "border-slate-700 bg-slate-900 text-slate-100"
    : "border-slate-200 bg-white text-slate-900";
  const textSecondary = isDark ? "text-slate-300" : "text-slate-600";
  const subtlePanel = isDark
    ? "border-slate-700 bg-slate-800/60"
    : "border-slate-200 bg-slate-50";
  const linkClass = `font-semibold underline underline-offset-4 transition-colors ${
    isDark ? "text-teal-300 hover:text-teal-200" : "text-teal-700 hover:text-teal-800"
  }`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="privacy-terms-title"
        className={`max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-2xl border shadow-2xl ${surfaceClass}`}
      >
        <div className="flex items-start justify-between gap-4 border-b border-inherit px-5 py-4 sm:px-7">
          <div>
            <h2 id="privacy-terms-title" className="text-2xl font-bold">
              Privacy &amp; Terms
            </h2>
            <p className={`mt-1 text-sm ${textSecondary}`}>Last updated September 24, 2026</p>
            {language !== "en" && (
              <p className={`mt-1 text-xs italic ${textSecondary}`}>{t("legal.translationNote")}</p>
            )}
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close Privacy & Terms"
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition-colors ${
              isDark
                ? "border-slate-700 hover:bg-slate-800"
                : "border-slate-200 hover:bg-slate-100"
            }`}
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className={`max-h-[calc(90vh-82px)] space-y-8 overflow-y-auto px-5 py-6 text-sm leading-6 sm:px-7 ${textSecondary}`}>
          <section className={`rounded-xl border p-4 ${subtlePanel}`}>
            <h3 className="mb-2 text-lg font-bold text-current">Quick summary</h3>
            <ul className="ml-5 list-disc space-y-1.5">
              <li>UpcurvEd Desktop is local-first: your local chats, settings, working files, and finished exports stay on your computer.</li>
              <li>When you generate AI content, your prompt and any attached inputs are sent to the AI provider you selected.</li>
              <li>Provider privacy rules differ, so avoid identifiable or sensitive student information unless your school has approved that provider and its data practices.</li>
            </ul>
          </section>

          <section>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-teal-500">Privacy Policy</p>
            <h3 className="mb-2 text-lg font-bold text-current">1. What stays on your device</h3>
            <p>
              UpcurvEd Desktop is designed as a local-first application. Your local chats, settings, working files,
              and finished content you download or export are stored on your computer rather than in an UpcurvEd cloud
              account.
            </p>
          </section>

          <section className={`rounded-xl border p-4 ${subtlePanel}`}>
            <h3 className="mb-2 text-lg font-bold text-current">2. What leaves your device</h3>
            <p>
              AI generation requires an internet connection. When you submit a prompt, the prompt and any images or
              other inputs needed for that request are sent to the provider you selected, such as Anthropic, OpenAI,
              Google, or a provider reached through OpenRouter. Those providers process the request under their own
              terms, privacy practices, and retention rules.
            </p>
          </section>

          <section>
            <h3 className="mb-3 text-lg font-bold text-current">3. AI provider data practices</h3>
            <div className="space-y-5">
              <div>
                <p className="font-semibold text-current">Anthropic / Claude API</p>
                <p>
                  Anthropic states that API inputs and outputs are not used to train its models by default. Standard API
                  inputs and outputs are generally deleted from Anthropic&apos;s systems within 30 days, subject to limited
                  exceptions such as legal obligations, policy enforcement, or services with different retention terms.
                </p>
                <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                  <a className={linkClass} href={POLICY_LINKS.anthropicApiData} target="_blank" rel="noreferrer">
                    Anthropic API data policy
                  </a>
                  <a className={linkClass} href={POLICY_LINKS.anthropicRetention} target="_blank" rel="noreferrer">
                    Anthropic retention policy
                  </a>
                </p>
              </div>

              <div>
                <p className="font-semibold text-current">OpenAI API</p>
                <p>
                  OpenAI states that API data is not used to train or improve OpenAI models unless the customer opts in.
                  Abuse-monitoring logs may include prompts, responses, and related metadata and are generally retained
                  for up to 30 days by default. Some API features can have additional application-state retention.
                </p>
                <p className="mt-1">
                  <a className={linkClass} href={POLICY_LINKS.openaiData} target="_blank" rel="noreferrer">
                    OpenAI API data controls
                  </a>
                </p>
              </div>

              <div>
                <p className="font-semibold text-current">OpenRouter</p>
                <p>
                  OpenRouter states that it does not store prompt or response content by default, but it does store
                  request metadata such as token counts and latency. OpenRouter routes requests to underlying AI
                  providers, so the selected provider&apos;s own logging, retention, and training policies can also apply.
                </p>
                <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                  <a className={linkClass} href={POLICY_LINKS.openrouterCollection} target="_blank" rel="noreferrer">
                    OpenRouter data collection
                  </a>
                  <a className={linkClass} href={POLICY_LINKS.openrouterProviders} target="_blank" rel="noreferrer">
                    OpenRouter provider policies
                  </a>
                </p>
              </div>

              <div>
                <p className="font-semibold text-current">Google Gemini API</p>
                <p>
                  Google treats unpaid Gemini API use differently from paid use. Under the unpaid service terms, Google
                  may use submitted content and generated responses to improve its products and machine-learning
                  technologies, and human reviewers may process inputs and outputs. Google advises users not to submit
                  sensitive, confidential, or personal information to unpaid services. For paid Gemini API use through a
                  billed Cloud project, Google states that prompts and responses are not used to improve its products,
                  although limited logging may still occur for safety, abuse prevention, or legal requirements.
                </p>
                <p className="mt-1">
                  <a className={linkClass} href={POLICY_LINKS.geminiTerms} target="_blank" rel="noreferrer">
                    Google Gemini API terms
                  </a>
                </p>
              </div>
            </div>
          </section>

          <section className={`rounded-xl border p-4 ${subtlePanel}`}>
            <h3 className="mb-2 text-lg font-bold text-current">4. Student and school information</h3>
            <p>
              For classroom use, use de-identified examples whenever practical. Avoid placing student names, IDs,
              contact information, health information, disciplinary information, or other sensitive or confidential
              student information into prompts unless your school has approved the selected provider and its data
              practices. This is especially important when using Gemini&apos;s unpaid API quota.
            </p>
          </section>

          <section>
            <h3 className="mb-2 text-lg font-bold text-current">5. API keys and local security</h3>
            <p>
              API keys are saved for use by UpcurvEd on your device. When secure operating-system keychain storage is
              available in the desktop app, you can choose to use it. Do not share API keys with students or publish them
              in prompts, screenshots, documents, or source code.
            </p>
          </section>

          <section>
            <h3 className="mb-2 text-lg font-bold text-current">6. Feedback and diagnostics</h3>
            <p>
              Sending feedback or exported diagnostics to the UpcurvEd team is optional. The diagnostics export is
              designed to exclude API keys, original prompts, chat messages, names, email addresses, and generated
              scripts. If you type personal information into a feedback form yourself, that information is included in
              what you submit.
            </p>
          </section>

          <section className="border-t border-inherit pt-7">
            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-purple-500">Terms of Use</p>
            <h3 className="mb-2 text-lg font-bold text-current">7. Educational use and AI output</h3>
            <p>
              UpcurvEd is an educational-content creation tool. AI-generated material can be incomplete, inaccurate, or
              unsuitable for a particular classroom. Review and adapt generated content before using it with students.
            </p>
          </section>

          <section>
            <h3 className="mb-2 text-lg font-bold text-current">8. Responsible use</h3>
            <p>
              You are responsible for following your school&apos;s policies, applicable privacy requirements, copyright and
              permission rules, and the terms of the AI provider you choose. Only upload or submit material you have the
              right to use.
            </p>
          </section>

          <section>
            <h3 className="mb-2 text-lg font-bold text-current">9. Provider availability, pricing, and limits</h3>
            <p>
              AI providers control their own model availability, free quotas, prices, rate limits, and data policies.
              These can change independently of UpcurvEd. A model that is free or available today may change later.
            </p>
          </section>

          <section className={`rounded-xl border p-4 ${subtlePanel}`}>
            <h3 className="mb-2 text-lg font-bold text-current">10. Service limitations</h3>
            <p>
              UpcurvEd is provided as an educational tool and does not guarantee that every generation will succeed or
              that every output will be accurate or appropriate for a specific purpose. Nothing in these terms limits
              rights or protections that cannot legally be waived.
            </p>
          </section>

          <section>
            <h3 className="mb-2 text-lg font-bold text-current">11. Updates</h3>
            <p>
              UpcurvEd may update this notice when the application, supported providers, or provider data practices
              change. Provider policies can also change, so the links above are the best source for their current terms.
            </p>
          </section>
        </div>
      </section>
    </div>
  );
}
