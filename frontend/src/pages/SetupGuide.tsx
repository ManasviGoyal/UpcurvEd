import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import SettingsMenu from "@/components/SettingsMenu";
import { Trans, useLanguage } from "@/lib/i18n";
import { useAppearance } from "@/lib/appearance";

// Screenshots from UpcurvEd_install_open_setup_guide_081626_mac_arm64.docx.
// `common` = website / in-app screens that look the same on every platform.
// `mac` / `win` = platform-specific, numbered in the order the guide walks through them.
const IMG = {
  common: {
    downloadPage: "/setup-guide/common/download-page.png",
    // The app window looks the same on both platforms, so mac and Windows share it.
    appRunning: "/setup-guide/common/app-running.png",
    settingsButton: "/setup-guide/common/settings-button.png",
    apiKeyEntry: "/setup-guide/common/api-key-entry.png",
    uninstallButton: "/setup-guide/common/uninstall-button.jpeg",
    uninstallConfirm: "/setup-guide/common/uninstall-confirm.jpeg",
  },
  mac: {
    dmgFile: "/setup-guide/mac/02-dmg-file.png",
    dragToApplications: "/setup-guide/mac/03-drag-to-applications.png",
    copyProgress: "/setup-guide/mac/04-copy-progress.png",
    applicationsFolderIcon: "/setup-guide/mac/05-applications-folder-icon.png",
    ejectInstaller: "/setup-guide/mac/06-eject-installer.png",
    doubleClickBlocked: "/setup-guide/mac/07-double-click-blocked.png",
    rightClickOpen: "/setup-guide/mac/08-right-click-open.png",
    confirmOpen: "/setup-guide/mac/09-confirm-open.png",
  },
  // Not committed yet — see frontend/public/setup-guide/windows/README.md.
  // Each renders a placeholder until the file is added, then works with no code change.
  win: {
    downloadedInstaller: "/setup-guide/windows/01-downloaded-installer.png",
    smartScreenWarning: "/setup-guide/windows/02-smartscreen-warning.png",
    smartScreenRunAnyway: "/setup-guide/windows/03-smartscreen-run-anyway.png",
    installing: "/setup-guide/windows/04-installing.png",
    startMenu: "/setup-guide/windows/05-start-menu.png",
  },
};

// Bumped from `app.setupGuide.os` so a value stored while the guide always
// defaulted to macOS is discarded and detection runs again.
const OS_STORAGE_KEY = "app.setupGuide.os.v2";

// Whether the install walkthrough is folded away. Remembered so someone who has
// already installed the app can come back for the API-key steps without
// scrolling past the whole thing again.
const INSTALL_COLLAPSED_KEY = "app.setupGuide.installCollapsed";

type TargetOS = "mac" | "windows";

const OPENROUTER_HOME_URL = "https://openrouter.ai/";
const OPENROUTER_KEYS_URL = "https://openrouter.ai/settings/keys";

// Anchor for the OpenRouter walkthrough further down the page; the provider table
// points at it instead of an outside tutorial.
const OPENROUTER_SECTION_ID = "openrouter-free";

type Provider = {
  // Company names are not translated; everything else is a translation key.
  name: string;
  modelsKey: string;
  free: boolean;
  href: string;
  linkKey: string;
  // In-page anchor rather than an outside tutorial, so it must not open a new tab.
  internal?: boolean;
};

const PROVIDERS: Provider[] = [
  {
    name: "OpenRouter",
    modelsKey: "setup.provider.openrouter.models",
    free: true,
    // No external tutorial needed — the step-by-step instructions are on this page.
    href: `#${OPENROUTER_SECTION_ID}`,
    linkKey: "setup.link.seeBelow",
    internal: true,
  },
  {
    name: "Google",
    modelsKey: "setup.provider.google.models",
    free: false,
    href: "https://ai.google.dev/gemini-api/docs/api-key",
    linkKey: "setup.link.tutorial",
  },
  {
    name: "Anthropic",
    modelsKey: "setup.provider.anthropic.models",
    free: false,
    href: "https://platform.claude.com/docs/en/get-api-key",
    linkKey: "setup.link.tutorial",
  },
  {
    name: "OpenAI",
    modelsKey: "setup.provider.openai.models",
    free: false,
    href: "https://www.apideck.com/blog/how-to-get-your-chatgpt-openai-api-key",
    linkKey: "setup.link.tutorial",
  },
];

// Best-effort guess at the visitor's platform. macOS is the fallback whenever we
// cannot positively identify Windows.
function detectOS(): TargetOS {
  if (typeof navigator === "undefined") return "mac";

  const uaData = (navigator as Navigator & { userAgentData?: { platform?: string } })
    .userAgentData;

  // userAgentData is the non-deprecated source, but it is Chromium-only and only
  // exposed in secure contexts — fall through to the UA string when it is absent
  // or reports an empty platform.
  const platform = `${uaData?.platform || ""} ${navigator.platform || ""} ${
    navigator.userAgent || ""
  }`.toLowerCase();

  return platform.includes("win") ? "windows" : "mac";
}

export default function SetupGuide() {
  const { t } = useLanguage();
  const { isDark } = useAppearance();
  const [os, setOS] = useState<TargetOS>("mac");
  const [installOpen, setInstallOpen] = useState(true);

  useEffect(() => {
    // Precedence: an explicit earlier choice, then platform detection, then macOS.
    try {
      const stored = localStorage.getItem(OS_STORAGE_KEY);
      if (stored === "mac" || stored === "windows") {
        setOS(stored);
        return;
      }
    } catch {}

    setOS(detectOS());
  }, []);

  useEffect(() => {
    // Expanded by default; only a previously saved "collapsed" folds it away.
    try {
      if (localStorage.getItem(INSTALL_COLLAPSED_KEY) === "1") setInstallOpen(false);
    } catch {}
  }, []);

  const toggleInstall = () => {
    setInstallOpen((previous) => {
      const next = !previous;
      try {
        localStorage.setItem(INSTALL_COLLAPSED_KEY, next ? "0" : "1");
      } catch {}
      return next;
    });
  };

  const chooseOS = (next: TargetOS) => {
    setOS(next);
    // Switching platform while collapsed would otherwise look like nothing happened.
    setInstallOpen(true);
    try {
      localStorage.setItem(OS_STORAGE_KEY, next);
      localStorage.setItem(INSTALL_COLLAPSED_KEY, "0");
    } catch {}
  };

  useEffect(() => {
    // index.css disables page scrolling app-wide (`body { overflow-y: hidden }`) for the
    // chat UI, which scrolls its own panes. This page is a long document, so re-enable it
    // here and restore the global behaviour on the way out.
    const previousOverflowY = document.body.style.overflowY;
    document.body.style.overflowY = "auto";

    // Router navigation keeps the previous page's scroll offset; start at the top.
    window.scrollTo(0, 0);

    return () => {
      document.body.style.overflowY = previousOverflowY;
    };
  }, []);

  const bgClass = isDark
    ? "bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900"
    : "bg-gradient-to-br from-slate-50 via-white to-slate-100";

  const textPrimary = isDark ? "text-white" : "text-slate-900";
  const textSecondary = isDark ? "text-slate-300" : "text-slate-600";
  const cardBg = isDark ? "bg-slate-800/60" : "bg-white";
  const cardBorder = isDark ? "border-slate-700" : "border-slate-200";
  const utilityButtonClass = isDark
    ? "border-slate-600 bg-slate-900/65 text-slate-100 hover:border-slate-500 hover:bg-slate-800"
    : "border-slate-300 bg-white/75 text-slate-800 hover:border-slate-400 hover:bg-white";
  const panelClass = isDark
    ? "border-slate-700 bg-slate-900/40"
    : "border-slate-200 bg-slate-50";
  const linkClass = "font-semibold text-teal-500 underline underline-offset-4";
  // Names of things the reader clicks. Operating-system labels (Downloads, Open,
  // Run anyway…) stay in English because that is what their machine shows unless
  // their whole OS is localised, and UpcurvEd's own Settings screen is still English.
  const ui = (label: string) => <strong>{label}</strong>;
  const noteLabel = <strong>{t("common.note")}</strong>;
  const headingClass = `mb-3 text-xl font-bold ${textPrimary}`;
  const listClass = `ml-5 list-decimal space-y-4 ${textSecondary}`;

  // Screenshot sitting directly under the instruction it illustrates, as in the
  // Word document. Windows files are not committed yet, so a missing image
  // degrades to a labelled placeholder instead of a broken-image icon.
  function Shot({
    src,
    alt,
    className = "mt-3 w-full",
  }: {
    src: string;
    alt: string;
    // Sizing/spacing only — small or portrait screenshots look bad stretched to
    // the full column width, so those callers pass a narrower cap.
    className?: string;
  }) {
    const [failed, setFailed] = useState(false);
    const name = src.split("/").slice(-2).join("/");

    if (failed) {
      return (
        <div
          className={`flex items-center justify-center rounded-xl border-2 border-dashed px-4 py-10 text-center text-sm ${className} ${
            isDark
              ? "border-slate-600 bg-slate-900/40 text-slate-400"
              : "border-slate-300 bg-slate-100 text-slate-500"
          }`}
        >
          <span>
            {t("setup.shotPending")}
            <span className="mt-1 block font-mono text-xs opacity-70">{name}</span>
          </span>
        </div>
      );
    }

    return (
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
        className={`rounded-xl border border-slate-600 shadow-lg ${className}`}
      />
    );
  }

  const osTabClass = (value: TargetOS) => {
    if (os === value) return "bg-teal-500 text-white shadow-sm";
    return isDark
      ? "text-slate-300 hover:bg-slate-700/60"
      : "text-slate-600 hover:bg-slate-200/70";
  };

  return (
    <div className={`min-h-screen ${bgClass} relative overflow-hidden transition-colors duration-500`}>
      <div className="absolute inset-0 overflow-hidden opacity-20">
        <div
          className={`absolute right-20 top-20 h-96 w-96 rounded-full ${isDark ? "bg-teal-500" : "bg-teal-400"} animate-pulse blur-3xl`}
        />
        <div
          className={`absolute bottom-20 left-20 h-96 w-96 rounded-full ${isDark ? "bg-purple-600" : "bg-purple-400"} blur-3xl`}
          style={{ animationDelay: "1s" }}
        />
      </div>

      <div className="relative z-10 mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-8">
          <div className="mb-4 flex items-center justify-between gap-3">
          <Link
            to="/home"
            className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition-colors ${utilityButtonClass}`}
          >
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path d="M15 5l-7 7 7 7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t("setup.backToHome")}
          </Link>

          <SettingsMenu isDark={isDark} buttonClassName={utilityButtonClass} />
          </div>

          <div className="text-center">
            <img
              src="/upcurved-logo.png"
              alt=""
              aria-hidden="true"
              className="mx-auto mb-4 h-20 w-20"
            />
            <h1 className={`text-2xl font-bold ${textPrimary}`}>{t("setup.title")}</h1>
            <p className={`mt-1 text-base ${textSecondary}`}>
              {t("setup.subtitle")}
            </p>
          </div>
        </header>

        <main className={`rounded-2xl border ${cardBorder} ${cardBg} shadow-2xl backdrop-blur-sm`}>
          <div className="space-y-8 p-5 sm:p-8">
            {/* Sets expectations before the long walkthrough: this is done once, not every time. */}
            <section
              className={`rounded-xl border p-5 ${
                isDark ? "border-teal-500/30 bg-teal-500/10" : "border-teal-300 bg-teal-50"
              }`}
            >
              <h2 className={`mb-2 text-xl font-bold ${textPrimary}`}>{t("setup.intro.heading")}</h2>
              <p className={textSecondary}>
                <Trans
                  k="setup.intro.body"
                  components={{ lead: <strong>{t("setup.intro.lead")}</strong> }}
                />
              </p>
            </section>

            {/* The only side-by-side section: a short list next to the download screenshot. */}
            <section className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
              <div>
                <h2 className={headingClass}>{t("setup.download.heading")}</h2>
                <ol className={`ml-5 list-decimal space-y-2 ${textSecondary}`}>
                  <li>
                    <Trans
                      k="setup.download.step1"
                      components={{
                        link: (
                          <a className={linkClass} href="https://upcurved.vercel.app/home" target="_blank" rel="noreferrer">
                            https://upcurved.vercel.app/home
                          </a>
                        ),
                      }}
                    />
                  </li>
                  <li>{t("setup.download.step2")}</li>
                </ol>
              </div>
              <img
                src={IMG.common.downloadPage}
                alt={t("setup.download.imageAlt")}
                className="w-full rounded-xl border border-slate-600 shadow-lg"
              />
            </section>

            {/* This block differs per platform; the sections around it are shared. */}
            <div className={`rounded-xl border p-5 ${panelClass}`}>
              <div
                className={`flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between ${
                  installOpen ? "mb-5" : ""
                }`}
              >
                <button
                  type="button"
                  onClick={toggleInstall}
                  aria-expanded={installOpen}
                  aria-controls="setup-install-body"
                  className="group flex items-start gap-3 rounded-lg text-left"
                >
                  <svg
                    viewBox="0 0 24 24"
                    className={`mt-1 h-5 w-5 shrink-0 transition-transform ${textSecondary} ${
                      installOpen ? "rotate-90" : ""
                    }`}
                    fill="none"
                    stroke="currentColor"
                    aria-hidden="true"
                  >
                    <path d="M9 5l7 7-7 7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>
                    <span className={`block text-xl font-bold ${textPrimary} group-hover:underline`}>
                      {t("setup.install.heading")}
                    </span>
                    {!installOpen && (
                      <span className={`mt-1 block text-sm ${textSecondary}`}>
                        {t("setup.install.collapsedHint")}
                      </span>
                    )}
                  </span>
                </button>

                <div
                  role="tablist"
                  aria-label={t("setup.os.aria")}
                  className={`inline-flex shrink-0 rounded-full border p-1 ${
                    isDark ? "border-slate-700 bg-slate-900/60" : "border-slate-300 bg-white"
                  }`}
                >
                  <button
                    type="button"
                    role="tab"
                    id="setup-tab-mac"
                    aria-selected={os === "mac"}
                    aria-controls="setup-panel-mac"
                    onClick={() => chooseOS("mac")}
                    className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors ${osTabClass("mac")}`}
                  >
                    macOS
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="setup-tab-windows"
                    aria-selected={os === "windows"}
                    aria-controls="setup-panel-windows"
                    onClick={() => chooseOS("windows")}
                    className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors ${osTabClass("windows")}`}
                  >
                    Windows
                  </button>
                </div>
              </div>

              <div id="setup-install-body" hidden={!installOpen}>
              {os === "mac" ? (
                <div role="tabpanel" id="setup-panel-mac" aria-labelledby="setup-tab-mac" className="space-y-8">
                  <section>
                    <h3 className={headingClass}>{t("setup.installer.heading")}</h3>
                    <ol className={listClass}>
                      <li>
                        <Trans
                          k="setup.mac.installer.step1"
                          components={{
                            downloads: ui("Downloads"),
                            file: ui("UpcurvEd-mac-arm64.dmg"),
                          }}
                        />
                        <Shot src={IMG.mac.dmgFile} alt={t("setup.mac.installer.step1.alt")} />
                      </li>
                      <li>
                        {t("setup.mac.installer.step2")}
                        <Shot
                          src={IMG.mac.dragToApplications}
                          alt={t("setup.mac.installer.step2.alt")}
                        />
                      </li>
                      <li>
                        {t("setup.mac.installer.step3")}
                        <Shot
                          src={IMG.mac.copyProgress}
                          alt={t("setup.mac.installer.step3.alt")}
                        />
                      </li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>{t("setup.finish.heading")}</h3>
                    <ol className={listClass}>
                      <li>{t("setup.mac.finish.step1")}</li>
                      <li>
                        {/* Just an app icon — sits beside the text rather than stretched below it. */}
                        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                          <span>{t("setup.mac.finish.step2")}</span>
                          <Shot
                            src={IMG.mac.applicationsFolderIcon}
                            alt={t("setup.mac.finish.step2.alt")}
                            className="w-24 shrink-0"
                          />
                        </div>
                      </li>
                      <li>
                        <Trans k="setup.mac.finish.step3" components={{ note: noteLabel }} />
                        <Shot src={IMG.mac.ejectInstaller} alt={t("setup.mac.finish.step3.alt")} />
                      </li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>{t("setup.mac.open.heading")}</h3>
                    <ol className={listClass}>
                      <li>
                        <Trans k="setup.mac.open.step1" components={{ note: noteLabel }} />
                        <Shot
                          src={IMG.mac.doubleClickBlocked}
                          alt={t("setup.mac.open.step1.alt")}
                        />
                      </li>
                      <li>
                        <Trans k="setup.mac.open.step2" components={{ open: ui("Open") }} />
                        <Shot src={IMG.mac.rightClickOpen} alt={t("setup.mac.open.step2.alt")} />
                      </li>
                      <li>
                        <Trans k="setup.mac.open.step3" components={{ open: ui("Open") }} />
                        <Shot src={IMG.mac.confirmOpen} alt={t("setup.mac.open.step3.alt")} />
                      </li>
                      <li>
                        {t("setup.mac.open.step4")}
                        <Shot src={IMG.common.appRunning} alt={t("setup.common.appRunningAlt")} />
                      </li>
                    </ol>
                  </section>
                </div>
              ) : (
                <div role="tabpanel" id="setup-panel-windows" aria-labelledby="setup-tab-windows" className="space-y-8">
                  <section>
                    <h3 className={headingClass}>{t("setup.installer.heading")}</h3>
                    <ol className={listClass}>
                      <li>
                        <Trans
                          k="setup.win.installer.step1"
                          components={{
                            downloads: ui("Downloads"),
                            file: ui("UpcurvEd-win-x64.exe"),
                          }}
                        />
                        <Shot
                          src={IMG.win.downloadedInstaller}
                          alt={t("setup.win.installer.step1.alt")}
                        />
                      </li>
                      <li>{t("setup.win.installer.step2")}</li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>{t("setup.win.smartscreen.heading")}</h3>
                    <ol className={listClass}>
                      <li>
                        <Trans
                          k="setup.win.smartscreen.step1"
                          components={{ note: noteLabel, screen: ui("Windows protected your PC") }}
                        />
                        <Shot src={IMG.win.smartScreenWarning} alt={t("setup.win.smartscreen.step1.alt")} />
                      </li>
                      <li>
                        <Trans
                          k="setup.win.smartscreen.step2"
                          components={{
                            moreInfo: ui("More info"),
                            unknownPublisher: ui("Unknown publisher"),
                            runAnyway: ui("Run anyway"),
                          }}
                        />
                        <Shot
                          src={IMG.win.smartScreenRunAnyway}
                          alt={t("setup.win.smartscreen.step2.alt")}
                        />
                      </li>
                      <li>{t("setup.win.smartscreen.step3")}</li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>{t("setup.finish.heading")}</h3>
                    <ol className={listClass}>
                      <li>
                        <Trans
                          k="setup.win.finish.step1"
                          components={{ installing: ui("Installing, please wait…") }}
                        />
                        <Shot src={IMG.win.installing} alt={t("setup.win.finish.step1.alt")} />
                      </li>
                      <li>{t("setup.win.finish.step2")}</li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>{t("setup.win.open.heading")}</h3>
                    <ol className={listClass}>
                      <li>
                        <Trans k="setup.win.open.step1" components={{ startMenu: ui("Start menu") }} />
                        <Shot src={IMG.win.startMenu} alt={t("setup.win.open.step1.alt")} />
                      </li>
                      <li>{t("setup.win.open.step2")}</li>
                      <li>{t("setup.win.open.step3")}</li>
                      <li>
                        {t("setup.win.open.step4")}
                        <Shot src={IMG.common.appRunning} alt={t("setup.common.appRunningAlt")} />
                      </li>
                    </ol>
                  </section>
                </div>
              )}
              </div>
            </div>

            <section className="space-y-5">
              <div>
                <h2 className={headingClass}>{t("setup.api.heading")}</h2>
                <div className={`space-y-3 ${textSecondary}`}>
                  <p>
                    <strong>{t("setup.api.whatIs.q")}</strong> {t("setup.api.whatIs.a")}
                  </p>
                  <p>{t("setup.api.internet")}</p>
                  <p>
                    <strong>{t("setup.api.where.q")}</strong> {t("setup.api.where.a")}
                  </p>
                  <ul className="ml-5 list-disc space-y-2">
                    <li>
                      <strong>{t("setup.api.bullet1.lead")}</strong> {t("setup.api.bullet1.body")}
                    </li>
                    <li>
                      <strong>{t("setup.api.bullet2.lead")}</strong> {t("setup.api.bullet2.body")}
                    </li>
                    <li>
                      <strong>{t("setup.api.bullet3.lead")}</strong>{" "}
                      <Trans
                        k="setup.api.bullet3.body"
                        components={{
                          settings: ui("Settings"),
                          secureKeyStorage: ui("Secure key storage"),
                        }}
                      />
                    </li>
                    <li>
                      <strong>{t("setup.api.bullet4.lead")}</strong> {t("setup.api.bullet4.body")}
                    </li>
                  </ul>
                </div>
              </div>

              <div className={`overflow-hidden rounded-xl border ${panelClass}`}>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-left text-sm">
                    <caption className="sr-only">{t("setup.table.caption")}</caption>
                    <thead>
                      <tr className={`border-b ${isDark ? "border-slate-700" : "border-slate-200"}`}>
                        <th scope="col" className={`px-4 py-3 font-semibold ${textPrimary}`}>{t("setup.table.provider")}</th>
                        <th scope="col" className={`px-4 py-3 font-semibold ${textPrimary}`}>{t("setup.table.models")}</th>
                        <th scope="col" className={`px-4 py-3 font-semibold ${textPrimary}`}>{t("setup.table.cost")}</th>
                        <th scope="col" className={`px-4 py-3 font-semibold ${textPrimary}`}>{t("setup.table.getKey")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {PROVIDERS.map((provider) => (
                        <tr
                          key={provider.name}
                          className={`border-b last:border-b-0 ${isDark ? "border-slate-800" : "border-slate-200"}`}
                        >
                          <th scope="row" className={`px-4 py-3 font-semibold ${textPrimary}`}>
                            {provider.name}
                          </th>
                          <td className={`px-4 py-3 ${textSecondary}`}>{t(provider.modelsKey)}</td>
                          <td className="px-4 py-3">
                            <span
                              className={`inline-block whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${
                                provider.free
                                  ? isDark
                                    ? "bg-emerald-500/15 text-emerald-300"
                                    : "bg-emerald-100 text-emerald-800"
                                  : isDark
                                    ? "bg-slate-700/60 text-slate-300"
                                    : "bg-slate-200 text-slate-700"
                              }`}
                            >
                              {t(provider.free ? "setup.cost.freeRateLimited" : "setup.cost.paid")}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <a
                              className={linkClass}
                              href={provider.href}
                              {...(provider.internal ? {} : { target: "_blank", rel: "noreferrer" })}
                            >
                              {t(provider.linkKey)}
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* The app shows an "est. $x.xx" figure after each generation — this sets
                  expectations that the number is our estimate, not the provider's bill. */}
              <div
                className={`rounded-lg border px-4 py-3 text-sm ${
                  isDark
                    ? "border-amber-500/40 bg-amber-500/10 text-amber-100"
                    : "border-amber-400 bg-amber-50 text-amber-900"
                }`}
              >
                <p>
                  <strong>{t("setup.costNotice.lead")}</strong> {t("setup.costNotice.body1")}
                </p>
                <p className="mt-2">{t("setup.costNotice.body2")}</p>
              </div>
            </section>

            {/* Linked from the "See below" cell in the provider table above. */}
            <section id={OPENROUTER_SECTION_ID} className={`scroll-mt-6 rounded-xl border p-5 ${panelClass}`}>
              <h2 className={headingClass}>{t("setup.openrouter.heading")}</h2>
              <ol className={`ml-5 list-decimal space-y-2 ${textSecondary}`}>
                <li>
                  <Trans
                    k="setup.openrouter.step1"
                    components={{
                      link: (
                        <a className={linkClass} href={OPENROUTER_HOME_URL} target="_blank" rel="noreferrer">
                          OpenRouter
                        </a>
                      ),
                    }}
                  />
                </li>
                <li>
                  <Trans
                    k="setup.openrouter.step2"
                    components={{
                      keysPage: (
                        <a className={linkClass} href={OPENROUTER_KEYS_URL} target="_blank" rel="noreferrer">
                          {t("setup.openrouter.keysPageLink")}
                        </a>
                      ),
                      createKey: ui("Create Key"),
                      name: ui("UpcurvEd"),
                    }}
                  />
                </li>
                <li>{t("setup.openrouter.step3")}</li>
                <li>
                  <Trans
                    k="setup.openrouter.step4"
                    components={{ settings: ui("Settings"), openrouter: ui("OpenRouter") }}
                  />
                </li>
                <li>
                  <Trans k="setup.openrouter.step5" components={{ openrouterFree: ui("OpenRouter Free") }} />
                </li>
              </ol>
              <div
                className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
                  isDark
                    ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
                    : "border-amber-300 bg-amber-50 text-amber-900"
                }`}
              >
                {t("setup.openrouter.note")}
              </div>
            </section>

            <section>
              <h2 className={headingClass}>{t("setup.settings.heading")}</h2>
              <ol className={listClass}>
                <li>
                  <Trans k="setup.settings.step1" components={{ settings: ui("Settings") }} />
                  <Shot
                    src={IMG.common.settingsButton}
                    alt={t("setup.settings.step1.alt")}
                    className="mt-3 w-full max-w-sm"
                  />
                </li>
                <li>
                  {t("setup.settings.step2")}
                  {/* Tall portrait screenshot (912x1696) — capped so it doesn't dominate the page. */}
                  <Shot
                    src={IMG.common.apiKeyEntry}
                    alt={t("setup.settings.step2.alt")}
                    className="mt-3 w-full max-w-xs"
                  />
                </li>
              </ol>
            </section>

            <section
              className={`rounded-xl border p-5 ${
                isDark ? "border-emerald-500/30 bg-emerald-500/10" : "border-emerald-300 bg-emerald-50"
              }`}
            >
              <h2 className={`mb-2 text-xl font-bold ${textPrimary}`}>🎉 {t("setup.congrats.heading")}</h2>
              <p className={textSecondary}>{t("setup.congrats.body")}</p>
            </section>

            <section>
              <h2 className={headingClass}>{t("setup.uninstall.heading")}</h2>
              <p className={`mb-4 ${textSecondary}`}>{t("setup.uninstall.intro")}</p>
              <ol className={listClass}>
                <li>
                  <Trans
                    k="setup.uninstall.step1"
                    components={{
                      settings: ui("Settings"),
                      section: ui("Uninstall UpcurvEd"),
                      button: ui("Uninstall UpcurvEd & Delete Local Data"),
                    }}
                  />
                  <Shot
                    src={IMG.common.uninstallButton}
                    alt={t("setup.uninstall.step1.alt")}
                    className="mt-3 w-full max-w-md"
                  />
                </li>
                <li>
                  <Trans
                    k="setup.uninstall.step2"
                    components={{
                      confirm: ui("Uninstall & Delete Local Data"),
                      cancel: ui("Cancel"),
                    }}
                  />
                  <Shot
                    src={IMG.common.uninstallConfirm}
                    alt={t("setup.uninstall.step2.alt")}
                    className="mt-3 w-full max-w-xs"
                  />
                </li>
                <li>{t("setup.uninstall.step3")}</li>
              </ol>
              <div
                className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
                  isDark
                    ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
                    : "border-amber-300 bg-amber-50 text-amber-900"
                }`}
              >
                <p>{t("setup.uninstall.keyNote")}</p>
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
