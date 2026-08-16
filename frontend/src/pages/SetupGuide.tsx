import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

// Screenshots from UpcurvEd_install_open_setup_guide_081626_mac_arm64.docx.
// `common` = website / in-app screens that look the same on every platform.
// `mac` / `win` = platform-specific, numbered in the order the guide walks through them.
const IMG = {
  common: {
    downloadPage: "/setup-guide/common/download-page.png",
    settingsButton: "/setup-guide/common/settings-button.png",
    apiKeyEntry: "/setup-guide/common/api-key-entry.png",
  },
  mac: {
    openZip: "/setup-guide/mac/01-open-zip.png",
    dmgFile: "/setup-guide/mac/02-dmg-file.png",
    dragToApplications: "/setup-guide/mac/03-drag-to-applications.png",
    copyProgress: "/setup-guide/mac/04-copy-progress.png",
    applicationsFolderIcon: "/setup-guide/mac/05-applications-folder-icon.png",
    ejectInstaller: "/setup-guide/mac/06-eject-installer.png",
    doubleClickBlocked: "/setup-guide/mac/07-double-click-blocked.png",
    rightClickOpen: "/setup-guide/mac/08-right-click-open.png",
    confirmOpen: "/setup-guide/mac/09-confirm-open.png",
    appRunningDock: "/setup-guide/mac/10-app-running-dock.png",
  },
  // Not committed yet — see frontend/public/setup-guide/windows/README.md.
  // Each renders a placeholder until the file is added, then works with no code change.
  win: {
    downloadedInstaller: "/setup-guide/windows/01-downloaded-installer.png",
    uacPrompt: "/setup-guide/windows/02-uac-prompt.png",
    installerWindow: "/setup-guide/windows/03-installer-window.png",
    smartScreenWarning: "/setup-guide/windows/04-smartscreen-warning.png",
    smartScreenRunAnyway: "/setup-guide/windows/05-smartscreen-run-anyway.png",
    startMenu: "/setup-guide/windows/06-start-menu.png",
    firewallPrompt: "/setup-guide/windows/07-firewall-prompt.png",
    appRunning: "/setup-guide/windows/08-app-running.png",
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

const PROVIDERS = [
  {
    name: "OpenRouter",
    models: "Many models, including open-source oss-gpt-5 and nvidia-nemotron-3",
    cost: "Free, rate-limited",
    href: "https://developer.puter.com/tutorials/how-to-get-openrouter-api-key/",
  },
  {
    name: "Google",
    models: "Gemini models",
    cost: "Paid",
    href: "https://ai.google.dev/gemini-api/docs/api-key",
  },
  {
    name: "Anthropic",
    models: "Claude models",
    cost: "Paid",
    href: "https://platform.claude.com/docs/en/get-api-key",
  },
  {
    name: "OpenAI",
    models: "ChatGPT models",
    cost: "Paid",
    href: "https://www.apideck.com/blog/how-to-get-your-chatgpt-openai-api-key",
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

          <h1 className={`text-2xl font-bold ${textPrimary}`}>Setup Guide</h1>
          <p className={`mt-1 text-base ${textSecondary}`}>
            How to install, open, and set up UpcurvEd Desktop.
          </p>
        </header>

        <main className={`rounded-2xl border ${cardBorder} ${cardBg} shadow-2xl backdrop-blur-sm`}>
          <div className="space-y-8 p-5 sm:p-8">
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
                        Once the ZIP is downloaded, open it and click the folder.
                        <Shot src={IMG.mac.openZip} alt="Downloaded ZIP opened in Finder" />
                      </li>
                      <li>
                        Click the file <strong>UpcurvEd-1.0.0-mac-arm64.dmg</strong>.
                        <Shot src={IMG.mac.dmgFile} alt="The UpcurvEd mac arm64 .dmg file" />
                      </li>
                      <li>
                        You will see this popup — drag the application icon to the Applications folder.
                        <Shot
                          src={IMG.mac.dragToApplications}
                          alt="Drag the UpcurvEd icon onto the Applications folder"
                        />
                      </li>
                      <li>
                        Wait for UpcurvEd to copy to Applications (size is 1.69 GB).
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
                        <Shot src={IMG.mac.appRunningDock} alt="UpcurvEd running, shown in the macOS dock" />
                      </li>
                    </ol>
                  </section>
                </div>
              ) : (
                <div role="tabpanel" id="setup-panel-windows" aria-labelledby="setup-tab-windows" className="space-y-8">
                  <section>
                    <h3 className={headingClass}>Run the installer</h3>
                    <ol className={listClass}>
                      <li>
                        Open your <strong>Downloads</strong> folder and find{" "}
                        <strong>upcurved-desktop-1.0.0-win-x64.exe</strong>.
                        <Shot src={IMG.win.downloadedInstaller} alt="The downloaded UpcurvEd installer" />
                      </li>
                      <li>
                        Double-click the file to start the installer. If Windows shows a{" "}
                        <strong>User Account Control</strong> prompt asking to allow the app to make changes, click{" "}
                        <strong>Yes</strong>.
                        <Shot src={IMG.win.uacPrompt} alt="Windows User Account Control prompt" />
                      </li>
                      <li>
                        Choose an install location if you are asked, then click <strong>Install</strong> and wait. The
                        build is around 1.69 GB, so this can take a few minutes.
                        <Shot src={IMG.win.installerWindow} alt="The UpcurvEd Windows installer window" />
                      </li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>Get past the SmartScreen warning</h3>
                    <ol className={listClass}>
                      <li>
                        <strong>Note:</strong> UpcurvEd is not code-signed yet, so Windows may show a blue{" "}
                        <strong>Windows protected your PC</strong> screen instead of running the installer.
                        <Shot src={IMG.win.smartScreenWarning} alt="Windows protected your PC SmartScreen warning" />
                      </li>
                      <li>
                        Click <strong>More info</strong>, then click the <strong>Run anyway</strong> button that
                        appears.
                        <Shot src={IMG.win.smartScreenRunAnyway} alt="The Run anyway button on the SmartScreen screen" />
                      </li>
                      <li>
                        If your antivirus quarantines the download, restore it and allow the file, then run it again.
                      </li>
                    </ol>
                  </section>

                  <section>
                    <h3 className={headingClass}>Open the app on Windows</h3>
                    <ol className={listClass}>
                      <li>
                        Open UpcurvEd from the <strong>Start menu</strong>, or from the desktop shortcut the installer
                        created.
                        <Shot src={IMG.win.startMenu} alt="UpcurvEd in the Windows Start menu" />
                      </li>
                      <li>
                        The first launch is slower than later ones — UpcurvEd starts a local server on your machine
                        before the window appears.
                      </li>
                      <li>
                        If <strong>Windows Defender Firewall</strong> asks, allow UpcurvEd on{" "}
                        <strong>Private networks</strong>. The app needs this to talk to its own local server.
                        <Shot src={IMG.win.firewallPrompt} alt="Windows Defender Firewall network access prompt" />
                      </li>
                      <li>
                        Once the window opens, you can pin UpcurvEd to your taskbar for quicker access.
                        <Shot src={IMG.win.appRunning} alt="UpcurvEd running on Windows" />
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
                            <a className={linkClass} href={provider.href} target="_blank" rel="noreferrer">
                              Tutorial
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section className={`rounded-xl border p-5 ${panelClass}`}>
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
          </div>
        </main>
      </div>
    </div>
  );
}
