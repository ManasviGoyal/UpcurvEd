import { useState } from "react";
import { useNavigate } from "react-router-dom";
import DocsModal from "@/components/landing/DocsModal";
import FeedbackModal from "@/components/landing/FeedbackModal";
import NoticeOfConsentModal from "@/components/landing/NoticeOfConsentModal";
import { trackEvent } from "@/lib/analytics";
import SettingsMenu from "@/components/SettingsMenu";
import { useLanguage } from "@/lib/i18n";
import { useAppearance } from "@/lib/appearance";

// Direct release-asset links. On a public repo these need no GitHub account: the URL
// redirects to a signed CDN link served with `Content-Disposition: attachment`, so the
// browser starts the download without ever showing a GitHub page. `latest/download/`
// always resolves to the newest published release, and electron-builder is configured to
// emit version-less filenames so these URLs never need editing.
//
// The owner/repo is not written here — vite.config.ts derives it from the root
// package.json `repository` field at build time.
const RELEASE_ASSETS = __RELEASE_ASSETS_BASE__;

const DOWNLOADS = {
  windows: `${RELEASE_ASSETS}/UpcurvEd-win-x64.exe`,
  // Apple Silicon only. The Intel build is still published as a release asset;
  // it is simply not surfaced here.
  macArm: `${RELEASE_ASSETS}/UpcurvEd-mac-arm64.dmg`,
  linux: `${RELEASE_ASSETS}/UpcurvEd-linux-x86_64.AppImage`,
} as const;

export default function Landing({ setView: _setView }: { setView?: (view: string) => void }) {
  const navigate = useNavigate();
  const { t } = useLanguage();
  const { isDark, reduceMotion } = useAppearance();
  const [mutedStates, setMutedStates] = useState([true, true, true]);
  const [isDocsOpen, setIsDocsOpen] = useState(false);
  const [isConsentOpen, setIsConsentOpen] = useState(false);
  const [isFeedbackOpen, setIsFeedbackOpen] = useState(false);
  const iconColor = isDark ? "FFFFFF" : "0F172A";
  const appleLogo = `https://cdn.simpleicons.org/apple/${iconColor}`;
  const linuxLogo = `https://cdn.simpleicons.org/linux/${iconColor}`;

  const toggleMute = (index: number) => {
    setMutedStates((previous) => {
      const next = [...previous];
      next[index] = !next[index];
      return next;
    });
  };

  // The <a href> performs the download; this only records the click.
  const handleDownloadClick = (platform: "windows" | "mac-arm64" | "linux") => {
    trackEvent("download_click", { platform });
  };

  const handleDocsOpen = () => {
    trackEvent("docs_open", { source: "landing" });
    setIsDocsOpen(true);
  };

  const handleSetupGuideClick = () => {
    trackEvent("setup_guide_open", { source: "landing" });
    navigate("/setup-guide");
  };

  const handleFeedbackClick = () => {
    trackEvent("feedback_click", { source: "landing" });
    setIsFeedbackOpen(true);
  };

  const handleConsentClick = () => {
    trackEvent("consent_open", { source: "landing" });
    setIsConsentOpen(true);
  };

  const bgClass = isDark
    ? "bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900"
    : "bg-gradient-to-br from-slate-50 via-white to-slate-100";

  const textPrimary = isDark ? "text-white" : "text-slate-900";
  const textSecondary = isDark ? "text-slate-300" : "text-slate-600";
  const textTertiary = isDark ? "text-slate-400" : "text-slate-500";
  const cardBg = isDark ? "bg-slate-800/50" : "bg-white";
  const cardBorder = isDark ? "border-slate-700" : "border-slate-200";
  const utilityButtonClass = isDark
    ? "border-slate-600 bg-slate-900/65 text-slate-100 hover:border-slate-500 hover:bg-slate-800"
    : "border-slate-300 bg-white/75 text-slate-800 hover:border-slate-400 hover:bg-white";

  // Titles are technical names and stay as written; the description and category are
  // ordinary UI copy and come from the translation table.
  const exampleVideos = [
    {
      title: "Convex Optimization",
      description: t("demo.convex.description"),
      videoUrl: "/landing_snippets/demo1_convex.mov",
      category: t("demo.category.algorithm"),
    },
    {
      title: "LangGraph Agent State",
      description: t("demo.langgraph.description"),
      videoUrl: "/landing_snippets/demo2_langgraph.mov",
      category: t("demo.category.aiSystems"),
    },
    {
      title: "Bellman Grid World",
      description: t("demo.bellman.description"),
      videoUrl: "/landing_snippets/demo3_bellman.mov",
      category: t("demo.category.mlTheory"),
    },
  ];

  return (
    <div
      className={`min-h-screen ${bgClass} relative overflow-hidden transition-colors duration-500`}
    >
      <div className="absolute inset-0 overflow-hidden opacity-20">
        <div
          className={`absolute right-20 top-20 h-96 w-96 rounded-full ${
            isDark ? "bg-teal-500" : "bg-teal-400"
          } ${reduceMotion ? "" : "animate-pulse"} blur-3xl`}
        />
        <div
          className={`absolute bottom-20 left-20 h-96 w-96 rounded-full ${
            isDark ? "bg-purple-600" : "bg-purple-400"
          } blur-3xl`}
          style={{ animationDelay: "1s" }}
        />
      </div>

      <div className="absolute right-4 top-4 z-20 flex items-center gap-2 sm:right-6 sm:top-6">
        <button
          type="button"
          onClick={handleSetupGuideClick}
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-semibold shadow-sm backdrop-blur-md transition-colors sm:px-4 ${utilityButtonClass}`}
          aria-label={t("nav.setup.aria")}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path d="M7 3.5A2.5 2.5 0 004.5 6v12A2.5 2.5 0 007 20.5h10A2.5 2.5 0 0019.5 18V6A2.5 2.5 0 0017 3.5H7z" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M8 8h8M8 12h8M8 16h6" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          {t("nav.setup")}
        </button>

        <button
          type="button"
          onClick={handleDocsOpen}
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-semibold shadow-sm backdrop-blur-md transition-colors sm:px-4 ${utilityButtonClass}`}
          aria-label={t("nav.help.aria")}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              d="M4 5.5A2.5 2.5 0 016.5 3H11v16H6.5A2.5 2.5 0 004 21.5v-16zM20 5.5A2.5 2.5 0 0017.5 3H13v16h4.5a2.5 2.5 0 012.5 2.5v-16z"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {t("nav.help")}
        </button>

        <button
          type="button"
          onClick={handleFeedbackClick}
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-semibold shadow-sm backdrop-blur-md transition-colors sm:px-4 ${utilityButtonClass}`}
          aria-label={t("nav.feedback.aria")}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2h-7l-4.5 3v-3H5a2 2 0 01-2-2V7a2 2 0 012-2z"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d="M7 9h10M7 13h6" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          {t("nav.feedback")}
        </button>

        <button
          type="button"
          onClick={handleConsentClick}
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-semibold shadow-sm backdrop-blur-md transition-colors sm:px-4 ${utilityButtonClass}`}
          aria-label={t("nav.consent.aria")}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path d="M7 4.5A2.5 2.5 0 004.5 7v10A2.5 2.5 0 007 19.5h10A2.5 2.5 0 0019.5 17V7A2.5 2.5 0 0017 4.5H7z" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M8 9h8M8 13h8" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          {t("nav.consent")}
        </button>

        <SettingsMenu isDark={isDark} buttonClassName={utilityButtonClass} />
      </div>

      <div className="relative z-10 flex min-h-screen flex-col items-center justify-center p-8 py-16">
        <div className="w-full max-w-7xl">
          <div className="mb-12 text-center">
            <div className="mb-6 inline-flex items-center gap-3">
              <div className="relative h-14 w-14">
                <div className="absolute left-0 top-0 h-10 w-10 rounded-full bg-teal-400" />
                <div className="absolute bottom-0 right-0 h-8 w-8 rounded bg-purple-500" />
                <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 transform">
                  <div
                    className={`h-0 w-0 border-b-[30px] border-l-[18px] border-r-[18px] border-l-transparent border-r-transparent ${
                      isDark ? "border-b-slate-900" : "border-b-slate-50"
                    }`}
                  />
                </div>
              </div>
              <h1 className={`text-4xl font-black md:text-5xl ${textPrimary}`}>UpcurvEd</h1>
            </div>
            <p
              className={`mx-auto mb-3 max-w-3xl text-xl font-light md:text-2xl ${textSecondary}`}
            >
              {t("landing.tagline")}
            </p>
            <p className={`mx-auto max-w-2xl text-lg ${textTertiary}`}>
              {t("landing.subtitle")}
            </p>
          </div>

          <div className="mx-auto mb-10 max-w-6xl">
            <h2 className={`mb-6 text-center text-xl font-semibold ${textPrimary}`}>
              {t("landing.examplesHeading")}
            </h2>
            <div className="flex flex-wrap justify-center gap-6">
              {exampleVideos.map((video, idx) => (
                <div
                  key={video.title}
                  className={`group relative w-80 overflow-hidden rounded-xl border ${cardBg} ${cardBorder} shadow-md backdrop-blur-sm transition-all duration-300 hover:scale-105 hover:shadow-xl`}
                >
                  <div className="relative aspect-video overflow-hidden bg-slate-800">
                    <video
                      className="h-full w-full object-cover"
                      autoPlay={!reduceMotion}
                      loop
                      muted={mutedStates[idx]}
                      playsInline
                      controls={reduceMotion}
                    >
                      <source src={video.videoUrl} type="video/mp4" />
                    </video>

                    <button
                      type="button"
                      onClick={() => toggleMute(idx)}
                      aria-label={
                        mutedStates[idx]
                          ? t("landing.unmute", { title: video.title })
                          : t("landing.mute", { title: video.title })
                      }
                      className={`absolute bottom-3 right-3 z-10 flex h-10 w-10 items-center justify-center rounded-full ${
                        isDark ? "bg-slate-900/70" : "bg-white/70"
                      } backdrop-blur-sm transition-transform hover:scale-110`}
                    >
                      {mutedStates[idx] ? (
                        <svg
                          className={`h-5 w-5 ${isDark ? "text-white" : "text-slate-900"}`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                          aria-hidden="true"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
                            clipRule="evenodd"
                          />
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2"
                          />
                        </svg>
                      ) : (
                        <svg
                          className={`h-5 w-5 ${isDark ? "text-white" : "text-slate-900"}`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                          aria-hidden="true"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
                          />
                        </svg>
                      )}
                    </button>

                    <div className="absolute left-2 top-2">
                      <span className="rounded-full bg-teal-500 px-2.5 py-1 text-xs font-semibold text-white">
                        {video.category}
                      </span>
                    </div>
                  </div>

                  <div className="p-4">
                    <h3 className={`mb-1 text-base font-bold ${textPrimary}`}>{video.title}</h3>
                    <p className={`text-sm ${textSecondary}`}>{video.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex flex-col items-center gap-4">
            <h3 className={`text-lg font-semibold md:text-xl ${textPrimary}`}>
              {t("landing.downloadHeading")}
            </h3>
            <div className="flex flex-wrap items-center justify-center gap-4">
              <a
                href={DOWNLOADS.windows}
                onClick={() => handleDownloadClick("windows")}
                className={`inline-flex min-w-[240px] items-center justify-center gap-3 rounded-xl border px-6 py-4 text-base font-semibold transition-colors ${
                  isDark
                    ? "border-teal-500 text-white hover:bg-teal-500 hover:text-white"
                    : "border-teal-500 text-slate-900 hover:bg-teal-500 hover:text-white"
                }`}
                title={t("landing.download.windows")}
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M2 3.5l9.5-1.3v9H2v-7.7zm10.8-1.5L22 0.7v10.5h-9.2V2zm-10.8 10.5h9.5v9L2 20.2v-7.7zm10.8 0H22V23.3l-9.2-1.3v-9.5z"
                  />
                </svg>
                {t("landing.download.windows")}
              </a>

              <a
                href={DOWNLOADS.macArm}
                onClick={() => handleDownloadClick("mac-arm64")}
                className={`inline-flex min-w-[240px] items-center justify-center gap-3 rounded-xl border px-6 py-4 text-base font-semibold transition-colors ${
                  isDark
                    ? "border-purple-500 text-white hover:bg-purple-500 hover:text-white"
                    : "border-purple-500 text-slate-900 hover:bg-purple-500 hover:text-white"
                }`}
                title={t("landing.download.mac.title")}
              >
                <img src={appleLogo} alt={t("landing.appleLogo")} className="h-5 w-5" loading="lazy" />
                {t("landing.download.mac")}
              </a>

              <a
                href={DOWNLOADS.linux}
                onClick={() => handleDownloadClick("linux")}
                className={`inline-flex min-w-[240px] items-center justify-center gap-3 rounded-xl border px-6 py-4 text-base font-semibold transition-colors ${
                  isDark
                    ? "border-blue-500 text-white hover:bg-blue-500 hover:text-white"
                    : "border-blue-500 text-slate-900 hover:bg-blue-500 hover:text-white"
                }`}
                title={t("landing.download.linux")}
              >
                <img src={linuxLogo} alt={t("landing.linuxLogo")} className="h-5 w-5" loading="lazy" />
                {t("landing.download.linux")}
              </a>
            </div>

          </div>
        </div>
      </div>

      {isDocsOpen && <DocsModal isDark={isDark} onClose={() => setIsDocsOpen(false)} />}
      {isFeedbackOpen && <FeedbackModal isDark={isDark} onClose={() => setIsFeedbackOpen(false)} />}
      {isConsentOpen && <NoticeOfConsentModal isDark={isDark} onClose={() => setIsConsentOpen(false)} />}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.2; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
