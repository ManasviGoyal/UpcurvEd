import { useState, useEffect, useRef, useMemo } from "react";
import type { FC } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Sidebar } from "@/components/Sidebar";
import { SettingsPage } from "@/pages/Settings";
import { MediaPlayer } from "@/components/MediaPlayer";
import { useSearchParams, useNavigate } from "react-router-dom";
import {
  Upload,
  Send,
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Volume2,
  Maximize,
  Minimize,
  Download,
  Menu,
  User as UserIcon,
  Bot,
  X,
  MessageSquare,
  Video as VideoIcon,
  HelpCircle,
  Square,
  Mic,
  Copy,
  Check,
  Share2,
  Search,
  Reply,
  Pencil,
  Brain,
  Zap,
  ExternalLink,
} from "lucide-react";
import type { User, Chat, ColorTheme, Theme, ApiKeys } from "@/types";
import {
  apiListChats,
  apiCreateChat,
  apiGetChat,
  apiListMessages,
  apiAppendMessage,
  apiRenameChat,
  apiDeleteChat,
  apiFetch,
  apiRefreshArtifact,
  apiToggleShare,
  apiDeleteAccount,
  apiQuiz,
  apiWidget,
  apiUrl,
} from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { isDesktopLocalMode } from "@/lib/runtime";
import { clearApiKeysForUser } from "@/lib/secureKeys";
import { prepareWidgetHtmlForIframe } from "@/lib/widgetRuntime";

interface ChatInterfaceProps {
  setView: (view: string) => void;
  user: User;
  setUser: (user: User | null) => void;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  colorTheme: ColorTheme;
  setColorTheme: (theme: ColorTheme) => void;
  users: User[];
  setUsers: (users: User[]) => void;
  apiKeys: ApiKeys; // required; App must pass it
  setApiKeys: (keys: ApiKeys) => void;
}

interface WidgetFrameProps {
  widgetCode: string;
  title?: string;
  className?: string;
  height?: string;
}

const WidgetFrame: FC<WidgetFrameProps> = ({ widgetCode, title, className, height }) => {
  const preparedHtml = useMemo(() => prepareWidgetHtmlForIframe(widgetCode), [widgetCode]);

  const widgetUrl = useMemo(() => {
    const blob = new Blob([preparedHtml], { type: "text/html" });
    return URL.createObjectURL(blob);
  }, [preparedHtml]);

  useEffect(() => {
    return () => URL.revokeObjectURL(widgetUrl);
  }, [widgetUrl]);

  return (
    <iframe
      src={widgetUrl}
      sandbox="allow-scripts"
      className={className || "w-full border-0"}
      style={height ? { height } : undefined}
      title={title || "Interactive Widget"}
      loading="eager"
    />
  );
};

export const ChatInterface: FC<ChatInterfaceProps> = ({
  setView,
  user,
  setUser,
  theme,
  setTheme,
  colorTheme,
  setColorTheme,
  users,
  setUsers,
  apiKeys,
  setApiKeys,
}: ChatInterfaceProps) => {
  const desktopLocal = isDesktopLocalMode();
  const { toast } = useToast();
  const currentUser = users.find((u) => u.email === user.email);
  const [chats, setChats] = useState<Chat[]>(currentUser?.chats || []);
  // Force re-render when cache updates
  const [, forceUpdate] = useState({});
  // URL as source of truth for active chat
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const forceBlank = (typeof window !== 'undefined' && sessionStorage.getItem('app.forceBlank') === '1');

  // Get active chat from URL query params (authoritative source)
  const urlChatId = searchParams.get('id');
  // Model is not in URL anymore - we'll fetch it from chat data or use default
  // Initialize activeChatId from URL immediately to preserve it on refresh
  const [activeChatId, setActiveChatId] = useState<string | number | null>(() => {
    // Initialize from URL on mount to prevent clearing on refresh
    const idFromUrl = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('id') : null;
    return idFromUrl || null;
  });
  const [model, setModel] = useState<string>('llm'); // default model, will be updated from chat data
  const [urlInitialized, setUrlInitialized] = useState(false); // Track if URL has been read initially

  // On mount/URL change, sync activeChatId from URL immediately to prevent redirects
  useEffect(() => {
    const idFromUrl = searchParams.get('id');
    if (idFromUrl && activeChatId !== idFromUrl) {
      setActiveChatId(idFromUrl);
      setUrlInitialized(true);
    } else if (!idFromUrl && !urlInitialized) {
      // Mark as initialized even if no ID to prevent clearing
      setUrlInitialized(true);
    }
  }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

  // Session ID management - stored in localStorage and used for X-Session-ID header
  const getOrCreateSessionId = (): string => {
    try {
      const stored = localStorage.getItem('app.sessionId');
      if (stored) return stored;
      const newId = crypto.randomUUID ? crypto.randomUUID() : `s_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
      localStorage.setItem('app.sessionId', newId);
      return newId;
    } catch {
      const fallback = `s_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
      try { localStorage.setItem('app.sessionId', fallback); } catch {}
      return fallback;
    }
  };
  const sessionIdRef = useRef<string>(getOrCreateSessionId());

  const [query, setQuery] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const [isCaptionsOn, setIsCaptionsOn] = useState(false);
  const [activeScript, setActiveScript] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [progress, setProgress] = useState([0]);
  const [volume, setVolume] = useState([75]);
  const [playbackSpeed, setPlaybackSpeed] = useState([1]);
  const [mediaDuration, setMediaDuration] = useState(0);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [modal, setModal] = useState<{ isOpen: boolean; type: string; data: any }>({
    isOpen: false,
    type: "",
    data: null,
  });
  // Edit mode state - for editing existing videos
  const [isEditMode, setIsEditMode] = useState(false);
  const [isQuizMode, setIsQuizMode] = useState(false);
  const [quotedMessage, setQuotedMessage] = useState<{ messageId: string; content: string; media: import('@/types').MediaAttachment } | null>(null);
  // backend integration state
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [widgetHtml, setWidgetHtml] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [videoProgress, setVideoProgress] = useState(0); // 0-100 visual progress during render
  const videoProgressTimer = useRef<number | null>(null);
  // Podcast generation visual progress (mirrors video progress UX)
  const [podcastProgress, setPodcastProgress] = useState(0);
  const podcastProgressTimer = useRef<number | null>(null);
  const [widgetProgress, setWidgetProgress] = useState(0);
  const widgetProgressTimer = useRef<number | null>(null);
  const [quizLoading, setQuizLoading] = useState(false);
  const [podcastLoading, setPodcastLoading] = useState(false);
  const [widgetLoading, setWidgetLoading] = useState(false);
  // Embedded quiz runtime state per chat, anchored to a specific messageId
  // quizzesByChat[chatId][messageId] => QuizRuntime
  interface QuizData { title: string; description?: string; questions: { prompt: string; options: string[]; correctIndex: number }[] }
  interface QuizRuntime { data: QuizData; index: number; answers: number[]; score: number | null; selected: number | null; revealed: boolean }
  const [quizzesByChat, setQuizzesByChat] = useState<Record<string, Record<string, QuizRuntime>>>({});
  const [subtitleLang, setSubtitleLang] = useState<string | undefined>(undefined);
  // Track what kind of generation was last attempted for clearer error copy
  const lastGenerateKindRef = useRef<"video" | "podcast" | null>(null);

  // Minimal inline typing indicator
  const TypingDots = () => (
    <div className="flex items-center gap-1 text-muted-foreground select-none py-2" aria-label="Assistant is typing">
      <span className="w-2 h-2 rounded-full bg-current animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-2 h-2 rounded-full bg-current animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-2 h-2 rounded-full bg-current animate-bounce" style={{ animationDelay: '300ms' }} />
    </div>
  );

  // Track typing state per chat (whether assistant is currently generating)
  const isTyping = (busy || podcastLoading || quizLoading || widgetLoading) && activeChatId !== null;

  // Copy message to clipboard state
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);

  const copyToClipboard = async (text: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(messageId);
      setTimeout(() => setCopiedMessageId(null), 2000);
      toast({
        title: "Copied to clipboard",
        duration: 2000,
      });
    } catch (err) {
      toast({
        title: "Failed to copy",
        variant: "destructive",
        duration: 2000,
      });
    }
  };


  const [vttUrl, setVttUrl] = useState<string | null>(null); // object URL for converted WebVTT captions
  const [currentMediaMeta, setCurrentMediaMeta] = useState<{ artifactId?: string; gcsPath?: string; type?: 'video'|'audio'|'widget' } | null>(null);
  type PersistedMediaSelection = {
    chatId: string;
    messageId?: string;
    type: "video" | "audio" | "widget";
    url?: string;
    subtitleUrl?: string;
    artifactId?: string;
    gcsPath?: string;
    widgetCode?: string;
    title?: string;
    updatedAt: number;
  };
  const videoAbortRef = useRef<AbortController | null>(null);
  const quizAbortRef = useRef<AbortController | null>(null);
  const podcastAbortRef = useRef<AbortController | null>(null);
  const widgetAbortRef = useRef<AbortController | null>(null);
  const currentVideoJobId = useRef<string | null>(null);
  // Cache messages per chat id to avoid flicker during CURRENT SESSION only
  // DO NOT persist across refreshes - Firestore is the single source of truth
  // This cache only prevents flicker when rapidly switching between chats in the same session
  const messagesCache = useRef<Record<string, Chat["messages"]>>({});

  // Track when we last sent a message to prevent premature server fetch (current session only)
  // Reset to 0 on page refresh - this is intentional so server can sync after refresh
  const lastMessageSentTime = useRef<number>(0);
  // Pagination state per chat
  const PAGE_SIZE = 50;
  const [hasMoreByChat, setHasMoreByChat] = useState<Record<string, boolean>>({});
  const [cursorByChat, setCursorByChat] = useState<Record<string, number | undefined>>({});

  const makeJobId = () =>
    Math.random().toString(36).slice(2, 10) + Math.random().toString(36).slice(2, 6);

  const toPlayableMediaUrl = (raw?: string | null): string | undefined => {
    if (!raw) return undefined;
    const value = String(raw).trim();
    if (!value) return undefined;
    if (/^https?:\/\//i.test(value)) return value;
    if (value.startsWith("blob:")) return value;
    return apiUrl(value);
  };

  const ensureLlmKey = (action: "video" | "quiz"): boolean => {
    const safe: ApiKeys = {
      claude: apiKeys?.claude || "",
      gemini: apiKeys?.gemini || "",
      provider: apiKeys?.provider || "",
      model: apiKeys?.model || "",
    };
    const provider = (safe.provider || (safe.gemini ? "gemini" : safe.claude ? "claude" : "")) as
      | "gemini"
      | "claude"
      | "";
    if (!provider || (provider === "gemini" && !safe.gemini) || (provider === "claude" && !safe.claude)) {
      const which = provider || "an LLM";
      toast({
        title: "Missing API key",
        description: `Add your ${which === "gemini" ? "Gemini" : which === "claude" ? "Claude" : "Gemini/Claude"} API key in Settings to ${action}.`,
        duration: 6000,
      });
      return false;
    }
    return true;
  };

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const previousActiveChatIdRef = useRef<string | number | null>(null);
  // Track chats we've auto-renamed on refresh so we don't rename repeatedly
  const autoRenamedChatIdsRef = useRef<Set<string>>(new Set());
  const videoContainerRef = useRef<HTMLDivElement>(null);
  // Unified media ref: may point to a <video> (for video) or <audio> (for podcast)
  const videoRef = useRef<HTMLVideoElement | HTMLAudioElement>(null);
  const [srtText, setSrtText] = useState<string | null>(null);
  const lastNonZeroVolumeRef = useRef<number>(75);
  const outboxFlushScheduled = useRef<boolean>(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Chat switch confirmation dialog visibility
  const [showSwitchWarning, setShowSwitchWarning] = useState(false);
  const NEW_CHAT_SENTINEL = Symbol('new-chat');
  type PendingChatTarget = string | number | typeof NEW_CHAT_SENTINEL;
  const [pendingChatSwitch, setPendingChatSwitch] = useState<PendingChatTarget | null>(null);
  const pendingChatsRef = useRef<Record<string, { sessionId?: string; name?: string; model?: string; createdAt?: number }>>({});
  const storedUpdatedAt = useMemo(() => {
    if (typeof window === 'undefined') return {};
    try {
      const raw = localStorage.getItem(`app.updatedAt.${user.email}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') return parsed;
      }
    } catch {}
    return {};
  }, [user.email]);
  const storedOrder = useMemo(() => {
    if (typeof window === 'undefined') return [];
    try {
      const raw = localStorage.getItem(`app.chatOrder.${user.email}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed.map(String);
      }
    } catch {}
    return [];
  }, [user.email]);
  const localUpdatedAtRef = useRef<Record<string, number>>(storedUpdatedAt);
  const chatOrderRef = useRef<string[]>(storedOrder);
  const firstPromptFingerprintRef = useRef<Record<string, { key: string; ts: number; messageId: string }>>({});
  // Captions cache keyed by artifactId (preferred) or media URL to keep correct pairs per media
  const captionsCacheRef = useRef<Record<string, { vttUrl?: string; lang?: string; isBlob?: boolean }>>({});
  const currentCaptionKeyRef = useRef<string | null>(null);
  const mediaSelectionStoreKey = useMemo(
    () => `app.mediaSelection.${(user.email || "desktop-local-user").toLowerCase()}`,
    [user.email]
  );
  const quizRuntimeStoreKey = useMemo(
    () => `app.quizRuntime.${(user.email || "desktop-local-user").toLowerCase()}`,
    [user.email]
  );

  const normalizeMessageContent = (text?: string | null) =>
    (text || '').trim().toLowerCase().replace(/\s+/g, ' ');

  const loadPersistedMediaSelections = (): Record<string, PersistedMediaSelection> => {
    try {
      const raw = localStorage.getItem(mediaSelectionStoreKey);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return {};
      return parsed;
    } catch {
      return {};
    }
  };

  const persistMediaSelection = (selection: PersistedMediaSelection | null) => {
    if (!activeChatId) return;
    const chatKey = String(activeChatId);
    try {
      const all = loadPersistedMediaSelections();
      if (!selection) {
        delete all[chatKey];
      } else {
        all[chatKey] = selection;
      }
      localStorage.setItem(mediaSelectionStoreKey, JSON.stringify(all));
    } catch {}
  };

  useEffect(() => {
    try {
      const raw = localStorage.getItem(quizRuntimeStoreKey);
      if (!raw) {
        setQuizzesByChat({});
        return;
      }
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        setQuizzesByChat(parsed);
      } else {
        setQuizzesByChat({});
      }
    } catch {
      setQuizzesByChat({});
    }
  }, [quizRuntimeStoreKey]);

  useEffect(() => {
    try {
      localStorage.setItem(quizRuntimeStoreKey, JSON.stringify(quizzesByChat));
    } catch {}
  }, [quizRuntimeStoreKey, quizzesByChat]);

  const makeMessageKey = (msg: any) => {
    const normalized = normalizeMessageContent(msg?.content);
    const mediaKey = msg?.media?.artifactId ? `|media:${msg.media.artifactId}` : '';
    const quizKey = msg?.quizAnchor ? `|quiz:${msg.quizTitle || 'untitled'}` : '';
    return `${msg?.role || 'bot'}|${normalized}${mediaKey}${quizKey}`;
  };

  const dedupeMessagesOrdered = (messages: any[]) => {
    const seen = new Map<string, { idx: number; msg: any }>();
    const out: any[] = [];
    messages.forEach((msg) => {
      const key = makeMessageKey(msg);
      const prev = seen.get(key);
      const isServer = msg?.messageId && !String(msg.messageId).startsWith('local-');
      if (!prev) {
        seen.set(key, { idx: out.length, msg });
        out.push(msg);
      } else {
        const prevMsg = prev.msg;
        const prevIsServer = prevMsg?.messageId && !String(prevMsg.messageId).startsWith('local-');
        if (isServer && !prevIsServer) {
          const preservedCreatedAt = prevMsg?.createdAt || msg?.createdAt;
          const replacement = { ...msg, createdAt: preservedCreatedAt };
          out[prev.idx] = replacement;
          seen.set(key, { idx: prev.idx, msg: replacement });
        }
      }
    });
    return out;
  };
  // Helper: immediately halt any active playback (media element or synthetic script timer)
  const stopPlayback = () => {
    try {
      const el = videoRef.current;
      if (el && !el.paused) {
        el.pause();
        try { el.currentTime = 0; } catch {}
      }
    } catch {}
    setIsPlaying(false);
    setProgress([0]);
  };

  // Pause media (but do not reset) when Settings overlay opens
  useEffect(() => {
    if (settingsOpen) {
      const el = videoRef.current;
      try { if (el && !el.paused) el.pause(); } catch {}
    }
  }, [settingsOpen]);

  // Wrap setApiKeys so saving changed provider/model/keys cancels in-flight generations
  const applyApiKeys = (next: ApiKeys) => {
    const changed = (next.provider !== apiKeys.provider) || (next.model !== apiKeys.model) || (next.claude !== apiKeys.claude) || (next.gemini !== apiKeys.gemini);
    if (changed) {
      try {
        if (busy && videoAbortRef.current) videoAbortRef.current.abort();
      } catch {}
      try {
        if (podcastLoading && podcastAbortRef.current) podcastAbortRef.current.abort();
      } catch {}
      try {
        if (quizLoading && quizAbortRef.current) quizAbortRef.current.abort();
      } catch {}
    }
    setApiKeys(next);
  };

  // Reusable caption utilities
  const srtToVtt = (srt: string) => {
    let text = srt.replace(/\r\n/g, '\n');
    if (/^\s*WEBVTT/i.test(text)) return text; // already vtt-like
    // Remove leading indices
    text = text.replace(/\n\d+\n/g, '\n');
    // Convert timestamps comma -> dot
    text = text.replace(/(\d{2}:\d{2}:\d{2}),(\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}),(\d{3})/g, (_m,a1,ms1,a2,ms2) => `${a1}.${ms1} --> ${a2}.${ms2}`);
    text = text.replace(/\n{3,}/g,'\n\n');
    return 'WEBVTT\n\n' + text.trim() + '\n';
  };

  const fetchCaptions = async (
    mediaUrl: string,
    explicitSubtitleUrl?: string,
    artifactId?: string | null,
    gcsPath?: string | null
  ) => {
    const metaArtifactId = artifactId ?? currentMediaMeta?.artifactId;
    const metaGcsPath = gcsPath ?? currentMediaMeta?.gcsPath;
    const key = (metaArtifactId || mediaUrl) as string;

    // Try explicit subtitle URL first if provided (backend already converted SRT to VTT)
    if (explicitSubtitleUrl) {
      try {
        const res = await fetch(explicitSubtitleUrl);
        if (res.ok) {
          const txt = await res.text();
          if (/WEBVTT/i.test(txt.slice(0,40))) {
            setVttUrl(explicitSubtitleUrl);
            const lang = subtitleLang || 'en';
            if (!subtitleLang) setSubtitleLang(lang);
            captionsCacheRef.current[key] = { vttUrl: explicitSubtitleUrl, lang, isBlob: false };
            currentCaptionKeyRef.current = key;
            return;
          } else {
            // Backend returned SRT, convert it
            setSrtText(txt);
            setActiveScript(txt);
            currentCaptionKeyRef.current = key;
            return;
          }
        }
      } catch {}
    }

    // Fallback: try to find .vtt file next to video
    const base = mediaUrl;
    const vttCandidate = base.endsWith('.vtt') ? base : base.replace(/\.[^/.]+$/i, '.vtt');
    try {
      const vttRes = await fetch(vttCandidate);
      if (vttRes.ok) {
        const txt = await vttRes.text();
        if (/WEBVTT/i.test(txt.slice(0,40))) {
          setVttUrl(vttCandidate);
          const lang = subtitleLang || 'en';
          if (!subtitleLang) setSubtitleLang(lang);
          captionsCacheRef.current[key] = { vttUrl: vttCandidate, lang, isBlob: false };
          currentCaptionKeyRef.current = key;
          return;
        }
      }
    } catch {}

    // Try to refresh signed subtitle URL from server (cloud mode only; desktop-local uses local files).
    try {
      if (!desktopLocal && (metaArtifactId || metaGcsPath)) {
        const refreshed = await apiRefreshArtifact({ artifactId: metaArtifactId, gcsPath: metaGcsPath, subtitle: true });
        const refreshedUrl: string | undefined = (refreshed?.signed_subtitle_url as any) || undefined;
        if (refreshedUrl) {
          const r = await fetch(refreshedUrl);
          if (r.ok) {
            const txt = await r.text();
            if (/WEBVTT/i.test(txt.slice(0,40))) {
              setVttUrl(refreshedUrl);
              const lang = subtitleLang || 'en';
              if (!subtitleLang) setSubtitleLang(lang);
              captionsCacheRef.current[key] = { vttUrl: refreshedUrl, lang, isBlob: false };
              currentCaptionKeyRef.current = key;
              return;
            } else {
              setSrtText(txt);
              setActiveScript(txt);
              currentCaptionKeyRef.current = key;
              return;
            }
          }
        }
      }
    } catch {}
    // Fallback to .srt
    const srtCandidate = base.endsWith('.srt') ? base : base.replace(/\.[^/.]+$/i, '.srt');
    try {
      const srtRes = await fetch(srtCandidate);
      if (srtRes.ok) {
        const srt = await srtRes.text();
        setSrtText(srt); // triggers conversion effect below
        setActiveScript(srt);
        // Conversion effect will populate cache
        currentCaptionKeyRef.current = key;
      }
    } catch {}
  };

  const openMediaFromMessage = async (
    message: any,
    opts?: { persist?: boolean; skipSignedRefresh?: boolean; autoplay?: boolean }
  ) => {
    const media = message?.media;
    if (!media) return;
    const persist = opts?.persist !== false;
    const skipSignedRefresh = opts?.skipSignedRefresh === true;
    const autoplay = opts?.autoplay === true;
    const chatKey = activeChatId != null ? String(activeChatId) : null;
    const messageId = message?.messageId ? String(message.messageId) : undefined;

    if (media.type === "widget" && media.widgetCode) {
      stopPlayback();
      setVideoUrl(null);
      setCurrentMediaMeta({
        artifactId: media.artifactId,
        gcsPath: media.gcsPath,
        type: "widget",
      });
      setVttUrl(null);
      setSrtText(null);
      setSubtitleLang(undefined);
      setWidgetHtml(media.widgetCode);
      if (persist && chatKey) {
        persistMediaSelection({
          chatId: chatKey,
          messageId,
          type: "widget",
          widgetCode: media.widgetCode,
          artifactId: media.artifactId,
          gcsPath: media.gcsPath,
          title: media.title,
          updatedAt: Date.now(),
        });
      }
      return;
    }

    if (!media.url) return;
    let mediaUrl = toPlayableMediaUrl(media.url) || "";
    if (!desktopLocal && !skipSignedRefresh && (media.artifactId || media.gcsPath)) {
      try {
        const refreshed = await apiRefreshArtifact({
          artifactId: media.artifactId,
          gcsPath: media.gcsPath,
          subtitle: true,
        });
        if (refreshed?.signed_video_url) {
          mediaUrl = refreshed.signed_video_url;
        }
      } catch {}
    }

    setWidgetHtml(null);
    setCurrentMediaMeta({
      artifactId: media.artifactId,
      gcsPath: media.gcsPath,
      type: media.type,
    });
    setVttUrl(null);
    setSrtText(null);
    const subtitleUrl = toPlayableMediaUrl(media.subtitleUrl);
    await fetchCaptions(mediaUrl, subtitleUrl, media.artifactId, media.gcsPath);
    setVideoUrl(mediaUrl);
    if (autoplay) {
      setTimeout(() => {
        const el = videoRef.current as HTMLVideoElement | HTMLAudioElement | null;
        if (!el) return;
        try {
          const p = el.play();
          if (p && typeof (p as any).catch === "function") {
            (p as any).catch(() => {});
          }
        } catch {}
      }, 120);
    }

    if (persist && chatKey) {
      persistMediaSelection({
        chatId: chatKey,
        messageId,
        type: media.type,
        url: mediaUrl,
        subtitleUrl,
        artifactId: media.artifactId,
        gcsPath: media.gcsPath,
        title: media.title,
        updatedAt: Date.now(),
      });
    }
  };

  useEffect(() => {
    const chatKey = activeChatId != null ? String(activeChatId) : "";
    if (!chatKey) return;
    if (widgetHtml) {
      persistMediaSelection({
        chatId: chatKey,
        type: "widget",
        widgetCode: widgetHtml,
        artifactId: currentMediaMeta?.artifactId,
        gcsPath: currentMediaMeta?.gcsPath,
        updatedAt: Date.now(),
      });
      return;
    }
    if (videoUrl && currentMediaMeta?.type && currentMediaMeta.type !== "widget") {
      persistMediaSelection({
        chatId: chatKey,
        type: currentMediaMeta.type,
        url: videoUrl,
        artifactId: currentMediaMeta.artifactId,
        gcsPath: currentMediaMeta.gcsPath,
        subtitleUrl: vttUrl || undefined,
        updatedAt: Date.now(),
      });
    }
  }, [activeChatId, widgetHtml, videoUrl, currentMediaMeta?.type, currentMediaMeta?.artifactId, currentMediaMeta?.gcsPath, vttUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const formatTime = (secs: number) => {
    if (!isFinite(secs) || secs < 0) secs = 0;
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    const mm = String(m).padStart(2, "0");
    const ss = String(s).padStart(2, "0");
    return `${mm}:${ss}`;
  };

  // Sync active chat with URL query params (URL is source of truth)
  useEffect(() => {
    const urlId = searchParams.get('id');

    // Update activeChatId if URL changed
    if (urlId && activeChatId !== urlId) {
      setActiveChatId(urlId);
      try { sessionStorage.removeItem('app.forceBlank'); } catch {}
    }

    // If URL has no id, show greeting if forceBlank is set
    if (!urlId) {
      const fb = sessionStorage.getItem('app.forceBlank') === '1';
      if (fb && activeChatId !== null) {
        setActiveChatId(null); // show greeting
      }
    }

    // If URL has an id, load chat if not cached or refresh if stale
    if (urlId && typeof urlId === 'string' && !urlId.startsWith('local-') && !urlId.startsWith('draft-')) {
      const cachedChat = chats.find(c => c.id === urlId);
      const cacheKey = String(urlId);

      // Determine model to use: from cached chat, or default to 'llm'
      const chatModel = (cachedChat as any)?.model || model || 'llm';

      // If chat not in local state or messages not loaded, fetch from backend
      if (!cachedChat || !cachedChat.messages || cachedChat.messages.length === 0) {
        // This will trigger the loadMessagesPage effect below
        // But we also need to ensure chat metadata is loaded
        const loadChatDetails = async () => {
          try {
            // Try with cached model or default, then update from response
            const chatDetail = await apiGetChat(urlId);
            if (chatDetail) {
              // Update model from chat data if available
              if (chatDetail.model && chatDetail.model !== model) {
                setModel(chatDetail.model);
              }

              // Update chat in list if exists, or add it
              const existingIdx = chats.findIndex(c => c.id === urlId);
              const msgs = (chatDetail.messages || []).map((m: any) => {
                const media = m.media ? {
                  type: (m.media.type === 'podcast' ? 'audio' : m.media.type) as 'audio'|'video'|'widget', // BUG FIX
                  url: toPlayableMediaUrl(m.media.url as string | undefined),
                  subtitleUrl: toPlayableMediaUrl(m.media.subtitleUrl as string | undefined),
                  artifactId: m.media.artifactId as string | undefined,
                  title: m.media.title as string | undefined,
                  gcsPath: m.media.gcsPath as string | undefined,
                  sceneCode: m.media.sceneCode as string | undefined,  // Include sceneCode for video editing
                  widgetCode: m.media.widgetCode as string | undefined, // Restore widget HTML on reload
                } : undefined;
                // Preserve quiz data
                const extras: any = {};
                if (m.quizAnchor || m.quizTitle || m.quizData) {
                  extras.quizAnchor = m.quizAnchor || false;
                  extras.quizTitle = m.quizTitle;
                  extras.quizData = m.quizData;
                }
                return {
                  role: m.role === 'assistant' ? 'bot' : 'user',
                  content: m.content,
                  media,
                  createdAt: m.createdAt,
                  messageId: m.message_id,
                  ...extras
                };
              });
              const updatedChat: Chat & { model?: string } = {
                id: chatDetail.chat_id,
                name: chatDetail.title || 'Untitled',
                messages: msgs,
                sessionId: chatDetail.sessionId,
                model: chatDetail.model || chatModel, // store model in chat object
              };

              if (existingIdx >= 0) {
                const updated = [...chats];
                updated[existingIdx] = updatedChat;
                updateUserChats(updated);
              } else {
                updateUserChats([updatedChat, ...chats]);
              }
              // Merge with existing cache instead of replacing
              const existingCache = messagesCache.current[cacheKey] || [];
              const byId = new Map();
              existingCache.forEach((m: any) => {
                if (m.messageId) byId.set(m.messageId, m);
              });
              msgs.forEach((m: any) => {
                if (m.messageId) byId.set(m.messageId, m);
              });
              const merged = Array.from(byId.values()).sort((a: any, b: any) => {
                const ta = typeof a.createdAt === 'number' ? a.createdAt : 0;
                const tb = typeof b.createdAt === 'number' ? b.createdAt : 0;
                return ta - tb;
              });
              messagesCache.current[cacheKey] = merged as any;
            }
          } catch (err) {
            // If default model fails, try 'llm' as fallback
            if (chatModel !== 'llm') {
              try {
                const chatDetail = await apiGetChat(urlId);
                if (chatDetail && chatDetail.model) {
                  setModel(chatDetail.model);
                }
              } catch {
                // Ignore fallback errors too
              }
            }
            // Ignore load errors - user might not have access or chat doesn't exist
          }
        };
        void loadChatDetails();
      } else if (cachedChat && (cachedChat as any)?.model && (cachedChat as any).model !== model) {
        // Update model from cached chat if available
        setModel((cachedChat as any).model);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Sync URL when activeChatId changes (update query params - no model in URL)
  useEffect(() => {
    const currentId = searchParams.get('id');
    const shouldUpdate = activeChatId !== currentId;

    // Don't clear URL if we're in the middle of a chat operation
    if (activeChatId == null) {
      // Only clear if we explicitly want to show greeting (not during chat creation or refresh)
      const fb = sessionStorage.getItem('app.forceBlank') === '1';
      // Preserve URL on refresh - don't clear if there's a chat ID in URL
      if (currentId && !fb) {
        // URL has a chat ID but activeChatId is null - set it from URL to preserve it
        setActiveChatId(currentId);
        return;
      }
      // Only clear URL if we explicitly want to show greeting AND URL is initialized
      // Don't clear on initial mount/refresh when URL has valid chat ID
      if (currentId && fb && urlInitialized) {
        setSearchParams(prev => {
          const next = new URLSearchParams(prev);
          next.delete('id');
          next.delete('model');
          return next;
        }, { replace: true });
      }
      // If URL has a chat ID on initial mount, preserve it
      if (currentId && !urlInitialized) {
        setActiveChatId(currentId);
        setUrlInitialized(true);
      }
      return;
    }

    // Only update URL for persisted chats (not local/draft)
    if (typeof activeChatId === 'string' && !activeChatId.startsWith('local-') && !activeChatId.startsWith('draft-')) {
      // Only update URL if it actually changed (avoid unnecessary updates)
      if (shouldUpdate && activeChatId !== currentId) {
        setSearchParams(prev => {
          const next = new URLSearchParams(prev);
          next.set('id', String(activeChatId));
          // Don't set model in URL - it's stored in chat data
          next.delete('model'); // Remove if present from old URLs
          return next;
        }, { replace: true });
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChatId, searchParams]);

  // Use messagesCache as source of truth to prevent message loss during state updates
  const baseChat = chats.find((c) => c.id === activeChatId) || { id: activeChatId!, name: "Chat", messages: [] as Chat["messages"] } as Chat;
  // Always prefer cached messages over chat messages - cache is updated immediately and never cleared
  const cachedMessages = activeChatId ? messagesCache.current[String(activeChatId)] : undefined;
  const activeChatMessages = (cachedMessages && cachedMessages.length > 0) ? cachedMessages : (baseChat.messages || []);


  // Create activeChat with messages from cache, but other properties from baseChat
  const activeChat = { ...baseChat, messages: activeChatMessages } as Chat;

  useEffect(() => {
    let cancelled = false;
    const restoreMediaContext = async () => {
      const chatKey = activeChatId != null ? String(activeChatId) : "";
      const messages = Array.isArray(activeChat.messages) ? activeChat.messages : [];
      if (!chatKey || !messages.length) {
        setWidgetHtml(null);
        setVideoUrl(null);
        setCurrentMediaMeta(null);
        return;
      }

      const persisted = loadPersistedMediaSelections()[chatKey];
      let target: any | undefined;
      if (persisted?.messageId) {
        target = messages.find((m: any) => String(m?.messageId || "") === persisted.messageId && m?.media);
      }
      if (!target && persisted?.type === "widget" && persisted?.widgetCode) {
        target = { messageId: persisted.messageId, media: { type: "widget", widgetCode: persisted.widgetCode, artifactId: persisted.artifactId, gcsPath: persisted.gcsPath, title: persisted.title } };
      }
      if (!target && persisted?.url && (persisted?.type === "video" || persisted?.type === "audio")) {
        target = {
          messageId: persisted.messageId,
          media: {
            type: persisted.type,
            url: persisted.url,
            subtitleUrl: persisted.subtitleUrl,
            artifactId: persisted.artifactId,
            gcsPath: persisted.gcsPath,
            title: persisted.title,
          },
        };
      }
      if (!target) {
        target = [...messages].reverse().find((m: any) => m?.media);
      }
      if (!target?.media) {
        setWidgetHtml(null);
        setVideoUrl(null);
        setCurrentMediaMeta(null);
        return;
      }
      if (!cancelled) {
        await openMediaFromMessage(target, {
          persist: false,
          // In desktop-local mode URLs are local and should not refresh;
          // in cloud mode let it refresh signed URLs.
          skipSignedRefresh: desktopLocal,
        });
      }
    };
    void restoreMediaContext();
    return () => {
      cancelled = true;
    };
  }, [activeChatId, activeChat.messages]); // eslint-disable-line react-hooks/exhaustive-deps


  // Render helper: support [text](url) markdown links, then autolink any leftover plain URLs
  const renderMessage = (text: string) => {
    const mdLink = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
    const urlRegex = /(https?:\/\/[^\s)]+)|(www\.[^\s)]+)/gi;

    const renderPlainWithAutoLinks = (t: string) => {
      const parts: Array<string | JSX.Element> = [];
      let lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = urlRegex.exec(t)) !== null) {
        const url = m[0];
        const start = m.index;
        if (start > lastIndex) parts.push(t.slice(lastIndex, start));
        const href = url.startsWith("http") ? url : `https://${url}`;
        parts.push(
          <a key={`${href}-${start}`} href={href} target="_blank" rel="noreferrer" className="underline">
            {url}
          </a>
        );
        lastIndex = start + url.length;
      }
      if (lastIndex < t.length) parts.push(t.slice(lastIndex));
      return parts;
    };

    const out: Array<string | JSX.Element> = [];
    let last = 0;
    let match: RegExpExecArray | null;
    while ((match = mdLink.exec(text)) !== null) {
      const [full, label, href] = match;
      const start = match.index;
      if (start > last) out.push(...renderPlainWithAutoLinks(text.slice(last, start)));
      out.push(
        <a key={`${href}-${start}`} href={href} target="_blank" rel="noreferrer" className="underline">
          {label}
        </a>
      );
      last = start + full.length;
    }
    if (last < text.length) out.push(...renderPlainWithAutoLinks(text.slice(last)));
    return <>{out}</>;
  };

  // Cache management: No persistence needed
  // Firestore is the single source of truth for deployed app
  // Cache only exists in-memory for current session to prevent flicker

  const isDefaultChatName = (name?: string | null) => {
    if (!name) return true;
    return /^New Chat$/i.test(name.trim());
  };

  const updateUserChats = (newChats: Chat[], opts: { bumpId?: string } = {}) => {
    try {
      if (!Array.isArray(newChats)) {
        console.warn('updateUserChats: newChats is not an array', newChats);
        return;
      }
      // Deduplicate by chat ID (keep first occurrence, which is newest due to our prepend logic)
      const seen = new Set<string | number>();
      const deduped = newChats.filter(c => {
        const id = String(c.id);
        if (seen.has(id)) return false;
        seen.add(id);
        return true;
      });
      // Preserve existing custom names if new data only has the placeholder
      const stabilized = deduped.map((chat) => {
        const existing = chats.find(c => String(c.id) === String(chat.id));
        if (existing && !isDefaultChatName(existing.name) && isDefaultChatName(chat.name)) {
          return { ...chat, name: existing.name } as Chat;
        }
        return chat;
      });
      const chatMap = new Map<string, Chat>();
      stabilized.forEach(chat => {
        chatMap.set(String(chat.id), chat);
      });
      let order: string[] = chatOrderRef.current.filter(id => chatMap.has(id));
      const newIds = stabilized.map(c => String(c.id)).filter(id => !order.includes(id));

      // Only reorder when explicitly bumping (user activity)
      // New chats from sync should be inserted based on stored order, not Firebase timestamps
      if (opts.bumpId) {
        const bumpId = String(opts.bumpId);
        order = [bumpId, ...order.filter(id => id !== bumpId), ...newIds.filter(id => id !== bumpId)];
      } else {
        // No bump: just append new chats to end to maintain stable order
        // They'll move to top only when user actually prompts in them
        order = [...order, ...newIds];
      }
      const sorted: Chat[] = [];
      order.forEach(id => {
        const chat = chatMap.get(id);
        if (chat) sorted.push(chat);
      });
      chatMap.forEach((chat, id) => {
        if (!order.includes(id)) sorted.push(chat);
      });
      chatOrderRef.current = order;
      try { localStorage.setItem(`app.chatOrder.${user.email}`, JSON.stringify(order)); } catch {}
      const updatedMap: Record<string, number> = { ...localUpdatedAtRef.current };
      sorted.forEach((chat) => {
        const id = String(chat.id);
        updatedMap[id] = (chat as any).updatedAt || 0;
      });
      localUpdatedAtRef.current = updatedMap;
      try {
        localStorage.setItem(`app.updatedAt.${user.email}`, JSON.stringify(updatedMap));
      } catch {}
      const updatedUsers = users.map((u) => (u.email === user.email ? { ...u, chats: sorted } : u));
      setUsers(updatedUsers);
      setChats(sorted);
      // Persist chat metadata only (no messages) - Firestore is source of truth
      try {
        // Do not persist unused empty drafts/local chats
        const persistable = newChats
          .filter(c => {
            const hasMsgs = Array.isArray(c.messages) && c.messages.length > 0;
            const idStr = String(c.id || '');
            const isPersistedServer = typeof c.id === 'string' && !idStr.startsWith('local-') && !idStr.startsWith('draft-');
            return hasMsgs || isPersistedServer;
          })
          .map(c => ({
            // Only persist metadata, strip out messages array
            id: c.id,
            name: c.name,
            messages: [], // Never persist messages to localStorage
            sessionId: (c as any).sessionId,
            model: (c as any).model,
            updatedAt: (c as any).updatedAt,
            shareable: (c as any).shareable,
            share_token: (c as any).share_token
          }));
        localStorage.setItem(`app.chats.${user.email}`, JSON.stringify(persistable));
      } catch {}
      // Deduplicate messages before updating cache (append-only)
      try {
        const ac = newChats.find(c => c.id === activeChatId);
        if (!ac) return;
        const cacheKey = String(ac.id);
        const existingCache = messagesCache.current[cacheKey] || [];
        const hasMessages = Array.isArray(ac.messages) && ac.messages.length > 0;

        if (hasMessages) {
          // Merge cache with new messages, prioritize existing cache
          const byContent: Record<string, any> = {};

          // First, add all existing cache messages (priority)
          existingCache.forEach((m: any) => {
            const messageId = m.messageId || '';
            // Include quiz key to prevent different quizzes from being merged
            const quizKey = m.quizAnchor ? `|quiz:${m.quizTitle || 'untitled'}` : '';
            const normalizedContent = (m.content || '').trim().toLowerCase().replace(/\s+/g, ' ');
            const contentKey = `${m.role}|${normalizedContent}|${m.media?.artifactId||''}${quizKey}`;
            byContent[contentKey] = m;
          });

          // Then merge in new messages from ac.messages (only if not already in cache by content)
          ac.messages.forEach((m: any) => {
            const messageId = m.messageId || '';
            // Include quiz key to prevent different quizzes from being merged
            const quizKey = m.quizAnchor ? `|quiz:${m.quizTitle || 'untitled'}` : '';
            const normalizedContent = (m.content || '').trim().toLowerCase().replace(/\s+/g, ' ');
            const contentKey = `${m.role}|${normalizedContent}|${m.media?.artifactId||''}${quizKey}`;
            const existingMsg = byContent[contentKey];

            if (!existingMsg) {
              // New message not in cache - add it
              byContent[contentKey] = m;
            } else {
              // Message already exists - prefer server version if available
              const isServerId = messageId && !String(messageId).startsWith('local-');
              const existingIsServerId = existingMsg.messageId && !String(existingMsg.messageId).startsWith('local-');

              if (isServerId && !existingIsServerId) {
                // Upgrade local to server message, preserve timestamp and quiz data
                const merged = {
                  ...existingMsg,
                  ...m,
                  messageId: m.messageId,
                  createdAt: existingMsg.createdAt || m.createdAt,
                  quizData: m.quizData || existingMsg.quizData,
                  quizAnchor: m.quizAnchor ?? existingMsg.quizAnchor,
                  quizTitle: m.quizTitle || existingMsg.quizTitle,
                  // Merge media data
                  media: m.media || existingMsg.media
                };
                byContent[contentKey] = merged;
              }
            }
          });

          // Convert to array and sort by timestamp
          const merged = Object.values(byContent).sort((a: any, b: any) => {
            const ta = typeof a.createdAt === 'number' ? a.createdAt : 0;
            const tb = typeof b.createdAt === 'number' ? b.createdAt : 0;
            return ta - tb;
          });

          // Only update cache if we have at least as many messages (append-only)
          if (merged.length >= existingCache.length) {
            messagesCache.current[cacheKey] = merged as any;
          }
        } else if (!existingCache.length && Array.isArray(ac.messages)) {
          // If cache is empty and we truly have empty messages, keep them in sync
          messagesCache.current[cacheKey] = ac.messages;
        }
      } catch {}
    } catch (error) {
      console.error('Error updating user chats:', error);
    }
  };

  useEffect(() => {
    try {
      const raw = localStorage.getItem(`app.chats.${user.email}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          const map: Record<string, number> = {};
          parsed.forEach((c: any) => {
            if (c && c.id != null) {
              map[String(c.id)] = c.updatedAt || 0;
            }
          });
          localUpdatedAtRef.current = map;
        }
      }
    } catch {}
  }, [user.email]);

  // Simple outbox for offline/idempotent writes
  const persistenceUserKey = desktopLocal
    ? (user?.email ? String(user.email).trim().toLowerCase() : null)
    : user?.uid || null;
  const outboxKey = persistenceUserKey ? `app.outbox.${persistenceUserKey}` : null;
  const enqueueOutbox = (item: any) => {
    try {
      if (!outboxKey) return;
      const raw = localStorage.getItem(outboxKey);
      const arr = raw ? JSON.parse(raw) : [];
      arr.push(item);
      localStorage.setItem(outboxKey, JSON.stringify(arr));
      scheduleFlushOutbox();
    } catch {}
  };
  const scheduleFlushOutbox = () => {
    if (outboxFlushScheduled.current) return;
    outboxFlushScheduled.current = true;
    setTimeout(() => {
      outboxFlushScheduled.current = false;
      void flushOutbox();
    }, 100);
  };
  const flushOutbox = async () => {
    try {
      if (!outboxKey) return;
      const raw = localStorage.getItem(outboxKey);
      const arr: any[] = raw ? JSON.parse(raw) : [];
      if (!arr.length) return;
      const remaining: any[] = [];
      for (const it of arr) {
        try {
          // Skip invalid local/draft chat ids
          if (typeof it.chatId === 'string' && (/^(local-|draft-)/.test(it.chatId))) {
            continue;
          }
          // Model is stored in chat data, not needed in URL
          await apiAppendMessage(it.chatId, it.payload);
        } catch {
          remaining.push(it); // keep for next attempt
        }
      }
      localStorage.setItem(outboxKey, JSON.stringify(remaining));
    } catch {}
  };
  useEffect(() => {
    const onOnline = () => void flushOutbox();
    window.addEventListener('online', onOnline);
    return () => window.removeEventListener('online', onOnline);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outboxKey]);

  // Ensure we have a server-side chat before persisting messages or generating media
  const ensurePersistedActiveChat = async (titleHint?: string): Promise<string | undefined> => {
    const canPersistViaBackend = desktopLocal || !!user?.uid;
    if (!canPersistViaBackend) return undefined;

    // If we already have a persisted Firestore chat id (not local-*), return it
    if (typeof activeChatId === 'string' && !String(activeChatId).startsWith('local-') && !String(activeChatId).startsWith('draft-')) {
      return String(activeChatId);
    }
    try {
      const raw = titleHint && titleHint.trim() ? titleHint : 'New Chat';
      // Trim excessive whitespace and punctuation similar to ChatGPT first message heuristic
      const normalized = raw.replace(/\s+/g,' ').replace(/[\?!.,;:]+$/,'').trim();
      const title = normalized.slice(0, 40) || 'New Chat';
      const sid = (typeof crypto !== 'undefined' && (crypto as any).randomUUID) ? (crypto as any).randomUUID() : `s_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
      const created = await apiCreateChat({ title, sessionId: sid, model });
      const newId: string = created.chat_id;
      if (activeChatId == null) {
        pendingChatsRef.current[newId] = { sessionId: sid, name: title, model, createdAt: Date.now() };
        setActiveChatId(newId);
        try { sessionStorage.removeItem('app.forceBlank'); } catch {}
        return newId;
      }
      const current = chats.find(c => c.id === activeChatId);
      if (current) {
        for (const m of current.messages || []) {
          try { await apiAppendMessage(newId, { role: m.role === 'bot' ? 'assistant' : 'user', content: m.content }); } catch {}
        }
      }
  const migrated = chats.map(c => c.id === activeChatId ? { ...c, id: newId, sessionId: sid, name: title, model, updatedAt: Date.now() } : c);
      // Add the new chat to the front of the list if it's not already there
      const existingIdx = migrated.findIndex(c => c.id === newId);
      let finalChat: Chat;
      if (existingIdx < 0) {
        // Chat not in list yet, add it at the front
        const newChat = chats.find(c => c.id === activeChatId);
        if (newChat) {
          finalChat = { ...newChat, id: newId, sessionId: sid, name: title, model, updatedAt: Date.now() };
          updateUserChats([finalChat, ...migrated.filter(c => c.id !== newId)], { bumpId: String(finalChat.id) });
        } else {
          // Create a new chat entry if none exists
          finalChat = { id: newId, name: title, messages: [], sessionId: sid, model, updatedAt: Date.now() };
          updateUserChats([finalChat, ...migrated], { bumpId: String(finalChat.id) });
        }
      } else {
        // Move to front since it was just updated
        finalChat = migrated[existingIdx];
        const others = migrated.filter(c => c.id !== newId);
        updateUserChats([finalChat, ...others], { bumpId: String(finalChat.id) });
      }
      // Set active chat ID and ensure it's in sync
      setActiveChatId(newId);
      // Small delay to ensure state updates propagate
      await new Promise(resolve => setTimeout(resolve, 50));
      // URL will update via effect hook
      return newId;
    } catch {
      // Cloud mode without auth should not create local-only IDs.
      if (!desktopLocal) return undefined;
      // Desktop-local fallback only if backend call fails unexpectedly.
      if (
        typeof activeChatId === "string" &&
        !String(activeChatId).startsWith("draft-") &&
        String(activeChatId).trim() !== ""
      ) {
        return String(activeChatId);
      }
      const raw = titleHint && titleHint.trim() ? titleHint : "New Chat";
      const normalized = raw.replace(/\s+/g, " ").replace(/[\?!.,;:]+$/, "").trim();
      const title = normalized.slice(0, 40) || "New Chat";
      const sid =
        typeof crypto !== "undefined" && (crypto as any).randomUUID
          ? (crypto as any).randomUUID()
          : `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const localId =
        typeof crypto !== "undefined" && (crypto as any).randomUUID
          ? `local-${(crypto as any).randomUUID()}`
          : `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const localChat: Chat = {
        id: localId,
        name: title,
        messages: [],
        sessionId: sid,
        model,
        updatedAt: Date.now(),
      };
      updateUserChats([localChat, ...chats], { bumpId: String(localChat.id) });
      setActiveChatId(localId);
      try {
        sessionStorage.removeItem("app.forceBlank");
      } catch {}
      return localId;
    }
  };

  // Keep local chats in sync if parent users change (e.g., after login or restore)
  useEffect(() => {
    const latest = users.find((u) => u.email === user.email)?.chats || [];
    const order = chatOrderRef.current;
    const sorted = [...latest].sort((a, b) => {
      const aKey = String(a.id);
      const bKey = String(b.id);
      const aIdx = order.indexOf(aKey);
      const bIdx = order.indexOf(bKey);
      if (aIdx !== -1 || bIdx !== -1) {
        if (aIdx === -1) return 1;
        if (bIdx === -1) return -1;
        return aIdx - bIdx;
      }
      const aTime = localUpdatedAtRef.current[aKey] ?? (a as any).updatedAt ?? 0;
      const bTime = localUpdatedAtRef.current[bKey] ?? (b as any).updatedAt ?? 0;
      return bTime - aTime;
    });
    setChats(sorted);
    const hydratedMap: Record<string, number> = { ...localUpdatedAtRef.current };
    sorted.forEach(chat => {
      const id = String(chat.id);
      if (hydratedMap[id] == null) {
        hydratedMap[id] = (chat as any).updatedAt || 0;
      }
    });
    localUpdatedAtRef.current = hydratedMap;
    try { localStorage.setItem(`app.updatedAt.${user.email}`, JSON.stringify(hydratedMap)); } catch {}
    // if activeChatId no longer exists, pick first unless greeting is forced
    const fb = (typeof window !== 'undefined' && sessionStorage.getItem('app.forceBlank') === '1');
    if (!fb && !sorted.find((c) => c.id === activeChatId!)) {
      setActiveChatId(sorted[0]?.id ?? null);
    }
  }, [users, user.email]);

  // Load chats from backend when Firebase user is present (debounced)
  useEffect(() => {
    let timeoutId: NodeJS.Timeout;
    async function syncChats() {
      try {
        const list = await apiListChats({ limit: 100 });
        const remote: Chat[] = list.map((c: any) => ({
          id: c.chat_id,
          name: c.title,
          messages: [],
          sessionId: c.sessionId,
          model: c.model, // Preserve model from backend
          updatedAt: c.dts // Preserve updatedAt timestamp
        }));
        // Merge strategy: preserve local messages, update metadata, add new remote chats
        const existingOrderIds = chats.map(c => String(c.id));
        const updatedInPlace: Chat[] = chats.map(c => {
          const rid = String(c.id);
          const rMatch = remote.find(r => String(r.id) === rid);
          if (rMatch) {
            // Preserve local messages when syncing metadata
            // Messages are loaded separately via loadMessagesPage, so we never clear them here
            // Preserve local updatedAt if more recent (prevents reordering on refresh)
            const localTime = (c as any).updatedAt || 0;
            const remoteTime = rMatch.updatedAt || 0;
            const remoteName = (rMatch.name || '').trim();
            const localName = (c.name || '').trim();
            const remoteHasCustomName = !!remoteName && !/^New Chat$/i.test(remoteName);
            const localHasCustomName = !!localName && !/^New Chat$/i.test(localName);
            const mergedName = remoteHasCustomName
              ? remoteName
              : (localHasCustomName ? localName : (remoteName || localName || 'New Chat'));
            return {
              ...c,
              name: mergedName,
              sessionId: c.sessionId || rMatch.sessionId,
              model: rMatch.model || (c as any).model,
              updatedAt: Math.max(localTime, remoteTime),
              // syncChats only updates metadata, never messages
              messages: Array.isArray(c.messages) ? c.messages : []
            };
          }
          return c;
        });
        // Only add new remote chats that don't exist locally - these can have empty messages
        const newRemote = remote.filter(r => !existingOrderIds.includes(String(r.id)));
        // Merge without sorting - updateUserChats will use chatOrderRef to maintain stable order
        const merged = [...updatedInPlace, ...newRemote];
  updateUserChats(merged);
  const fb = sessionStorage.getItem('app.forceBlank') === '1';
  if (!fb && merged.length && !activeChatId) setActiveChatId(merged[0].id);
      } catch {
        // ignore
      }
    }
    const canPersistViaBackend = desktopLocal || !!user?.uid;
    if (canPersistViaBackend) {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => { void syncChats(); }, 80);
    } else {
      // restore from localStorage if not authenticated
      try {
        const raw = localStorage.getItem(`app.chats.${user.email}`);
        if (raw) {
          const parsed = JSON.parse(raw);
            if (Array.isArray(parsed) && parsed.length) {
              setChats(parsed as any);
            }
        }
      } catch {}
    }
    return () => clearTimeout(timeoutId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktopLocal, user?.uid, user?.email]);

  // One-time migration: if user just authenticated and we have local-only chats, push them to Firestore
  useEffect(() => {
    async function migrateLocalChats() {
      if (!user?.uid) return;
      const flagKey = `app.migrated.${user.uid}`;
      if (localStorage.getItem(flagKey)) return;
      // migrate only chats that are not string ids (Firestore) i.e., legacy numbers or local-*
      const localOnly = chats.filter(c => typeof c.id === 'number' || String(c.id).startsWith('local-'));
      if (localOnly.length === 0) return;
      try {
        const updated: Chat[] = [...chats];
        for (const lc of localOnly) {
          const sid = (typeof crypto !== 'undefined' && (crypto as any).randomUUID) ? (crypto as any).randomUUID() : `s_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
          const created = await apiCreateChat({ title: lc.name || 'New Chat', sessionId: sid, model });
          const newId = created.chat_id as string;
          // append messages in order
          for (const m of lc.messages) {
            await apiAppendMessage(newId, { role: m.role === 'bot' ? 'assistant' : 'user', content: m.content }, model);
          }
          // swap id locally so UI points to persisted chat
          const idx = updated.findIndex(c => c.id === lc.id);
          if (idx >= 0) updated[idx] = { ...lc, id: newId, sessionId: sid, model } as Chat;
        }
        updateUserChats(updated);
        localStorage.setItem(flagKey, '1');
      } catch {
        // soft-fail; keep local-only
      }
    }
    void migrateLocalChats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.uid, chats.length]);

  // Clear cache when user changes to ensure fresh data from Firestore
  useEffect(() => {
    if (!user?.email) return;
    // Reset cache to ensure we always fetch fresh data from Firestore after login/user change
    messagesCache.current = {};
    lastMessageSentTime.current = 0;

    // Clean up stale localStorage cache from previous versions (backwards compatibility)
    try {
      localStorage.removeItem(`app.messagesCache.${user.email}`);
      localStorage.removeItem(`app.lastMessageTime.${user.email}`);
    } catch {}
  }, [user?.email]);

  // Persist active chat per user and restore it on mount/user change
  useEffect(() => {
    try {
      const key = `app.activeChatId.${user.email}`;
      const saved = localStorage.getItem(key);
      const forceBlank = sessionStorage.getItem('app.forceBlank') === '1';
      if (!forceBlank) {
        if (activeChatId == null && saved && chats.find(c => String(c.id) === saved)) {
          setActiveChatId(saved);
        }
      } else if (activeChatId != null) {
        setActiveChatId(null); // honor greeting on every login
      }
    } catch {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.email]);

  useEffect(() => {
    // Save
    try {
      const key = `app.activeChatId.${user.email}`;
      if (activeChatId != null) localStorage.setItem(key, String(activeChatId));
    } catch {}
  }, [activeChatId, user.email]);

  const handleNewChat = () => {
    if (busy || podcastLoading || quizLoading || widgetLoading) {
      setPendingChatSwitch(NEW_CHAT_SENTINEL);
      setShowSwitchWarning(true);
      return;
    }
    startDraftChat();
  };

  const handleRenameChat = async (chatId: string | number, newName: string) => {
    const newChats = chats.map((c) => (c.id === chatId ? { ...c, name: newName } : c)); // optimistic
    updateUserChats(newChats);
    if (typeof chatId === 'string') {
      try { await apiRenameChat(chatId, newName); } catch {}
    }
  };

  const handleDeleteChat = (chatId: string | number) =>
    setModal({ isOpen: true, type: "deleteChat", data: chatId });

  // Handle share toggle
  const handleToggleShare = async (chatId: string | number, shareable: boolean) => {
    if (typeof chatId !== 'string') return;
    try {
      const result = await apiToggleShare(chatId, shareable);
      // Update chat in local state
      const updatedChats = chats.map(c =>
        c.id === chatId
          ? { ...c, shareable: result.shareable, share_token: result.share_token } as Chat
          : c
      );
      updateUserChats(updatedChats);
    } catch (err) {
      toast({
        title: "Failed to update sharing",
        variant: "destructive",
        duration: 2000,
      });
    }
  };

  // Abort any in-flight generation (video/podcast/quiz)
  const abortAllGeneration = () => {
    try { videoAbortRef.current?.abort(); } catch {}
    try { podcastAbortRef.current?.abort(); } catch {}
    try { quizAbortRef.current?.abort(); } catch {}
    try { widgetAbortRef.current?.abort(); } catch {}
    // Reset loading flags; progress bars will settle via existing effects
    setBusy(false);
    setPodcastLoading(false);
    setQuizLoading(false);
    setWidgetLoading(false);
  };

  const confirmChatSwitch = () => {
    const dest = pendingChatSwitch;
    setShowSwitchWarning(false);
    setPendingChatSwitch(null);
    if (dest == null) return;
    abortAllGeneration();
    setWidgetHtml(null);
    if (dest === NEW_CHAT_SENTINEL) {
      startDraftChat();
      return;
    }
    setActiveChatId(dest);
  };

  const cancelChatSwitch = () => {
    setShowSwitchWarning(false);
    setPendingChatSwitch(null);
  };

  const confirmDeleteChat = async () => {
    const targetId = modal.data;
    if (typeof targetId === 'string') {
      try { await apiDeleteChat(targetId); } catch {}
    }
    let newChats = chats.filter((c) => c.id !== targetId);
    if (newChats.length === 0) {
      setActiveChatId(null);
      setSearchParams(prev => {
        const next = new URLSearchParams(prev);
        next.delete('id');
        next.delete('model');
        return next;
      }, { replace: true });
    } else if (activeChatId === targetId) {
      setActiveChatId(newChats[0].id);
    }
    updateUserChats(newChats);
    setModal({ isOpen: false, type: "", data: null });
  };

  // Ensure current chat has a sessionId and return it
  const ensureChatSessionId = (): string | undefined => {
    if (activeChatId == null) return undefined;
    const idx = chats.findIndex(c => c.id === activeChatId);
    if (idx < 0) {
      return pendingChatsRef.current[String(activeChatId)]?.sessionId || undefined;
    }
    let sid = (chats[idx] as Chat).sessionId;
    if (!sid) {
      sid = (typeof crypto !== 'undefined' && (crypto as any).randomUUID) ? (crypto as any).randomUUID() : `s_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
      const updated = [...chats];
      updated[idx] = { ...(updated[idx] as Chat), sessionId: sid } as Chat;
      updateUserChats(updated);
    }
    return sid;
  };

  const startDraftChat = () => {
    stopPlayback();
    // Reset edit mode when starting a new chat
    setIsEditMode(false);
    setIsQuizMode(false);
    setQuotedMessage(null);
    setActiveChatId(null);
    setActiveScript(null);
    setQuery("");
    setUploadedFiles([]);
    setApiError(null);
    setWidgetHtml(null);
    setVideoUrl(null);
    setSrtText(null);
    setCurrentMediaMeta(null);
    setIsCaptionsOn(false);
    setVttUrl(null);
    setSubtitleLang(undefined);
    try { sessionStorage.setItem('app.forceBlank', '1'); } catch {}
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      next.delete('id');
      next.delete('model');
      return next;
    }, { replace: true });
  };

  // Helper to extract text content from VTT subtitle file (from GCS bucket)
  const extractTranscriptFromVtt = async (vttUrl: string): Promise<string> => {
    try {
      const res = await fetch(vttUrl);
      if (!res.ok) throw new Error(`Failed to fetch VTT: ${res.status}`);
      const vttText = await res.text();

      // Parse VTT format: remove header, timing lines, and empty lines
      const lines = vttText.split('\n');
      const transcript: string[] = [];

      for (const line of lines) {
        const trimmed = line.trim();
        // Skip WEBVTT header, timing lines (contain -->), and empty lines
        if (trimmed && !trimmed.startsWith('WEBVTT') && !trimmed.includes('-->')) {
          // Skip cue settings and tags
          if (!trimmed.startsWith('NOTE') && !trimmed.startsWith('<')) {
            transcript.push(trimmed);
          }
        }
      }

      const result = transcript.join(' ').replace(/\s+/g, ' ').trim();
      if (!result) {
        throw new Error('VTT file is empty or contains no text');
      }
      return result;
    } catch (err) {
      console.error('Failed to extract transcript from VTT:', err);
      throw new Error(`Could not extract captions: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const processAndAddMessage = async (
    content: string,
    isUser = true,
    media?: import('@/types').MediaAttachment,
    persistChatIdOverride?: string,
    extras?: Record<string, any>
  ): Promise<string | undefined> => {
    try {
      const role: 'user' | 'bot' = isUser ? 'user' : 'bot';
  const newMessage = { role, content, media, createdAt: Date.now(), messageId: `local-${Date.now()}-${Math.random().toString(36).slice(2,6)}` , ...(extras || {}) } as any;
      // Prefer the override id (persisted chat) for local updates too
      let localTargetId = (persistChatIdOverride as any) ?? activeChatId;

      // Get the latest chats state - if persistChatIdOverride was just created, ensure we have it
      let currentChats = chats;
      if (persistChatIdOverride && !chats.find(c => c.id === persistChatIdOverride)) {
        // Chat was just created but state hasn't updated yet - check users array
        const latestUser = users.find((u) => u.email === user.email);
        if (latestUser?.chats) {
          currentChats = latestUser.chats;
        }
      }

      let currentChat = currentChats.find(c => c.id === localTargetId);
      const isMigration = !currentChat && !!persistChatIdOverride && activeChatId !== persistChatIdOverride;
      if (!currentChat && persistChatIdOverride) {
        // If ensurePersistedActiveChat just migrated and state hasn't caught up, map active chat to new id
        const ac = currentChats.find(c => c.id === activeChatId);
        if (ac) {
          // Migration: map existing chat to new ID
          currentChat = { ...ac, id: persistChatIdOverride } as Chat;
        } else {
          // No existing chat found: create a new one with the persisted id
          const pendingMeta = pendingChatsRef.current[String(persistChatIdOverride)];
          const draftTitle =
            pendingMeta?.name ||
            (content || '').replace(/\s+/g, ' ').replace(/[\?!.,;:]+$/,'').trim().slice(0, 40) ||
            'Chat';
          currentChat = {
            id: persistChatIdOverride,
            name: draftTitle,
            messages: [],
            updatedAt: Date.now(),
            sessionId: pendingMeta?.sessionId,
            model: pendingMeta?.model || model,
          } as unknown as Chat;
          // Immediately add to sidebar so chat is visible
          if (!currentChats.find(c => c.id === persistChatIdOverride)) {
            updateUserChats([currentChat as Chat, ...currentChats], { bumpId: String(currentChat.id) });
            currentChats = [currentChat as Chat, ...currentChats];
          }
        }
      }
      if (!currentChat) {
        console.warn('No active chat found for message processing', { localTargetId, persistChatIdOverride, activeChatId, chatsCount: currentChats.length });
        return;
      }
      if (!localTargetId && currentChat) {
        localTargetId = currentChat.id;
      }

      // Read from cache first to ensure latest messages
      const historyKey = String(localTargetId);
      const cachedHistory = messagesCache.current[historyKey];
      let history = cachedHistory && cachedHistory.length > 0 ? [...cachedHistory] : [...currentChat.messages];
  const isCompletion = /^(✅|❌|⏹️)/.test(content);
      // Allow repeated user prompts; duplicate suppression removed to preserve user intent
      const wasEmptyBefore = history.length === 0;
      history.push(newMessage);
      const normalizedContent = (content || '').trim().toLowerCase().replace(/\s+/g, ' ');
      const chatKeyForFingerprint = String((persistChatIdOverride as any) ?? localTargetId ?? 'draft');
      if (isUser) {
        if (wasEmptyBefore) {
          const fingerprint = firstPromptFingerprintRef.current[chatKeyForFingerprint];
          if (fingerprint && fingerprint.key === normalizedContent && Date.now() - fingerprint.ts < 2000) {
            return fingerprint.messageId;
          }
          firstPromptFingerprintRef.current[chatKeyForFingerprint] = {
            key: normalizedContent,
            ts: Date.now(),
            messageId: newMessage.messageId,
          };
        } else {
          delete firstPromptFingerprintRef.current[chatKeyForFingerprint];
        }
      }
      if (isUser && wasEmptyBefore && history.length > 1) {
        const firstUserMsg = history.find((msg) => msg.role === 'user');
        if (firstUserMsg) {
          const normalizedFirst = (firstUserMsg.content || '').trim().toLowerCase().replace(/\s+/g, ' ');
          history = history.filter((msg) => {
            if (msg === firstUserMsg) return true;
            if (msg.role !== 'user') return true;
            const normalized = (msg.content || '').trim().toLowerCase().replace(/\s+/g, ' ');
            return normalized !== normalizedFirst;
          });
        }
      }
      messagesCache.current[historyKey] = history as any;

      // Track when message was sent to prevent premature server fetch
      if (isUser) {
        lastMessageSentTime.current = Date.now();
      }

      // Force re-render for immediate UI update
      forceUpdate({});


      const isStatusMessage = !isUser && /^([✅❌⏹️])/u.test((content || '').trim());
      const updatedAtValue = (isUser || isStatusMessage) ? Date.now() : (currentChat.updatedAt || Date.now());
      let modifiedChat = { ...currentChat, messages: history, updatedAt: updatedAtValue } as Chat;
      // Instant rename ONLY on first user message (ChatGPT behavior: first prompt sets permanent name)
      if (isUser && wasEmptyBefore) {
        const title = content.replace(/\s+/g,' ').replace(/[\?!.,;:]+$/,'').trim().slice(0,40) || 'Chat';
        modifiedChat = { ...modifiedChat, name: title } as Chat;
        // Immediately update backend if persisted
        if (typeof modifiedChat.id === 'string' && !String(modifiedChat.id).startsWith('local-') && !String(modifiedChat.id).startsWith('draft-')) {
          try {
            void apiRenameChat(String(modifiedChat.id), title);
          } catch {}
        }
      }
      // First user message: clear forceBlank flag so greeting won't reappear until next login
      if (isUser) {
        try { sessionStorage.removeItem('app.forceBlank'); } catch {}
      }
      // If we just migrated from a draft/local to a persisted chat id, replace the draft entry with the new id
      if (isMigration && persistChatIdOverride) {
        // Use latest chats state
        const filtered = currentChats.filter(c => c.id !== activeChatId && c.id !== persistChatIdOverride);
        const mergedChats = [modifiedChat, ...filtered];
        updateUserChats(mergedChats, { bumpId: String(modifiedChat.id) });
        // Update cache with new chat ID after migration
        const oldCacheKey = String(activeChatId);
        const newCacheKey = String(persistChatIdOverride);
        if (messagesCache.current[oldCacheKey]) {
          messagesCache.current[newCacheKey] = messagesCache.current[oldCacheKey];
          delete messagesCache.current[oldCacheKey];
        } else {
          messagesCache.current[newCacheKey] = history as any;
        }
        setActiveChatId(persistChatIdOverride);
      } else {
        // Normal case: move target chat to front based on activity
        // Use latest chats state to avoid stale data
        // Filter out both the target chat ID and activeChatId (in case they differ during migration)
        const targetId = String(persistChatIdOverride || currentChat!.id);
        const updatedChatsList = currentChats.some(c => String(c.id) === targetId)
          ? currentChats.map(c => String(c.id) === targetId ? modifiedChat : c)
          : [modifiedChat, ...currentChats];
        updateUserChats(updatedChatsList, { bumpId: String(modifiedChat.id) });
        // Keep cache in sync with latest messages
        const finalCacheKey = String(persistChatIdOverride || modifiedChat.id);
        messagesCache.current[finalCacheKey] = history as any;
        // Ensure activeChatId matches the chat we just modified (in case it changed)
      if (persistChatIdOverride && persistChatIdOverride !== activeChatId) {
        setActiveChatId(persistChatIdOverride);
      } else if (!persistChatIdOverride && modifiedChat.id !== activeChatId) {
        setActiveChatId(modifiedChat.id);
      }
        if (persistChatIdOverride) {
          delete pendingChatsRef.current[String(persistChatIdOverride)];
        }
      }
  // Persist remotely
      const targetChatId = persistChatIdOverride || (typeof activeChatId === 'string' ? String(activeChatId) : undefined);
      if (targetChatId && !String(targetChatId).startsWith('local-')) {
        const serverRole: 'user' | 'assistant' = role === 'bot' ? 'assistant' : 'user';
        const mid = (typeof crypto !== 'undefined' && (crypto as any).randomUUID) ? (crypto as any).randomUUID() : `m_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
        const payload: any = { message_id: mid, role: serverRole, content };
        if (media) {
          payload.media = {
            type: media.type,
            url: media.url,
            subtitleUrl: media.subtitleUrl,
            artifactId: media.artifactId,
            title: media.title,
            gcsPath: media.gcsPath,
            sceneCode: media.sceneCode,  // Include sceneCode for video editing
            widgetCode: media.widgetCode,        // BUG FIX: persist widget HTML
          };
        }
        // Persist quiz data if present in extras
        if (extras?.quizAnchor || extras?.quizData) {
          payload.quizAnchor = extras.quizAnchor || false;
          payload.quizTitle = extras.quizTitle;
          payload.quizData = extras.quizData;
        }
        try { await apiAppendMessage(String(targetChatId), payload); }
        catch { enqueueOutbox({ chatId: String(targetChatId), payload, model }); }
      }
  if (!isUser) setActiveScript(content);
      // If this was the first user message that created a persisted chat, move to conversation route
      if (isUser && persistChatIdOverride && wasEmptyBefore) {
  try { navigate(`/chat?id=${persistChatIdOverride}`); } catch {}
      }
      return newMessage.messageId as string;
    } catch (error) {
      console.error('Error processing message:', error);
      return undefined;
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      setUploadedFiles((prev) => [...prev, ...Array.from(files)]);
    }
    e.target.value = ""; // allow re-uploading the same file
  };

  const removeFile = (index: number) => {
    setUploadedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = () => {
    const prompt = query.trim();
    if (!prompt && uploadedFiles.length === 0) return;

    // Show toast and keep prompt in input - user must select generation type
    toast({
      title: "Select a Generation Type",
      description: "Please choose whether you'd like to create a Video, Podcast, or Quiz from your prompt.",
      duration: 4000
    });
    // Don't clear query or add message - keep prompt in typing area
  };

  const generatePodcastFromPrompt = async () => {
    lastGenerateKindRef.current = 'podcast';
    // If already loading, treat as cancel toggle
    if (podcastLoading && podcastAbortRef.current) {
      podcastAbortRef.current.abort();
      return;
    }
    // Stop any current playback/progress immediately when starting generation
    stopPlayback();
    // Build a candidate prompt first so we can warn if it's empty
    let prompt = "";
    if (query.trim()) {
      prompt = query.trim();
    }
    if (!prompt) {
      toast({ title: "Enter a prompt", description: "Please enter a prompt first.", duration: 4000 });
      return;
    }

    // Persist (may migrate draft) BEFORE adding message so user prompt always visible
    let persistedId = await ensurePersistedActiveChat(prompt);
    // Use persistedId or activeChatId, or let processAndAddMessage create a local one
    const finalChatId = persistedId || activeChatId;
    if (!finalChatId) {
      toast({ title: "Unable to start chat", description: "Please sign in and try again.", duration: 4000 });
      return;
    }
    setActiveChatId(finalChatId);
    // Add user message FIRST - this ensures prompt is visible in chat
    await processAndAddMessage(prompt, true, undefined, persistedId);
    // Now clear the query input AFTER message is added
    setQuery("");
    // Gate after recording user prompt so it never disappears
    if (!ensureLlmKey("video")) return; // reuse existing gating label
    // Pass the chat ID to generatePodcast to avoid duplicate chat creation
    generatePodcast(prompt, finalChatId);
  };

  async function generatePodcast(prompt: string, chatIdOverride?: string | number | null) {
    setPodcastLoading(true);
    setApiError(null);
    // Reset current media
    setWidgetHtml(null);
    setVideoUrl(null);
    setSrtText(null);
    // Use the provided chat ID or fall back to activeChatId
    let currentChatId = chatIdOverride || activeChatId;
    if (currentChatId == null) {
      setApiError("No active chat selected.");
      return;
    }
    // Ensure activeChatId is set
    if (currentChatId && currentChatId !== activeChatId) {
      setActiveChatId(currentChatId);
    }
    // Store the chat ID we'll use for this generation
    const chatIdForGeneration = typeof currentChatId === 'string' ? currentChatId : String(currentChatId);
    // start visual progress ramp-up (synthetic) similar to video
    setPodcastProgress(5);
    if (podcastProgressTimer.current) window.clearInterval(podcastProgressTimer.current);
    podcastProgressTimer.current = window.setInterval(() => {
      setPodcastProgress((p) => (p < 60 ? Math.min(p + 2, 60) : 60));
    }, 700);
    let aborted = false;
    try {
      const safe: ApiKeys = {
        claude: apiKeys?.claude || "",
        gemini: apiKeys?.gemini || "",
        provider: apiKeys?.provider || "",
        model: apiKeys?.model || "",
      };

      const sessionId = ensureChatSessionId();
      const body = {
        prompt,
        keys: { claude: safe.claude, gemini: safe.gemini },
        provider: safe.provider || undefined,
        model: safe.model || undefined,
        sessionId,
      };
      const controller = new AbortController();
      podcastAbortRef.current = controller;
      const res = await apiFetch("/podcast", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, chatId: chatIdForGeneration }),
        signal: controller.signal,
      });
      const { data, raw } = await parseResponse(res);
      if (res.ok && data?.status === "ok" && data?.video_url) {
        // Use signed URL if available, otherwise use regular URL
        const audioUrl = toPlayableMediaUrl(data.signed_video_url || data.video_url) || "";
        setVideoUrl(audioUrl);
        setCurrentMediaMeta({ artifactId: data.artifact_id, gcsPath: data.gcs_path, type: 'audio' });
        setSubtitleLang((data.lang as string) || undefined);


        // Create media attachment for persistent access - always use signed URL if available
        const mediaAttachment: import('@/types').MediaAttachment = {
          type: 'audio',
          url: audioUrl, // Use signed URL for persistence
          subtitleUrl: toPlayableMediaUrl(data.signed_subtitle_url),
          title: `Podcast: ${prompt.slice(0, 50)}...`,
          artifactId: data.artifact_id,
          gcsPath: data.gcs_path,
          scriptGcsPath: data.script_gcs_path // GCS path for persistent script fallback
        };

        // Use the same chat ID we started with to ensure message goes to correct chat
        await processAndAddMessage("✅ Podcast generated.", false, mediaAttachment, chatIdForGeneration);

        // Captions for podcast (audio): attempt fetch using helper
        // Clear old captions first
        setVttUrl(null);
        setSrtText(null);
        void fetchCaptions(audioUrl, data.signed_subtitle_url);
      } else {
        // Prefer backend-provided detail; otherwise fall back to HTTP status and body, then sanitize
        let msg: string = "";
        try {
          const primary = (data && (data.detail ?? data)) ?? raw;
          if (primary !== undefined && primary !== null) {
            if (typeof primary === "string") msg = primary;
            else msg = JSON.stringify(primary, null, 2);
          }
        } catch {}
        if (!msg || msg.replace(/\s+/g, "") === "\"\"") {
          const statusText = (res as any).statusText || "";
          msg = `HTTP ${(res as any).status || "error"} ${statusText || ""}`.trim();
          if (!raw || String(raw).trim() === "") {
            msg += " (empty body)";
          }
        }
        const friendly = "Podcast generation failed." + (msg ? ` ${String(msg).slice(0, 180)}` : "");
        setApiError(friendly);
        await processAndAddMessage("❌ Podcast generation failed.", false, undefined, chatIdForGeneration);
      }
    } catch (err: any) {
      if (err?.name === "AbortError") {
        setApiError(null);
        await processAndAddMessage("⏹️ Canceled podcast generation.", false, undefined, chatIdForGeneration);
        aborted = true;
      } else {
        const networkMsg = err?.message && /Failed to fetch|NetworkError|TypeError/i.test(err.message)
          ? "We couldn't reach the server. Check your connection and try again."
          : (err?.message || "Request failed");
        setApiError(networkMsg);
        await processAndAddMessage("❌ Network error.", false, undefined, chatIdForGeneration);
      }
    } finally {
      setPodcastLoading(false);
      podcastAbortRef.current = null;
      if (podcastProgressTimer.current) window.clearInterval(podcastProgressTimer.current);
      setPodcastProgress(aborted ? 0 : 100);
    }
  }

  const generateVideoFromPrompt = async (promptOverride?: string) => {
    lastGenerateKindRef.current = 'video';
    // If already generating, treat as cancel toggle
    if (busy && videoAbortRef.current) {
      videoAbortRef.current.abort();
      // best-effort server-side cancel if a jobId exists
      if (currentVideoJobId.current) {
        fetch(apiUrl(`/jobs/cancel?jobId=${encodeURIComponent(currentVideoJobId.current)}`), {
          method: "POST",
        }).catch(() => {});
      }
      return;
    }
    // Stop any current playback/progress before starting generation
    stopPlayback();
    // Build a candidate prompt first so we can warn if it's empty
    let prompt = "";
    if (query.trim()) {
      prompt = query.trim();
    }
    if (!prompt) {
      toast({ title: "Enter a prompt", description: "Please enter a prompt first.", duration: 4000 });
      return;
    }
    // Persist (may migrate draft) BEFORE adding message so user prompt always visible
    let persistedId = await ensurePersistedActiveChat(prompt);
    // Use persistedId or activeChatId, or let processAndAddMessage create a local one
    const finalChatId = persistedId || activeChatId;
    if (!finalChatId) {
      toast({ title: "Unable to start chat", description: "Please sign in and try again.", duration: 4000 });
      return;
    }
    setActiveChatId(finalChatId);
    // Add user message FIRST - this ensures prompt is visible in chat
    await processAndAddMessage(prompt, true, undefined, persistedId);
    // Now clear the query input AFTER message is added
    setQuery("");
    // Gate after recording user prompt so it never disappears
    if (!ensureLlmKey("video")) return;
    // Pass the chat ID to generateVideo to avoid duplicate chat creation
    generateVideo(prompt, finalChatId);
  };

  const getLastUserPrompt = () => {
    const msgs = (activeChat as Chat).messages || [];
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === "user" && msgs[i].content) return msgs[i].content;
    }
    return "";
  };

  // Normalize a prompt by stripping any leading labels like
  // "📝 Generate quiz:", "▶️ Generate video:", "🎙️ Generate podcast:", or
  // "⏳ Generating <type>:" that may have been used in previous user messages
  const normalizePrompt = (raw: string, type: "quiz" | "video" | "podcast") => {
    if (!raw) return "";
    const t = raw.trim();
    // Build patterns for this type and generic forms
    const patterns = [
      /^\s*[\u270D\uFE0F\uD83D\uDCDD\uD83D\uDCC4\uD83D\uDCDD\uD83D\uDCD1\uD83D\uDCDD]?\s*Generate\s+quiz\s*:\s*/i,
      /^\s*[\u25B6\uFE0F]?\s*Generate\s+video\s*:\s*/i,
      /^\s*[\uD83C\uDF99\uFE0F\uD83C\uDF99]?\s*Generate\s+podcast\s*:\s*/i,
      /^\s*⏳\s*Generating\s+quiz\s*:\s*/i,
      /^\s*⏳\s*Generating\s+video\s*:\s*/i,
      /^\s*⏳\s*Generating\s+podcast\s*:\s*/i,
    ];
    let out = t;
    for (const re of patterns) out = out.replace(re, "");
    return out.trim();
  };

  async function generateQuiz() {
    // Cancel if already loading
    if (quizLoading && quizAbortRef.current) {
      quizAbortRef.current.abort();
      return;
    }
    // Always use the current prompt typed in the box
    const currentPrompt = (query || '').trim();
    if (!currentPrompt) {
      // Show popup for empty prompt (requested)
      toast({ title: 'Enter a prompt', description: 'Please enter a prompt first.', duration: 4000 });
      return;
    }
    if (!ensureLlmKey('quiz')) return;
    setQuizLoading(true);
    let persistedId: string | undefined;
    try {
      const pendingPrompt = normalizePrompt(currentPrompt, 'quiz');
      persistedId = await ensurePersistedActiveChat(pendingPrompt || 'Generate quiz');
      // Use persistedId or activeChatId, or let processAndAddMessage create a local one
      const finalChatId = persistedId || activeChatId;
      if (!finalChatId) {
        toast({ title: "Unable to start chat", description: "Please sign in and try again.", duration: 4000 });
        return;
      }
      setActiveChatId(finalChatId);
      // Record the user's current prompt FIRST - this ensures prompt is visible in chat
      await processAndAddMessage(pendingPrompt, true, undefined, persistedId);
      // Now clear the query input AFTER message is added
      setQuery("");
      const safe: ApiKeys = { claude: apiKeys?.claude || '', gemini: apiKeys?.gemini || '', provider: apiKeys?.provider || '', model: apiKeys?.model || '' };
      const sessionId = ensureChatSessionId();
  const body = { prompt: pendingPrompt || '', num_questions: 5, difficulty: 'medium', keys: { claude: safe.claude, gemini: safe.gemini }, provider: safe.provider || undefined, model: safe.model || undefined, sessionId };
      console.debug('POST /quiz/embedded', body);
      const controller = new AbortController();
      quizAbortRef.current = controller;
      const res = await fetch(apiUrl('/quiz/embedded'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal
      });
      const { data, raw: quizRawResponse } = await parseResponse(res);
      // Use the same chat ID we started with
      const quizChatId = persistedId || activeChatId;
      if (quizChatId && res.ok && data?.status === 'ok' && data?.quiz?.questions?.length) {
        // Insert a hidden bot anchor message (no visible bubble) to attach the quiz UI
        // Store quiz data in message extras so it persists on refresh
        const quizTitle = (data.quiz?.title as string) || 'Quiz';
        const quizMsgId = await processAndAddMessage('', false, undefined, String(quizChatId), {
          quizAnchor: true,
          quizTitle,
          quizData: data.quiz // Store quiz data in message for persistence
        });
          if (quizMsgId) {
            // Initialize runtime for this quiz
            setQuizzesByChat(prev => ({
              ...prev,
              [String(quizChatId)]: {
                ...(prev[String(quizChatId)] || {}),
                [quizMsgId]: { data: data.quiz, index: 0, answers: [], score: null, selected: null, revealed: false }
              }
            }));
          }
      } else {
        const rawMsg = JSON.stringify(data?.detail ?? data ?? quizRawResponse, null, 2) || '';
        const concise = rawMsg ? String(rawMsg).slice(0,160) : '';
        await processAndAddMessage('❌ Quiz generation failed.', false, undefined, persistedId);
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        await processAndAddMessage('⏹️ Canceled quiz generation.', false, undefined, persistedId);
      } else {
        await processAndAddMessage('❌ Quiz generation failed.', false, undefined, persistedId);
      }
    } finally {
      setQuizLoading(false);
      quizAbortRef.current = null;
    }
  }

  async function generateWidgetFromPrompt() {
    // Cancel toggle if already loading
    if (widgetLoading && widgetAbortRef.current) {
      widgetAbortRef.current.abort();
      return;
    }

    const prompt = query.trim();
    if (!prompt) {
      toast({ title: "Enter a prompt", description: "Please enter a prompt first.", duration: 4000 });
      return;
    }
    if (!ensureLlmKey("quiz")) return; // reuse key check

    setWidgetLoading(true);
    setWidgetProgress(5);
    if (widgetProgressTimer.current) window.clearInterval(widgetProgressTimer.current);
    widgetProgressTimer.current = window.setInterval(() => {
      setWidgetProgress((p) => (p < 60 ? Math.min(p + 2, 60) : 60));
    }, 700);
    let aborted = false;
    let persistedId: string | undefined;

    try {
      persistedId = await ensurePersistedActiveChat(prompt);
      const finalChatId = persistedId || activeChatId;
      if (!finalChatId) {
        toast({ title: "Unable to start chat", description: "Please sign in and try again.", duration: 4000 });
        return;
      }
      setActiveChatId(finalChatId);

      // Add user message first
      await processAndAddMessage(prompt, true, undefined, persistedId);
      setQuery("");

      const safe: ApiKeys = {
        claude: apiKeys?.claude || "",
        gemini: apiKeys?.gemini || "",
        provider: apiKeys?.provider || "",
        model: apiKeys?.model || "",
      };

      const controller = new AbortController();
      widgetAbortRef.current = controller;

      const data = await apiWidget({
        prompt,
        provider: safe.provider || undefined,
        model: safe.model || undefined,
        keys: { claude: safe.claude, gemini: safe.gemini },
        chatId: String(finalChatId),
      }, controller.signal);

      if (data?.status === "ok" && data?.widget_html) {
        // Store widget HTML in media attachment (no URL, no GCS — fully inline)
        const mediaAttachment: import('@/types').MediaAttachment = {
          type: 'widget',
          widgetCode: data.widget_html,
          title: `Widget: ${prompt.slice(0, 50)}`,
        };
        const widgetMessageId = await processAndAddMessage(
          "✅ Interactive widget generated.",
          false,
          mediaAttachment,
          String(finalChatId)
        );
        setVideoUrl(null);
        setCurrentMediaMeta({ type: 'widget' });
        setSrtText(null);
        setVttUrl(null);
        setSubtitleLang(undefined);
        setWidgetHtml(data.widget_html);
      } else {
        await processAndAddMessage("❌ Widget generation failed.", false, undefined, persistedId);
      }
    } catch (err: any) {
      if (err?.name === "AbortError") {
        await processAndAddMessage("⏹️ Canceled widget generation.", false, undefined, persistedId);
        aborted = true;
      } else {
        await processAndAddMessage("❌ Widget generation failed.", false, undefined, persistedId);
        toast({ title: "Widget failed", description: err?.message || "Unknown error", duration: 4000 });
      }
    } finally {
      setWidgetLoading(false);
      if (widgetProgressTimer.current) window.clearInterval(widgetProgressTimer.current);
      setWidgetProgress(aborted ? 0 : 100);
      widgetAbortRef.current = null;
    }
  }

  // Embedded quiz interaction helpers (per-chat runtime)
  const submitQuizAnswer = (quizMessageId: string, answerIdx: number) => {
    if (typeof activeChatId !== 'string') return;
    setQuizzesByChat(prev => {
  const chatQuizzes = prev[activeChatId] || {};
      const rt = chatQuizzes[quizMessageId];
      if (!rt || rt.score != null) return prev;
      const nextAnswers = [...rt.answers, answerIdx];
      const nextIndex = rt.index + 1;
      if (nextIndex >= rt.data.questions.length) {
        let score = 0;
        rt.data.questions.forEach((q, i) => { if (nextAnswers[i] === q.correctIndex) score += 1; });
        return {
          ...prev,
          [activeChatId]: {
            ...chatQuizzes,
            [quizMessageId]: { ...rt, answers: nextAnswers, index: nextIndex, score, selected: null, revealed: true }
          }
        };
      } else {
        return {
          ...prev,
          [activeChatId]: { ...chatQuizzes, [quizMessageId]: { ...rt, answers: nextAnswers, index: nextIndex, selected: null, revealed: false } }
        };
      }
    });
  };

  const retakeQuiz = (quizMessageId: string) => {
    if (typeof activeChatId !== 'string') return;
    setQuizzesByChat(prev => {
      const chatQuizzes = prev[activeChatId] || {};
      const rt = chatQuizzes[quizMessageId];
      if (!rt) return prev;
      return { ...prev, [activeChatId]: { ...chatQuizzes, [quizMessageId]: { ...rt, index: 0, answers: [], score: null, selected: null, revealed: false } } };
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleLogout = () => setModal({ isOpen: true, type: "logout", data: null });

  const handleUpdateDisplayName = (nextName: string) => {
    const trimmed = String(nextName || "").trim();
    if (!trimmed) return;
    setUser({ ...user, name: trimmed });
    setUsers(users.map((u) => (u.email === user.email ? { ...u, name: trimmed } : u)));
    if (desktopLocal) {
      try {
        localStorage.setItem("app.localUser", JSON.stringify({ name: trimmed, email: user.email }));
      } catch {}
    }
  };

  const handleResetLocalData = async () => {
    if (!desktopLocal) return;
    const ok = window.confirm(
      "Reset all local desktop data? This removes local chats, media history, settings, and saved keys on this device."
    );
    if (!ok) return;

    try {
      try {
        await apiDeleteAccount();
      } catch {}
      try {
        await clearApiKeysForUser(user.email);
      } catch {}
      try {
        Object.keys(localStorage).forEach((key) => {
          if (key.startsWith("app.")) localStorage.removeItem(key);
        });
      } catch {}
      try {
        sessionStorage.removeItem("app.forceBlank");
      } catch {}
      setSettingsOpen(false);
      window.location.assign("/home");
    } catch (e: any) {
      toast({
        title: "Reset failed",
        description: e?.message || "Could not reset local data.",
        variant: "destructive",
      });
    }
  };

  const confirmLogout = async () => {
    if (desktopLocal) {
      try {
        localStorage.removeItem("app.localUser");
        if (user?.email) {
          localStorage.removeItem(`app.activeChatId.${user.email}`);
        }
      } catch {}
      setUser(null);
      setModal({ isOpen: false, type: "", data: null });
      setView("home");
      return;
    }
    try {
      const { getFirebaseAuth } = await import("@/firebase");
      const auth = getFirebaseAuth();
      await auth.signOut();
    } catch {}
    // Clear per-user cached state
    try {
      if (user?.email) {
        localStorage.removeItem(`app.activeChatId.${user.email}`);
      }
      // Reset session-only flags so next real login triggers a fresh chat
      sessionStorage.removeItem('app.justLoggedIn');
      sessionStorage.removeItem('app.wasAuthed');
    } catch {}
    setModal({ isOpen: false, type: "", data: null });
  };




  // State for reauth modal
  const [reauthPassword, setReauthPassword] = useState("");
  const [reauthError, setReauthError] = useState<string | null>(null);
  const [reauthLoading, setReauthLoading] = useState(false);
  // --- Modal rendering for delete account ---
  // Delete Account Modal Flow: Step 1 - Confirm, Step 2 - Password/OAuth
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showDeletePassword, setShowDeletePassword] = useState(false);
  const [pendingAuthType, setPendingAuthType] = useState<'password' | 'oauth' | null>(null);

  // Open delete account confirmation modal
  const handleDeleteAccount = async () => {
    if (desktopLocal) {
      await clearApiKeysForUser(user.email);
      try {
        Object.keys(localStorage).forEach((key) => {
          if (key.startsWith("app.")) localStorage.removeItem(key);
        });
        Object.keys(sessionStorage).forEach((key) => {
          if (key.startsWith("app.")) sessionStorage.removeItem(key);
        });
        localStorage.removeItem("app.localUser");
      } catch {}
      setUsers(users.filter((u) => u.email !== user.email));
      setUser(null);
      toast({
        title: "Local profile cleared",
        description: "All local app data has been removed from this device.",
        duration: 3000,
      });
      setView("home");
      return;
    }
    let authType: 'password' | 'oauth' | null = null;
    try {
      const { getFirebaseAuth } = await import("@/firebase");
      const auth = getFirebaseAuth();
      const currentUser = auth.currentUser;
      if (!currentUser) {
        toast({ title: "No user signed in", description: "Please sign in and try again.", variant: "destructive", duration: 4000 });
        return;
      }
      if (currentUser.providerData.some((p: any) => p.providerId === 'password')) {
        authType = 'password';
      } else {
        authType = 'oauth';
      }
    } catch {
      authType = null;
    }
    setPendingAuthType(authType);
    setShowDeleteConfirm(true);
    setShowDeletePassword(false);
    setReauthPassword("");
    setReauthError(null);
  };

  // Step 1: Confirmation modal
  const renderDeleteAccountConfirmModal = () => {
    if (!showDeleteConfirm) return null;
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-60">
        <div className="bg-background rounded-lg shadow-lg p-6 w-full max-w-md border border-border">
          <h2 className="text-lg font-semibold mb-2">Delete Account</h2>
          <p className="mb-4 text-sm text-foreground">
            Are you sure you want to delete your account? This will permanently delete all your chats, settings, and associated media files. This action cannot be undone.
          </p>
          <div className="flex justify-end gap-2 mt-4">
            <button
              className="px-4 py-2 rounded bg-muted text-foreground border"
              onClick={() => { setShowDeleteConfirm(false); setPendingAuthType(null); }}
              disabled={reauthLoading}
            >
              Cancel
            </button>
            <button
              className="px-4 py-2 rounded bg-destructive text-white font-semibold hover:bg-destructive/90 disabled:opacity-60"
              onClick={async () => {
                setShowDeleteConfirm(false);
                if (pendingAuthType === 'password') {
                  setShowDeletePassword(true);
                } else if (pendingAuthType === 'oauth') {
                  setReauthLoading(true);
                  setReauthError(null);
                  // OAuth reauth: open popup
                  try {
                    const { getFirebaseAuth } = await import("@/firebase");
                    const auth = getFirebaseAuth();
                    const currentUser = auth.currentUser;
                    const { GoogleAuthProvider, GithubAuthProvider, reauthenticateWithPopup } = await import("firebase/auth");
                    let provider;
                    if (currentUser.providerData.some((p: any) => p.providerId === 'google.com')) {
                      provider = new GoogleAuthProvider();
                    } else if (currentUser.providerData.some((p: any) => p.providerId === 'github.com')) {
                      provider = new GithubAuthProvider();
                    } else {
                      setReauthError("Unsupported provider. Please log out and log back in.");
                      setReauthLoading(false);
                      return;
                    }
                    await reauthenticateWithPopup(currentUser, provider);
                  } catch (err: any) {
                    setReauthError("Confirmation cancelled or failed. Please try again.");
                    setReauthLoading(false);
                    return;
                  }
                  // Backend delete
                  try {
                    await apiDeleteAccount();
                  } catch (err: any) {
                    toast({
                      title: "Failed to delete account",
                      description: "Could not delete account data. Try again.",
                      variant: "destructive",
                      duration: 4000,
                    });
                    setReauthLoading(false);
                    return;
                  }
                  // Delete Firebase Auth user
                  try {
                    const { getFirebaseAuth } = await import("@/firebase");
                    const auth = getFirebaseAuth();
                    const currentUser = auth.currentUser;
                    await currentUser.delete();
                  } catch {}
                  // Clear all local/session storage and user settings
                  try {
                    if (user?.email) {
                      localStorage.removeItem(`app.activeChatId.${user.email}`);
                      localStorage.removeItem(`app.apiKeys.${user.email}`);
                      localStorage.removeItem(`app.theme.${user.email}`);
                      localStorage.removeItem(`app.colorTheme.${user.email}`);
                    }
                    localStorage.removeItem('app.apiKeys');
                    localStorage.removeItem('app.theme');
                    localStorage.removeItem('app.colorTheme');
                    localStorage.removeItem('app.users');
                    localStorage.removeItem('app.messagesCache');
                    localStorage.removeItem('app.lastMessageTime');
                    sessionStorage.removeItem('app.justLoggedIn');
                    sessionStorage.removeItem('app.wasAuthed');
                    sessionStorage.removeItem('app.forceBlank');
                    Object.keys(localStorage).forEach((key) => {
                      if (key.startsWith('app.')) localStorage.removeItem(key);
                    });
                    Object.keys(sessionStorage).forEach((key) => {
                      if (key.startsWith('app.')) sessionStorage.removeItem(key);
                    });
                  } catch {}
                  toast({
                    title: "Account deleted",
                    description: "Your account and all associated data have been permanently deleted.",
                    duration: 3000,
                  });
                  window.location.replace("/");
                }
              }}
              disabled={reauthLoading}
            >
              {reauthLoading ? "Processing..." : "Delete Permanently"}
            </button>
          </div>
        </div>
      </div>
    );
  };

  // Step 2: Password modal for manual users
  const renderDeleteAccountPasswordModal = () => {
    if (!showDeletePassword) return null;
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-60">
        <div className="bg-background rounded-lg shadow-lg p-6 w-full max-w-md border border-border">
          <h2 className="text-lg font-semibold mb-2">Delete Account</h2>
          <p className="mb-4 text-sm text-foreground">
            Please enter your password to confirm account deletion. This action cannot be undone.
          </p>
          <div className="mb-4">
            <label className="block text-sm font-medium mb-1" htmlFor="reauth-password">Password</label>
            <input
              id="reauth-password"
              type="password"
              className="w-full border rounded px-3 py-2 text-base bg-background text-foreground border-border focus:outline-none focus:ring-2 focus:ring-destructive"
              value={reauthPassword}
              onChange={e => setReauthPassword(e.target.value)}
              disabled={reauthLoading}
              autoFocus
              autoComplete="current-password"
              style={{ fontFamily: 'inherit', letterSpacing: '0.1em' }}
            />
          </div>
          {reauthError && <div className="text-red-600 text-sm mb-2">{reauthError}</div>}
          <div className="flex justify-end gap-2 mt-4">
            <button
              className="px-4 py-2 rounded bg-muted text-foreground border"
              onClick={() => { setShowDeletePassword(false); setReauthPassword(""); setReauthError(null); setPendingAuthType(null); }}
              disabled={reauthLoading}
            >
              Cancel
            </button>
            <button
              className="px-4 py-2 rounded bg-destructive text-white font-semibold hover:bg-destructive/90 disabled:opacity-60"
              onClick={async () => {
                setReauthError(null);
                setReauthLoading(true);
                try {
                  const { getFirebaseAuth } = await import("@/firebase");
                  const auth = getFirebaseAuth();
                  const currentUser = auth.currentUser;
                  if (!currentUser) throw new Error("No user is currently signed in");
                  if (!reauthPassword) {
                    setReauthError("Please enter your password.");
                    setReauthLoading(false);
                    return;
                  }
                  const { EmailAuthProvider, reauthenticateWithCredential } = await import("firebase/auth");
                  const credential = EmailAuthProvider.credential(currentUser.email, reauthPassword);
                  try {
                    await reauthenticateWithCredential(currentUser, credential);
                  } catch (err: any) {
                    setReauthError("Incorrect password. Please try again.");
                    setReauthLoading(false);
                    return;
                  }
                  // Backend delete
                  try {
                    await apiDeleteAccount();
                  } catch (err: any) {
                    toast({
                      title: "Failed to delete account",
                      description: "Could not delete account data. Try again.",
                      variant: "destructive",
                      duration: 4000,
                    });
                    setReauthLoading(false);
                    return;
                  }
                  // Delete Firebase Auth user
                  await currentUser.delete();
                  // Clear all local/session storage and user settings
                  try {
                    if (user?.email) {
                      localStorage.removeItem(`app.activeChatId.${user.email}`);
                      localStorage.removeItem(`app.apiKeys.${user.email}`);
                      localStorage.removeItem(`app.theme.${user.email}`);
                      localStorage.removeItem(`app.colorTheme.${user.email}`);
                    }
                    localStorage.removeItem('app.apiKeys');
                    localStorage.removeItem('app.theme');
                    localStorage.removeItem('app.colorTheme');
                    localStorage.removeItem('app.users');
                    localStorage.removeItem('app.messagesCache');
                    localStorage.removeItem('app.lastMessageTime');
                    sessionStorage.removeItem('app.justLoggedIn');
                    sessionStorage.removeItem('app.wasAuthed');
                    sessionStorage.removeItem('app.forceBlank');
                    Object.keys(localStorage).forEach((key) => {
                      if (key.startsWith('app.')) localStorage.removeItem(key);
                    });
                    Object.keys(sessionStorage).forEach((key) => {
                      if (key.startsWith('app.')) sessionStorage.removeItem(key);
                    });
                  } catch {}
                  toast({
                    title: "Account deleted",
                    description: "Your account and all associated data have been permanently deleted.",
                    duration: 3000,
                  });
                  // window.location.replace("/"); // Removed to prevent double redirect
                } catch (error: any) {
                  const errorMessage = error?.code === 'auth/requires-recent-login'
                    ? "For security, please reauthenticate before deleting your account."
                    : "Could not delete account, try again.";
                  toast({
                    title: "Failed to delete account",
                    description: errorMessage,
                    variant: "destructive",
                    duration: 4000,
                  });
                }
                setReauthLoading(false);
                setShowDeletePassword(false);
                setPendingAuthType(null);
              }}
              disabled={reauthLoading || !reauthPassword}
            >
              {reauthLoading ? "Deleting..." : "Delete Permanently"}
            </button>
          </div>
        </div>
      </div>
    );
  };

  // ...existing code...

  // Confirm delete account with reauth
  const confirmDeleteAccount = async () => {
    setReauthError(null);
    setReauthLoading(true);
    try {
      const { getFirebaseAuth } = await import("@/firebase");
      const auth = getFirebaseAuth();
      const currentUser = auth.currentUser;
      if (!currentUser) throw new Error("No user is currently signed in");
      // Detect provider type
      const isPassword = currentUser.providerData.some((p: any) => p.providerId === 'password');
      // Reauth step
      if (isPassword) {
        if (!reauthPassword) {
          setReauthError("Please enter your password.");
          setReauthLoading(false);
          return;
        }
        // Reauthenticate with password
        const { EmailAuthProvider, reauthenticateWithCredential } = await import("firebase/auth");
        const credential = EmailAuthProvider.credential(currentUser.email, reauthPassword);
        try {
          await reauthenticateWithCredential(currentUser, credential);
        } catch (err: any) {
          setReauthError("Incorrect password. Please try again.");
          setReauthLoading(false);
          return;
        }
      } else {
        // OAuth reauth: open popup
        const { GoogleAuthProvider, GithubAuthProvider, reauthenticateWithPopup } = await import("firebase/auth");
        let provider;
        if (currentUser.providerData.some((p: any) => p.providerId === 'google.com')) {
          provider = new GoogleAuthProvider();
        } else if (currentUser.providerData.some((p: any) => p.providerId === 'github.com')) {
          provider = new GithubAuthProvider();
        } else {
          setReauthError("Unsupported provider. Please log out and log back in.");
          setReauthLoading(false);
          return;
        }
        try {
          await reauthenticateWithPopup(currentUser, provider);
        } catch (err: any) {
          setReauthError("Confirmation cancelled or failed. Please try again.");
          setReauthLoading(false);
          return;
        }
      }
      // Backend delete
      try {
        await apiDeleteAccount();
      } catch (err: any) {
        toast({
          title: "Failed to delete account",
          description: "Could not delete account data. Try again.",
          variant: "destructive",
          duration: 4000,
        });
        setReauthLoading(false);
        return;
      }
      // Delete Firebase Auth user
      await currentUser.delete();
      // Clear all local/session storage and user settings
      try {
        if (user?.email) {
          localStorage.removeItem(`app.activeChatId.${user.email}`);
          localStorage.removeItem(`app.apiKeys.${user.email}`);
          localStorage.removeItem(`app.theme.${user.email}`);
          localStorage.removeItem(`app.colorTheme.${user.email}`);
        }
        // Remove global and per-user API keys, theme, color theme, and other user settings
        localStorage.removeItem('app.apiKeys');
        localStorage.removeItem('app.theme');
        localStorage.removeItem('app.colorTheme');
        localStorage.removeItem('app.users');
        localStorage.removeItem('app.messagesCache');
        localStorage.removeItem('app.lastMessageTime');
        sessionStorage.removeItem('app.justLoggedIn');
        sessionStorage.removeItem('app.wasAuthed');
        sessionStorage.removeItem('app.forceBlank');
        // Remove any other app.* keys
        Object.keys(localStorage).forEach((key) => {
          if (key.startsWith('app.')) localStorage.removeItem(key);
        });
        Object.keys(sessionStorage).forEach((key) => {
          if (key.startsWith('app.')) sessionStorage.removeItem(key);
        });
      } catch {}
      toast({
        title: "Account deleted",
        description: "Your account and all associated data have been permanently deleted.",
        duration: 3000,
      });
      window.location.replace("/");
    } catch (error: any) {
      const errorMessage = error?.code === 'auth/requires-recent-login'
        ? "For security, please reauthenticate before deleting your account."
        : "Could not delete account, try again.";
      toast({
        title: "Failed to delete account",
        description: errorMessage,
        variant: "destructive",
        duration: 4000,
      });
    }
    setReauthLoading(false);
    setModal({ isOpen: false, type: "", data: null });
  };

  // --- Place this inside your main return JSX, wherever you render modals ---
  // {renderDeleteAccountModal()}
  // ...existing code...
  // Pleasant, theme‑tinted three‑stop gradients (not exact theme colors, but harmonious)
  const getThemeGradient = (theme: ColorTheme) => {
    switch (theme) {
      case "rose":
        // Softer rose blend that avoids harsh magenta clash
        return "from-rose-500 via-rose-400 to-pink-400";
      case "green":
        // Fresh emerald/teal blend
        return "from-emerald-500 via-teal-500 to-green-600";
      case "orange":
        // Sunset amber/orange/rose blend
        return "from-amber-500 via-orange-500 to-rose-500";
      case "blue":
      default:
        // Cool sky/indigo/violet blend
        return "from-sky-500 via-indigo-500 to-violet-600";
    }
  };

  // Robust fetch helper: parse JSON if possible, else return text
  async function parseResponse(res: Response) {
    const text = await res.text();
    try {
      return { data: JSON.parse(text), raw: text };
    } catch {
      return { data: null as any, raw: text };
    }
  }

  async function generateVideo(prompt: string, chatIdOverride?: string | number | null) {
    // if already busy, treat as cancel
    if (busy && videoAbortRef.current) {
      videoAbortRef.current.abort();
      if (currentVideoJobId.current) {
        fetch(apiUrl(`/jobs/cancel?jobId=${encodeURIComponent(currentVideoJobId.current)}`), {
          method: "POST",
        }).catch(() => {});
      }
      return;
    }

    // Use the provided chat ID or fall back to activeChatId
    let currentChatId = chatIdOverride || activeChatId;
    if (currentChatId == null) {
      setApiError("No active chat selected.");
      return;
    }
    // Ensure activeChatId is set
    if (currentChatId && currentChatId !== activeChatId) {
      setActiveChatId(currentChatId);
    }
    // Store the chat ID we'll use for this generation
    const chatIdForGeneration = typeof currentChatId === 'string' ? currentChatId : String(currentChatId);

    setBusy(true);
    setApiError(null);
    setWidgetHtml(null);
    setVideoUrl(null);
    setSrtText(null);
  setSubtitleLang(undefined);
    // start visual progress ramp-up
    setVideoProgress(5);
    if (videoProgressTimer.current) window.clearInterval(videoProgressTimer.current);
    // Smooth ramp up to 60%, then wait until completion
    videoProgressTimer.current = window.setInterval(() => {
      setVideoProgress((p) => (p < 60 ? Math.min(p + 2, 60) : 60));
    }, 700);

  let aborted = false;
  try {
      // Defensive defaults: ensure keys object always exists
      const safe: ApiKeys = {
        claude: apiKeys?.claude || "",
        gemini: apiKeys?.gemini || "",
        provider: apiKeys?.provider || "",
        model: apiKeys?.model || "",
      };

      // assign a client job id so backend can cancel the right process
      const jobId = makeJobId();
      currentVideoJobId.current = jobId;
      const sessionId = ensureChatSessionId();
      const body = {
        prompt,
        keys: { claude: safe.claude, gemini: safe.gemini },
        provider: safe.provider || undefined, // "" -> undefined
        model: safe.model || undefined,
        jobId,
        sessionId,
      };

      console.debug("POST /generate", body);

      const controller = new AbortController();
      videoAbortRef.current = controller;
      const res = await apiFetch("/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, chatId: chatIdForGeneration }),
        signal: controller.signal,
      });

      const { data, raw } = await parseResponse(res);

      if (res.ok && data?.status === "ok") {
        // Show toast when initial try failed and first retry starts (tries === 1)
        if (data.tries === 1) {
          toast({
            title: "This may take a while.",
            duration: 5000
          });
        }

        // Use signed URL if available, otherwise use regular URL
        const videoUrl = toPlayableMediaUrl(data.signed_video_url || data.video_url) || "";
        setVideoUrl(videoUrl);
        setCurrentMediaMeta({ artifactId: data.artifact_id, gcsPath: data.gcs_path, type: 'video' });
        setSubtitleLang((data.lang as string) || undefined);

        // Debug subtitle URL
        console.log("Video generation response:", {
          videoUrl,
          signed_subtitle_url: data.signed_subtitle_url,
          video_url: data.video_url,
          scene_code_present: !!data.scene_code,
          scene_code_length: data.scene_code?.length || 0,
        });

        // Create media attachment for persistent access
        const mediaAttachment: import('@/types').MediaAttachment = {
          type: 'video',
          url: videoUrl,
          subtitleUrl: toPlayableMediaUrl(data.signed_subtitle_url),
          title: `Video: ${prompt.slice(0, 50)}...`,
          artifactId: data.artifact_id,
          gcsPath: data.gcs_path,
          sceneCode: data.scene_code,  // Store scene code for video editing
        };

        // Use the same chat ID we started with to ensure message goes to correct chat
        await processAndAddMessage("✅ Video generated.", false, mediaAttachment, chatIdForGeneration);

        // Captions for video: attempt fetch using helper
        // Clear old captions first
        setVttUrl(null);
        setSrtText(null);
        void fetchCaptions(videoUrl, data.signed_subtitle_url);
      } else {
        // Keep the UI clean: show a friendly message only
        const msg =
          (data && typeof data === "object" && "message" in data && (data as any).message) ||
          "Video generation failed.";
        const debugDetail =
          (data && typeof data === "object" && "debug_detail" in data && String((data as any).debug_detail || "").trim()) ||
          "";
        setApiError(msg);
        await processAndAddMessage("❌ Video generation failed.", false, undefined, chatIdForGeneration);
        if (debugDetail) {
          toast({
            title: "Render detail",
            description: debugDetail.slice(0, 220),
            duration: 7000,
          });
        }

        console.debug("generate() error payload:", data);
      }
    } catch (err: any) {
      if (err?.name === "AbortError") {
        // canceled by user
        setApiError(null);
        await processAndAddMessage("⏹️ Canceled video generation.", false, undefined, chatIdForGeneration);
        aborted = true;
      } else {
        const networkMsg = err?.message && /Failed to fetch|NetworkError|TypeError/i.test(err.message)
          ? "We couldn't reach the server. Check your connection and try again."
          : (err?.message || "Request failed");
        setApiError(networkMsg);
        await processAndAddMessage("❌ Network error.", false, undefined, chatIdForGeneration);
      }
    } finally {
      setBusy(false);
      // finalize progress
      if (videoProgressTimer.current) window.clearInterval(videoProgressTimer.current);
      // if canceled, reset to 0; else complete to 100
      setVideoProgress(aborted ? 0 : 100);
      videoAbortRef.current = null;
      currentVideoJobId.current = null;
    }
  }

  // Handle quiz generation directly from media (video or podcast)
  async function handleQuizMediaDirect(msg: any) {
    if (!msg.media?.subtitleUrl) {
      const mediaType = msg.media?.type === 'audio' ? 'podcast' : 'video';
      toast({ title: "No captions", description: `This ${mediaType} needs captions. Regenerate it to add captions.`, duration: 4000 });
      return;
    }

    if (!ensureLlmKey("quiz")) return;

    stopPlayback();
    setQuizLoading(true);
    setApiError(null);

    const safe: ApiKeys = {
      claude: apiKeys?.claude || "",
      gemini: apiKeys?.gemini || "",
      provider: apiKeys?.provider || "",
      model: apiKeys?.model || "",
    };

    let persistedId: string | undefined;

    try {
      // Get media filename/title for the user prompt
      const mediaTitle = msg.media?.title || (msg.media?.type === 'audio' ? 'podcast' : 'video');
      const userPrompt = `❓ Quiz from ${mediaTitle}`;

      // Ensure we have a persisted chat
      persistedId = await ensurePersistedActiveChat(userPrompt);
      const finalChatId = persistedId || activeChatId;
      if (!finalChatId) {
        toast({ title: "Unable to start chat", description: "Please sign in and try again.", duration: 4000 });
        return;
      }
      setActiveChatId(finalChatId);

      // Add user message showing what quiz is being generated
      await processAndAddMessage(userPrompt, true, undefined, persistedId);

      const videoAbort = new AbortController();
      quizAbortRef.current = videoAbort;

      // Extract transcript from VTT captions (stored in GCS bucket)
      let vttUrl = msg.media.subtitleUrl;

      // Try to extract transcript; in cloud mode refresh expired signed URL if needed.
      let transcript = '';
      try {
        transcript = await extractTranscriptFromVtt(vttUrl);
      } catch (err: any) {
        // If fetch failed with 400/403 (expired signed URL), try to refresh in cloud mode.
        if (!desktopLocal && err.message && (err.message.includes('400') || err.message.includes('403'))) {
          console.log('VTT URL expired, attempting to refresh...');
          try {
            const refreshed = await apiRefreshArtifact({
              artifactId: msg.media.artifactId,
              gcsPath: msg.media.gcsPath,
              subtitle: true
            });
            if (refreshed?.signed_subtitle_url) {
              vttUrl = refreshed.signed_subtitle_url;
              transcript = await extractTranscriptFromVtt(vttUrl);
              console.log('Successfully refreshed VTT URL and extracted transcript');
            } else {
              throw new Error('Could not refresh expired caption URL');
            }
          } catch (refreshErr) {
            console.error('Failed to refresh VTT URL:', refreshErr);
            throw new Error('Caption URL has expired. Please refresh the page and try again.');
          }
        } else {
          // For podcasts, try fetching script from GCS as fallback
          if (!desktopLocal && msg.media.type === 'audio') {
            if (msg.media.scriptGcsPath || msg.media.artifactId) {
              console.log('Attempting to fetch podcast script from GCS...');
              try {
                const refreshed = await apiRefreshArtifact({
                  artifactId: msg.media.artifactId,
                  gcsPath: msg.media.scriptGcsPath || msg.media.gcsPath?.replace(/\.mp3$/, '_script.txt'),
                  subtitle: false
                });
                if (refreshed?.signed_video_url) {
                  const scriptRes = await fetch(refreshed.signed_video_url);
                  if (scriptRes.ok) {
                    transcript = await scriptRes.text();
                    console.log('Successfully fetched podcast script from GCS');
                  } else {
                    throw new Error(`Failed to fetch script: ${scriptRes.status}`);
                  }
                } else {
                  throw new Error('Could not get signed URL for script');
                }
              } catch (scriptErr) {
                console.error('Failed to fetch podcast script from GCS:', scriptErr);
                throw new Error('No captions or script available for this podcast. Please regenerate it.');
              }
            } else {
              throw new Error('No captions or script available for this podcast.');
            }
          } else {
            throw err;
          }
        }
      }

      const response = await apiQuiz({
        transcript,
        sceneCode: msg.media.sceneCode || "",
        provider: safe.provider || undefined,
        model: safe.model || undefined,
        provider_keys: { claude: safe.claude, gemini: safe.gemini },
      }, videoAbort.signal);

      // Store quiz data like embedded quiz for interactive UI
      const quizChatId = persistedId || activeChatId;
      if (quizChatId && response.quiz?.questions?.length) {
        const quizTitle = (response.quiz?.title as string) || 'Media Quiz';
        const quizMsgId = await processAndAddMessage('', false, undefined, String(quizChatId), {
          quizAnchor: true,
          quizTitle,
          quizData: response.quiz
        });

        if (quizMsgId) {
          // Initialize runtime for this quiz
          setQuizzesByChat(prev => ({
            ...prev,
            [String(quizChatId)]: {
              ...(prev[String(quizChatId)] || {}),
              [quizMsgId]: { data: response.quiz, index: 0, answers: [], score: null, selected: null, revealed: false }
            }
          }));
        }
      } else {
        await processAndAddMessage('❌ Quiz generation failed.', false, undefined, persistedId);
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setApiError(err.message);
        toast({ title: "Quiz generation failed", description: err.message, duration: 4000 });
        await processAndAddMessage(`❌ Quiz generation failed: ${err.message}`, false, undefined, persistedId);
      } else {
        await processAndAddMessage('⏹️ Canceled quiz generation.', false, undefined, persistedId);
      }
    } finally {
      setQuizLoading(false);
      quizAbortRef.current = null;
    }
  }

  // Handle video editing in edit mode
  async function handleEditVideo() {
    if (!isEditMode || !quotedMessage?.media?.sceneCode) {
      toast({ title: "No video to edit", description: "Please select a video to edit first.", duration: 4000 });
      return;
    }

    const editInstructions = query.trim();
    if (!editInstructions) {
      toast({ title: "Enter edit instructions", description: "Please describe what changes you want to make.", duration: 4000 });
      return;
    }

    if (!ensureLlmKey("video")) return;

    // Cancel toggle if already busy
    if (busy && videoAbortRef.current) {
      videoAbortRef.current.abort();
      return;
    }

    stopPlayback();
    setBusy(true);
    setApiError(null);
    setWidgetHtml(null);
    setVideoUrl(null);
    setSrtText(null);
    setSubtitleLang(undefined);

    // Start progress
    setVideoProgress(5);
    if (videoProgressTimer.current) window.clearInterval(videoProgressTimer.current);
    videoProgressTimer.current = window.setInterval(() => {
      setVideoProgress((p) => (p < 60 ? Math.min(p + 2, 60) : 60));
    }, 700);

    let aborted = false;
    const chatIdForGeneration = typeof activeChatId === 'string' ? activeChatId : String(activeChatId);

    try {
      // Add user message showing the edit request
      await processAndAddMessage(`✏️ Edit: ${editInstructions}`, true, undefined, chatIdForGeneration);
      setQuery("");

      const safe: ApiKeys = {
        claude: apiKeys?.claude || "",
        gemini: apiKeys?.gemini || "",
        provider: apiKeys?.provider || "",
        model: apiKeys?.model || "",
      };

      const jobId = makeJobId();
      currentVideoJobId.current = jobId;
      const sessionId = ensureChatSessionId();

      const body = {
        original_code: quotedMessage.media.sceneCode,
        edit_instructions: editInstructions,
        keys: { claude: safe.claude, gemini: safe.gemini },
        provider: safe.provider || undefined,
        model: safe.model || undefined,
        jobId,
        sessionId,
        chatId: chatIdForGeneration,
      };

      const controller = new AbortController();
      videoAbortRef.current = controller;

      const res = await apiFetch("/edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      const { data } = await parseResponse(res);

      if (res.ok && data?.status === "ok" && data?.video_url) {
        const videoUrl = toPlayableMediaUrl(data.signed_video_url || data.video_url) || "";
        setVideoUrl(videoUrl);
        setCurrentMediaMeta({ artifactId: data.artifact_id, gcsPath: data.gcs_path, type: 'video' });
        setSubtitleLang((data.lang as string) || undefined);

        const mediaAttachment: import('@/types').MediaAttachment = {
          type: 'video',
          url: videoUrl,
          subtitleUrl: toPlayableMediaUrl(data.signed_subtitle_url),
          title: `Edited Video: ${editInstructions.slice(0, 30)}...`,
          artifactId: data.artifact_id,
          gcsPath: data.gcs_path,
          sceneCode: data.scene_code,
        };

        await processAndAddMessage("✅ Video edited successfully.", false, mediaAttachment, chatIdForGeneration);

        setVttUrl(null);
        setSrtText(null);
        void fetchCaptions(videoUrl, data.signed_subtitle_url);

        // Exit edit mode
        setIsEditMode(false);
        setIsQuizMode(false);
        setQuotedMessage(null);
      } else {
        const msg = (data?.message) || "Video editing failed.";
        setApiError(msg);
        await processAndAddMessage(`❌ Video editing failed: ${msg}`, false, undefined, chatIdForGeneration);
      }
    } catch (err: any) {
      console.error("Video edit error:", err);
      if (err?.name === "AbortError") {
        setApiError(null);
        await processAndAddMessage("⏹️ Canceled video editing.", false, undefined, chatIdForGeneration);
        aborted = true;
      } else {
        const networkMsg = err?.message && /Failed to fetch|NetworkError|TypeError/i.test(err.message)
          ? "We couldn't reach the server. Check your connection and try again."
          : (err?.message || "Request failed");
        setApiError(networkMsg);
        await processAndAddMessage(`❌ Error: ${networkMsg}`, false, undefined, chatIdForGeneration);
      }
    } finally {
      setBusy(false);
      if (videoProgressTimer.current) window.clearInterval(videoProgressTimer.current);
      setVideoProgress(aborted ? 0 : 100);
      videoAbortRef.current = null;
      currentVideoJobId.current = null;
    }
  }

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [query]);

  useEffect(() => {
    // Scroll instantly when switching chats to avoid visible jump; smooth when new message in same chat
    const chatJustSwitched = previousActiveChatIdRef.current !== activeChatId;
    previousActiveChatIdRef.current = activeChatId;
    chatEndRef.current?.scrollIntoView({ behavior: chatJustSwitched ? "instant" : "smooth" });
  }, [(activeChat as Chat).messages, activeChatId]);

  // Track scroll distance from bottom to toggle Jump to latest button
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const handle = () => {
      const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowJumpLatest(distance > 140); // show if more than 140px away from bottom
    };
    el.addEventListener('scroll', handle, { passive: true });
    handle();
    return () => el.removeEventListener('scroll', handle);
  }, [activeChatId]);

  // Convert SRT (when fetched) to VTT blob URL; if vttUrl already points to remote .vtt leave it
  useEffect(() => {
    if (vttUrl) {
      // If vttUrl is a blob (object URL) we regenerate; if it's remote .vtt keep
      const isBlob = /^blob:/.test(vttUrl);
      if (isBlob) {
        URL.revokeObjectURL(vttUrl);
        setVttUrl(null);
      } else {
        return; // remote .vtt already selected
      }
    }
    if (!srtText) return;
    try {
      const vtt = srtToVtt(srtText);
      const blob = new Blob([vtt], { type: 'text/vtt' });
      const url = URL.createObjectURL(blob);
      setVttUrl(url);
      // default to 'en' when unknown
      if (!subtitleLang) setSubtitleLang('en');
      // Populate cache for current media key
      const key = currentCaptionKeyRef.current;
      if (key) {
        // Revoke any previous blob cached for this key
        const prev = captionsCacheRef.current[key];
        if (prev?.isBlob && prev.vttUrl && prev.vttUrl !== url) {
          try { URL.revokeObjectURL(prev.vttUrl); } catch {}
        }
        captionsCacheRef.current[key] = { vttUrl: url, lang: subtitleLang || 'en', isBlob: true };
      }
    } catch {}
  }, [srtText]);

  // When switching media, immediately clear captions and load matching ones
  useEffect(() => {
    const key = (currentMediaMeta?.artifactId || videoUrl) || null;
    const prevKey = currentCaptionKeyRef.current;

    // Always clear captions first when media changes to prevent old captions showing
    if (prevKey !== key) {
      // If previous was a generated blob and we're leaving it, revoke it if not reused in cache elsewhere
      if (prevKey && /^blob:/.test(vttUrl || '')) {
        try { URL.revokeObjectURL(vttUrl!); } catch {}
      }
      // Immediately clear old captions
      setVttUrl(null);
      setSrtText(null);
      setActiveScript(null);

      currentCaptionKeyRef.current = key;

      if (key) {
        const cached = captionsCacheRef.current[key];
        if (cached?.vttUrl) {
          // Use cached captions immediately
          setVttUrl(cached.vttUrl);
          if (cached.lang) setSubtitleLang(cached.lang);
        }
        // If no cache, captions will be loaded by fetchCaptions call
      }
    }
  }, [videoUrl, currentMediaMeta?.artifactId, vttUrl]);

  // After setting VTT on the video, ensure cues are actually loaded; if not, force a one-time reload
  useEffect(() => {
    const vid = videoRef.current as HTMLVideoElement | HTMLAudioElement | null;
    if (!vid || !vttUrl || currentMediaMeta?.type !== 'video') return;
    let triedReload = false;
    const checkCues = () => {
      try {
        const v = vid as HTMLVideoElement;
        const track = v.textTracks && v.textTracks[0];
        const cuesLen = track && track.cues ? track.cues.length : 0;
        if (cuesLen && cuesLen > 0) {
          return true;
        }
      } catch {}
      return false;
    };
    const t1 = setTimeout(() => {
      if (!checkCues() && !triedReload) {
        triedReload = true;
        try { (vid as HTMLVideoElement).load(); } catch {}
      }
    }, 600);
    const t2 = setTimeout(() => {
      checkCues();
    }, 1400);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [vttUrl, videoUrl, currentMediaMeta?.type]);

  // Attempt automatic refresh of an expired signed video URL when playback fails
  useEffect(() => {
    const vid = videoRef.current;
    if (!vid) return;
    const onError = async () => {
      // In desktop-local mode, media URLs are local static files and do not use signed URL refresh.
      if (desktopLocal) return;
      // If we have meta info, try refresh
      if (!currentMediaMeta) return;
      try {
        const refreshed = await apiRefreshArtifact({ artifactId: currentMediaMeta.artifactId, gcsPath: currentMediaMeta.gcsPath, subtitle: true });
        if (refreshed?.signed_video_url) {
          setVideoUrl(refreshed.signed_video_url);
        }
        if (refreshed?.signed_subtitle_url) {
          try {
            const r = await fetch(refreshed.signed_subtitle_url);
            if (r.ok) {
              const srt = await r.text();
              setSrtText(srt);
              setActiveScript(srt);
            }
          } catch {}
        }
        if (!refreshed?.signed_video_url && !refreshed?.signed_subtitle_url) {
          try { toast({ title: 'Couldn’t refresh media links', description: 'Try again or re‑generate the media.', duration: 6000 }); } catch {}
        }
      } catch (e: any) {
        try { toast({ title: 'Couldn’t refresh media links', description: e?.message || 'Try again or re‑generate the media.', duration: 6000 }); } catch {}
      }
    };
    vid.addEventListener('error', onError);
    return () => vid.removeEventListener('error', onError);
  }, [currentMediaMeta, videoUrl]);

  // Keep caption display state synchronized (video or audio)
  useEffect(() => {
    const el = videoRef.current as HTMLVideoElement | HTMLAudioElement | null;
    if (!el) return;
    try {
      const tracks = (el as any).textTracks as TextTrackList | undefined;
      if (tracks && tracks.length > 0) {
        tracks[0].mode = isCaptionsOn ? 'showing' : 'hidden';
      }
    } catch {}
  }, [isCaptionsOn, vttUrl, videoUrl]);

  // Load first page of messages for persisted chat
  useEffect(() => {
  async function loadMessagesPage() {
      // Don't load from server for local/draft chats
      if (typeof activeChatId !== 'string' || String(activeChatId).startsWith('local-') || String(activeChatId).startsWith('draft-')) {
        const lastBotMessage = [...(activeChat as Chat).messages].reverse().find((m) => m.role === 'bot');
        setActiveScript(lastBotMessage ? lastBotMessage.content : null);
        setIsPlaying(false);
        setProgress([0]);
        return;
      }

      // Wait 3s after sending message before fetching from server (cooldown)
      const timeSinceLastMessage = Date.now() - lastMessageSentTime.current;
      if (timeSinceLastMessage < 3000) {
        // Message was sent less than 3 seconds ago - skip server fetch to preserve local message
        // Schedule a retry after the cooldown period to sync with server
        const capturedChatId = activeChatId;
        const retryDelay = 3000 - timeSinceLastMessage + 500; // Add 500ms buffer
        setTimeout(() => {
          // Only retry if chat hasn't changed
          if (capturedChatId === activeChatId) {
            void loadMessagesPage();
          }
        }, retryDelay);
        return;
      }
      try {
        // Model is stored in chat data, not needed in URL
        const page = await apiListMessages(String(activeChatId), undefined, { limit: PAGE_SIZE });
        const msgs = page?.messages || [];
        const mapped = (msgs || []).map((m: any) => {
          const media = m.media ? {
            type: (m.media.type === 'podcast' ? 'audio' : m.media.type) as 'audio'|'video'|'widget', // BUG FIX
            url: toPlayableMediaUrl(m.media.url as string | undefined),
            subtitleUrl: toPlayableMediaUrl(m.media.subtitleUrl as string | undefined),
            artifactId: m.media.artifactId as string | undefined,
            gcsPath: m.media.gcsPath as string | undefined,
            title: m.media.title as string | undefined,
            sceneCode: m.media.sceneCode as string | undefined,  // Include sceneCode for video editing
            widgetCode: m.media.widgetCode as string | undefined, // BUG FIX: restore widget HTML on reload
          } : undefined;
          // Ensure all messages have createdAt for proper ordering
          const createdAt = typeof m.createdAt === 'number' ? m.createdAt : (m.timestamp || Date.now());
          const messageId = m.message_id as string | undefined;
          // Preserve quiz data and other extras from backend
          const extras: any = {};
          if (m.quizAnchor || m.quizTitle || m.quizData) {
            extras.quizAnchor = m.quizAnchor || false;
            extras.quizTitle = m.quizTitle;
            extras.quizData = m.quizData;
          }
          return { role: m.role === 'assistant' ? 'bot' : 'user', content: m.content, media, createdAt, messageId, ...extras } as const;
        });
  const cacheKey = String(activeChatId);
  // messagesCache is session-only; chats.messages is empty after refresh (not persisted)
  const cachedMessages = messagesCache.current[cacheKey];
  const chatMessages = chats.find(c => c.id === activeChatId)?.messages || [];
  const existing = (cachedMessages && cachedMessages.length > 0) ? cachedMessages : chatMessages;
        // Merge: keep any local messages whose messageId not yet in remote or that lack a messageId
        const remoteIds = new Set(mapped.map(m => m.messageId).filter(Boolean));
        // Filter out local messages that have been persisted (their messageId is now in remote)
        // But keep local messages with temporary IDs (local-*) that haven't been matched yet
        const pendingLocals = existing.filter(em => {
          const emId = (em as any).messageId;
          // Keep if no messageId or if messageId not in remote set
          if (!emId) return true;
          // If it's a temporary local ID, check if there's a matching server message by content ONLY
          if (String(emId).startsWith('local-')) {
            const emNormContent = (em.content || '').trim().toLowerCase().replace(/\s+/g, ' ');
            const emQuizKey = (em as any).quizAnchor ? (em as any).quizTitle || 'untitled' : '';
            // Check if there's a server message with same role and content (ignore timestamp)
            const hasMatchingServer = mapped.some(rm => {
              const rmNormContent = (rm.content || '').trim().toLowerCase().replace(/\s+/g, ' ');
              const rmQuizKey = (rm as any).quizAnchor ? (rm as any).quizTitle || 'untitled' : '';
              return rm.role === em.role &&
                     rmNormContent === emNormContent &&
                     rm.media?.artifactId === em.media?.artifactId &&
                     rmQuizKey === emQuizKey;
            });
            // Drop local message if matching server message exists
            return !hasMatchingServer;
          }
          // For non-local IDs, keep only if not in remote set
          return !remoteIds.has(emId);
        });
        // Deduplicate by content+role, prefer server messages
        const prelim = [...mapped, ...pendingLocals];
        const byKey: Record<string, any> = {};
        for (const m of prelim) {
          const messageId = (m as any).messageId || '';
          // Include quiz title in key to distinguish different quizzes
          const quizKey = (m as any).quizAnchor ? `|quiz:${(m as any).quizTitle || 'untitled'}` : '';
          const normalizedContent = (m.content || '').trim().toLowerCase().replace(/\s+/g, ' ');
          // Use normalized content+role+media+quiz as key (ignore timestamp variations)
          const contentKey = `${m.role}|${normalizedContent}|${m.media?.artifactId||''}${quizKey}`;
          const existingMsg = byKey[contentKey];

          if (!existingMsg) {
            byKey[contentKey] = m;
          } else {
            // If duplicate exists, always prefer server messages (non-local IDs)
            const isServerId = messageId && !String(messageId).startsWith('local-');
            const existingIsServerId = (existingMsg as any).messageId && !String((existingMsg as any).messageId).startsWith('local-');

            if (isServerId && !existingIsServerId) {
              // Replace local with server message, but preserve local timestamp to maintain order
              byKey[contentKey] = {
                ...m,
                createdAt: existingMsg.createdAt || m.createdAt,
                quizData: m.quizData || existingMsg.quizData,
                quizAnchor: m.quizAnchor ?? existingMsg.quizAnchor,
                quizTitle: m.quizTitle || existingMsg.quizTitle,
                media: m.media || existingMsg.media
              };
            } else if (!isServerId && !existingIsServerId) {
              // Both are local, keep the one with newer timestamp
              const tNew = typeof (m as any).createdAt === 'number' ? (m as any).createdAt : 0;
              const tOld = typeof (existingMsg as any).createdAt === 'number' ? (existingMsg as any).createdAt : 0;
              if (tNew > tOld) {
                byKey[contentKey] = m;
              }
            }
            // Otherwise keep existing (already a server message)
          }
        }
        // Ensure all messages have createdAt for proper chronological ordering (prompt-response-prompt-response)
        let finalMsgsWithTimestamps = dedupeMessagesOrdered(
          Object.values(byKey).map((msg: any) => {
            if (!msg.createdAt || typeof msg.createdAt !== 'number') {
              return { ...msg, createdAt: Date.now() };
            }
            return msg;
          })
        );

        let finalMsgsSorted = finalMsgsWithTimestamps.sort((a: any, b: any) => {
          const ta = typeof a.createdAt === 'number' ? a.createdAt : 0;
          const tb = typeof b.createdAt === 'number' ? b.createdAt : 0;
          return ta - tb; // Ascending order: oldest first (like ChatGPT)
        });

        // Restore quiz data from messages that have quizAnchor/quizData
        // Do this before updating chats so quiz state is ready
        finalMsgsSorted.forEach((msg: any) => {
          if (msg.quizAnchor && msg.quizData && typeof activeChatId === 'string' && msg.messageId) {
            setQuizzesByChat(prev => {
              const chatQuizzes = prev[String(activeChatId)] || {};
              // Always restore quiz data even if it exists (in case data changed)
              return {
                ...prev,
                [String(activeChatId)]: {
                  ...chatQuizzes,
                  [msg.messageId]: {
                    data: msg.quizData,
                    index: chatQuizzes[msg.messageId]?.index || 0, // Preserve progress if exists
                    answers: chatQuizzes[msg.messageId]?.answers || [],
                    score: chatQuizzes[msg.messageId]?.score ?? null,
                    selected: chatQuizzes[msg.messageId]?.selected ?? null,
                    revealed: chatQuizzes[msg.messageId]?.revealed || false
                  }
                }
              };
            });
          }
        });

        // Preserve unpersisted local messages
        const hasLocalUnpersisted = existing.some((m: any) => {
          const msgId = m.messageId;
          return !msgId || String(msgId).startsWith('local-') || !remoteIds.has(msgId);
        });

        // If we have local unpersisted messages, ensure they're included in finalMsgsSorted
        if (hasLocalUnpersisted && finalMsgsSorted.length > 0) {
          // Double-check all local messages are included
          const finalIds = new Set(finalMsgsSorted.map((m: any) => m.messageId).filter(Boolean));
          const missingLocals = existing.filter((em: any) => {
            const emId = em.messageId;
            return emId && !finalIds.has(emId) && String(emId).startsWith('local-');
          });
          if (missingLocals.length > 0) {
            // Add missing local messages back
            finalMsgsSorted.push(...missingLocals);
            finalMsgsSorted = dedupeMessagesOrdered(finalMsgsSorted);
            // Re-sort by createdAt
            finalMsgsSorted.sort((a: any, b: any) => {
              const ta = typeof a.createdAt === 'number' ? a.createdAt : 0;
              const tb = typeof b.createdAt === 'number' ? b.createdAt : 0;
              return ta - tb;
            });
          }
        }

        // Guard: if remote returned empty and we already had local messages, don't clobber them
        if (finalMsgsSorted.length === 0 && Array.isArray(existing) && existing.length > 0) {
          // Preserve existing; just update cache and cursors
          messagesCache.current[cacheKey] = existing as any;
        } else {
          // Merge server messages with local messages
          const updatedList = chats.map(c => {
            if (c.id === activeChatId) {
              // Prefer finalMsgsSorted if available, otherwise use existing
              let messagesToUse: any[];
              if (finalMsgsSorted.length > 0) {
                messagesToUse = finalMsgsSorted;
              } else if (existing.length > 0) {
                // Keep existing messages if server returned empty (might be a sync issue)
                messagesToUse = existing;
              } else {
                // Last resort: use chat messages
                messagesToUse = c.messages || [];
              }
              return { ...c, messages: messagesToUse as any } as Chat;
            }
            return c;
          });
          setChats(updatedList);
          // Update cache with deduplicated messages (append-only)
          const currentCacheSize = (messagesCache.current[cacheKey] || []).length;
          if (finalMsgsSorted.length >= currentCacheSize) {
            messagesCache.current[cacheKey] = finalMsgsSorted as any;
          }

        }
        const first = (msgs && msgs[0]) || null;
        const before = first && typeof first.createdAt === 'number' ? first.createdAt : undefined;
        setCursorByChat(prev => ({ ...prev, [cacheKey]: before }));
  setHasMoreByChat(prev => ({ ...prev, [cacheKey]: !!page?.has_more }));
        const lastBotMessage = [...(messagesCache.current[cacheKey] || finalMsgsSorted)].reverse().find((m) => m.role === 'bot');
        setActiveScript(lastBotMessage ? lastBotMessage.content : null);
        setIsPlaying(false);
        setProgress([0]);

        // Scroll instantly to bottom after loading messages to avoid visible jump
        requestAnimationFrame(() => {
          const container = scrollContainerRef.current;
          if (container) container.scrollTop = container.scrollHeight;
        });
      } catch {
        // ignore load errors silently
      }
    }
    void loadMessagesPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChatId]);

  const loadOlderMessages = async () => {
    if (typeof activeChatId !== 'string') return;
    const key = String(activeChatId);
    const before = cursorByChat[key];
    try {
      // Model is stored in chat data, not needed in URL
      const page = await apiListMessages(key, undefined, { limit: PAGE_SIZE, before });
      const older = page?.messages || [];
      const mapped = (older || []).map((m: any) => {
        const media = m.media ? {
          type: (m.media.type === 'podcast' ? 'audio' : m.media.type) as 'audio'|'video'|'widget', // BUG FIX
          url: toPlayableMediaUrl(m.media.url as string | undefined),
          subtitleUrl: toPlayableMediaUrl(m.media.subtitleUrl as string | undefined),
          artifactId: m.media.artifactId as string | undefined,
          gcsPath: m.media.gcsPath as string | undefined,
          title: m.media.title as string | undefined,
          sceneCode: m.media.sceneCode as string | undefined,  // Include sceneCode for video editing
          widgetCode: m.media.widgetCode as string | undefined, // Restore widget HTML on reload
        } : undefined;
        // Ensure all messages have createdAt for proper ordering
        const createdAt = typeof m.createdAt === 'number' ? m.createdAt : (m.timestamp || Date.now());
        const messageId = m.message_id as string | undefined;
        // Preserve quiz data and other extras from backend
        const extras: any = {};
        if (m.quizAnchor || m.quizTitle || m.quizData) {
          extras.quizAnchor = m.quizAnchor || false;
          extras.quizTitle = m.quizTitle;
          extras.quizData = m.quizData;
        }
        return { role: m.role === 'assistant' ? 'bot' : 'user', content: m.content, media, createdAt, messageId, ...extras } as const;
      });
      if (!mapped.length) {
        setHasMoreByChat(prev => ({ ...prev, [key]: false }));
        return;
      }
      // Use cache as source instead of chats array to ensure we have latest messages
      const current = messagesCache.current[key] || chats.find(c => c.id === activeChatId)?.messages || [];
      const remoteIds = new Set(mapped.map(m => m.messageId).filter(Boolean));
      // Filter out local messages that have been persisted (their messageId is now in remote)
      // But keep local messages with temporary IDs (local-*) that haven't been matched yet
      const pendingLocals = current.filter(em => {
        const emId = (em as any).messageId;
        // Keep if no messageId or if messageId not in remote set
        if (!emId) return true;
        // If it's a temporary local ID, check if there's a matching server message by content ONLY
        if (String(emId).startsWith('local-')) {
          // Check if there's a server message with same role and content (ignore timestamp)
          const hasMatchingServer = mapped.some(rm =>
            rm.role === em.role &&
            rm.content?.trim() === em.content?.trim() &&
            rm.media?.artifactId === em.media?.artifactId
          );
          // Drop local message if matching server message exists
          return !hasMatchingServer;
        }
        // For non-local IDs, keep only if not in remote set
        return !remoteIds.has(emId);
      });
      // Deduplicate by content+role, prefer server messages
      const prelim = [...mapped as any, ...pendingLocals];
      const byKey: Record<string, any> = {};
      for (const m of prelim) {
        const messageId = (m as any).messageId || '';
        // Use content+role as key (ignore timestamp variations)
        const contentKey = `${m.role}|${m.content?.trim() || ''}|${(m as any).media?.artifactId||''}`;
        const existing = byKey[contentKey];

        if (!existing) {
          byKey[contentKey] = m;
        } else {
          // If duplicate exists, always prefer server messages (non-local IDs)
          const isServerId = messageId && !String(messageId).startsWith('local-');
          const existingIsServerId = (existing as any).messageId && !String((existing as any).messageId).startsWith('local-');

          if (isServerId && !existingIsServerId) {
            // Replace local with server message
            byKey[contentKey] = m;
          } else if (!isServerId && !existingIsServerId) {
            // Both are local, keep the one with newer timestamp
            const tNew = typeof (m as any).createdAt === 'number' ? (m as any).createdAt : 0;
            const tOld = typeof (existing as any).createdAt === 'number' ? (existing as any).createdAt : 0;
            if (tNew > tOld) {
              byKey[contentKey] = m;
            }
          }
          // Otherwise keep existing (already a server message)
        }
      }
      // Ensure all messages have createdAt for proper chronological ordering
      let combined = Object.values(byKey).map((msg: any) => {
        if (!msg.createdAt || typeof msg.createdAt !== 'number') {
          return { ...msg, createdAt: Date.now() };
        }
        return msg;
      }).sort((a: any, b: any) => {
        const ta = typeof a.createdAt === 'number' ? a.createdAt : 0;
        const tb = typeof b.createdAt === 'number' ? b.createdAt : 0;
        return ta - tb; // Ascending order: oldest first (like ChatGPT)
      });

        // Restore quiz data from older messages that have quizAnchor/quizData
        combined.forEach((msg: any) => {
          if (msg.quizAnchor && msg.quizData && typeof activeChatId === 'string' && msg.messageId) {
            setQuizzesByChat(prev => {
              const chatQuizzes = prev[String(activeChatId)] || {};
              // Always restore quiz data even if it exists (in case data changed)
              return {
                ...prev,
                [String(activeChatId)]: {
                  ...chatQuizzes,
                  [msg.messageId]: {
                    data: msg.quizData,
                    index: chatQuizzes[msg.messageId]?.index || 0, // Preserve progress if exists
                    answers: chatQuizzes[msg.messageId]?.answers || [],
                    score: chatQuizzes[msg.messageId]?.score ?? null,
                    selected: chatQuizzes[msg.messageId]?.selected ?? null,
                    revealed: chatQuizzes[msg.messageId]?.revealed || false
                  }
                }
              };
            });
          }
        });

      // Update chat with merged messages
      const updatedList = chats.map(c => c.id === activeChatId ? ({ ...c, messages: combined as any } as Chat) : c);
      setChats(updatedList);
      // Merge with existing cache instead of replacing
      const existingCache = messagesCache.current[key] || [];
      const byId = new Map();
      existingCache.forEach((m: any) => {
        if (m.messageId) byId.set(m.messageId, m);
      });
      combined.forEach((m: any) => {
        if (m.messageId) byId.set(m.messageId, m);
      });
      const finalMerged = Array.from(byId.values()).sort((a: any, b: any) => {
        const ta = typeof a.createdAt === 'number' ? a.createdAt : 0;
        const tb = typeof b.createdAt === 'number' ? b.createdAt : 0;
        return ta - tb;
      });
      messagesCache.current[key] = finalMerged as any;
      const first = mapped[0] as any;
      const newBefore = first && typeof first.createdAt === 'number' ? first.createdAt : before;
      setCursorByChat(prev => ({ ...prev, [key]: newBefore }));
      setHasMoreByChat(prev => ({ ...prev, [key]: !!page?.has_more }));
    } catch {}
  };

  // Synthetic progress only when no media is loaded; real media uses timeupdate
  useEffect(() => {
    if (videoUrl) return; // real media present
    let interval: NodeJS.Timeout | undefined;
    if (isPlaying && activeScript) {
      interval = setInterval(() => {
        setProgress((prev) => {
          const nextVal = prev[0] + playbackSpeed[0];
          if (nextVal >= 100) {
            setIsPlaying(false);
            return [100];
          }
          return [nextVal];
        });
      }, 500);
    } else if (!isPlaying && progress[0] === 100) {
      const t = setTimeout(() => setProgress([0]), 500);
      return () => clearTimeout(t);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [isPlaying, activeScript, playbackSpeed, videoUrl]);

  // Bind media element events for unified controls
  useEffect(() => {
    const vid = videoRef.current;
    if (!vid) return;
    const onLoadedMetadata = () => {
      const d = isFinite(vid.duration) ? vid.duration : 0;
      setMediaDuration(d);
      const t = vid.currentTime || 0;
      setProgress([d > 0 ? Math.min(100, Math.max(0, (t / d) * 100)) : 0]);
      // initialize from UI state so sliders work reliably
      try {
        const rate = Math.max(0.25, Math.min(2, playbackSpeed[0] ?? 1));
        vid.defaultPlaybackRate = rate;
        vid.playbackRate = rate;
        vid.volume = Math.max(0, Math.min(1, (volume[0] ?? 0) / 100));
        vid.muted = false;
        // Match YouTube behavior: preserve pitch when changing speed
        (vid as any).preservesPitch = true;
        (vid as any).webkitPreservesPitch = true;
      } catch {}
      if (currentMediaMeta?.type === 'video') {
        try {
          const tracks = (vid as HTMLVideoElement).textTracks;
          if (tracks && tracks.length > 0) {
            for (let i = 0; i < tracks.length; i++) {
              tracks[i].mode = isCaptionsOn ? 'showing' : 'hidden';
            }
          }
        } catch {}
      }
    };
    const onTimeUpdate = () => {
      const d = isFinite(vid.duration) ? vid.duration : 0;
      const t = vid.currentTime || 0;
      setMediaDuration(d);
      setProgress([d > 0 ? Math.min(100, Math.max(0, (t / d) * 100)) : 0]);
    };
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnded = () => setIsPlaying(false);
  const onRateChange = () => setPlaybackSpeed([vid.playbackRate || 1]);
  const onVolumeChange = () => setVolume([Math.round((vid.volume || 0) * 100)]);
  const onSeeking = () => onTimeUpdate();
  const onSeeked = () => onTimeUpdate();

    vid.addEventListener("loadedmetadata", onLoadedMetadata);
    vid.addEventListener("timeupdate", onTimeUpdate);
  vid.addEventListener("play", onPlay);
  vid.addEventListener("playing", onPlay);
    vid.addEventListener("pause", onPause);
    vid.addEventListener("ended", onEnded);
    vid.addEventListener("ratechange", onRateChange);
    vid.addEventListener("volumechange", onVolumeChange);
  vid.addEventListener("seeking", onSeeking);
  vid.addEventListener("seeked", onSeeked);
    return () => {
      vid.removeEventListener("loadedmetadata", onLoadedMetadata);
      vid.removeEventListener("timeupdate", onTimeUpdate);
  vid.removeEventListener("play", onPlay);
  vid.removeEventListener("playing", onPlay);
      vid.removeEventListener("pause", onPause);
      vid.removeEventListener("ended", onEnded);
      vid.removeEventListener("ratechange", onRateChange);
      vid.removeEventListener("volumechange", onVolumeChange);
      vid.removeEventListener("seeking", onSeeking);
      vid.removeEventListener("seeked", onSeeked);
    };
  }, [videoUrl, isCaptionsOn]);

  // Ensure playbackRate sticks whenever state changes or media swaps
  useEffect(() => {
    const vid = videoRef.current;
    if (!vid) return;
    const rate = Math.max(0.25, Math.min(2, playbackSpeed[0] ?? 1));
    try {
      vid.defaultPlaybackRate = rate;
      vid.playbackRate = rate;
      (vid as any).preservesPitch = true;
      (vid as any).webkitPreservesPitch = true;
    } catch {}
  }, [playbackSpeed, videoUrl]);

  // Ensure volume sticks whenever state changes or media swaps
  useEffect(() => {
    const vid = videoRef.current;
    if (!vid) return;
    const vol = Math.max(0, Math.min(1, (volume[0] ?? 0) / 100));
    try {
      vid.volume = vol;
      vid.muted = vol === 0 ? true : false;
    } catch {}
  }, [volume, videoUrl]);

  // Fullscreen handlers
  const toggleFullscreen = async () => {
    if (!videoContainerRef.current) return;
    try {
      if (!isFullscreen) {
        if (videoContainerRef.current.requestFullscreen) {
          await videoContainerRef.current.requestFullscreen();
        }
      } else {
        if (document.exitFullscreen) {
          await document.exitFullscreen();
        }
      }
    } catch (error) {
      console.error('Fullscreen error:', error);
    }
  };

  useEffect(() => {
    const handleFullscreenChange = () => {
      const fullEl = document.fullscreenElement;
      setIsFullscreen(!!fullEl);
      const vid = videoRef.current;
      if (vid) {
        const container = videoContainerRef.current;
        const containsVideo = !!fullEl && (fullEl === vid || fullEl === container || fullEl.contains(vid));
        vid.classList.toggle('fullscreen-active', containsVideo);
      }
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      const vid = videoRef.current;
      if (vid) vid.classList.remove('fullscreen-active');
    };
  }, []);

  // Download handler - downloads directly without opening new tab
  const handleDownload = async () => {
    if (!videoUrl) return;

    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10); // YYYY-MM-DD
    // const timeStr = now.toISOString().slice(11, 19).replace(/:/g, '-'); // HH-MM-SS
    const artifactId = currentMediaMeta?.artifactId ? `_${currentMediaMeta.artifactId}` : '';
    const fileName = currentMediaMeta?.type === 'video'
      ? `upcurved_video_${dateStr}${artifactId}.mp4`
      : `upcurved_podcast_${dateStr}${artifactId}.mp3`;

    try {
      const response = await fetch(videoUrl);
      if (!response.ok) {
        throw new Error('Failed to fetch video');
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = fileName;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
      toast({ title: 'Download started', description: 'File download initiated' });
    } catch (error) {
      console.error('Download failed:', error);
      toast({ title: 'Download failed', description: 'Could not download the file', variant: 'destructive' });
    }
  };

  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      const vid = videoRef.current;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        if (videoUrl && vid) {
          vid.currentTime = Math.min((vid.duration || Infinity), (vid.currentTime || 0) + 5);
        } else if (activeScript) {
          setProgress((prev) => [Math.min(prev[0] + 5, 100)]);
        }
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        if (videoUrl && vid) {
          vid.currentTime = Math.max(0, (vid.currentTime || 0) - 5);
        } else if (activeScript) {
          setProgress((prev) => [Math.max(prev[0] - 5, 0)]);
        }
      }
    };

    window.addEventListener("keydown", handleKeyPress);
    return () => window.removeEventListener("keydown", handleKeyPress);
  }, [activeScript, videoUrl]);

  // (Removed duplicate captions toggle effect to avoid thrash/reset)

  return (
    <div className="h-screen flex bg-background">
      <AlertDialog
        open={modal.isOpen && modal.type !== "deleteAccount"}
        onOpenChange={(open) => !open && setModal({ isOpen: false, type: "", data: null })}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {modal.type === "logout" ? "Confirm Logout" : "Delete Chat"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {modal.type === "logout"
                ? "Are you sure you want to log out?"
                : "Are you sure you want to delete this chat?"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={modal.type === "logout" ? confirmLogout : confirmDeleteChat}
            >
              Confirm
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

  <Sidebar
    user={user}
  chats={chats}
    activeChatId={activeChatId}
    setActiveChatId={(id) => {
      if (id === activeChatId) return;
      // If a generation is active, require confirmation before switching
      if (busy || podcastLoading || quizLoading || widgetLoading) {
        setPendingChatSwitch(id);
        setShowSwitchWarning(true);
        return;
      }
      // Reset edit mode when switching chats
      setIsEditMode(false);
      setIsQuizMode(false);
      setQuotedMessage(null);
      setWidgetHtml(null);
      setVideoUrl(null);
      setCurrentMediaMeta(null);
      setVttUrl(null);
      setSrtText(null);
      // Immediately update activeChatId - URL will sync via effect
      setActiveChatId(id);
      // Also update URL immediately to prevent race conditions and auto-refresh issues
      if (typeof id === 'string' && !id.startsWith('local-') && !id.startsWith('draft-')) {
        setSearchParams(prev => {
          const next = new URLSearchParams(prev);
          next.set('id', String(id));
          next.delete('model');
          return next;
        }, { replace: true });
      } else if (id == null) {
        // Only clear URL if explicitly setting to null and forceBlank is set
        const fb = sessionStorage.getItem('app.forceBlank') === '1';
        if (fb) {
          setSearchParams(prev => {
            const next = new URLSearchParams(prev);
            next.delete('id');
            next.delete('model');
            return next;
          }, { replace: true });
        }
      }
    }}
        handleNewChat={handleNewChat}
        setView={setView}
        onOpenSettings={() => {
          setSettingsOpen(true);
          const el = videoRef.current;
          try { if (el && !el.paused) el.pause(); } catch {}
        }}
        theme={theme}
        setTheme={setTheme}
        handleLogout={handleLogout}
        handleDeleteAccount={handleDeleteAccount}
        isSidebarCollapsed={isSidebarCollapsed}
        setIsSidebarCollapsed={setIsSidebarCollapsed}
        colorTheme={colorTheme}
        setColorTheme={setColorTheme}
        handleRenameChat={handleRenameChat}
        handleDeleteChat={handleDeleteChat}
        onToggleShare={handleToggleShare}
        desktopLocal={desktopLocal}
      />

      <div className="flex-1 flex">
        <div className="w-full md:w-1/2 border-r border-border flex flex-col h-screen">
          <div className="p-2 border-b border-border flex items-center md:hidden">
            <Button variant="ghost" size="icon">
              <Menu className="w-5 h-5" />
            </Button>
            <h2 className="text-lg font-semibold ml-2 truncate">
              {(activeChat as Chat).name || "Chat"}
            </h2>
          </div>

          <div ref={scrollContainerRef} className="flex-1 p-6 overflow-y-auto relative">
            <div className="space-y-6">
              {hasMoreByChat[String(activeChatId)] && (activeChat as Chat).messages.length > 0 && typeof activeChatId === 'string' && (
                <div className="flex justify-center">
                  <Button variant="secondary" size="sm" onClick={loadOlderMessages}>Load older messages</Button>
                </div>
              )}
              {(activeChat as Chat).messages.length === 0 && typeof window !== 'undefined' && sessionStorage.getItem('app.forceBlank') === '1' ? (
                <div className="flex flex-col items-center justify-center h-full text-center">
                  <div className="space-y-4">
                    <div className={`w-16 h-16 rounded-full bg-gradient-to-br ${getThemeGradient(colorTheme)} flex items-center justify-center mx-auto`}>
                      <MessageSquare className="w-8 h-8 text-white" />
                    </div>
                    <h2 className="text-2xl font-semibold">Hello, {user.name}</h2>
                    <p className="text-muted-foreground">How can I help you today?</p>
                    {/* Removed start-a-conversation banner per user request */}
                  </div>
                </div>
              ) : (
                (activeChat as Chat).messages.map((msg, index) => (
                  <div key={(msg as any).messageId || `${index}-${msg.role}-${(msg as any).createdAt || ''}`} className={`flex flex-col gap-2 ${msg.role === "user" ? "items-end" : "items-start"}`}>
                    {msg.role === "bot" && !(msg as any)?.quizAnchor && (
                      <div className="flex items-start gap-4 group relative">
                        <div className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center flex-shrink-0">
                          <Bot className="w-5 h-5 text-secondary-foreground" />
                        </div>
                        <div className={`rounded-lg p-4 max-w-lg bg-secondary text-secondary-foreground relative`}>
                          <div className="whitespace-pre-wrap">
                            {msg.content ? (
                              renderMessage(msg.content)
                            ) : null}
                          </div>
                          {/* Only show media if it has actual media */}
                          {msg.media && msg.media.url && (
                            <div className={`mt-3 ${busy ? 'opacity-50 pointer-events-none' : ''}`}>
                              <MediaPlayer
                                videoUrl={msg.media.type === 'video' ? msg.media.url : undefined}
                                audioUrl={msg.media.type === 'audio' ? msg.media.url : undefined}
                                subtitleUrl={msg.media.subtitleUrl}
                                title={msg.media.title}
                                variant="thumbnail"
                                gradientClass={getThemeGradient(colorTheme)}
                                onExpand={async () => {
                                  // Don't allow playing videos while generating
                                  if (busy) return;
                                  await openMediaFromMessage(msg, { autoplay: true });
                                }}
                              />
                            </div>
                          )}
                          {/* Copy button - appears on hover */}
                          {msg.media && msg.media.type === 'widget' && msg.media.widgetCode && (
                            <div
                              className={`mt-3 bg-card border rounded-lg p-3 cursor-pointer hover:bg-accent transition-colors ${busy ? 'opacity-50 pointer-events-none' : ''}`}
                              onClick={() => { if (!busy && !podcastLoading && !quizLoading && !widgetLoading) void openMediaFromMessage(msg); }}
                              title="Open widget"
                            >
                              <div className="flex items-center gap-3">
                                <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 bg-gradient-to-br ${getThemeGradient(colorTheme)}`}>
                                  <Zap className="w-5 h-5 text-white" />
                                </div>
                                <div className="flex-1 min-w-0">
                                  <p className="font-medium text-sm truncate">
                                    {msg.media.title || "Interactive Widget"}
                                  </p>
                                  <p className="text-xs text-muted-foreground">
                                    Click to open in right panel
                                  </p>
                                </div>
                                <ExternalLink className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                              </div>
                            </div>
                          )}
                          {msg.content && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 h-7 w-7"
                              onClick={() => copyToClipboard(msg.content, (msg as any).messageId || `bot-${index}`)}
                              title="Copy message"
                            >
                              {copiedMessageId === ((msg as any).messageId || `bot-${index}`) ? (
                                <Check className="w-4 h-4" />
                              ) : (
                                <Copy className="w-4 h-4" />
                              )}
                            </Button>
                          )}
                          {/* Quiz button for podcast messages - appears on hover */}
                          {msg.media && msg.media.type === 'audio' && msg.media.subtitleUrl && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute top-2 right-10 opacity-0 group-hover:opacity-100 h-7 w-7"
                              onClick={() => {
                                if (!msg.media?.subtitleUrl) {
                                  toast({ title: "No captions", description: "This podcast needs captions.", duration: 4000 });
                                  return;
                                }
                                // Generate quiz directly without entering quiz mode
                                void handleQuizMediaDirect(msg);
                              }}
                              title="Generate quiz from podcast"
                              disabled={busy || podcastLoading || quizLoading || widgetLoading}
                            >
                              <Brain className="w-4 h-4" />
                            </Button>
                          )}
                          {/* Edit & Quiz buttons for video messages - appears on hover */}
                          {msg.media && msg.media.type === 'video' && (
                            <>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="absolute top-2 right-16 opacity-0 group-hover:opacity-100 h-7 w-7"
                                onClick={() => {
                                  if (!msg.media?.subtitleUrl) {
                                    toast({ title: "No captions", description: "This video needs captions. Regenerate it with a podcast to add captions.", duration: 4000 });
                                    return;
                                  }
                                  // Generate quiz directly without entering quiz mode
                                  void handleQuizMediaDirect(msg);
                                }}
                                  title="Generate quiz from video"
                                  disabled={busy || podcastLoading || quizLoading || widgetLoading}
                              >
                                <Brain className="w-4 h-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="absolute top-2 right-10 opacity-0 group-hover:opacity-100 h-7 w-7"
                                onClick={() => {
                                  if (!msg.media?.sceneCode) {
                                    toast({ title: "Cannot edit this video", description: "This video was generated before edit mode was available. Generate a new video to enable editing.", duration: 4000 });
                                    return;
                                  }
                                  setIsEditMode(true);
                                  setQuotedMessage({
                                    messageId: (msg as any).messageId || `bot-${index}`,
                                    content: msg.content,
                                    media: msg.media!
                                  });
                                  textareaRef.current?.focus();
                                }}
                                title="Edit this video"
                                disabled={busy || podcastLoading || quizLoading || widgetLoading}
                              >
                                <Pencil className="w-4 h-4" />
                              </Button>
                            </>
                          )}
                        </div>
                      </div>
                    )}
                    {msg.role === "user" && (
                      <div className="flex items-start gap-4 justify-end group relative">
                        <div className={`rounded-lg p-4 max-w-lg bg-gradient-to-br ${getThemeGradient(colorTheme)} text-white relative`}>
                          <div className="whitespace-pre-wrap">{renderMessage(msg.content)}</div>
                          {/* Copy button - appears on hover */}
                          <Button
                            variant="ghost"
                            size="icon"
                            className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 h-7 w-7 text-white hover:bg-white/20"
                            onClick={() => copyToClipboard(msg.content, (msg as any).messageId || `user-${index}`)}
                            title="Copy message"
                          >
                            {copiedMessageId === ((msg as any).messageId || `user-${index}`) ? (
                              <Check className="w-4 h-4" />
                            ) : (
                              <Copy className="w-4 h-4" />
                            )}
                          </Button>
                        </div>
                        <div className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center flex-shrink-0">
                          <UserIcon className="w-5 h-5 text-secondary-foreground" />
                        </div>
                      </div>
                    )}

                    {/* If this message anchors a quiz, render the quiz card right after it */}
                    {typeof activeChatId === 'string' && (msg as any).messageId && quizzesByChat[String(activeChatId)] && quizzesByChat[String(activeChatId)][String((msg as any).messageId)] && (
                      <div className="flex justify-start w-full">
                        {(() => { const quiz = quizzesByChat[String(activeChatId)][String((msg as any).messageId)]; const quizId = String((msg as any).messageId); return (
                          <div className={`rounded-xl p-5 w-full max-w-lg bg-gradient-to-br ${getThemeGradient(colorTheme)} text-white shadow-lg`}>
                            {quiz.score == null ? (
                              <div>
                                <h3 className="font-semibold mb-2 flex items-center gap-2"><span>📝</span>{quiz.data.title || 'Quiz'}</h3>
                                <p className="text-sm mb-4 opacity-80">Question {quiz.index + 1} of {quiz.data.questions.length}</p>
                                <div className="bg-white/10 rounded-md p-4 backdrop-blur-sm">
                                  <p className="font-medium mb-3">{quiz.data.questions[quiz.index].prompt}</p>
                                  <form
                                    onSubmit={(e) => {
                                      e.preventDefault();
                                      const selected = quiz.selected;
                                      // First submit reveals; second advances
                                      if (!quiz.revealed) {
                                        if (selected == null) return; // require a selection
                                        setQuizzesByChat(prev => {
                                          const cq = prev[String(activeChatId!) ] || {};
                                          const rt = cq[quizId];
                                          if (!rt) return prev;
                                          return { ...prev, [String(activeChatId!)]: { ...cq, [quizId]: { ...rt, revealed: true } } };
                                        })
                                      } else {
                                        if (selected != null) submitQuizAnswer(quizId, selected);
                                      }
                                    }}
                                    key={quiz.index}
                                  >
                                    <div className="space-y-2 mb-4">
                                      {quiz.data.questions[quiz.index].options.map((opt, i) => {
                                        const correct = quiz.data.questions[quiz.index].correctIndex;
                                        const isCorrect = i === correct;
                                        const isSelected = quiz.selected === i;
                                        const show = quiz.revealed;
                                        const highlight = show && isCorrect ? 'ring-2 ring-green-300 bg-green-500/20' : show && isSelected && !isCorrect ? 'ring-2 ring-red-300 bg-red-500/20' : '';
                                        return (
                                        <label key={i} className={`flex items-center gap-2 cursor-pointer group rounded-md px-2 py-1 ${highlight}`}>
                                          <input
                                            type="radio"
                                            name={`answer-${quizId}`}
                                            value={i}
                                            checked={quiz.selected === i}
                                            disabled={quiz.revealed}
                                            onChange={() => setQuizzesByChat(prev => {
                                              const cq = prev[String(activeChatId!)] || {};
                                              const rt = cq[quizId];
                                              if (!rt || rt.score != null) return prev;
                                              return { ...prev, [String(activeChatId!)]: { ...cq, [quizId]: { ...rt, selected: i } } };
                                            })}
                                            className="accent-rose-300 group-hover:scale-105 transition-transform"
                                          />
                                          <span className="text-sm">{String.fromCharCode(65 + i)}. {opt} {show && isCorrect ? '✅' : ''} {show && isSelected && !isCorrect ? '❌' : ''}</span>
                                        </label>
                                        );
                                      })}
                                    </div>
                                    <Button type="submit" variant="secondary" className="w-full font-semibold">
                                      {!quiz.revealed
                                        ? 'Submit'
                                        : (quiz.index + 1 === quiz.data.questions.length ? 'Finish' : 'Next')}
                                    </Button>
                                  </form>
                                </div>
                              </div>
                            ) : (
                              <div>
                                <h3 className="font-semibold mb-2 flex items-center gap-2"><span>🏆</span>Results</h3>
                                <p className="text-sm mb-1">Score: {quiz.score}/{quiz.data.questions.length}</p>
                                <p className="mb-4 font-medium">{quiz.score === quiz.data.questions.length ? 'Perfect score! Outstanding! 🎉' : quiz.score >= Math.ceil(quiz.data.questions.length * 0.8) ? 'Great job, almost perfect! ✨' : quiz.score >= Math.ceil(quiz.data.questions.length * 0.6) ? 'Nice work. keep practicing! 👍' : 'You can boost this score, give it another shot! 💪'}</p>
                                <Button onClick={() => retakeQuiz(quizId)} variant="secondary" className="w-full font-semibold">Retake Quiz</Button>
                              </div>
                            )}
                          </div>
                        ); })()}
                      </div>
                    )}
                  </div>
                ))
              )}
              {/* Show typing indicator after last message if actively generating */}
              {isTyping && (
                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center flex-shrink-0">
                    <Bot className="w-5 h-5 text-secondary-foreground" />
                  </div>
                  <div className={`rounded-lg p-4 max-w-lg bg-secondary text-secondary-foreground`}>
                    <TypingDots />
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
              {showJumpLatest && (
                <div className="sticky bottom-4 flex justify-end">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })}
                    className="shadow-lg rounded-full px-4"
                  >
                    Jump to latest
                  </Button>
                </div>
              )}
            </div>
          </div>

          <div className="p-4 border-t border-border">
            {/* Edit mode quote preview */}
            {isEditMode && quotedMessage && (
              <div className="mb-2 flex items-start gap-2 rounded-lg bg-secondary/50 border-l-4 border-primary px-3 py-2">
                <Reply className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                    <Pencil className="w-3 h-3" />
                    Editing video
                  </div>
                  <p className="text-sm truncate">{quotedMessage.media.title || 'Video'}</p>
                </div>
                <button
                  onClick={() => {
                    setIsEditMode(false);
                    setIsQuizMode(false);
                    setQuotedMessage(null);
                  }}
                  className="text-muted-foreground hover:text-foreground flex-shrink-0"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}
            {uploadedFiles.length > 0 && (
              <div className="mb-2 space-y-1">
                {uploadedFiles.map((file, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between rounded-lg bg-secondary px-3 py-2 text-sm"
                  >
                    <span className="truncate">{file.name}</span>
                    <button
                      onClick={() => removeFile(index)}
                      className="text-muted-foreground hover:text-foreground flex-shrink-0 ml-2"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="relative">
              <Textarea
                ref={textareaRef}
                placeholder={
                  isEditMode
                    ? "Describe what changes you want to make to the video..."
                    : uploadedFiles.length > 0
                    ? `${uploadedFiles.length} file(s) attached. Press Generate to continue.`
                    : "Enter a prompt..."
                }
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                className="min-h-[48px] resize-none pr-24 md:pr-36 py-3"
                disabled={false}
              />
              <div className="absolute top-1/2 right-3 -translate-y-1/2 flex gap-1">
                {isEditMode ? (
                  /* Edit mode: only show edit video button */
                  <Button
                    size="icon"
                    variant="default"
                    className={`bg-gradient-to-r ${getThemeGradient(colorTheme)} text-white hover:opacity-90`}
                    onClick={() => void handleEditVideo()}
                    title={busy ? "Stop editing" : "Apply edits to video"}
                    disabled={!query.trim()}
                  >
                    {busy ? <Square className="w-5 h-5" /> : <Pencil className="w-5 h-5" />}
                  </Button>
                ) : (
                  /* Normal mode: mutually exclusive generation buttons */
                  <>
                    <Button
                      size="icon"
                      variant="default"
                      className={`bg-gradient-to-r ${getThemeGradient(colorTheme)} text-white hover:opacity-90`}
                      onClick={generatePodcastFromPrompt}
                      title={podcastLoading ? "Stop podcast" : (busy || quizLoading || widgetLoading ? "Wait for current generation" : "Generate podcast")}
                      disabled={(!podcastLoading && (busy || quizLoading || widgetLoading))}
                    >
                      {podcastLoading ? <Square className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
                    </Button>
                    <Button
                      size="icon"
                      variant="default"
                      className={`bg-gradient-to-r ${getThemeGradient(colorTheme)} text-white hover:opacity-90`}
                      onClick={() => void generateVideoFromPrompt()}
                      title={busy ? "Stop video" : (podcastLoading || quizLoading || widgetLoading ? "Wait for current generation" : "Generate video")}
                      disabled={(!busy && (podcastLoading || quizLoading || widgetLoading))}
                    >
                      {busy ? <Square className="w-5 h-5" /> : <VideoIcon className="w-5 h-5" />}
                    </Button>
                    <Button
                      size="icon"
                      variant="default"
                      className={`bg-gradient-to-r ${getThemeGradient(colorTheme)} text-white hover:opacity-90`}
                      onClick={generateQuiz}
                      title={quizLoading ? "Stop quiz" : (busy || podcastLoading || widgetLoading ? "Wait for current generation" : "Generate quiz")}
                      disabled={(!quizLoading && (busy || podcastLoading || widgetLoading))}
                    >
                      {quizLoading ? <Square className="w-5 h-5" /> : <Brain className="w-5 h-5" />}
                    </Button>
                    <Button
                      size="icon"
                      variant="default"
                      className={`bg-gradient-to-r ${getThemeGradient(colorTheme)} text-white hover:opacity-90`}
                      onClick={generateWidgetFromPrompt}
                      title={widgetLoading ? "Stop widget" : (busy || podcastLoading || quizLoading ? "Wait for current generation" : "Generate interactive widget")}
                      disabled={(!widgetLoading && (busy || podcastLoading || quizLoading))}
                    >
                      {widgetLoading ? <Square className="w-5 h-5" /> : <Zap className="w-5 h-5" />}
                    </Button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>

        <div
          className="hidden md:flex w-1/2 flex-col p-6 space-y-4 h-screen overflow-y-auto"
          ref={videoContainerRef}
        >
          <Card
            className="flex-grow bg-muted/50 border-border flex items-center justify-center aspect-video min-h-[200px] relative"
            onContextMenu={(e) => e.preventDefault()}
          >
            {widgetHtml ? (
              <WidgetFrame
                widgetCode={widgetHtml}
                className="w-full h-full rounded-xl border-0"
                title="Interactive Widget"
              />
            ) : !videoUrl ? (
              <div className="text-center p-4">
                {busy || podcastLoading || widgetLoading ? (
                  <div className="flex flex-col items-center gap-3">
                    <div className="relative h-16 w-16">
                      <svg className="h-16 w-16 -rotate-90" viewBox="0 0 36 36">
                        <path className="text-muted stroke-current" strokeWidth="3" fill="none" d="M18 2 a 16 16 0 1 1 0 32 a 16 16 0 1 1 0 -32" opacity="0.2"/>
                        <path className="text-primary stroke-current" strokeWidth="3" fill="none" strokeLinecap="round"
                          d="M18 2 a 16 16 0 1 1 0 32 a 16 16 0 1 1 0 -32"
                          strokeDasharray={`${busy ? videoProgress : widgetLoading ? widgetProgress : podcastProgress}, 100`} />
                      </svg>
                      <div className="absolute inset-0 flex items-center justify-center text-sm font-medium">
                        {widgetLoading ? `${widgetProgress}%` : busy ? `${videoProgress}%` : `${podcastProgress}%`}
                      </div>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {busy ? "Rendering video…" : widgetLoading ? "Generating widget…" : "Generating podcast…"}
                    </p>
                  </div>
                ) : apiError ? (
                  <div className="flex flex-col items-center gap-2">
                    <svg viewBox="0 0 24 24" className="w-10 h-10 text-red-500" aria-hidden="true">
                      <path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 14h-2v-2h2v2Zm0-4h-2V6h2v6Z"/>
                    </svg>
                    <p className="text-sm text-red-600 font-medium">Generation failed.</p>
                  </div>
                ) : (
                  <Play className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                )}
              </div>
            ) : (
              currentMediaMeta?.type === 'audio' ? (
                vttUrl ? (
                  // Use a <video> element to display text tracks overlay for audio content when captions available
                  <video
                    key={`${videoUrl || ''}|${vttUrl || 'no-vtt'}`}
                    ref={videoRef as React.RefObject<HTMLVideoElement>}
                    src={videoUrl || undefined}
                    crossOrigin="anonymous"
                    playsInline
                    className="w-full h-full rounded-xl bg-black video-cc"
                    onContextMenu={(e) => e.preventDefault()}
                  >
                    {vttUrl && (
                      <track
                        key={`${currentMediaMeta?.artifactId || videoUrl || ''}|${vttUrl}`}
                        kind="captions"
                        label="Captions"
                        default
                        src={vttUrl}
                        srcLang={subtitleLang}
                      />
                    )}
                  </video>
                ) : (
                  <audio
                    key={`${videoUrl || ''}`}
                    ref={videoRef as React.RefObject<HTMLAudioElement>}
                    src={videoUrl || undefined}
                    preload="metadata"
                    crossOrigin="anonymous"
                    className="w-full h-full rounded-xl bg-black"
                    onContextMenu={(e) => e.preventDefault()}
                  />
                )
              ) : (
                <div className="relative w-full h-full">
                  <video
                    key={`${videoUrl || ''}|${vttUrl || 'no-vtt'}`}
                    ref={videoRef as React.RefObject<HTMLVideoElement>}
                    src={videoUrl || undefined}
                    crossOrigin="anonymous"
                    playsInline
                    className="w-full h-full rounded-xl bg-black video-cc"
                    onContextMenu={(e) => e.preventDefault()}
                    onDoubleClick={(e) => {
                      const vid = videoRef.current as any;
                      if (!vid || currentMediaMeta?.type === 'audio') return; // skip double-click seek for audio
                      const rect = (e.currentTarget as HTMLVideoElement).getBoundingClientRect();
                      const x = e.clientX - rect.left;
                      const isRightHalf = x > rect.width / 2;
                      if (isRightHalf) {
                        vid.currentTime = Math.min((vid.duration || Infinity), (vid.currentTime || 0) + 5);
                      } else {
                        vid.currentTime = Math.max(0, (vid.currentTime || 0) - 5);
                      }
                    }}
                  >
                    {vttUrl && (
                      <track
                        key={`${currentMediaMeta?.artifactId || videoUrl || ''}|${vttUrl}`}
                        kind="captions"
                        label="Captions"
                        default={isCaptionsOn}
                        src={vttUrl}
                        srcLang={subtitleLang}
                        // @ts-ignore
                        type="text/vtt"
                      />
                    )}
                  </video>
                  {/* Fullscreen Button - Bottom Right Corner */}
                  {currentMediaMeta?.type === 'video' && videoUrl && (
                    <Button
                      variant="ghost"
                      size="icon"
                      title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
                      onClick={toggleFullscreen}
                      className="absolute bottom-4 right-4 h-10 w-10 bg-black/70 hover:bg-black/90 text-white z-10 rounded-md"
                    >
                      {isFullscreen ? (
                        <Minimize className="w-5 h-5" />
                      ) : (
                        <Maximize className="w-5 h-5" />
                      )}
                    </Button>
                  )}
                </div>
              )
            )}
          </Card>

          {!widgetHtml && (
            <div className="space-y-4">
            <Slider
              value={progress}
              onValueChange={(val) => {
                setProgress(val);
                const vid = videoRef.current as any;
                if (!vid || !mediaDuration || !isFinite(mediaDuration)) return;
                const pct = Math.max(0, Math.min(100, val[0] || 0));
                try { vid.currentTime = (pct / 100) * mediaDuration; } catch {}
              }}
              max={100}
              step={0.1}
              disabled={!videoUrl}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-0">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  disabled={!videoUrl}
                  onClick={() => {
                    const vid = videoRef.current as any;
                    if (!vid) return;
                    try { vid.currentTime = Math.max(0, (vid.currentTime || 0) - 5); } catch {}
                  }}
                >
                  <SkipBack className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-10 w-10"
                  onClick={() => {
                    const vid = videoRef.current as any;
                    if (!vid) return;
                    try {
                      if (vid.paused) {
                        const p: Promise<any> = vid.play();
                        setIsPlaying(true);
                        // Ensure UI stays correct if browser blocks autoplay or play fails
                        if (p && typeof p.then === 'function') {
                          p.catch(() => setIsPlaying(false));
                        }
                      } else {
                        vid.pause();
                        setIsPlaying(false);
                      }
                    } catch {}
                  }}
                  disabled={!videoUrl}
                >
                  {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  disabled={!videoUrl}
                  onClick={() => {
                    const vid = videoRef.current as any;
                    if (!vid || !isFinite(vid.duration)) return;
                    try { vid.currentTime = Math.min(vid.duration, (vid.currentTime || 0) + 5); } catch {}
                  }}
                >
                  <SkipForward className="w-4 h-4" />
                </Button>
                <span className="text-xs text-muted-foreground ml-1 min-w-[60px] tabular-nums">
                  {formatTime(((progress[0] || 0) / 100) * (isFinite(mediaDuration) ? mediaDuration : 0))}
                  {" / "}
                  {formatTime(isFinite(mediaDuration) ? mediaDuration : 0)}
                </span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Button
                  variant={isCaptionsOn ? "secondary" : "ghost"}
                  onClick={() => {
                    setIsCaptionsOn(prev => !prev);
                  }}
                  className="h-7 w-7 px-0"
                  title="Captions"
                  disabled={!videoUrl || !vttUrl}
                >
                  <span className="font-bold text-xs">CC</span>
                </Button>
                <div className="flex items-center gap-0">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 p-0 leading-none"
                    title="Slower"
                    disabled={!videoUrl}
                    onClick={() => {
                      const current = Math.max(0.25, Math.min(2, playbackSpeed[0] ?? 1));
                      const next = Math.max(0.25, Math.round((current - 0.25) * 100) / 100);
                      setPlaybackSpeed([next]);
                      const vid = videoRef.current;
                      if (vid) {
                        vid.defaultPlaybackRate = next;
                        vid.playbackRate = next;
                        (vid as any).preservesPitch = true;
                        (vid as any).webkitPreservesPitch = true;
                      }
                    }}
                  >
                    -
                  </Button>
                  <span className="text-xs text-muted-foreground min-w-[2rem] text-center tabular-nums">
                    {playbackSpeed[0].toFixed(2)}x
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 p-0 leading-none"
                    title="Faster"
                    disabled={!videoUrl}
                    onClick={() => {
                      const current = Math.max(0.25, Math.min(2, playbackSpeed[0] ?? 1));
                      const next = Math.min(2, Math.round((current + 0.25) * 100) / 100);
                      setPlaybackSpeed([next]);
                      const vid = videoRef.current;
                      if (vid) {
                        vid.defaultPlaybackRate = next;
                        vid.playbackRate = next;
                        (vid as any).preservesPitch = true;
                        (vid as any).webkitPreservesPitch = true;
                      }
                    }}
                  >
                    +
                  </Button>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    title="Mute/unmute"
                    disabled={!videoUrl}
                    onClick={() => {
                      const vid = videoRef.current;
                      if (!vid) return;
                      if (vid.muted || (volume[0] ?? 0) === 0) {
                        const restore = lastNonZeroVolumeRef.current || 50;
                        setVolume([restore]);
                        vid.muted = false;
                        vid.volume = Math.max(0, Math.min(1, restore / 100));
                      } else {
                        lastNonZeroVolumeRef.current = volume[0] ?? 50;
                        setVolume([0]);
                        vid.volume = 0;
                        vid.muted = true;
                      }
                    }}
                  >
                    <Volume2 className="w-8 h-4 text-muted-foreground" />
                  </Button>
                  <Slider
                    value={volume}
                    onValueChange={(v) => {
                      setVolume(v);
                      const vid = videoRef.current;
                      if (vid) {
                        const vol = Math.max(0, Math.min(1, (v[0] ?? 0) / 100));
                        vid.volume = vol;
                        vid.muted = vol === 0 ? true : false;
                        if (vol > 0) lastNonZeroVolumeRef.current = Math.round(vol * 100);
                      }
                    }}
                    onValueCommit={(v) => {
                      const vid = videoRef.current;
                      if (!vid) return;
                      const vol = Math.max(0, Math.min(1, (v[0] ?? 0) / 100));
                      vid.volume = vol;
                      vid.muted = vol === 0 ? true : false;
                      if (vol > 0) lastNonZeroVolumeRef.current = Math.round(vol * 100);
                    }}
                    max={100}
                    step={1}
                    className="w-36"
                    disabled={!videoUrl}
                  />
                  {/* Download Button */}
                  <Button
                    variant="ghost"
                    size="icon"
                    title="Download"
                    disabled={!videoUrl}
                    onClick={handleDownload}
                    className="h-7 w-7 ml-2"
                  >
                    <Download className="w-5 h-5" />
                  </Button>
                </div>
              </div>
            </div>
            {/* Removed "Open Quiz" button; link already shown in chat messages */}
            {/* Quiz error panel removed per request; quiz errors surface in chat/toast instead */}
            </div>
          )}
        </div>
      </div>
      {settingsOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm">
          <SettingsPage
            setView={() => setSettingsOpen(false)}
            user={user}
            apiKeys={apiKeys}
            setApiKeys={(k) => applyApiKeys(k)}
            asDialog
            onUpdateName={handleUpdateDisplayName}
            desktopLocal={desktopLocal}
            onResetLocalData={desktopLocal ? handleResetLocalData : undefined}
          />
        </div>
      )}
      {/* Chat switch confirmation dialog */}
      <AlertDialog open={showSwitchWarning} onOpenChange={(open) => { if (!open) cancelChatSwitch(); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{pendingChatSwitch === NEW_CHAT_SENTINEL ? "Start a new chat?" : "Switch chats?"}</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingChatSwitch === NEW_CHAT_SENTINEL
                ? "Starting a new chat will cancel the current generation. Continue?"
                : "Switching chats will cancel the current generation. Continue?"}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={cancelChatSwitch}>Stay</AlertDialogCancel>
            <AlertDialogAction onClick={confirmChatSwitch}>Switch</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {/* Delete Account Modals (always mounted at top level for global overlay) */}
      {renderDeleteAccountConfirmModal()}
      {renderDeleteAccountPasswordModal()}
    </div>
  );
};

// Settings overlay mounted inside Chat to avoid unmounting Chat state
