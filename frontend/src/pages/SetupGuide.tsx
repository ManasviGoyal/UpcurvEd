import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

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
  name: string;
  models: string;
  cost: string;
  href: string;
  linkLabel: string;
  // In-page anchor rather than an outside tutorial, so it must not open a new tab.
  internal?: boolean;
};

const PROVIDERS: Provider[] = [
  {
    name: "OpenRouter",
    models: "Many models, including open-source oss-gpt-5 and nvidia-nemotron-3",
    cost: "Free, rate-limited",
    // No external tutorial needed — the step-by-step instructions are on this page.
    href: `#${OPENROUTER_SECTION_ID}`,
    linkLabel: "See below",
    internal: true,
  },
  {
    name: "Google",
    models: "Gemini models",
    cost: "Paid",
    href: "https://ai.google.dev/gemini-api/docs/api-key",
    linkLabel: "Tutorial",
  },
  {
    name: "Anthropic",
    models: "Claude models",
    cost: "Paid",
    href: "https://platform.claude.com/docs/en/get-api-key",
    linkLabel: "Tutorial",
  },
  {
    name: "OpenAI",
    models: "ChatGPT models",
    cost: "Paid",
    href: "https://www.apideck.com/blog/how-to-get-your-chatgpt-openai-api-key",
    linkLabel: "Tutorial",
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
  const [isDark, setIsDark] = useState(true);
  const [os, setOS] = useState<TargetOS>("mac");
  const [installOpen, setInstallOpen] = useState(true);

  useEffect(() => {
    const hour = new Date().getHours();
    setIsDark(hour >= 18 || hour < 6);
  }, []);

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
            Screenshot coming soon
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
          <Link
            to="/home"
            className={`mb-4 inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition-colors ${utilityButtonClass}`}
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
            Back to home
          </Link>

          <div className="text-center">
            <img
              src="/upcurved-logo.png"
              alt=""
              aria-hidden="true"
              className="mx-auto mb-4 h-20 w-20"
            />
            <h1 className={`text-2xl font-bold ${textPrimary}`}>Setup Guide</h1>
            <p className={`mt-1 text-base ${textSecondary}`}>
              How to install, open, and set up UpcurvEd Desktop.
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
              <h2 className={`mb-2 text-xl font-bold ${textPrimary}`}>Before you start</h2>
              <p className={textSecondary}>
                <strong>These are one-time setup steps.</strong> You install UpcurvEd and add your API key
                once — after that, just open the app and start working. Come back to this page only if you
                switch computers, or need a new API key.
              </p>
            </section>

            {/* The only side-by-side section: a short list next to the download screenshot. */}
            <section className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
              <div>
                <h2 className={headingClass}>Download the app</h2>
                <ol className={`ml-5 list-decimal space-y-2 ${textSecondary}`}>
                  <li>
                    Go to{" "}
                    <a className={linkClass} href="https://upcurved.vercel.app/home" target="_blank" rel="noreferrer">
                      https://upcurved.vercel.app/home
                    </a>
                  </li>
                  <li>Click the download button for your operating system.</li>
                </ol>
              </div>
              <img
                src={IMG.common.downloadPage}
                alt="UpcurvEd home page download section"
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
                      Install and open the app
                    </span>
                    {!installOpen && (
                      <span className={`mt-1 block text-sm ${textSecondary}`}>
                        Already installed? Leave this collapsed and skip to the API key steps below.
                      </span>
                    )}
                  </span>
                </button>

                <div
                  role="tablist"
                  aria-label="Operating system"
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
                    <h3 className={headingClass}>Open the installer</h3>
                    <ol className={listClass}>
                      <li>
                        Once the download finishes, open your <strong>Downloads</strong> folder and click the
                        file <strong>UpcurvEd-mac-arm64.dmg</strong>.
                        <Shot src={IMG.mac.dmgFile} alt="The UpcurvEd mac arm64 .dmg file in Finder" />
                      </li>
                      <li>
                        You will see this popup — drag the application icon to the Applications folder.
                        <Shot
                          src={IMG.mac.dragToApplications}
                          alt="Drag the UpcurvEd icon onto the Applications folder"
                        />
                      </li>
                      <li>
                        Wait for UpcurvEd to copy to Applications (around 1.5 GB).
                        <Shot
                          src={IMG.mac.copyProgress}
                          alt="Copy progress dialog showing UpcurvEd being copied to Applications"
                        />
                      </li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>Finish installation</h3>
                    <ol className={listClass}>
                      <li>Double-click the Applications folder icon.</li>
                      <li>
                        {/* Just an app icon — sits beside the text rather than stretched below it. */}
                        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                          <span>In the Applications folder you will find the UpcurvEd icon.</span>
                          <Shot
                            src={IMG.mac.applicationsFolderIcon}
                            alt="UpcurvEd icon inside the Applications folder"
                            className="w-24 shrink-0"
                          />
                        </div>
                      </li>
                      <li>
                        <strong>Note:</strong> once it is installed, you can safely eject the UpcurvEd installer.
                        <Shot src={IMG.mac.ejectInstaller} alt="Ejecting the UpcurvEd installer" />
                      </li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>Open the app on macOS</h3>
                    <ol className={listClass}>
                      <li>
                        <strong>Note:</strong> if you double-click it, it will not let you open it.
                        <Shot
                          src={IMG.mac.doubleClickBlocked}
                          alt="macOS warning shown when double-clicking the app"
                        />
                      </li>
                      <li>
                        Instead, right-click the icon (on a Mac trackpad, click the icon with two fingers). You will
                        see the <strong>Open</strong> option — click it.
                        <Shot src={IMG.mac.rightClickOpen} alt="Right-click menu showing the Open option" />
                      </li>
                      <li>
                        You will get the popup warning and the option to Open. Click <strong>Open</strong>.
                        <Shot src={IMG.mac.confirmOpen} alt="macOS popup with the Open button" />
                      </li>
                      <li>
                        Now that the application is open you will see it on your dock at the bottom of the screen, and
                        it will be open for you. It should look like this:
                        <Shot src={IMG.common.appRunning} alt="UpcurvEd open and ready to use" />
                      </li>
                    </ol>
                  </section>
                </div>
              ) : (
                <div role="tabpanel" id="setup-panel-windows" aria-labelledby="setup-tab-windows" className="space-y-8">
                  <section>
                    <h3 className={headingClass}>Open the installer</h3>
                    <ol className={listClass}>
                      <li>
                        Once the download finishes, open your <strong>Downloads</strong> folder and find{" "}
                        <strong>UpcurvEd-win-x64.exe</strong>.
                        <Shot
                          src={IMG.win.downloadedInstaller}
                          alt="The downloaded UpcurvEd installer in the Downloads folder"
                        />
                      </li>
                      <li>Double-click the file to start the installer.</li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>Get past the SmartScreen warning</h3>
                    <ol className={listClass}>
                      <li>
                        <strong>Note:</strong> UpcurvEd is not code-signed yet, so Windows shows a blue{" "}
                        <strong>Windows protected your PC</strong> screen instead of running the installer.
                        <Shot src={IMG.win.smartScreenWarning} alt="Windows protected your PC SmartScreen warning" />
                      </li>
                      <li>
                        Click <strong>More info</strong>. It expands to show the app name and{" "}
                        <strong>Unknown publisher</strong>, along with a <strong>Run anyway</strong> button. Click{" "}
                        <strong>Run anyway</strong>.
                        <Shot
                          src={IMG.win.smartScreenRunAnyway}
                          alt="SmartScreen expanded with the Run anyway button"
                        />
                      </li>
                      <li>
                        If your antivirus quarantines the download, restore it and allow the file, then run it again.
                      </li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>Finish installation</h3>
                    <ol className={listClass}>
                      <li>
                        UpcurvEd installs on its own — there is nothing to choose. Wait for{" "}
                        <strong>Installing, please wait…</strong> to finish. The app is around 1.5 GB, so this can take
                        a few minutes.
                        <Shot src={IMG.win.installing} alt="UpcurvEd Setup showing an install progress bar" />
                      </li>
                      <li>UpcurvEd opens by itself once the install completes.</li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>Open the app on Windows</h3>
                    <ol className={listClass}>
                      <li>
                        After the first launch, open UpcurvEd from the <strong>Start menu</strong> or the desktop
                        shortcut.
                        <Shot src={IMG.win.startMenu} alt="UpcurvEd in the Windows Start menu" />
                      </li>
                      <li>
                        The first launch is slower than later ones — UpcurvEd starts a local server on your machine
                        before the window appears.
                      </li>
                      <li>Once the window opens, you can pin UpcurvEd to your taskbar for quicker access.</li>
                      <li>
                        It should look like this:
                        <Shot src={IMG.common.appRunning} alt="UpcurvEd open and ready to use" />
                      </li>
                    </ol>
                  </section>
                </div>
              )}
              </div>
            </div>

            <section className="space-y-5">
              <div>
                <h2 className={headingClass}>Get your API key</h2>
                <div className={`space-y-3 ${textSecondary}`}>
                  <p>
                    <strong>What is an API key?</strong> API stands for Application Programming Interface. API keys are
                    used to securely access and send data — in this case prompts and generated responses — to the AI
                    model provider&apos;s online server.
                  </p>
                  <p>Because of this, UpcurvEd requires an internet connection to work.</p>
                  <p>
                    <strong>Where do I obtain an API key?</strong> UpcurvEd supports four AI model providers. Of these
                    four, only OpenRouter has models that are free but rate-limited, meaning you have a certain daily
                    limit.
                  </p>
                  <ul className="ml-5 list-disc space-y-2">
                    <li>
                      <strong>You obtain an API key once.</strong> Create it at your provider, paste it into UpcurvEd,
                      and you are done — you do not need a new key each time you use the app.
                    </li>
                    <li>
                      <strong>Store your API key in a secure place.</strong> Most providers show the key only once, so
                      keep a copy somewhere safe (a password manager, for example) before you close the page. Treat it
                      like a password and do not share it.
                    </li>
                    <li>
                      <strong>Use the Secure key storage toggle.</strong> In UpcurvEd&apos;s{" "}
                      <strong>Settings</strong>, turn on <strong>Secure key storage</strong> to keep your key in your
                      operating system&apos;s keychain instead of ordinary app storage. Your system may show a prompt
                      the first time you save.
                    </li>
                    <li>
                      <strong>Some API keys expire.</strong> Depending on the limit or expiry you set when creating the
                      key — and on your provider&apos;s own policy — a key can stop working. If generation suddenly
                      fails, create a fresh key and paste the new one into Settings.
                    </li>
                  </ul>
                </div>
              </div>

              <div className={`overflow-hidden rounded-xl border ${panelClass}`}>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-left text-sm">
                    <caption className="sr-only">Supported AI model providers and where to get an API key</caption>
                    <thead>
                      <tr className={`border-b ${isDark ? "border-slate-700" : "border-slate-200"}`}>
                        <th scope="col" className={`px-4 py-3 font-semibold ${textPrimary}`}>Provider</th>
                        <th scope="col" className={`px-4 py-3 font-semibold ${textPrimary}`}>Models</th>
                        <th scope="col" className={`px-4 py-3 font-semibold ${textPrimary}`}>Cost</th>
                        <th scope="col" className={`px-4 py-3 font-semibold ${textPrimary}`}>Get a key</th>
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
                          <td className={`px-4 py-3 ${textSecondary}`}>{provider.models}</td>
                          <td className="px-4 py-3">
                            <span
                              className={`inline-block whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${
                                provider.cost.startsWith("Free")
                                  ? isDark
                                    ? "bg-emerald-500/15 text-emerald-300"
                                    : "bg-emerald-100 text-emerald-800"
                                  : isDark
                                    ? "bg-slate-700/60 text-slate-300"
                                    : "bg-slate-200 text-slate-700"
                              }`}
                            >
                              {provider.cost}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <a
                              className={linkClass}
                              href={provider.href}
                              {...(provider.internal ? {} : { target: "_blank", rel: "noreferrer" })}
                            >
                              {provider.linkLabel}
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            {/* Linked from the "See below" cell in the provider table above. */}
            <section id={OPENROUTER_SECTION_ID} className={`scroll-mt-6 rounded-xl border p-5 ${panelClass}`}>
              <h2 className={headingClass}>Use UpcurvEd for free with OpenRouter</h2>
              <ol className={`ml-5 list-decimal space-y-2 ${textSecondary}`}>
                <li>
                  Visit{" "}
                  <a className={linkClass} href={OPENROUTER_HOME_URL} target="_blank" rel="noreferrer">
                    OpenRouter
                  </a>{" "}
                  and create an account or sign in.
                </li>
                <li>
                  Open the{" "}
                  <a className={linkClass} href={OPENROUTER_KEYS_URL} target="_blank" rel="noreferrer">
                    API Keys page
                  </a>
                  , select <strong>Create Key</strong>, and give it a recognizable name such as{" "}
                  <strong>UpcurvEd</strong>.
                </li>
                <li>Copy the new key when OpenRouter shows it.</li>
                <li>
                  In UpcurvEd, open <strong>Settings</strong>, select <strong>OpenRouter</strong>, paste the key, and
                  save it.
                </li>
                <li>
                  Choose <strong>OpenRouter Free</strong> or another model marked as free, then start generating.
                </li>
              </ol>
              <div
                className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
                  isDark
                    ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
                    : "border-amber-300 bg-amber-50 text-amber-900"
                }`}
              >
                Free models do not charge for model requests, but availability, speed, and usage limits can vary. During
                busy periods, try again or select a different free model.
              </div>
            </section>

            <section>
              <h2 className={headingClass}>Add your key in Settings</h2>
              <ol className={listClass}>
                <li>
                  Click <strong>Settings</strong> in the lower right.
                  <Shot
                    src={IMG.common.settingsButton}
                    alt="Settings button in the lower right of UpcurvEd"
                    className="mt-3 w-full max-w-sm"
                  />
                </li>
                <li>
                  Here is where you enter your API key and the model you want to use in the current chat.
                  {/* Tall portrait screenshot (912x1696) — capped so it doesn't dominate the page. */}
                  <Shot
                    src={IMG.common.apiKeyEntry}
                    alt="UpcurvEd settings screen showing API key and model entry"
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
              <h2 className={`mb-2 text-xl font-bold ${textPrimary}`}>🎉 Congratulations</h2>
              <p className={textSecondary}>
                Your setup is complete, and you are now ready to use UpcurvEd. We hope the tool helps you with your
                learning or teaching.
              </p>
            </section>

            <section>
              <h2 className={headingClass}>Uninstall UpcurvEd</h2>
              <p className={`mb-4 ${textSecondary}`}>
                You only need this if you want to remove UpcurvEd from your computer. UpcurvEd can uninstall itself
                from inside the app.
              </p>
              <ol className={listClass}>
                <li>
                  In UpcurvEd, click <strong>Settings</strong> in the lower right and scroll down to{" "}
                  <strong>Uninstall UpcurvEd</strong>. Click{" "}
                  <strong>Uninstall UpcurvEd &amp; Delete Local Data</strong>.
                  <Shot
                    src={IMG.common.uninstallButton}
                    alt="The Uninstall UpcurvEd and Delete Local Data button in Settings"
                    className="mt-3 w-full max-w-md"
                  />
                </li>
                <li>
                  A confirmation appears. Click <strong>Uninstall &amp; Delete Local Data</strong> to go ahead, or{" "}
                  <strong>Cancel</strong> to keep the app.
                  <Shot
                    src={IMG.common.uninstallConfirm}
                    alt="Confirmation dialog asking whether to uninstall UpcurvEd and delete its local data"
                    className="mt-3 w-full max-w-xs"
                  />
                </li>
                <li>
                  UpcurvEd closes and removes itself along with your local chats, generated working files,
                  diagnostics, settings, caches, and saved API keys. Files you exported or downloaded yourself are
                  left alone.
                </li>
              </ol>
              <div
                className={`mt-4 rounded-lg border px-4 py-3 text-sm ${
                  isDark
                    ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
                    : "border-amber-300 bg-amber-50 text-amber-900"
                }`}
              >
                <p>
                  <strong>On Windows:</strong> the in-app uninstall is currently macOS only. Uninstall UpcurvEd from{" "}
                  <strong>Settings &rsaquo; Apps &rsaquo; Installed apps</strong>, find <strong>UpcurvEd</strong>, and
                  choose <strong>Uninstall</strong>.
                </p>
                <p className="mt-2">
                  Uninstalling deletes the copy of your API key on this computer, but the key itself stays active at
                  your provider. Delete it in your provider&apos;s dashboard if you no longer want it.
                </p>
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
