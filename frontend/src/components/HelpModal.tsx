// In-app Help & FAQ, opened from the sidebar.
//
// Separate from the landing page's DocsModal: that one answers "should I install
// this and how", this one answers "I am in the app, how do I get a good result".
// The per-type descriptions are the same keys the generation dropdown shows on
// hover, so the two can never drift apart.
import { useEffect } from "react";
import { HelpCircle, X } from "lucide-react";

import { useLanguage } from "@/lib/i18n";
import { isMacPlatform, shortcutLabel } from "@/lib/hotkeys";

const GENERATION_TYPES = [
  "video",
  "story",
  "diagram",
  "static_worksheet",
  "widget",
  "quiz",
  "podcast_single",
  "podcast_debate",
] as const;

const LEARNER_LEVELS = [
  "auto",
  "early_learning",
  "elementary",
  "middle_school",
  "high_school",
  "university",
] as const;

const FAQ = ["context", "slow", "language", "cost", "offline"] as const;

const TIPS = ["topic", "angle", "level", "iterate"] as const;

const EXAMPLES = ["1", "2", "3"] as const;

// Labels come from shortcutLabel() so macOS sees ⌘ and everyone else sees Ctrl.
const SHORTCUTS: { keys: string; descriptionKey: string }[] = [
  { keys: shortcutLabel("K"), descriptionKey: "help.shortcut.palette" },
  { keys: shortcutLabel("Enter"), descriptionKey: "help.shortcut.send" },
  { keys: shortcutLabel("/"), descriptionKey: "help.shortcut.help" },
  { keys: "Enter", descriptionKey: "help.shortcut.enter" },
  { keys: "Esc", descriptionKey: "help.shortcut.escape" },
];

export function HelpModal({ onClose }: { onClose: () => void }) {
  const { t } = useLanguage();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="upcurved-help-title"
        className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <h2 id="upcurved-help-title" className="flex items-center gap-2 text-xl font-bold">
            <HelpCircle className="h-5 w-5" aria-hidden="true" />
            {t("help.title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("help.close")}
            className="flex h-9 w-9 items-center justify-center rounded-full border border-border transition-colors hover:bg-accent"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-7 overflow-y-auto px-5 py-5 sm:px-6">
          <section>
            <h3 className="mb-2 text-base font-semibold">{t("help.prompting.heading")}</h3>
            <p className="mb-3 text-sm text-muted-foreground">{t("help.prompting.intro")}</p>
            <ul className="ml-5 list-disc space-y-2 text-sm text-muted-foreground">
              {TIPS.map((tip) => (
                <li key={tip}>{t(`help.tip.${tip}`)}</li>
              ))}
            </ul>
          </section>

          <section>
            <h3 className="mb-2 text-base font-semibold">{t("help.examples.heading")}</h3>
            <div className="space-y-2">
              {EXAMPLES.map((example) => (
                <p
                  key={example}
                  className="rounded-lg border border-border bg-muted/40 px-3 py-2 font-mono text-xs"
                >
                  {t(`help.example.${example}`)}
                </p>
              ))}
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-base font-semibold">{t("help.types.heading")}</h3>
            <p className="mb-3 text-sm text-muted-foreground">{t("help.types.intro")}</p>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40">
                    <th scope="col" className="px-3 py-2 font-semibold">{t("help.table.type")}</th>
                    <th scope="col" className="px-3 py-2 font-semibold">{t("help.table.makes")}</th>
                  </tr>
                </thead>
                <tbody>
                  {GENERATION_TYPES.map((type) => (
                    <tr key={type} className="border-b border-border last:border-b-0">
                      <th scope="row" className="whitespace-nowrap px-3 py-2 align-top font-semibold">
                        {t(`chat.gen.${type}`)}
                      </th>
                      <td className="px-3 py-2 align-top text-muted-foreground">
                        {t(`chat.gen.${type}.desc`)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-base font-semibold">{t("help.levels.heading")}</h3>
            <p className="mb-3 text-sm text-muted-foreground">{t("help.levels.intro")}</p>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40">
                    <th scope="col" className="px-3 py-2 font-semibold">{t("help.table.level")}</th>
                    <th scope="col" className="px-3 py-2 font-semibold">{t("help.table.who")}</th>
                  </tr>
                </thead>
                <tbody>
                  {LEARNER_LEVELS.map((level) => (
                    <tr key={level} className="border-b border-border last:border-b-0">
                      <th scope="row" className="whitespace-nowrap px-3 py-2 align-top font-semibold">
                        {t(`chat.level.${level}`)}
                      </th>
                      <td className="px-3 py-2 align-top text-muted-foreground">
                        {t(`chat.level.${level}.desc`)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-base font-semibold">{t("help.shortcuts.heading")}</h3>
            {/* Only worth explaining the modifier difference to people who will
                actually see the other one. */}
            {isMacPlatform() ? null : (
              <p className="mb-3 text-sm text-muted-foreground">{t("help.shortcuts.intro")}</p>
            )}
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40">
                    <th scope="col" className="px-3 py-2 font-semibold">{t("help.table.shortcut")}</th>
                    <th scope="col" className="px-3 py-2 font-semibold">{t("help.table.does")}</th>
                  </tr>
                </thead>
                <tbody>
                  {SHORTCUTS.map(({ keys, descriptionKey }) => (
                    <tr key={descriptionKey} className="border-b border-border last:border-b-0">
                      <th scope="row" className="whitespace-nowrap px-3 py-2 align-top">
                        <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-xs">
                          {keys}
                        </kbd>
                      </th>
                      <td className="px-3 py-2 align-top text-muted-foreground">
                        {t(descriptionKey)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h3 className="mb-2 text-base font-semibold">{t("help.faq.heading")}</h3>
            <dl className="space-y-4">
              {FAQ.map((item) => (
                <div key={item}>
                  <dt className="text-sm font-semibold">{t(`help.faq.${item}.q`)}</dt>
                  <dd className="mt-1 text-sm text-muted-foreground">{t(`help.faq.${item}.a`)}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      </div>
    </div>
  );
}

export default HelpModal;
