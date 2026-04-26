import { useState, useEffect } from 'react';
import { trackEvent } from "@/lib/analytics";

export default function Landing({ setView }: { setView?: (view: string) => void }) {
  const [isDark, setIsDark] = useState(true);
  const [mutedStates, setMutedStates] = useState([true, true, true]);
  const windowsDownloadUrl = (import.meta.env.VITE_WINDOWS_DOWNLOAD_URL as string | undefined) || "";
  const macDownloadUrl = (import.meta.env.VITE_MAC_DOWNLOAD_URL as string | undefined) || "";

  useEffect(() => {
    // Determine theme based on time of day
    const hour = new Date().getHours();
    // Dark mode from 6 PM (18) to 6 AM (6)
    setIsDark(hour >= 18 || hour < 6);
  }, []);

  const toggleMute = (index) => {
    setMutedStates(prev => {
      const newStates = [...prev];
      newStates[index] = !newStates[index];
      return newStates;
    });
  };

  const handleDownloadClick = (platform: "windows" | "mac", url: string) => {
    trackEvent("download_click", { platform, has_url: Boolean(url) });
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const bgClass = isDark 
    ? 'bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900' 
    : 'bg-gradient-to-br from-slate-50 via-white to-slate-100';
  
  const textPrimary = isDark ? 'text-white' : 'text-slate-900';
  const textSecondary = isDark ? 'text-slate-300' : 'text-slate-600';
  const textTertiary = isDark ? 'text-slate-400' : 'text-slate-500';
  const cardBg = isDark ? 'bg-slate-800/50' : 'bg-white';
  const cardBorder = isDark ? 'border-slate-700' : 'border-slate-200';

  // Example videos data
  const exampleVideos = [
    {
      title: 'Convex Optimization',
      description: 'Visualize 3D graphs',
      videoUrl: '/landing_snippets/demo1_convex.mov',
      category: 'Algorithm'
    },
    {
      title: 'LangGraph Agent State',
      description: 'Visualize systems',
      videoUrl: '/landing_snippets/demo2_langgraph.mov',
      category: 'AI Systems'
    },
    {
      title: 'Bellman Grid World',
      description: 'Include code snippets',
      videoUrl: '/landing_snippets/demo3_bellman.mov',
      category: 'ML Theory'
    }
  ];

  return (
    <div className={`min-h-screen ${bgClass} transition-colors duration-500 relative overflow-hidden`}>
      {/* Decorative background elements */}
      <div className="absolute inset-0 overflow-hidden opacity-20">
        <div className={`absolute top-20 right-20 w-96 h-96 ${isDark ? 'bg-teal-500' : 'bg-teal-400'} rounded-full blur-3xl animate-pulse`}></div>
        <div className={`absolute bottom-20 left-20 w-96 h-96 ${isDark ? 'bg-purple-600' : 'bg-purple-400'} rounded-full blur-3xl`} style={{ animationDelay: '1s' }}></div>
      </div>

      <div className="relative z-10 min-h-screen flex flex-col items-center justify-center p-8 py-16">
        <div className="max-w-7xl w-full">
          {/* Header with Logo */}
          <div className="text-center mb-12">
            <div className="inline-flex items-center gap-3 mb-6">
              <div className="relative w-14 h-14">
                <div className="absolute top-0 left-0 w-10 h-10 bg-teal-400 rounded-full"></div>
                <div className="absolute bottom-0 right-0 w-8 h-8 bg-purple-500 rounded"></div>
                <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2">
                  <div className={`w-0 h-0 border-l-[18px] border-l-transparent border-r-[18px] border-r-transparent border-b-[30px] ${isDark ? 'border-b-slate-900' : 'border-b-slate-50'}`}></div>
                </div>
              </div>
              <h1 className={`text-4xl md:text-5xl font-black ${textPrimary}`}>
                UpcurvEd
              </h1>
            </div>
            <p className={`text-xl md:text-2xl ${textSecondary} font-light max-w-3xl mx-auto mb-3`}>
              Create Educational Content with Natural Language
            </p>
            <p className={`text-lg ${textTertiary} max-w-2xl mx-auto`}>
              Transform concepts into stunning animations, podcasts, and quizzes
            </p>
          </div>

          {/* Video Showcase - Bigger Size */}
          <div className="mb-10 max-w-6xl mx-auto">
            <h2 className={`text-xl font-semibold ${textPrimary} text-center mb-6`}>
              See What You Can Create
            </h2>
            <div className="flex gap-6 justify-center flex-wrap">
              {exampleVideos.map((video, idx) => (
                <div 
                  key={idx}
                  className={`group relative ${cardBg} backdrop-blur-sm rounded-xl overflow-hidden border ${cardBorder} shadow-md hover:shadow-xl transition-all duration-300 hover:scale-105 w-80`}
                >
                  {/* Video */}
                  <div className="relative aspect-video bg-slate-800 overflow-hidden">
                    <video 
                      className="w-full h-full object-cover"
                      autoPlay
                      loop
                      muted={mutedStates[idx]}
                      playsInline
                    >
                      <source src={video.videoUrl} type="video/mp4" />
                    </video>
                    
                    {/* Sound Toggle Button */}
                    <button
                      onClick={() => toggleMute(idx)}
                      className={`absolute bottom-3 right-3 w-10 h-10 rounded-full ${isDark ? 'bg-slate-900/70' : 'bg-white/70'} backdrop-blur-sm flex items-center justify-center hover:scale-110 transition-transform z-10`}
                    >
                      {mutedStates[idx] ? (
                        <svg className={`w-5 h-5 ${isDark ? 'text-white' : 'text-slate-900'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" clipRule="evenodd" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
                        </svg>
                      ) : (
                        <svg className={`w-5 h-5 ${isDark ? 'text-white' : 'text-slate-900'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                        </svg>
                      )}
                    </button>

                    {/* Category Badge */}
                    <div className="absolute top-2 left-2">
                      <span className="px-2.5 py-1 bg-teal-500 text-white text-xs font-semibold rounded-full">
                        {video.category}
                      </span>
                    </div>
                  </div>
                  
                  {/* Video Info */}
                  <div className="p-4">
                    <h3 className={`text-base font-bold ${textPrimary} mb-1`}>
                      {video.title}
                    </h3>
                    <p className={`text-sm ${textSecondary}`}>
                      {video.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* CTA Section - Minimal Create Button */}
          <div className="flex flex-col items-center gap-5">
            <a 
              href="#"
              onClick={(e) => {
                e.preventDefault();
                trackEvent("create_click", { source: "landing" });
                if (setView) setView('login');
              }}
              className="group relative bg-white dark:bg-slate-800/50 hover:bg-gradient-to-r hover:from-teal-300 hover:to-purple-400 border-2 border-teal-500 rounded-2xl shadow-lg hover:shadow-2xl hover:shadow-purple-400/50 transition-all duration-300 hover:scale-105 overflow-hidden cursor-pointer"
              style={{
                backgroundColor: isDark ? 'rgba(30, 41, 59, 0.5)' : 'white'
              }}
            >
              <div className="absolute inset-0 bg-gradient-to-r from-teal-300 to-purple-400 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-1000"></div>
              
              <div className="relative px-12 py-6 flex items-center justify-center gap-4">
                <span className={`text-2xl font-bold ${textPrimary} group-hover:text-slate-900 transition-colors duration-300`}>
                  Create
                </span>
              </div>
            </a>

            <div className="flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={() => handleDownloadClick("windows", windowsDownloadUrl)}
                className="px-4 py-2 rounded-lg border border-teal-500 text-sm font-semibold hover:bg-teal-500 hover:text-white transition-colors"
                disabled={!windowsDownloadUrl}
                title={windowsDownloadUrl ? "Download for Windows" : "Windows download URL not configured"}
              >
                Download for Windows
              </button>
              <button
                type="button"
                onClick={() => handleDownloadClick("mac", macDownloadUrl)}
                className="px-4 py-2 rounded-lg border border-purple-500 text-sm font-semibold hover:bg-purple-500 hover:text-white transition-colors"
                disabled={!macDownloadUrl}
                title={macDownloadUrl ? "Download for macOS" : "macOS download URL not configured"}
              >
                Download for macOS
              </button>
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.2; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
