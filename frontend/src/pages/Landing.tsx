import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { useNavigate } from "react-router-dom";

import DocsModal from "@/components/landing/DocsModal";
import FeedbackModal from "@/components/landing/FeedbackModal";
import LandingHelpMenu from "@/components/landing/LandingHelpMenu";
import PrivacyTermsModal from "@/components/landing/PrivacyTermsModal";
import LanguageMenu from "@/components/LanguageMenu";
import { trackEvent } from "@/lib/analytics";
import { useAppearance } from "@/lib/appearance";
import { useLanguage } from "@/lib/i18n";

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

const DEMO_COPY = {
  en: [
    {
      title: "Butterfly Life Cycle",
      description: "Show a science process step by step.",
      category: "Science",
    },
    {
      title: "Fractions Made Visual",
      description: "Turn a math idea into an easy visual.",
      category: "Math",
    },
    {
      title: "The Water Cycle",
      description: "Explain a familiar concept with motion.",
      category: "Science",
    },
  ],
  id: [
    {
      title: "Siklus Hidup Kupu-Kupu",
      description: "Tunjukkan proses sains langkah demi langkah.",
      category: "Sains",
    },
    {
      title: "Pecahan Secara Visual",
      description: "Ubah konsep matematika menjadi visual yang mudah dipahami.",
      category: "Matematika",
    },
    {
      title: "Siklus Air",
      description: "Jelaskan konsep yang familiar dengan animasi sederhana.",
      category: "Sains",
    },
  ],
} as const;

const DEMO_VIDEO_URLS = [
  "/landing_snippets/demo1_butterfly.mp4",
  "/landing_snippets/demo2_fractions.mp4",
  "/landing_snippets/demo3_water_cycle.mp4",
] as const;

export default function Landing({ setView: _setView }: { setView?: (view: string) => void }) {
  const navigate = useNavigate();
  const { t, language } = useLanguage();
  const { isDark, reduceMotion, setMode } = useAppearance();
  const [isDocsOpen, setIsDocsOpen] = useState(false);
  const [isFeedbackOpen, setIsFeedbackOpen] = useState(false);
  const [isPrivacyTermsOpen, setIsPrivacyTermsOpen] = useState(false);
  const iconColor = isDark ? "FFFFFF" : "0F172A";
  const appleLogo = `https://cdn.simpleicons.org/apple/${iconColor}`;
  const linuxLogo = `https://cdn.simpleicons.org/linux/${iconColor}`;

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

  const handlePrivacyTermsClick = () => {
    trackEvent("privacy_terms_open", { source: "landing" });
    setIsPrivacyTermsOpen(true);
  };

  const toggleAppearance = () => {
    setMode(isDark ? "light" : "dark");
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

  const demoCopy = language === "id" ? DEMO_COPY.id : DEMO_COPY.en;
  const exampleVideos = demoCopy.map((copy, index) => ({
    ...copy,
    videoUrl: DEMO_VIDEO_URLS[index],
  }));

  const appearanceLabel = isDark
    ? t("settings.appearance.light")
    : t("settings.appearance.dark");

  return (
    <div className={`min-h-screen ${bgClass} relative overflow-hidden transition-colors duration-500`}>
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

      {/* Keep only the first-run actions visible. Secondary information lives under Help. */}
      <div className="absolute left-4 right-4 top-4 z-20 flex flex-wrap items-center justify-end gap-2 sm:left-auto sm:right-6 sm:top-6">
        <button
          type="button"
          onClick={handleSetupGuideClick}
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-semibold shadow-sm backdrop-blur-md transition-colors sm:px-4 ${utilityButtonClass}`}
          aria-label={t("nav.setup.aria")}
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" aria-hidden="true">
            <path d="M7 3.5A2.5 2.5 0 004.5 6v12A2.5 2.5 0 007 20.5h10A2.5 2.5 0 0019.5 18V6A2.5 2.5 0 0017 3.5H7z" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M8 8h8M8 12h8M8 16h6" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          {t("nav.setup")}
        </button>

        <LandingHelpMenu
          isDark={isDark}
          buttonClassName={utilityButtonClass}
          onOpenFaq={handleDocsOpen}
          onOpenFeedback={handleFeedbackClick}
          onOpenPrivacyTerms={handlePrivacyTermsClick}
        />

        <LanguageMenu
          variant="pill"
          isDark={isDark}
          buttonClassName={utilityButtonClass}
          align="end"
        />

        <button
          type="button"
          onClick={toggleAppearance}
          aria-label={appearanceLabel}
          title={appearanceLabel}
          className={`inline-flex h-10 w-10 items-center justify-center rounded-full border shadow-sm backdrop-blur-md transition-colors ${utilityButtonClass}`}
        >
          {isDark ? <Sun className="h-4 w-4" aria-hidden="true" /> : <Moon className="h-4 w-4" aria-hidden="true" />}
        </button>
      </div>

      <div className="relative z-10 flex min-h-screen flex-col items-center justify-center px-6 pb-16 pt-32 sm:p-8 sm:py-16">
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
            <p className={`mx-auto mb-3 max-w-3xl text-xl font-light md:text-2xl ${textSecondary}`}>
              {t("landing.tagline")}
            </p>
            <p className={`mx-auto max-w-2xl text-lg ${textTertiary}`}>{t("landing.subtitle")}</p>
          </div>

          <div className="mx-auto mb-10 max-w-6xl">
            <h2 className={`mb-6 text-center text-xl font-semibold ${textPrimary}`}>
              {t("landing.examplesHeading")}
            </h2>
            <div className="flex flex-wrap justify-center gap-6">
              {exampleVideos.map((video) => (
                <div
                  key={video.title}
                  className={`group relative w-80 overflow-hidden rounded-xl border ${cardBg} ${cardBorder} shadow-md backdrop-blur-sm transition-all duration-300 hover:scale-[1.02] hover:shadow-xl`}
                >
                  <div className="relative aspect-video overflow-hidden bg-slate-100">
                    <video
                      className="h-full w-full object-cover"
                      autoPlay={!reduceMotion}
                      loop
                      muted
                      playsInline
                      controls={reduceMotion}
                      aria-label={video.title}
                    >
                      <source src={video.videoUrl} type="video/mp4" />
                    </video>

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
            <h3 className={`text-lg font-semibold md:text-xl ${textPrimary}`}>{t("landing.downloadHeading")}</h3>
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
                  <path fill="currentColor" d="M2 3.5l9.5-1.3v9H2v-7.7zm10.8-1.5L22 0.7v10.5h-9.2V2zm-10.8 10.5h9.5v9L2 20.2v-7.7zm10.8 0H22V23.3l-9.2-1.3v-9.5z" />
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
      {isPrivacyTermsOpen && (
        <PrivacyTermsModal isDark={isDark} onClose={() => setIsPrivacyTermsOpen(false)} />
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.2; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
