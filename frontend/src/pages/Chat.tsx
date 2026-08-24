// frontend/src/pages/Chat.tsx
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
import HelpModal from "@/components/HelpModal";
import CommandPalette from "@/components/CommandPalette";
import { useHotkeys } from "@/hooks/useHotkeys";
import { hasPlatformModifier, isTypingTarget } from "@/lib/hotkeys";
import { loadCustomContext } from "@/lib/customContext";
import { useLanguage, type Translate } from "@/lib/i18n";
import { useJobProgress } from "@/hooks/useJobProgress";
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
  HelpCircle,
  Square,
  Copy,
  Check,
  Share2,
  Search,
  Reply,
  Pencil,
  Brain,
  Zap,
  ExternalLink,
  ChevronLeft,
  Eye,
} from "lucide-react";
import type {
  User,
  Chat,
  ArtifactKind,
  AudienceLevel,
  ColorTheme,
  Theme,
  ApiKeys,
  MediaAttachment,
  GenerationDiagnostics,
  GenerationQualityStatus,
  Message,
} from "@/types";
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
  apiUrl,
} from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import { buildDownloadFilename } from "@/lib/downloadName";
import { isDesktopLocalMode } from "@/lib/runtime";
import { clearApiKeysForUser, loadApiKeysForUser, persistApiKeysForUser } from "@/lib/secureKeys";
import {
  apiKeysChanged,
  apiKeysFingerprint,
  buildLlmRequestConfig,
  hasSelectedProviderKey,
  normalizeApiKeys,
  providerDisplayName,
  selectedProvider,
} from "@/lib/providerConfig";
import { prepareWidgetHtmlForIframe } from "@/lib/widgetRuntime";
import { prepareStaticWorksheetHtml, staticWorksheetStorageKey } from "@/lib/staticWorksheetRuntime";
import {
  createMessageIdentity,
  mergeMessages,
} from "@/lib/messageOrdering";
import {
  MAX_GENERATION_IMAGES,
  prepareGenerationImages,
  validateGenerationImageFiles,
} from "@/lib/generationImages";
import type { GenerationImagePayload } from "@/lib/generationImages";

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
      title={title || "Interactive Worksheet"}
      loading="eager"
    />
  );
};

interface StaticWorksheetFrameProps {
  worksheetHtml: string;
  worksheetId: string;
  userEmail: string;
  title?: string;
  className?: string;
}

const StaticWorksheetFrame: FC<StaticWorksheetFrameProps> = ({
  worksheetHtml,
  worksheetId,
  userEmail,
  title,
  className,
}) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const preparedHtml = useMemo(
    () => prepareStaticWorksheetHtml(worksheetHtml, worksheetId),
    [worksheetHtml, worksheetId],
  );
  const worksheetUrl = useMemo(() => {
    const blob = new Blob([preparedHtml], { type: "text/html;charset=utf-8" });
    return URL.createObjectURL(blob);
  }, [preparedHtml]);
  const storageKey = useMemo(
    () => staticWorksheetStorageKey(userEmail, worksheetId),
    [userEmail, worksheetId],
  );

  useEffect(() => () => URL.revokeObjectURL(worksheetUrl), [worksheetUrl]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data || {};
      if (data.worksheetId !== worksheetId) return;

      if (data.type === "upcurved-static-worksheet-restore-request") {
        let responses: any[] = [];
        try {
          const raw = localStorage.getItem(storageKey);
          const parsed = raw ? JSON.parse(raw) : [];
          responses = Array.isArray(parsed) ? parsed : [];
        } catch {}
        iframeRef.current?.contentWindow?.postMessage({
          type: "upcurved-static-worksheet-restore",
          worksheetId,
          responses,
        }, "*");
        return;
      }

      if (data.type === "upcurved-static-worksheet-save") {
        try {
          if (Array.isArray(data.responses)) {
            localStorage.setItem(storageKey, JSON.stringify(data.responses));
          }
        } catch {}
        iframeRef.current?.contentWindow?.postMessage({
          type: "upcurved-static-worksheet-saved",
          worksheetId,
          announce: data.announce !== false,
        }, "*");
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [storageKey, worksheetId]);

  return (
    <iframe
      ref={iframeRef}
      src={worksheetUrl}
      sandbox="allow-scripts allow-modals"
      className={className || "w-full border-0"}
      title={title || "Static Worksheet"}
      loading="eager"
    />
  );
};


interface DiagramFrameProps {
  svgCode: string;
  title?: string;
  className?: string;
}

const DiagramFrame: FC<DiagramFrameProps> = ({ svgCode, title, className }) => {
  const diagramUrl = useMemo(() => {
    const blob = new Blob([svgCode], { type: "image/svg+xml" });
    return URL.createObjectURL(blob);
  }, [svgCode]);

  useEffect(() => {
    return () => URL.revokeObjectURL(diagramUrl);
  }, [diagramUrl]);

  return (
    <div className={className || "flex h-full w-full items-center justify-center overflow-auto bg-white p-3"}>
      <img
        src={diagramUrl}
        alt={title || "Educational diagram"}
        className="max-h-full max-w-full object-contain"
        draggable={false}
      />
    </div>
  );
};

const svgToPngBlob = async (svgCode: string): Promise<Blob> => {
  const parser = new DOMParser();
  const doc = parser.parseFromString(svgCode, "image/svg+xml");
  const svg = doc.documentElement;
  if (!svg || svg.nodeName.toLowerCase() !== "svg" || doc.querySelector("parsererror")) {
    throw new Error("The diagram SVG could not be read.");
  }

  const viewBox = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
  let width = viewBox.length === 4 && Number.isFinite(viewBox[2]) ? viewBox[2] : Number(svg.getAttribute("width"));
  let height = viewBox.length === 4 && Number.isFinite(viewBox[3]) ? viewBox[3] : Number(svg.getAttribute("height"));
  if (!Number.isFinite(width) || width <= 0) width = 1200;
  if (!Number.isFinite(height) || height <= 0) height = 800;

  // Export at document-friendly resolution while bounding memory use.
  const scale = Math.min(2, 2400 / width, 1800 / height);
  const outputWidth = Math.max(1, Math.round(width * Math.max(1, scale)));
  const outputHeight = Math.max(1, Math.round(height * Math.max(1, scale)));
  const sourceBlob = new Blob([svgCode], { type: "image/svg+xml" });
  const sourceUrl = URL.createObjectURL(sourceBlob);

  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("The diagram could not be rendered as PNG."));
      image.src = sourceUrl;
    });
    const canvas = document.createElement("canvas");
    canvas.width = outputWidth;
    canvas.height = outputHeight;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("PNG export is unavailable in this browser.");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, outputWidth, outputHeight);
    context.drawImage(image, 0, 0, outputWidth, outputHeight);
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("PNG export failed."))),
        "image/png",
      );
    });
  } finally {
    URL.revokeObjectURL(sourceUrl);
  }
};

const ImageAttachmentPreview: FC<{ file: File }> = ({ file }) => {
  const previewUrl = useMemo(() => URL.createObjectURL(file), [file]);

  useEffect(() => {
    return () => URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  return (
    <img
      src={previewUrl}
      alt=""
      className="h-12 w-12 rounded-md border border-border object-cover"
    />
  );
};

const NEEDS_CLARIFICATION_MESSAGE =
  "The model determined the prompt's learning intention was unclear. Please try again.";

const clarificationMessageFrom = (value: any): string | null => {
  if (String(value?.status || "").trim() !== "needs_clarification") return null;
  const message = String(value?.message || "").trim();
  return message || NEEDS_CLARIFICATION_MESSAGE;
};

type GenerationSelection =
  | "static_worksheet"
  | "widget"
  | "diagram"
  | "video"
  | "quiz"
  | "podcast_single"
  | "podcast_debate"
  | "story";

const GENERATION_SELECTIONS: GenerationSelection[] = [
  "widget",
  "static_worksheet",
  "diagram",
  "video",
  "quiz",
  "podcast_single",
  "podcast_debate",
  "story",
];

const AUDIENCE_LEVELS = [
  "auto",
  "early_learning",
  "elementary",
  "middle_school",
  "high_school",
  "university",
] as const;

type MultimodalGenerationDiagnostics = GenerationDiagnostics & {
  input_modality?: "text" | "image";
  image_count?: number;
  vision_mode?: "none" | "native" | "helper" | string;
  vision_provider?: string;
  vision_model?: string;
  vision_fallback_reason?: string;
  default_image_prompt_used?: boolean;
  artifact_generated?: boolean;
};

const diagnosticCount = (value: unknown): number | undefined => {
  if (value === undefined || value === null || value === "") return undefined;
  const count = Number(value);
  return Number.isFinite(count) && count >= 0
    ? Math.floor(count)
    : undefined;
};

const diagnosticNumber = (value: unknown): number | undefined => {
  if (value === undefined || value === null || value === "") return undefined;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : undefined;
};

const diagnosticText = (value: unknown): string | undefined => {
  const text = String(value ?? "").trim();
  return text || undefined;
};

const normalizeGenerationDiagnostics = (
  value: unknown,
): MultimodalGenerationDiagnostics | undefined => {
  if (!value || typeof value !== "object") return undefined;
  const raw = value as Record<string, unknown>;
  const hasDiagnosticSignal = [
    raw.quality_status,
    raw.provider,
    raw.model,
    raw.llm_calls,
    raw.input_modality,
    raw.image_count,
    raw.vision_mode,
    raw.total_tokens,
    raw.estimated_cost_usd,
  ].some((entry) => entry !== undefined && entry !== null && entry !== "");
  if (!hasDiagnosticSignal) return undefined;

  const status = (
    diagnosticText(raw.quality_status) || "standard"
  ) as GenerationQualityStatus;

  const recoveryStages = Array.isArray(raw.recovery_stages)
    ? raw.recovery_stages
        .map((stage) => diagnosticText(stage))
        .filter((stage): stage is string => Boolean(stage))
    : [];
  const repairedScenes = diagnosticCount(raw.repaired_scenes)
    ?? ((diagnosticCount(raw.sanitizer_repaired) || 0)
      + (diagnosticCount(raw.render_repaired) || 0));
  const legacyPlanRepairWasModelCall =
    Boolean(raw.plan_repaired)
    && recoveryStages.includes("plan_repair");
  const callDetails = Array.isArray(raw.calls)
    ? raw.calls
        .filter((call): call is Record<string, unknown> => Boolean(call) && typeof call === "object")
        .map((call) => ({
          provider: diagnosticText(call.provider),
          model: diagnosticText(call.model),
          actual_model: diagnosticText(call.actual_model),
          purpose: diagnosticText(call.purpose),
          input_tokens: diagnosticCount(call.input_tokens),
          output_tokens: diagnosticCount(call.output_tokens),
          total_tokens: diagnosticCount(call.total_tokens),
          usage_reported: Boolean(call.usage_reported),
          status: diagnosticText(call.status),
          pricing_known: Boolean(call.pricing_known),
          estimated_cost_usd: diagnosticNumber(call.estimated_cost_usd) ?? null,
        }))
    : [];

  return {
    quality_status: status,
    provider: diagnosticText(raw.provider),
    model: diagnosticText(raw.model),
    llm_calls: diagnosticCount(raw.llm_calls),
    input_tokens: diagnosticCount(raw.input_tokens),
    cached_input_tokens: diagnosticCount(raw.cached_input_tokens),
    cache_write_input_tokens: diagnosticCount(raw.cache_write_input_tokens),
    output_tokens: diagnosticCount(raw.output_tokens),
    total_tokens: diagnosticCount(raw.total_tokens),
    estimated_cost_usd: diagnosticNumber(raw.estimated_cost_usd),
    pricing_complete:
      raw.pricing_complete === undefined ? undefined : Boolean(raw.pricing_complete),
    usage_complete:
      raw.usage_complete === undefined ? undefined : Boolean(raw.usage_complete),
    unpriced_calls: diagnosticCount(raw.unpriced_calls),
    usage_missing_calls: diagnosticCount(raw.usage_missing_calls),
    calls: callDetails,
    total_scenes: diagnosticCount(raw.total_scenes),
    creative_scenes: diagnosticCount(raw.creative_scenes),
    repaired_scenes: repairedScenes,
    plan_repaired_by_model:
      Boolean(raw.plan_repaired_by_model) || legacyPlanRepairWasModelCall,
    simplified_scenes: diagnosticCount(raw.simplified_scenes),
    component_fallbacks: diagnosticCount(raw.component_fallbacks),
    recovery_stages: recoveryStages,
    failure_stage: diagnosticText(raw.failure_stage) || null,
    summary: diagnosticText(raw.summary),
    input_modality:
      diagnosticText(raw.input_modality) === "image" ? "image" : "text",
    image_count: diagnosticCount(raw.image_count),
    vision_mode: diagnosticText(raw.vision_mode),
    vision_provider: diagnosticText(raw.vision_provider),
    vision_model: diagnosticText(raw.vision_model),
    vision_fallback_reason: diagnosticText(raw.vision_fallback_reason),
    default_image_prompt_used: Boolean(raw.default_image_prompt_used),
    artifact_generated:
      raw.artifact_generated === undefined
        ? undefined
        : Boolean(raw.artifact_generated),
  };
};

const humanizeDiagnosticToken = (value: string): string =>
  value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const compactTokenCount = (tokens: number, t: Translate): string => {
  // Abbreviated counts keep the Latin K/M suffixes: they are units, not words, and
  // every locale we ship renders them that way in technical contexts.
  if (tokens >= 1_000_000) {
    return t("diag.tokens.other", {
      count: `${(tokens / 1_000_000).toFixed(tokens >= 10_000_000 ? 1 : 2)}M`,
    });
  }
  if (tokens >= 1_000) {
    return t("diag.tokens.other", {
      count: `${(tokens / 1_000).toFixed(tokens >= 10_000 ? 1 : 2)}K`,
    });
  }
  return tokens === 1 ? t("diag.tokens.one") : t("diag.tokens.other", { count: tokens });
};

const compactEstimatedCost = (cost: number): string => {
  if (cost <= 0) return "$0";
  if (cost < 0.0001) return `$${cost.toFixed(6)}`;
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(3)}`;
};

const compactModelLabel = (diagnostics: MultimodalGenerationDiagnostics): string => {
  const provider = diagnostics.provider
    ? humanizeDiagnosticToken(diagnostics.provider)
    : "";
  const model = diagnostics.model || "";
  return [provider, model].filter(Boolean).join(" · ");
};

const GenerationDiagnosticsPanel: FC<{
  diagnostics?: MultimodalGenerationDiagnostics;
}> = ({ diagnostics }) => {
  const { t } = useLanguage();
  if (!diagnostics) return null;

  const firstLine: string[] = [];
  const sourceLine: string[] = [];
  const secondLine: string[] = [];
  const modelLabel = compactModelLabel(diagnostics);

  if (modelLabel) firstLine.push(modelLabel);
  if (typeof diagnostics.llm_calls === "number") {
    firstLine.push(
      diagnostics.llm_calls === 1
        ? t("diag.modelCalls.one")
        : t("diag.modelCalls.other", { count: diagnostics.llm_calls }),
    );
  }
  if (typeof diagnostics.total_tokens === "number" && diagnostics.total_tokens > 0) {
    firstLine.push(compactTokenCount(diagnostics.total_tokens, t));
  }
  if (typeof diagnostics.estimated_cost_usd === "number") {
    if (diagnostics.pricing_complete) {
      firstLine.push(
        t("diag.est", { cost: compactEstimatedCost(diagnostics.estimated_cost_usd) }),
      );
    } else if ((diagnostics.unpriced_calls || 0) > 0) {
      firstLine.push(
        diagnostics.estimated_cost_usd > 0
          ? t("diag.knownEst", {
              cost: compactEstimatedCost(diagnostics.estimated_cost_usd),
              count: diagnostics.unpriced_calls || 0,
            })
          : (diagnostics.unpriced_calls === 1
              ? t("diag.unpriced.one")
              : t("diag.unpriced.other", { count: diagnostics.unpriced_calls || 0 })),
      );
    }
  }
  if (diagnostics.image_count) {
    sourceLine.push(
      diagnostics.image_count === 1
        ? t("diag.images.one")
        : t("diag.images.other", { count: diagnostics.image_count }),
    );
    if (diagnostics.vision_mode === "helper") {
      const helperLabel = [
        diagnostics.vision_provider
          ? humanizeDiagnosticToken(diagnostics.vision_provider)
          : "",
        diagnostics.vision_model || "",
      ].filter(Boolean).join(" · ");
      sourceLine.push(
        helperLabel ? t("diag.visionHelperWith", { label: helperLabel }) : t("diag.visionHelper"),
      );
    } else if (diagnostics.vision_mode === "native") {
      sourceLine.push(t("diag.nativeVision"));
    }
  }

  if (typeof diagnostics.total_scenes === "number") {
    secondLine.push(
      diagnostics.total_scenes === 1
        ? t("diag.scenes.one")
        : t("diag.scenes.other", { count: diagnostics.total_scenes }),
    );
  }
  if (diagnostics.creative_scenes) {
    secondLine.push(t("diag.creative", { count: diagnostics.creative_scenes }));
  }

  const outcome: string[] = [];
  if (diagnostics.quality_status === "failed") {
    outcome.push(
      diagnostics.failure_stage
        ? t("diag.failedAt", { stage: humanizeDiagnosticToken(diagnostics.failure_stage) })
        : t("diag.generationFailed"),
    );
  } else if (diagnostics.component_fallbacks) {
    outcome.push(
      diagnostics.component_fallbacks === 1
        ? t("diag.fallback.one")
        : t("diag.fallback.other", { count: diagnostics.component_fallbacks }),
    );
  } else if (diagnostics.simplified_scenes) {
    outcome.push(
      diagnostics.simplified_scenes === 1
        ? t("diag.simplified.one")
        : t("diag.simplified.other", { count: diagnostics.simplified_scenes }),
    );
  } else {
    if (diagnostics.plan_repaired_by_model) outcome.push(t("diag.planRepaired"));
    if (diagnostics.repaired_scenes) {
      outcome.push(
        diagnostics.repaired_scenes === 1
          ? t("diag.repaired.one")
          : t("diag.repaired.other", { count: diagnostics.repaired_scenes }),
      );
    }
    if (outcome.length === 0) outcome.push(t("diag.noRepair"));
  }
  secondLine.push(outcome.join(" · "));

  return (
    <div
      className="mt-3 border-t border-border/70 pt-2 text-[11px] text-muted-foreground"
      aria-label={t("chat.diagnostics")}
    >
      {firstLine.length > 0 && <p>{firstLine.join(" · ")}</p>}
      {sourceLine.length > 0 && <p className="mt-0.5">{sourceLine.join(" · ")}</p>}
      {secondLine.length > 0 && <p className="mt-0.5">{secondLine.join(" · ")}</p>}
    </div>
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
  const { t } = useLanguage();
  const desktopLocal = isDesktopLocalMode();
  // Standing context saved in Settings, read fresh for each request so an edit
  // takes effect on the very next generation.
  const currentCustomContext = () => loadCustomContext(user?.email) || undefined;

  // Job ids for the generations that are not a subprocess. Aborting the request
  // only closes the connection; this tells the server to stop the work too.
  const currentPodcastJobId = useRef<string | null>(null);
  const currentQuizJobId = useRef<string | null>(null);
  const currentWidgetJobId = useRef<string | null>(null);

  const cancelServerJob = (jobId: string | null | undefined) => {
    if (!jobId) return;
    // Best effort: the user has already seen the run stop locally.
    fetch(apiUrl(`/jobs/cancel?jobId=${encodeURIComponent(jobId)}`), {
      method: "POST",
    }).catch(() => {});
  };
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
  const imageFileInputRef = useRef<HTMLInputElement>(null);
  const [isCaptionsOn, setIsCaptionsOn] = useState(false);
  const [activeScript, setActiveScript] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [progress, setProgress] = useState([0]);
  const [volume, setVolume] = useState([100]);
  const [playbackSpeed, setPlaybackSpeed] = useState([1]);
  const [mediaDuration, setMediaDuration] = useState(0);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [modal, setModal] = useState<{ isOpen: boolean; type: string; data: any }>({
    isOpen: false,
    type: "",
    data: null,
  });
  // Edit mode state - for editing existing artifacts
  const [isEditMode, setIsEditMode] = useState(false);
  const [isQuizMode, setIsQuizMode] = useState(false);
  const [generationType, setGenerationType] = useState<GenerationSelection>("widget");
  const [quotedMessage, setQuotedMessage] = useState<{ messageId: string; content: string; media?: import('@/types').MediaAttachment; quizData?: QuizData; artifactKind?: ArtifactKind } | null>(null);
  // backend integration state
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [widgetHtml, setWidgetHtml] = useState<string | null>(null);
  const [htmlDownloadUrl, setHtmlDownloadUrl] = useState<string | null>(null);
  const [htmlDownloadFilename, setHtmlDownloadFilename] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [videoProgress, setVideoProgress] = useState(0); // fallback ramp when the backend reports nothing
  const [activeVideoJobId, setActiveVideoJobId] = useState<string | null>(null);
  // Mobile only: the artifact pane is a full-screen overlay rather than a column.
  const [mobileArtifactOpen, setMobileArtifactOpen] = useState(false);
  // Real stages from the backend. `percent` stays null until it reports, and the
  // synthetic ramp covers that gap and any generation type without instrumentation.
  const jobProgress = useJobProgress(activeVideoJobId, busy);

  useHotkeys([
    { key: "k", handler: () => setPaletteOpen((open) => !open) },
    { key: "/", handler: () => setHelpOpen((open) => !open) },
  ]);
  const videoProgressTimer = useRef<number | null>(null);
  // Podcast generation visual progress (mirrors video progress UX)
  const [podcastProgress, setPodcastProgress] = useState(0);
  const podcastProgressTimer = useRef<number | null>(null);
  const [audienceLevel, setAudienceLevel] = useState<AudienceLevel>("auto");
  const [storyConfigOpen, setStoryConfigOpen] = useState(false);
  const [storyHostChoice, setStoryHostChoice] = useState<"auto" | "scientist" | "friendly_robot" | "animal_guide" | "explorer" | "artist" | "athlete">("auto");
  const [storyThemeChoice, setStoryThemeChoice] = useState<"auto" | "space" | "jungle" | "ocean" | "city_lab" | "sunset_farm" | "meadow">("auto");
  const [widgetProgress, setWidgetProgress] = useState(0);
  const widgetProgressTimer = useRef<number | null>(null);
  const [quizLoading, setQuizLoading] = useState(false);
  const [podcastLoading, setPodcastLoading] = useState(false);
  const [widgetLoading, setWidgetLoading] = useState(false);
  // Embedded quiz runtime state per chat, anchored to a specific messageId
  // quizzesByChat[chatId][messageId] => QuizRuntime
  interface QuizData { title: string; description?: string; questions: { prompt: string; options: string[]; correctIndex: number }[]; downloadUrl?: string; downloadFilename?: string; generationDiagnostics?: MultimodalGenerationDiagnostics }
  interface QuizRuntime { data: QuizData; index: number; answers: number[]; score: number | null; selected: number | null; revealed: boolean }
  const [quizzesByChat, setQuizzesByChat] = useState<Record<string, Record<string, QuizRuntime>>>({});
  const [subtitleLang, setSubtitleLang] = useState<string | undefined>(undefined);
  // Track what kind of generation was last attempted for clearer error copy
  const lastGenerateKindRef = useRef<"video" | "podcast" | null>(null);

  // Minimal inline typing indicator
  const TypingDots = () => (
    <div className="flex items-center gap-1 text-muted-foreground select-none py-2" aria-label={t("chat.typing")}>
      <span className="w-2 h-2 rounded-full bg-current animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-2 h-2 rounded-full bg-current animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-2 h-2 rounded-full bg-current animate-bounce" style={{ animationDelay: '300ms' }} />
    </div>
  );

  // Track generation state across the mutually exclusive artifact types.
  const anyGenerationLoading = busy || podcastLoading || quizLoading || widgetLoading;
  const isTyping = anyGenerationLoading && activeChatId !== null;

  // Copy message to clipboard state
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);

  const copyToClipboard = async (text: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(messageId);
      setTimeout(() => setCopiedMessageId(null), 2000);
      toast({
        title: t("toast.copied"),
        duration: 2000,
      });
    } catch (err) {
      toast({
        title: t("toast.copyFailed"),
        variant: "destructive",
        duration: 2000,
      });
    }
  };



  const normalizeArtifactKind = (media?: import('@/types').MediaAttachment | null, msg?: any): ArtifactKind | undefined => {
    const explicit = (media as any)?.artifactKind as ArtifactKind | undefined;
    if (explicit) return explicit;
    if (!media) {
      if (msg?.quizAnchor || msg?.quizData) return 'quiz';
      return undefined;
    }
    if (media.type === 'video') return 'video';
    if (media.type === 'audio') return 'podcast';
    if (media.type === 'widget') {
      const title = String(media.title || msg?.content || '').toLowerCase();
      if (title.includes('story')) return 'story';
      return 'widget';
    }
    return undefined;
  };

  // Lower-case nouns meant to sit inside a sentence ("Edit this video"), which is
  // why they are separate keys from the Title Case names in the generation picker.
  const artifactLabel = (kind?: ArtifactKind) => {
    switch (kind) {
      case 'video': return t('artifact.video');
      case 'audio':
      case 'podcast': return t('artifact.podcast');
      case 'story': return t('artifact.story');
      case 'widget': return t('artifact.widget');
      case 'static_worksheet': return t('artifact.static_worksheet');
      case 'diagram': return t('artifact.diagram');
      case 'quiz': return t('artifact.quiz');
      default: return t('artifact.default');
    }
  };

  const plainTextFromHtml = (html?: string, fallback = ''): string => {
    const raw = String(html || '').trim();
    if (!raw) return fallback;
    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(raw, 'text/html');
      doc.querySelectorAll('script, style, noscript, svg, canvas').forEach((el) => el.remove());
      const text = (doc.body?.innerText || doc.body?.textContent || '').replace(/\s+/g, ' ').trim();
      return text || fallback;
    } catch {
      return raw
        .replace(/<script[\s\S]*?<\/script>/gi, ' ')
        .replace(/<style[\s\S]*?<\/style>/gi, ' ')
        .replace(/<[^>]+>/g, ' ')
        .replace(/\s+/g, ' ')
        .trim() || fallback;
    }
  };

  const plainTextFromSvg = (svg?: string, fallback = ''): string => {
    const raw = String(svg || '').trim();
    if (!raw) return fallback;
    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(raw, 'image/svg+xml');
      if (doc.querySelector('parsererror')) return fallback;
      const pieces = Array.from(doc.querySelectorAll('title, desc, text, tspan'))
        .map((node) => (node.textContent || '').replace(/\s+/g, ' ').trim())
        .filter(Boolean);
      return pieces.join(' ').replace(/\s+/g, ' ').trim() || fallback;
    } catch {
      return fallback;
    }
  };

  const quizToText = (quiz?: QuizData | null): string => {
    if (!quiz) return '';
    const pieces: string[] = [];
    if (quiz.title) pieces.push(`Title: ${quiz.title}`);
    if (quiz.description) pieces.push(`Description: ${quiz.description}`);
    for (const [idx, q] of (quiz.questions || []).entries()) {
      pieces.push(`Question ${idx + 1}: ${q.prompt}`);
      (q.options || []).forEach((opt, optIdx) => {
        pieces.push(`${String.fromCharCode(65 + optIdx)}. ${opt}`);
      });
      if (typeof q.correctIndex === 'number') {
        pieces.push(`Correct answer: ${String.fromCharCode(65 + q.correctIndex)}. ${q.options?.[q.correctIndex] || ''}`);
      }
    }
    return pieces.join('\n');
  };

  const startEditArtifact = (
    msg: any,
    index: number,
    kindOverride?: ArtifactKind,
    quizData?: QuizData,
  ) => {
    const kind = kindOverride || normalizeArtifactKind(msg?.media, msg) || (quizData ? 'quiz' : undefined);
    if (!kind) {
      toast({ title: t("toast.cannotEdit"), description: t("toast.notEnoughInfoToEdit"), duration: 4000 });
      return;
    }
    if (kind === 'video' && !msg.media?.sceneCode) {
      toast({ title: t("toast.cannotEditVideo"), description: t("toast.videoTooOldToEdit"), duration: 4000 });
      return;
    }
    if ((kind === 'story' || kind === 'widget' || kind === 'static_worksheet' || kind === 'diagram') && !msg.media?.widgetCode) {
      toast({ title: t("toast.cannotEditArtifact"), description: kind === 'diagram' ? "The original SVG is missing. Regenerate it to enable editing." : "The original HTML is missing. Regenerate it to enable editing.", duration: 4000 });
      return;
    }
    if (kind === 'quiz' && !quizData && !msg?.quizData) {
      toast({ title: t("toast.cannotEditQuiz"), description: t("toast.quizDataMissing"), duration: 4000 });
      return;
    }

    setUploadedFiles([]);
    setIsEditMode(true);
    setIsQuizMode(false);
    setQuotedMessage({
      messageId: String(msg?.messageId || `bot-${index}`),
      content: msg?.content || '',
      media: msg?.media,
      quizData: quizData || msg?.quizData,
      artifactKind: kind,
    });
    textareaRef.current?.focus();
  };


  const [vttUrl, setVttUrl] = useState<string | null>(null); // object URL for converted WebVTT captions
  // `title` carries the prompt/episode name so downloads get a meaningful filename.
  const [currentMediaMeta, setCurrentMediaMeta] = useState<{ artifactId?: string; gcsPath?: string; type?: 'video'|'audio'|'widget'; artifactKind?: ArtifactKind; title?: string; worksheetId?: string } | null>(null);
  type PersistedMediaSelection = {
    chatId: string;
    messageId?: string;
    type: "video" | "audio" | "widget";
    artifactKind?: ArtifactKind;
    url?: string;
    subtitleUrl?: string;
    artifactId?: string;
    gcsPath?: string;
    widgetCode?: string;
    title?: string;
    downloadFilename?: string;
    worksheetId?: string;
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

  const optionalMessageNumber = (value: unknown): number | undefined => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  };

  const mapApiMessage = (message: any): Message => {
    const media = message?.media
      ? {
          type: (message.media.type === "podcast" ? "audio" : message.media.type) as
            | "audio"
            | "video"
            | "widget",
          url: toPlayableMediaUrl(message.media.url as string | undefined),
          subtitleUrl: toPlayableMediaUrl(message.media.subtitleUrl as string | undefined),
          artifactId: message.media.artifactId as string | undefined,
          title: message.media.title as string | undefined,
          gcsPath: message.media.gcsPath as string | undefined,
          sceneCode: message.media.sceneCode as string | undefined,
          widgetCode: message.media.widgetCode as string | undefined,
          artifactKind: message.media.artifactKind as ArtifactKind | undefined,
          downloadFilename: message.media.downloadFilename as string | undefined,
          worksheetId: message.media.worksheetId as string | undefined,
          scriptGcsPath: message.media.scriptGcsPath as string | undefined,
          generationDiagnostics: normalizeGenerationDiagnostics(
            message.media.generationDiagnostics,
          ),
        }
      : undefined;

    return {
      role: message?.role === "assistant" ? "bot" : "user",
      content: String(message?.content || ""),
      media,
      createdAt: optionalMessageNumber(message?.createdAt),
      clientCreatedAt: optionalMessageNumber(message?.clientCreatedAt),
      sequence: optionalMessageNumber(message?.sequence),
      messageId: message?.message_id ? String(message.message_id) : undefined,
      quizAnchor:
        message?.quizAnchor === undefined
          ? undefined
          : Boolean(message.quizAnchor),
      quizTitle: message?.quizTitle ? String(message.quizTitle) : undefined,
      quizData: message?.quizData,
    };
  };

  const appendPayloadFromMessage = (message: Message) => {
    const baseTime =
      optionalMessageNumber(message.clientCreatedAt)
      ?? optionalMessageNumber(message.createdAt)
      ?? Date.now();
    const identity = message.messageId
      ? {
          messageId: message.messageId,
          clientCreatedAt: baseTime,
          sequence: optionalMessageNumber(message.sequence) ?? baseTime * 1000,
        }
      : createMessageIdentity(baseTime);

    return {
      message_id: identity.messageId,
      role: message.role === "bot" ? ("assistant" as const) : ("user" as const),
      content: message.content,
      media: message.media,
      clientCreatedAt: identity.clientCreatedAt,
      sequence: identity.sequence,
      quizAnchor: message.quizAnchor,
      quizTitle: message.quizTitle,
      quizData: message.quizData,
    };
  };

  const reconcileMessagesForChat = (
    chatId: string | number,
    incoming: readonly Message[],
  ): Message[] => {
    const cacheKey = String(chatId);
    const current =
      messagesCache.current[cacheKey]
      || chats.find((chat) => String(chat.id) === cacheKey)?.messages
      || [];
    const merged = mergeMessages(current, incoming);
    messagesCache.current[cacheKey] = merged;
    setChats((previous) =>
      previous.map((chat) =>
        String(chat.id) === cacheKey ? { ...chat, messages: merged } : chat,
      ),
    );
    forceUpdate({});
    return merged;
  };

  const restoreQuizMessages = (
    chatId: string,
    messages: readonly Message[],
  ) => {
    const quizMessages = messages.filter(
      (message) => message.quizAnchor && message.quizData && message.messageId,
    );
    if (!quizMessages.length) return;

    setQuizzesByChat((previous) => {
      const current = previous[chatId] || {};
      const next = { ...current };
      for (const message of quizMessages) {
        const messageId = message.messageId!;
        const existing = current[messageId];
        next[messageId] = {
          data: message.quizData as unknown as QuizData,
          index: existing?.index || 0,
          answers: existing?.answers || [],
          score: existing?.score ?? null,
          selected: existing?.selected ?? null,
          revealed: existing?.revealed || false,
        };
      }
      return { ...previous, [chatId]: next };
    });
  };

  const htmlFilenameFromTitle = (title?: string | null, fallback = "upcurved_export.html") => {
    const base = String(title || fallback)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 80) || "upcurved_export";
    return base.endsWith(".html") ? base : `${base}.html`;
  };

  const svgFilenameFromTitle = (title?: string | null, fallback = "upcurved_diagram.svg") => {
    const raw = String(title || fallback).replace(/\.svg$/i, "");
    const base = raw
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 80) || "upcurved_diagram";
    return `${base}.svg`;
  };

  type GenerationAction = "video" | "story" | "podcast" | "widget" | "static_worksheet" | "diagram" | "quiz" | "edit";

  const ensureLlmKey = (action: GenerationAction): boolean => {
    const normalized = normalizeApiKeys(apiKeys);
    const provider = selectedProvider(normalized);

    if (!provider || !hasSelectedProviderKey(normalized)) {
      const actionText: Record<GenerationAction, string> = {
        video: "generate a video",
        story: "generate a story",
        podcast: "generate a podcast",
        widget: "generate an interactive worksheet",
        static_worksheet: "generate a static worksheet",
        diagram: "generate a diagram",
        quiz: "generate a quiz",
        edit: "edit this artifact",
      };
      toast({
        title: t("toast.missingApiKey"),
        description: `Add your ${providerDisplayName(provider)} API key in Settings to ${actionText[action]}.`,
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
  const [helpOpen, setHelpOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [isDraggingImages, setIsDraggingImages] = useState(false);
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

  // Message identity and ordering are centralized in messageOrdering.ts.
  // The cache stores one permanent ID per message from optimistic insertion
  // through persistence and reload.
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

  // Saving any provider/model/key change cancels all in-flight generation types.
  const applyApiKeys = (next: ApiKeys) => {
    const normalizedNext = normalizeApiKeys(next);
    if (apiKeysChanged(apiKeys, normalizedNext)) {
      try { videoAbortRef.current?.abort(); } catch {}
      try { podcastAbortRef.current?.abort(); } catch {}
      try { quizAbortRef.current?.abort(); } catch {}
      try { widgetAbortRef.current?.abort(); } catch {}
    }
    setApiKeys(normalizedNext);
  };

  const normalizedApiKeys = useMemo(() => normalizeApiKeys(apiKeys), [apiKeys]);
  const apiKeysPersistenceKey = useMemo(
    () => apiKeysFingerprint(normalizedApiKeys),
    [normalizedApiKeys]
  );

  const [apiKeysHydratedFor, setApiKeysHydratedFor] = useState<string>("");

  // On a fresh renderer load (including Cmd+R), hydrate API keys from their configured
  // storage before allowing the normal persistence effect to run.
  useEffect(() => {
    const email = String(user?.email || "").trim();
    if (!email) {
      setApiKeysHydratedFor("");
      return;
    }

    let cancelled = false;
    setApiKeysHydratedFor("");
    void (async () => {
      const loaded = normalizeApiKeys(await loadApiKeysForUser(email));
      if (cancelled) return;
      setApiKeys(loaded);
      setApiKeysHydratedFor(email);
    })();
    return () => { cancelled = true; };
  }, [user?.email]); // eslint-disable-line react-hooks/exhaustive-deps

  // Persist every registered provider key only after startup hydration completes.
  useEffect(() => {
    const email = String(user?.email || "").trim();
    if (!email || apiKeysHydratedFor !== email) return;
    void persistApiKeysForUser(email, normalizedApiKeys);
  }, [user?.email, apiKeysHydratedFor, apiKeysPersistenceKey]); // eslint-disable-line react-hooks/exhaustive-deps

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
      const widgetDownloadUrl = toPlayableMediaUrl(media.url);
      const artifactKind = normalizeArtifactKind(media, message);
      const widgetDownloadFilename = media.downloadFilename || (
        artifactKind === "diagram"
          ? svgFilenameFromTitle(media.title, "upcurved_diagram.svg")
          : htmlFilenameFromTitle(
              media.title,
              artifactKind === "static_worksheet"
                ? "upcurved_static_worksheet.html"
                : "upcurved_interactive_worksheet.html",
            )
      );
      setVideoUrl(null);
      setCurrentMediaMeta({
        artifactId: media.artifactId,
        gcsPath: media.gcsPath,
        type: "widget",
        artifactKind,
        title: media.title,
        worksheetId: media.worksheetId,
      });
      setVttUrl(null);
      setSrtText(null);
      setSubtitleLang(undefined);
      setWidgetHtml(media.widgetCode);
      setHtmlDownloadUrl(widgetDownloadUrl || null);
      setHtmlDownloadFilename(widgetDownloadFilename || null);
      if (persist && chatKey) {
        persistMediaSelection({
          chatId: chatKey,
          messageId,
          type: "widget",
          artifactKind: normalizeArtifactKind(media, message),
          url: widgetDownloadUrl,
          widgetCode: media.widgetCode,
          artifactId: media.artifactId,
          gcsPath: media.gcsPath,
          title: media.title,
          downloadFilename: widgetDownloadFilename,
          worksheetId: media.worksheetId,
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
    setHtmlDownloadUrl(null);
    setHtmlDownloadFilename(null);
    setCurrentMediaMeta({
      artifactId: media.artifactId,
      gcsPath: media.gcsPath,
      type: media.type,
      artifactKind: normalizeArtifactKind(media, message),
      title: media.title,
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
        artifactKind: normalizeArtifactKind(media, message),
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
        artifactKind: currentMediaMeta?.artifactKind,
        url: htmlDownloadUrl || undefined,
        widgetCode: widgetHtml,
        artifactId: currentMediaMeta?.artifactId,
        gcsPath: currentMediaMeta?.gcsPath,
        downloadFilename: htmlDownloadFilename || undefined,
        title: currentMediaMeta?.title,
        worksheetId: currentMediaMeta?.worksheetId,
        updatedAt: Date.now(),
      });
      return;
    }
    if (videoUrl && currentMediaMeta?.type && currentMediaMeta.type !== "widget") {
      persistMediaSelection({
        chatId: chatKey,
        type: currentMediaMeta.type,
        artifactKind: currentMediaMeta.artifactKind || currentMediaMeta.type,
        url: videoUrl,
        artifactId: currentMediaMeta.artifactId,
        gcsPath: currentMediaMeta.gcsPath,
        subtitleUrl: vttUrl || undefined,
        // Without this the restore path rebuilds media with no title, which then
        // flows back into currentMediaMeta and downloads lose their prompt name.
        title: currentMediaMeta.title,
        updatedAt: Date.now(),
      });
    }
  }, [activeChatId, widgetHtml, htmlDownloadUrl, htmlDownloadFilename, videoUrl, currentMediaMeta?.type, currentMediaMeta?.artifactId, currentMediaMeta?.gcsPath, currentMediaMeta?.title, currentMediaMeta?.worksheetId, vttUrl]); // eslint-disable-line react-hooks/exhaustive-deps

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
              const msgs = (chatDetail.messages || []).map(mapApiMessage);
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
              messagesCache.current[cacheKey] = mergeMessages(
                messagesCache.current[cacheKey] || [],
                msgs,
              );
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
        setHtmlDownloadUrl(null);
        setHtmlDownloadFilename(null);
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
        target = {
          messageId: persisted.messageId,
          media: {
            type: "widget",
            url: persisted.url,
            widgetCode: persisted.widgetCode,
            artifactKind: persisted.artifactKind,
            artifactId: persisted.artifactId,
            gcsPath: persisted.gcsPath,
            title: persisted.title,
            downloadFilename: persisted.downloadFilename,
            worksheetId: persisted.worksheetId,
          },
        };
      }
      if (!target && persisted?.url && (persisted?.type === "video" || persisted?.type === "audio")) {
        target = {
          messageId: persisted.messageId,
          media: {
            type: persisted.type,
            artifactKind: persisted.artifactKind,
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
        setHtmlDownloadUrl(null);
        setHtmlDownloadFilename(null);
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
      // Keep the in-memory cache aligned with the same ID-based merge used by
      // refresh, pagination, optimistic inserts, and outbox reconciliation.
      try {
        const active = newChats.find(
          (chat) => String(chat.id) === String(activeChatId),
        );
        if (active && Array.isArray(active.messages)) {
          const cacheKey = String(active.id);
          messagesCache.current[cacheKey] = mergeMessages(
            messagesCache.current[cacheKey] || [],
            active.messages,
          );
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
          // Model is stored in chat data, not needed in URL.
          const persisted = await apiAppendMessage(it.chatId, it.payload);
          reconcileMessagesForChat(it.chatId, [mapApiMessage(persisted)]);
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
        for (const message of current.messages || []) {
          try {
            await apiAppendMessage(newId, appendPayloadFromMessage(message));
          } catch {}
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
          for (const message of lc.messages) {
            await apiAppendMessage(
              newId,
              appendPayloadFromMessage(message),
              model,
            );
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
        title: t("toast.sharingUpdateFailed"),
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
    // Closing the connection is not enough; tell the server to stop as well.
    cancelServerJob(currentVideoJobId.current);
    cancelServerJob(currentPodcastJobId.current);
    cancelServerJob(currentQuizJobId.current);
    cancelServerJob(currentWidgetJobId.current);
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
    setHtmlDownloadUrl(null);
    setHtmlDownloadFilename(null);
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
    setHtmlDownloadUrl(null);
    setHtmlDownloadFilename(null);
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
      const identity = createMessageIdentity();
      const newMessage: Message = {
        role,
        content,
        media,
        ...identity,
        ...(extras || {}),
      };
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

      // Read from the cache first, then add the optimistic message using the
      // same permanent ID that will be sent to the backend.
      const historyKey = String(localTargetId);
      const cachedHistory = messagesCache.current[historyKey];
      let history = cachedHistory && cachedHistory.length > 0
        ? [...cachedHistory]
        : [...currentChat.messages];
      const wasEmptyBefore = history.length === 0;
      const normalizedContent = (content || "")
        .trim()
        .toLowerCase()
        .replace(/\s+/g, " ");
      const chatKeyForFingerprint = String(
        (persistChatIdOverride as any) ?? localTargetId ?? "draft",
      );

      if (isUser && wasEmptyBefore) {
        const fingerprint = firstPromptFingerprintRef.current[chatKeyForFingerprint];
        if (
          fingerprint
          && fingerprint.key === normalizedContent
          && Date.now() - fingerprint.ts < 2000
        ) {
          return fingerprint.messageId;
        }
        firstPromptFingerprintRef.current[chatKeyForFingerprint] = {
          key: normalizedContent,
          ts: Date.now(),
          messageId: newMessage.messageId!,
        };
      } else if (isUser) {
        delete firstPromptFingerprintRef.current[chatKeyForFingerprint];
      }

      history = mergeMessages(history, [newMessage]);
      messagesCache.current[historyKey] = history;

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
        messagesCache.current[newCacheKey] = mergeMessages(
          messagesCache.current[oldCacheKey] || [],
          history,
        );
        delete messagesCache.current[oldCacheKey];
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
      // Persist remotely with the exact same ID and client order metadata.
      const targetChatId = String(persistChatIdOverride || modifiedChat.id);
      if (targetChatId && !targetChatId.startsWith("local-")) {
        const payload = appendPayloadFromMessage(newMessage);
        try {
          const persisted = await apiAppendMessage(targetChatId, payload);
          reconcileMessagesForChat(targetChatId, [mapApiMessage(persisted)]);
        } catch {
          enqueueOutbox({ chatId: targetChatId, payload, model });
        }
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

  const addGenerationImages = (incoming: File[]) => {
    if (!incoming.length) return;
    const validation = validateGenerationImageFiles(uploadedFiles, incoming);
    if (validation.rejected.length > 0) {
      const first = validation.rejected[0];
      toast({
        title: t("toast.imageNotAttached"),
        description: `${first.file.name || "Image"}: ${first.reason}`,
        duration: 5000,
      });
    }
    if (validation.limitReached) {
      toast({
        title: t("toast.imageLimit", { count: MAX_GENERATION_IMAGES }),
        description: t("toast.imageLimit.body", { count: MAX_GENERATION_IMAGES }),
        duration: 4000,
      });
    }
    if (validation.accepted.length > 0) {
      setUploadedFiles((previous) => [
        ...previous,
        ...validation.accepted.slice(0, Math.max(0, MAX_GENERATION_IMAGES - previous.length)),
      ]);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    addGenerationImages(Array.from(e.target.files || []));
    e.target.value = ""; // allow re-uploading the same file
  };

  /** Pull image files out of a clipboard or drag payload, however the platform exposed them. */
  const imagesFromTransfer = (data: DataTransfer | null): File[] => {
    if (!data) return [];

    const named = (file: File, index: number): File => {
      const extension = file.type === "image/jpeg"
        ? "jpg"
        : file.type === "image/webp"
        ? "webp"
        : "png";
      return new File(
        [file],
        file.name || `pasted-image-${Date.now()}-${index + 1}.${extension}`,
        { type: file.type, lastModified: Date.now() },
      );
    };

    const fromItems = Array.from(data.items || [])
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item, index) => {
        const file = item.getAsFile();
        return file ? named(file, index) : null;
      })
      .filter((file): file is File => Boolean(file));
    if (fromItems.length) return fromItems;

    // Some platforms and some source apps populate `files` but not `items`.
    return Array.from(data.files || [])
      .filter((file) => file.type.startsWith("image/"))
      .map(named);
  };

  /** True when the clipboard clearly held an image we simply cannot use. */
  const clipboardHasUnusableImage = (data: DataTransfer | null): boolean => {
    if (!data) return false;
    const types = Array.from(data.types || []);
    return types.some((type) => type.startsWith("image/"));
  };

  // Nested elements fire dragleave as the pointer crosses them, so a plain
  // boolean flickers. Counting enter/leave pairs is the usual remedy.
  const dragDepth = useRef(0);

  const dragHasFiles = (event: React.DragEvent) =>
    Array.from(event.dataTransfer?.types || []).includes("Files");

  const handleDragEnter = (event: React.DragEvent<HTMLDivElement>) => {
    if (isEditMode || !dragHasFiles(event)) return;
    event.preventDefault();
    dragDepth.current += 1;
    setIsDraggingImages(true);
  };

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    if (isEditMode || !dragHasFiles(event)) return;
    // Without this the browser navigates to the dropped file instead.
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };

  const handleDragLeave = () => {
    if (isEditMode) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setIsDraggingImages(false);
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    if (isEditMode) return;
    dragDepth.current = 0;
    setIsDraggingImages(false);
    if (!dragHasFiles(event)) return;
    event.preventDefault();
    handlePastedImages(event.dataTransfer);
  };

  /** Paste is deliberately scoped to the prompt box, not the whole composer. */
  const handleImagePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (isEditMode) return;
    if (handlePastedImages(e.clipboardData)) {
      e.preventDefault();
    }
  };

  const handlePastedImages = (data: DataTransfer | null): boolean => {
    const images = imagesFromTransfer(data);
    if (images.length) {
      addGenerationImages(images);
      return true;
    }
    if (clipboardHasUnusableImage(data)) {
      // Linux and some Windows apps put screenshots on the clipboard as BMP or
      // TIFF. Saying so beats appearing broken.
      toast({
        title: t("toast.pasteUnsupported"),
        description: t("toast.pasteUnsupported.body"),
        duration: 6000,
      });
      return true;
    }
    return false;
  };

  const removeFile = (index: number) => {
    setUploadedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const attachmentSummary = (files: readonly File[]): string => {
    if (!files.length) return "";
    const names = files.map((file) => file.name || "image").join(", ");
    return `🖼️ ${files.length} ${files.length === 1 ? "image" : "images"} attached: ${names}`;
  };

  const userMessageWithAttachments = (prompt: string, files: readonly File[]): string =>
    [prompt.trim(), attachmentSummary(files)].filter(Boolean).join("\n\n");

  const prepareAttachedImages = async (files: readonly File[]): Promise<GenerationImagePayload[]> => {
    if (!files.length) return [];
    try {
      return await prepareGenerationImages(files);
    } catch (error: any) {
      toast({
        title: t("toast.couldNotPrepareImage"),
        description: error?.message || "Please try attaching the image again.",
        duration: 5000,
      });
      throw error;
    }
  };

  const handleSubmit = () => {
    const prompt = query.trim();
    if (!prompt && uploadedFiles.length === 0) return;
    if (isEditMode) {
      void handleEditVideo();
      return;
    }
    void handleSelectedGeneration();
  };

  const generatePodcastFromPrompt = async (
    requestedMode: "standard" | "debate" = "standard",
  ) => {
    lastGenerateKindRef.current = 'podcast';
    if (podcastLoading && podcastAbortRef.current) {
      podcastAbortRef.current.abort();
      cancelServerJob(currentPodcastJobId.current);
      return;
    }
    stopPlayback();

    const prompt = query.trim();
    const sourceFiles = [...uploadedFiles];
    if (!prompt && sourceFiles.length === 0) {
      toast({ title: t("toast.needInput"), description: t("toast.addTextFirst"), duration: 4000 });
      return;
    }
    if (!ensureLlmKey("podcast")) return;

    let images: GenerationImagePayload[];
    try {
      images = await prepareAttachedImages(sourceFiles);
    } catch {
      return;
    }

    const requestAudience = audienceLevel === "auto" ? undefined : audienceLevel;
    const chatSeed = prompt || sourceFiles[0]?.name || "Image learning request";
    const persistedId = await ensurePersistedActiveChat(chatSeed);
    const finalChatId = persistedId || activeChatId;
    if (!finalChatId) {
      toast({ title: t("toast.unableToStartChat"), description: t("toast.signInAgain"), duration: 4000 });
      return;
    }
    setActiveChatId(finalChatId);
    await processAndAddMessage(
      userMessageWithAttachments(prompt, sourceFiles),
      true,
      undefined,
      persistedId,
    );
    setQuery("");
    setUploadedFiles([]);
    void generatePodcast(prompt, finalChatId, requestAudience, images, requestedMode);
  };

  async function generatePodcast(
    prompt: string,
    chatIdOverride?: string | number | null,
    requestAudience: AudienceLevel | undefined = undefined,
    images: GenerationImagePayload[] = [],
    requestedMode: "standard" | "debate" = "standard",
  ) {
    setPodcastLoading(true);
    setApiError(null);
    // Reset current media
    setWidgetHtml(null);
    setHtmlDownloadUrl(null);
    setHtmlDownloadFilename(null);
    setVideoUrl(null);
    setSrtText(null);
    // Use the provided chat ID or fall back to activeChatId
    let currentChatId = chatIdOverride || activeChatId;
    if (currentChatId == null) {
      setApiError(t("chat.msg.noActiveChat"));
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
      const llmConfig = buildLlmRequestConfig(apiKeys);

      const sessionId = ensureChatSessionId();
      const podcastJobId = makeJobId();
      currentPodcastJobId.current = podcastJobId;
      const body = {
        prompt,
        keys: llmConfig.keys,
        provider: llmConfig.provider,
        model: llmConfig.model,
        mode: requestedMode,
        audience: requestAudience,
        customContext: currentCustomContext(),
        images,
        sessionId,
        jobId: podcastJobId,
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
      const clarificationMessage = clarificationMessageFrom(data);
      if (clarificationMessage) {
        setApiError(null);
        await processAndAddMessage(clarificationMessage, false, undefined, chatIdForGeneration);
        return;
      }
      if (res.ok && data?.status === "ok" && data?.video_url) {
        // Use signed URL if available, otherwise use regular URL
        const audioUrl = toPlayableMediaUrl(data.signed_video_url || data.video_url) || "";
        setVideoUrl(audioUrl);
        const sourceLabel = prompt || images.map((image) => image.name).filter(Boolean).join(", ") || "Image learning request";
        setCurrentMediaMeta({ artifactId: data.artifact_id, gcsPath: data.gcs_path, type: 'audio', artifactKind: 'podcast', title: sourceLabel });
        setSubtitleLang((data.lang as string) || undefined);


        // Create media attachment for persistent access - always use signed URL if available
        const mediaAttachment: import('@/types').MediaAttachment = {
          type: 'audio',
          artifactKind: 'podcast' as any,
          url: audioUrl, // Use signed URL for persistence
          subtitleUrl: toPlayableMediaUrl(data.signed_subtitle_url),
          title: `${requestedMode === "debate" ? "Debate Podcast" : "Podcast"}: ${sourceLabel.slice(0, 50)}...`,
          artifactId: data.artifact_id,
          gcsPath: data.gcs_path,
          scriptGcsPath: data.script_gcs_path, // GCS path for persistent script fallback
          generationDiagnostics: normalizeGenerationDiagnostics(
            data.generation_diagnostics,
          ),
        };

        // Use the same chat ID we started with to ensure message goes to correct chat
        await processAndAddMessage(
          requestedMode === "debate" ? `✅ ${t("chat.msg.generated", { kind: t("artifact.debatePodcast") })}` : `✅ ${t("chat.msg.generated", { kind: t("artifact.podcast") })}`,
          false,
          mediaAttachment,
          chatIdForGeneration
        );

        // Captions for podcast (audio): attempt fetch using helper
        // Clear old captions first
        setVttUrl(null);
        setSrtText(null);
        void fetchCaptions(audioUrl, data.signed_subtitle_url);
      } else {
        const errorBody = responseErrorBody(res, data, raw);
        const friendly = formatGenerationError("Podcast generation", errorBody);
        setApiError(friendly);
        await processAndAddMessage(friendly, false, undefined, chatIdForGeneration);
      }
    } catch (err: any) {
      if (err?.name === "AbortError") {
        setApiError(null);
        await processAndAddMessage(`⏹️ ${t("chat.msg.canceled", { kind: t("artifact.podcast") })}`, false, undefined, chatIdForGeneration);
        aborted = true;
      } else {
        const body = thrownErrorBody(err);
        const networkMsg = err?.message && /Failed to fetch|NetworkError|TypeError/i.test(err.message)
          ? "We couldn't reach the server. Check your connection and try again."
          : (err?.message || "Request failed");
        const friendly = body
          ? formatGenerationError("Podcast generation", body, networkMsg)
          : `❌ ${t("chat.msg.networkError")}\n\n${t("chat.msg.reason", { reason: networkMsg })}`;
        setApiError(friendly);
        await processAndAddMessage(friendly, false, undefined, chatIdForGeneration);
      }
    } finally {
      setPodcastLoading(false);
      podcastAbortRef.current = null;
      if (podcastProgressTimer.current) window.clearInterval(podcastProgressTimer.current);
      setPodcastProgress(aborted ? 0 : 100);
    }
  }

  const generateVideoFromPrompt = async (
    promptOverride?: string,
    storyOptions?: { host_character?: string; theme?: string },
    requestedMode: "standard" | "story" = "standard",
  ) => {
    lastGenerateKindRef.current = 'video';
    if (busy && videoAbortRef.current) {
      videoAbortRef.current.abort();
      if (currentVideoJobId.current) {
        fetch(apiUrl(`/jobs/cancel?jobId=${encodeURIComponent(currentVideoJobId.current)}`), {
          method: "POST",
        }).catch(() => {});
      }
      return;
    }

    stopPlayback();
    const prompt = (promptOverride ?? query).trim();
    const sourceFiles = [...uploadedFiles];
    if (!prompt && sourceFiles.length === 0) {
      toast({ title: t("toast.needInput"), description: t("toast.addTextFirst"), duration: 4000 });
      return;
    }
    if (!ensureLlmKey("video")) return;

    let images: GenerationImagePayload[];
    try {
      images = await prepareAttachedImages(sourceFiles);
    } catch {
      return;
    }

    const requestAudience = audienceLevel === "auto" ? undefined : audienceLevel;
    const chatSeed = prompt || sourceFiles[0]?.name || "Image learning request";
    const persistedId = await ensurePersistedActiveChat(chatSeed);
    const finalChatId = persistedId || activeChatId;
    if (!finalChatId) {
      toast({ title: t("toast.unableToStartChat"), description: t("toast.signInAgain"), duration: 4000 });
      return;
    }
    setActiveChatId(finalChatId);
    await processAndAddMessage(
      userMessageWithAttachments(prompt, sourceFiles),
      true,
      undefined,
      persistedId,
    );
    setQuery("");
    setUploadedFiles([]);
    void generateVideo(
      prompt,
      finalChatId,
      storyOptions,
      requestAudience,
      images,
      requestedMode,
    );
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
    if (quizLoading && quizAbortRef.current) {
      quizAbortRef.current.abort();
      cancelServerJob(currentQuizJobId.current);
      return;
    }

    const currentPrompt = (query || "").trim();
    const sourceFiles = [...uploadedFiles];
    if (!currentPrompt && sourceFiles.length === 0) {
      toast({ title: t("toast.needInput"), description: t("toast.addTextFirst"), duration: 4000 });
      return;
    }
    if (!ensureLlmKey("quiz")) return;

    let images: GenerationImagePayload[];
    try {
      images = await prepareAttachedImages(sourceFiles);
    } catch {
      return;
    }

    const requestAudience = audienceLevel === "auto" ? undefined : audienceLevel;
    setQuizLoading(true);
    let persistedId: string | undefined;
    try {
      const pendingPrompt = normalizePrompt(currentPrompt, "quiz");
      const chatSeed = pendingPrompt || sourceFiles[0]?.name || "Image learning request";
      persistedId = await ensurePersistedActiveChat(chatSeed);
      const finalChatId = persistedId || activeChatId;
      if (!finalChatId) {
        toast({ title: t("toast.unableToStartChat"), description: t("toast.signInAgain"), duration: 4000 });
        return;
      }
      setActiveChatId(finalChatId);
      await processAndAddMessage(
        userMessageWithAttachments(pendingPrompt, sourceFiles),
        true,
        undefined,
        persistedId,
      );
      setQuery("");
      setUploadedFiles([]);

      const llmConfig = buildLlmRequestConfig(apiKeys);
      const sessionId = ensureChatSessionId();
      const jobId = makeJobId();
      currentQuizJobId.current = jobId;
      const body = {
        prompt: pendingPrompt || "",
        images,
        num_questions: 5,
        difficulty: "medium",
        keys: llmConfig.keys,
        provider: llmConfig.provider,
        model: llmConfig.model,
        audience: requestAudience,
        customContext: currentCustomContext(),
        sessionId,
        jobId,
        chatId: String(finalChatId),
      };
      console.debug("POST /quiz/embedded", { ...body, images: images.map((image) => ({ mimeType: image.mimeType, name: image.name })) });
      const controller = new AbortController();
      quizAbortRef.current = controller;
      const res = await apiFetch("/quiz/embedded", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const { data, raw: quizRawResponse } = await parseResponse(res);
      const quizChatId = persistedId || activeChatId;
      const clarificationMessage = clarificationMessageFrom(data);
      if (clarificationMessage) {
        setApiError(null);
        // activeChatId can be numeric for local drafts; the override is a string id.
        await processAndAddMessage(clarificationMessage, false, undefined, String(quizChatId || persistedId));
        return;
      }
      if (quizChatId && res.ok && data?.status === "ok" && data?.quiz?.questions?.length) {
        const quizPayload = {
          ...data.quiz,
          downloadUrl: toPlayableMediaUrl(data.download_url),
          downloadFilename: data.download_filename,
          generationDiagnostics: normalizeGenerationDiagnostics(data.generation_diagnostics),
        };
        const quizTitle = (quizPayload?.title as string) || "Quiz";
        const quizMsgId = await processAndAddMessage("", false, undefined, String(quizChatId), {
          quizAnchor: true,
          quizTitle,
          quizData: quizPayload,
        });
        if (quizMsgId) {
          setQuizzesByChat((prev) => ({
            ...prev,
            [String(quizChatId)]: {
              ...(prev[String(quizChatId)] || {}),
              [quizMsgId]: { data: quizPayload, index: 0, answers: [], score: null, selected: null, revealed: false },
            },
          }));
        }
      } else {
        const errorBody = responseErrorBody(res, data, quizRawResponse);
        await processAndAddMessage(formatGenerationError("Quiz generation", errorBody), false, undefined, persistedId);
      }
    } catch (err: any) {
      if (err?.name === "AbortError") {
        await processAndAddMessage(`⏹️ ${t("chat.msg.canceled", { kind: t("artifact.quiz") })}`, false, undefined, persistedId);
      } else {
        const body = thrownErrorBody(err);
        await processAndAddMessage(formatGenerationError("Quiz generation", body, err?.message), false, undefined, persistedId);
      }
    } finally {
      setQuizLoading(false);
      quizAbortRef.current = null;
    }
  }

  async function generateWidgetFromPrompt(
    artifactKind: "widget" | "static_worksheet" | "diagram" = "widget",
  ) {
    if (widgetLoading && widgetAbortRef.current) {
      widgetAbortRef.current.abort();
      cancelServerJob(currentWidgetJobId.current);
      return;
    }

    const prompt = query.trim();
    const sourceFiles = [...uploadedFiles];
    const isDiagram = artifactKind === "diagram";
    const isStaticWorksheet = artifactKind === "static_worksheet";
    const artifactName = isDiagram ? "Diagram" : isStaticWorksheet ? "Static Worksheet" : "Interactive Worksheet";
    if (!prompt && sourceFiles.length === 0) {
      toast({ title: t("toast.needInput"), description: t("toast.addTextFirst"), duration: 4000 });
      return;
    }
    if (!ensureLlmKey(isDiagram ? "diagram" : isStaticWorksheet ? "static_worksheet" : "widget")) return;

    let images: GenerationImagePayload[];
    try {
      images = await prepareAttachedImages(sourceFiles);
    } catch {
      return;
    }

    const requestAudience = audienceLevel === "auto" ? undefined : audienceLevel;
    setWidgetLoading(true);
    setWidgetProgress(5);
    if (widgetProgressTimer.current) window.clearInterval(widgetProgressTimer.current);
    widgetProgressTimer.current = window.setInterval(() => {
      setWidgetProgress((p) => (p < 60 ? Math.min(p + 2, 60) : 60));
    }, 700);
    let aborted = false;
    let persistedId: string | undefined;

    try {
      const chatSeed = prompt || sourceFiles[0]?.name || "Image learning request";
      persistedId = await ensurePersistedActiveChat(chatSeed);
      const finalChatId = persistedId || activeChatId;
      if (!finalChatId) {
        toast({ title: t("toast.unableToStartChat"), description: t("toast.signInAgain"), duration: 4000 });
        return;
      }
      setActiveChatId(finalChatId);
      await processAndAddMessage(
        userMessageWithAttachments(prompt, sourceFiles),
        true,
        undefined,
        persistedId,
      );
      setQuery("");
      setUploadedFiles([]);

      const llmConfig = buildLlmRequestConfig(apiKeys);
      const controller = new AbortController();
      widgetAbortRef.current = controller;
      const widgetJobId = makeJobId();
      currentWidgetJobId.current = widgetJobId;
      const body = {
        prompt,
        images,
        provider: llmConfig.provider,
        model: llmConfig.model,
        keys: llmConfig.keys,
        audience: requestAudience,
        customContext: currentCustomContext(),
        chatId: String(finalChatId),
        sessionId: ensureChatSessionId(),
        jobId: widgetJobId,
      };
      const endpoint = isDiagram ? "/diagram" : isStaticWorksheet ? "/static_worksheet" : "/widget";
      console.debug(`POST ${endpoint}`, {
        ...body,
        images: images.map((image) => ({ mimeType: image.mimeType, name: image.name })),
      });
      const res = await apiFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const { data, raw } = await parseResponse(res);
      const clarificationMessage = clarificationMessageFrom(data);
      if (clarificationMessage) {
        setApiError(null);
        await processAndAddMessage(clarificationMessage, false, undefined, String(finalChatId));
        return;
      }

      const artifactSource = isDiagram ? data?.svg_code : isStaticWorksheet ? data?.worksheet_html : data?.widget_html;
      if (res.ok && data?.status === "ok" && artifactSource) {
        const sourceLabel = prompt || images.map((image) => image.name).filter(Boolean).join(", ") || "Image learning request";
        const downloadUrl = toPlayableMediaUrl(data.download_url);
        const downloadFilename = data.download_filename || (
          isDiagram
            ? svgFilenameFromTitle(`upcurved_diagram_${sourceLabel.slice(0, 50)}`)
            : htmlFilenameFromTitle(
                `${artifactName}: ${sourceLabel.slice(0, 50)}`,
                isStaticWorksheet ? "upcurved_static_worksheet.html" : "upcurved_interactive_worksheet.html",
              )
        );
        const mediaAttachment: import('@/types').MediaAttachment = {
          type: 'widget',
          artifactKind,
          url: downloadUrl,
          // widgetCode is the persisted text-artifact source slot. For Diagram it contains
          // validated standalone SVG instead of HTML.
          widgetCode: artifactSource,
          worksheetId: isStaticWorksheet ? String(data.worksheet_id || body.jobId || "") : undefined,
          title: `${artifactName}: ${sourceLabel.slice(0, 50)}`,
          downloadFilename,
          generationDiagnostics: normalizeGenerationDiagnostics(
            data.generation_diagnostics,
          ),
        };
        await processAndAddMessage(
          isDiagram ? `✅ ${t("chat.msg.generated", { kind: t("artifact.diagram") })}` : isStaticWorksheet ? `✅ ${t("chat.msg.generated", { kind: t("artifact.static_worksheet") })}` : `✅ ${t("chat.msg.generated", { kind: t("artifact.widget") })}`,
          false,
          mediaAttachment,
          String(finalChatId),
        );
        setVideoUrl(null);
        setCurrentMediaMeta({ type: 'widget', artifactKind, title: mediaAttachment.title, worksheetId: mediaAttachment.worksheetId });
        setSrtText(null);
        setVttUrl(null);
        setSubtitleLang(undefined);
        setWidgetHtml(artifactSource);
        setHtmlDownloadUrl(downloadUrl || null);
        setHtmlDownloadFilename(downloadFilename || null);
      } else {
        const errorBody = responseErrorBody(res, data, raw);
        const friendly = formatGenerationError(
          `${artifactName} generation`,
          errorBody,
          `${artifactName} response did not include ${isDiagram ? "svg_code" : isStaticWorksheet ? "worksheet_html" : "widget_html"}.`,
        );
        await processAndAddMessage(friendly, false, undefined, persistedId);
      }
    } catch (err: any) {
      if (err?.name === "AbortError") {
        await processAndAddMessage(
          `⏹️ Canceled ${artifactName.toLowerCase()} generation.`,
          false,
          undefined,
          persistedId,
        );
        aborted = true;
      } else {
        const body = thrownErrorBody(err);
        const friendly = formatGenerationError(
          `${artifactName} generation`,
          body,
          err?.message || "Unknown error",
        );
        await processAndAddMessage(friendly, false, undefined, persistedId);
        toast({ title: `${artifactName} failed`, description: err?.message || "Unknown error", duration: 4000 });
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
    // Cmd/Ctrl+Enter sends from anywhere in the box, including mid-paragraph.
    if (e.key === "Enter" && hasPlatformModifier(e)) {
      e.preventDefault();
      handleSubmit();
      return;
    }
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
        title: t("toast.localProfileCleared"),
        description: t("toast.localDataRemoved"),
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
        toast({ title: t("toast.noUserSignedIn"), description: t("toast.signInAgain"), variant: "destructive", duration: 4000 });
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
          <h2 className="text-lg font-semibold mb-2">{t("dialog.deleteAccount.title")}</h2>
          <p className="mb-4 text-sm text-foreground">
            {t("dialog.deleteAccount.body")}
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
                      title: t("toast.deleteAccountFailed"),
                      description: t("toast.deleteAccountFailed.body"),
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
                    title: t("toast.accountDeleted"),
                    description: t("toast.accountDeleted.body"),
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
          <h2 className="text-lg font-semibold mb-2">{t("dialog.deleteAccount.title")}</h2>
          <p className="mb-4 text-sm text-foreground">
            {t("dialog.deleteAccount.password")}
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
                      title: t("toast.deleteAccountFailed"),
                      description: t("toast.deleteAccountFailed.body"),
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
                    title: t("toast.accountDeleted"),
                    description: t("toast.accountDeleted.body"),
                    duration: 3000,
                  });
                  // window.location.replace("/"); // Removed to prevent double redirect
                } catch (error: any) {
                  const errorMessage = error?.code === 'auth/requires-recent-login'
                    ? "For security, please reauthenticate before deleting your account."
                    : "Could not delete account, try again.";
                  toast({
                    title: t("toast.deleteAccountFailed"),
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
          title: t("toast.deleteAccountFailed"),
          description: t("toast.deleteAccountFailed.body"),
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
        title: t("toast.accountDeleted"),
        description: t("toast.accountDeleted.body"),
        duration: 3000,
      });
      window.location.replace("/");
    } catch (error: any) {
      const errorMessage = error?.code === 'auth/requires-recent-login'
        ? "For security, please reauthenticate before deleting your account."
        : "Could not delete account, try again.";
      toast({
        title: t("toast.deleteAccountFailed"),
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

  function responseErrorBody(res: Response, data: any, raw?: string) {
    if (data && typeof data === "object") return data;
    const statusText = `${res.status || "error"} ${(res as any).statusText || ""}`.trim();
    const fallback = raw && raw.trim() ? raw.trim().slice(0, 500) : `HTTP ${statusText}`;
    return { ok: false, status: "error", error: fallback, message: fallback };
  }

  function thrownErrorBody(err: any) {
    return err?.errorBody || err?.body || err?.responseBody || null;
  }

  function stringifyDiagnosticReason(value: any): string {
    if (value === undefined || value === null) return "";
    if (typeof value === "string") return value;
    try { return JSON.stringify(value); } catch { return String(value); }
  }

  function cleanGenerationReason(raw?: any): string {
    let text = stringifyDiagnosticReason(raw).trim();
    if (!text) return "";

    const jsonStart = text.indexOf("{");
    if (jsonStart >= 0) {
      try {
        const parsed = JSON.parse(text.slice(jsonStart));
        const message = parsed?.error?.message || parsed?.message || parsed?.detail;
        if (message) text = String(message);
      } catch {
        // Keep the original text if it is not valid JSON.
      }
    }

    text = text
      .replace(/"user_id"\s*:\s*"[^"]+"/g, '"user_id":"hidden"')
      .replace(/user_[A-Za-z0-9_-]+/g, "user_hidden")
      .replace(/sk-[A-Za-z0-9_-]+/g, "sk_hidden")
      .replace(/\s+/g, " ")
      .trim();

    const lower = text.toLowerCase();
    if (lower.includes("input must have at least 1 token")) {
      return "The model received an empty prompt. Try again or switch models.";
    }

    const capacityPhrases = [
      "resourceexhausted",
      "resource exhausted",
      "request limit reached",
      "worker local total request limit reached",
      "upstream capacity",
      "model is overloaded",
      "temporarily overloaded",
      "temporarily unavailable",
      "no available providers",
      "provider unavailable",
      "service unavailable",
    ];

    if (capacityPhrases.some((phrase) => lower.includes(phrase))) {
      return "The selected model is temporarily at capacity. Try again in a moment or switch models.";
    }

    if ((lower.includes("keyerror") && lower.includes("choices")) || lower.includes("missing choices") || lower.includes("did not return choices")) {
      return "The model provider returned an unexpected response. Try again or switch models.";
    }
    if (lower.includes("complete html document") || lower.includes("incomplete html")) {
      return "The model returned an incomplete HTML file. Try again or switch models.";
    }
    if (lower.includes("json") && (lower.includes("parse") || lower.includes("decode") || lower.includes("invalid"))) {
      return "The model returned malformed JSON. Try again or switch models.";
    }
    if (lower.includes("rate limit") || lower.includes("too many requests") || lower.includes("429")) {
      return "The model provider is rate-limiting requests. Wait a moment or switch models.";
    }
    if (lower.includes("unauthorized") || lower.includes("invalid api key") || lower.includes("401")) {
      return "The API key was rejected. Check the key in Settings.";
    }
    if (lower.includes("forbidden") || lower.includes("403")) {
      return "The model provider blocked this request. Try a different model or rephrase the prompt.";
    }
    if (lower.includes("timeout") || lower.includes("timed out")) {
      return "The request took too long. Try again or switch models.";
    }
    if (lower.includes("ffmpeg")) {
      return "The media export step failed. Try again, or check the backend terminal for details.";
    }

    return text.length > 220 ? `${text.slice(0, 220).trim()}…` : text;
  }

  function formatGenerationError(label: string, errorBody?: any, fallbackReason?: string) {
    const d = errorBody?.diagnostics;
    const lines = [`❌ ${t("chat.msg.failed", { kind: label })}`, ""];

    if (d?.step) lines.push(`Step: ${d.step}`);

    const reason = cleanGenerationReason(
      errorBody?.error ?? errorBody?.message ?? errorBody?.detail ?? fallbackReason
    );
    if (reason) lines.push(`Reason: ${reason}`);

    const technicalDetails = [d?.provider, d?.model].filter(Boolean).join(" · ");
    if (technicalDetails) {
      lines.push("", `Technical details: ${technicalDetails}`);
    }

    const generationDiagnostics = normalizeGenerationDiagnostics(
      errorBody?.generation_diagnostics,
    );
    if (generationDiagnostics?.recovery_stages?.length) {
      lines.push(
        "",
        `Recovery attempted: ${generationDiagnostics.recovery_stages
          .map(humanizeDiagnosticToken)
          .join(" → ")}`,
      );
    }
    if (generationDiagnostics?.failure_stage) {
      lines.push(
        `Final stage: ${humanizeDiagnosticToken(
          generationDiagnostics.failure_stage,
        )}`,
      );
    }
    if (typeof generationDiagnostics?.llm_calls === "number") {
      lines.push(`Model calls used: ${generationDiagnostics.llm_calls}`);
    }
    if (typeof generationDiagnostics?.total_tokens === "number" && generationDiagnostics.total_tokens > 0) {
      lines.push(`Tokens used: ${generationDiagnostics.total_tokens.toLocaleString()}`);
    }
    if (typeof generationDiagnostics?.estimated_cost_usd === "number") {
      if (generationDiagnostics.pricing_complete) {
        lines.push(`Estimated model cost: ${compactEstimatedCost(generationDiagnostics.estimated_cost_usd)}`);
      } else if ((generationDiagnostics.unpriced_calls || 0) > 0) {
        lines.push(
          generationDiagnostics.estimated_cost_usd > 0
            ? `Estimated known model cost: ${compactEstimatedCost(generationDiagnostics.estimated_cost_usd)} (${generationDiagnostics.unpriced_calls} unpriced call${generationDiagnostics.unpriced_calls === 1 ? "" : "s"})`
            : `Model cost unavailable for ${generationDiagnostics.unpriced_calls} call${generationDiagnostics.unpriced_calls === 1 ? "" : "s"}.`,
        );
      }
    }

    return lines.join("\n").trimEnd();
  }

  async function generateVideo(
    prompt: string,
    chatIdOverride?: string | number | null,
    storyOptions?: { host_character?: string; theme?: string },
    requestAudience: AudienceLevel | undefined = undefined,
    images: GenerationImagePayload[] = [],
    requestedMode: "standard" | "story" = "standard",
  ) {
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
      setApiError(t("chat.msg.noActiveChat"));
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
    setHtmlDownloadUrl(null);
    setHtmlDownloadFilename(null);
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
      const llmConfig = buildLlmRequestConfig(apiKeys);
      const sourceLabel = prompt || images.map((image) => image.name).filter(Boolean).join(", ") || "Image learning request";

      // assign a client job id so backend can cancel the right process
      const jobId = makeJobId();
      currentVideoJobId.current = jobId;
    setActiveVideoJobId(jobId);
      const sessionId = ensureChatSessionId();
      const body = {
        prompt,
        keys: llmConfig.keys,
        provider: llmConfig.provider, // "" -> undefined
        model: llmConfig.model,
        mode: requestedMode,
        audience: requestAudience,
        customContext: currentCustomContext(),
        images,
        storyOptions: requestedMode === "story" ? (storyOptions || {}) : undefined,
        jobId,
        sessionId,
      };

      console.debug("POST /generate", { ...body, images: images.map((image) => ({ mimeType: image.mimeType, name: image.name })) });

      const controller = new AbortController();
      videoAbortRef.current = controller;
      const res = await apiFetch("/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, chatId: chatIdForGeneration }),
        signal: controller.signal,
      });

      const { data, raw } = await parseResponse(res);
      const clarificationMessage = clarificationMessageFrom(data);
      if (clarificationMessage) {
        setApiError(null);
        await processAndAddMessage(clarificationMessage, false, undefined, chatIdForGeneration);
        return;
      }

      if (res.ok && data?.status === "ok") {
        if (requestedMode === "story" && data?.widget_html) {
          const storyDownloadUrl = toPlayableMediaUrl(data.download_url);
          const storyDownloadFilename = data.download_filename || htmlFilenameFromTitle(`Story Scenes: ${sourceLabel.slice(0, 50)}`, "upcurved_story.html");
          const mediaAttachment: import('@/types').MediaAttachment = {
            type: 'widget',
            artifactKind: 'story' as any,
            url: storyDownloadUrl,
            widgetCode: data.widget_html,
            title: `Story Scenes: ${sourceLabel.slice(0, 50)}...`,
            downloadFilename: storyDownloadFilename,
            generationDiagnostics: normalizeGenerationDiagnostics(
              data.generation_diagnostics,
            ),
          };
          setCurrentMediaMeta({ type: 'widget', artifactKind: 'story' });
          setWidgetHtml(data.widget_html);
          setHtmlDownloadUrl(storyDownloadUrl || null);
          setHtmlDownloadFilename(storyDownloadFilename || null);
          await processAndAddMessage(
            `✅ ${t("chat.msg.generated", { kind: t("artifact.storySlider") })}`,
            false,
            mediaAttachment,
            chatIdForGeneration
          );
          setVideoUrl(null);
          setVttUrl(null);
          setSrtText(null);
          return;
        }

        // Show toast when initial try failed and first retry starts (tries === 1)
        if (data.tries === 1) {
          toast({
            title: t("toast.mayTakeAWhile"),
            duration: 5000
          });
        }

        // Use signed URL if available, otherwise use regular URL
        const videoUrl = toPlayableMediaUrl(data.signed_video_url || data.video_url) || "";
        setVideoUrl(videoUrl);
        setCurrentMediaMeta({ artifactId: data.artifact_id, gcsPath: data.gcs_path, type: 'video', artifactKind: 'video', title: sourceLabel });
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
          artifactKind: 'video' as any,
          url: videoUrl,
          subtitleUrl: toPlayableMediaUrl(data.signed_subtitle_url),
          title: `${requestedMode === "story" ? "Story Video" : "Video"}: ${sourceLabel.slice(0, 50)}...`,
          artifactId: data.artifact_id,
          gcsPath: data.gcs_path,
          sceneCode: data.scene_code,  // Store scene code for video editing
          generationDiagnostics: normalizeGenerationDiagnostics(
            data.generation_diagnostics,
          ),
        };

        // Use the same chat ID we started with to ensure message goes to correct chat
        await processAndAddMessage(
          requestedMode === "story" ? `✅ ${t("chat.msg.generated", { kind: t("artifact.storyVideo") })}` : `✅ ${t("chat.msg.generated", { kind: t("artifact.video") })}`,
          false,
          mediaAttachment,
          chatIdForGeneration
        );

        // Captions for video: attempt fetch using helper
        // Clear old captions first
        setVttUrl(null);
        setSrtText(null);
        void fetchCaptions(videoUrl, data.signed_subtitle_url);
      } else {
        const errorBody = responseErrorBody(res, data, raw);
        const friendly = formatGenerationError(
          "Video generation",
          errorBody,
          "Video generation failed."
        );

        setApiError(friendly);
        await processAndAddMessage(
          friendly,
          false,
          undefined,
          chatIdForGeneration
        );

        const debugDetail =
          data &&
          typeof data === "object" &&
          "debug_detail" in data
            ? String((data as any).debug_detail || "").trim()
            : "";

        if (debugDetail) {
          toast({
            title: t("toast.renderDetail"),
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
        await processAndAddMessage(`⏹️ ${t("chat.msg.canceled", { kind: t("artifact.video") })}`, false, undefined, chatIdForGeneration);
        aborted = true;
      } else {
        const networkMsg = err?.message && /Failed to fetch|NetworkError|TypeError/i.test(err.message)
          ? "We couldn't reach the server. Check your connection and try again."
          : (err?.message || "Request failed");
        setApiError(networkMsg);
        await processAndAddMessage(`❌ ${t("chat.msg.networkError")}`, false, undefined, chatIdForGeneration);
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

  const handleVideoGenerateClick = async (
    requestedMode: "standard" | "story",
  ) => {
    // Preserve existing stop behavior when already generating.
    if (busy) {
      await generateVideoFromPrompt(undefined, undefined, requestedMode);
      return;
    }
    if (requestedMode !== "story") {
      await generateVideoFromPrompt(undefined, undefined, "standard");
      return;
    }
    // Story selection: collect optional host/theme first.
    setStoryConfigOpen(true);
  };

  const confirmStoryConfigAndGenerate = async () => {
    setStoryConfigOpen(false);
    const opts: { host_character?: string; theme?: string } = {};
    if (storyHostChoice !== "auto") {
      const hostMap: Record<string, string> = {
        scientist: "scientist",
        friendly_robot: "friendly robot",
        animal_guide: "animal guide",
        explorer: "explorer",
        artist: "artist",
        athlete: "athlete",
      };
      opts.host_character = hostMap[storyHostChoice] || undefined;
    }
    if (storyThemeChoice !== "auto") {
      const themeMap: Record<string, string> = {
        space: "space",
        jungle: "jungle",
        ocean: "ocean",
        city_lab: "city lab",
        sunset_farm: "sunset farm",
        meadow: "meadow",
      };
      opts.theme = themeMap[storyThemeChoice] || undefined;
    }
    await generateVideoFromPrompt(undefined, opts, "story");
  };

  async function handleSelectedGeneration() {
    switch (generationType) {
      case "static_worksheet":
        await generateWidgetFromPrompt("static_worksheet");
        return;
      case "video":
        await handleVideoGenerateClick("standard");
        return;
      case "story":
        await handleVideoGenerateClick("story");
        return;
      case "podcast_single":
        await generatePodcastFromPrompt("standard");
        return;
      case "podcast_debate":
        await generatePodcastFromPrompt("debate");
        return;
      case "quiz":
        await generateQuiz();
        return;
      case "widget":
        await generateWidgetFromPrompt("widget");
        return;
      case "diagram":
        await generateWidgetFromPrompt("diagram");
        return;
      default:
        return;
    }
  }

  // Handle quiz generation directly from media (video or podcast)
  async function handleQuizMediaDirect(msg: any) {
    if (!msg.media?.subtitleUrl) {
      const mediaType = msg.media?.type === 'audio' ? 'podcast' : 'video';
      toast({ title: t("toast.noCaptions"), description: `This ${mediaType} needs captions. Regenerate it to add captions.`, duration: 4000 });
      return;
    }

    if (!ensureLlmKey("quiz")) return;
    const requestAudience = audienceLevel === "auto" ? undefined : audienceLevel;

    stopPlayback();
    setQuizLoading(true);
    setApiError(null);

    const llmConfig = buildLlmRequestConfig(apiKeys);

    let persistedId: string | undefined;

    try {
      // Get media filename/title for the user prompt
      const mediaTitle = msg.media?.title || (msg.media?.type === 'audio' ? 'podcast' : 'video');
      const userPrompt = `❓ Quiz from ${mediaTitle}`;

      // Ensure we have a persisted chat
      persistedId = await ensurePersistedActiveChat(userPrompt);
      const finalChatId = persistedId || activeChatId;
      if (!finalChatId) {
        toast({ title: t("toast.unableToStartChat"), description: t("toast.signInAgain"), duration: 4000 });
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
        provider: llmConfig.provider,
        model: llmConfig.model,
        provider_keys: llmConfig.keys,
        chatId: String(finalChatId),
        jobId: makeJobId(),
        audience: requestAudience,
        customContext: currentCustomContext(),
      } as any, videoAbort.signal);

      // Store quiz data like embedded quiz for interactive UI
      const quizChatId = persistedId || activeChatId;
      if (quizChatId && response.quiz?.questions?.length) {
        const quizPayload = {
          ...response.quiz,
          downloadUrl: toPlayableMediaUrl(response.download_url),
          downloadFilename: response.download_filename,
          generationDiagnostics: normalizeGenerationDiagnostics(response.generation_diagnostics),
        };
        const quizTitle = (quizPayload?.title as string) || 'Media Quiz';
        const quizMsgId = await processAndAddMessage('', false, undefined, String(quizChatId), {
          quizAnchor: true,
          quizTitle,
          quizData: quizPayload
        });

        if (quizMsgId) {
          // Initialize runtime for this quiz
          setQuizzesByChat(prev => ({
            ...prev,
            [String(quizChatId)]: {
              ...(prev[String(quizChatId)] || {}),
              [quizMsgId]: { data: quizPayload, index: 0, answers: [], score: null, selected: null, revealed: false }
            }
          }));
        }
      } else {
        await processAndAddMessage(formatGenerationError('Quiz generation', response, 'Quiz response did not include questions.'), false, undefined, persistedId);
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        const body = thrownErrorBody(err);
        const friendly = formatGenerationError('Quiz generation', body, err?.message || 'Request failed');
        setApiError(friendly);
        toast({ title: t("toast.quizFailed"), description: err.message, duration: 4000 });
        await processAndAddMessage(friendly, false, undefined, persistedId);
      } else {
        await processAndAddMessage('⏹️ Canceled quiz generation.', false, undefined, persistedId);
      }
    } finally {
      setQuizLoading(false);
      quizAbortRef.current = null;
    }
  }


  async function handleQuizHtmlArtifactDirect(msg: any) {
    const media = msg.media;
    const kind = normalizeArtifactKind(media, msg);
    if (!media?.widgetCode || (kind !== 'story' && kind !== 'widget' && kind !== 'static_worksheet' && kind !== 'diagram')) {
      toast({ title: t("toast.cannotGenerateQuiz"), description: t("toast.noReadableContent"), duration: 4000 });
      return;
    }

    const transcript = (kind === 'diagram'
      ? plainTextFromSvg(media.widgetCode, msg.content)
      : plainTextFromHtml(media.widgetCode, msg.content)
    ).slice(0, 14000);
    if (!transcript || transcript.length < 30) {
      toast({ title: t("toast.cannotGenerateQuiz"), description: t("toast.notEnoughText"), duration: 4000 });
      return;
    }

    if (!ensureLlmKey("quiz")) return;
    const requestAudience = audienceLevel === "auto" ? undefined : audienceLevel;

    stopPlayback();
    setQuizLoading(true);
    setApiError(null);

    const llmConfig = buildLlmRequestConfig(apiKeys);

    let persistedId: string | undefined;

    try {
      const mediaTitle = media.title || (kind === 'story' ? 'story' : kind === 'diagram' ? 'diagram' : kind === 'static_worksheet' ? 'static worksheet' : 'interactive worksheet');
      const userPrompt = `❓ Quiz from ${mediaTitle}`;

      persistedId = await ensurePersistedActiveChat(userPrompt);
      const finalChatId = persistedId || activeChatId;
      if (!finalChatId) {
        toast({ title: t("toast.unableToStartChat"), description: t("toast.signInAgain"), duration: 4000 });
        return;
      }
      setActiveChatId(finalChatId);
      await processAndAddMessage(userPrompt, true, undefined, persistedId);

      const controller = new AbortController();
      quizAbortRef.current = controller;

      const response = await apiQuiz({
        transcript,
        sceneCode: "",
        provider: llmConfig.provider,
        model: llmConfig.model,
        provider_keys: llmConfig.keys,
        chatId: String(finalChatId),
        jobId: makeJobId(),
        audience: requestAudience,
        customContext: currentCustomContext(),
      } as any, controller.signal);

      const quizChatId = persistedId || activeChatId;
      if (quizChatId && response.quiz?.questions?.length) {
        const quizPayload = {
          ...response.quiz,
          downloadUrl: toPlayableMediaUrl(response.download_url),
          downloadFilename: response.download_filename,
          generationDiagnostics: normalizeGenerationDiagnostics(response.generation_diagnostics),
        };
        const quizTitle = (quizPayload?.title as string) || `${artifactLabel(kind)} Quiz`;
        const quizMsgId = await processAndAddMessage('', false, undefined, String(quizChatId), {
          quizAnchor: true,
          quizTitle,
          quizData: quizPayload,
        });

        if (quizMsgId) {
          setQuizzesByChat(prev => ({
            ...prev,
            [String(quizChatId)]: {
              ...(prev[String(quizChatId)] || {}),
              [quizMsgId]: { data: quizPayload, index: 0, answers: [], score: null, selected: null, revealed: false }
            }
          }));
        }
      } else {
        await processAndAddMessage(formatGenerationError('Quiz generation', response, 'Quiz response did not include questions.'), false, undefined, persistedId);
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        const body = thrownErrorBody(err);
        const friendly = formatGenerationError('Quiz generation', body, err?.message || 'Request failed');
        setApiError(friendly);
        toast({ title: t("toast.quizFailed"), description: err.message, duration: 4000 });
        await processAndAddMessage(friendly, false, undefined, persistedId);
      } else {
        await processAndAddMessage('⏹️ Canceled quiz generation.', false, undefined, persistedId);
      }
    } finally {
      setQuizLoading(false);
      quizAbortRef.current = null;
    }
  }

  async function handleEditNonVideoArtifact(kind: ArtifactKind) {
    if (!isEditMode || !quotedMessage) {
      toast({ title: t("toast.nothingSelected"), description: t("toast.selectArtifactFirst"), duration: 4000 });
      return;
    }

    const editInstructions = query.trim();
    if (!editInstructions) {
      toast({ title: t("toast.enterEditInstructions"), description: t("toast.describeChanges"), duration: 4000 });
      return;
    }

    if (!ensureLlmKey("edit")) return;
    const requestAudience = audienceLevel === "auto" ? undefined : audienceLevel;

    const llmConfig = buildLlmRequestConfig(apiKeys);

    const chatIdForGeneration = typeof activeChatId === 'string' ? activeChatId : String(activeChatId);
    if (!chatIdForGeneration || chatIdForGeneration === "null") {
      toast({ title: t("toast.noActiveChat"), description: t("toast.openChatAndRetry"), duration: 4000 });
      return;
    }

    const sourceTitle = quotedMessage.media?.title || quotedMessage.quizData?.title || artifactLabel(kind);
    const userEditMessage = `✏️ Edit ${artifactLabel(kind)}: ${editInstructions}`;

    try {
      await processAndAddMessage(userEditMessage, true, undefined, chatIdForGeneration);
      setQuery("");

      if (kind === 'widget' || kind === 'static_worksheet' || kind === 'story' || kind === 'diagram') {
        const originalSource = quotedMessage.media?.widgetCode || '';
        if (!originalSource.trim()) {
          toast({
            title: t("toast.cannotEdit"),
            description: kind === 'diagram' ? t("toast.svgSourceMissing") : t("toast.htmlSourceMissing"),
            duration: 4000,
          });
          return;
        }

        setWidgetLoading(true);
        const controller = new AbortController();
        widgetAbortRef.current = controller;
        const endpoint = kind === 'story' ? '/edit/story' : kind === 'diagram' ? '/edit/diagram' : kind === 'static_worksheet' ? '/edit/static_worksheet' : '/edit/widget';
        const res = await apiFetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            // The shared edit request model calls this field original_html; Diagram sends SVG here.
            original_html: originalSource,
            edit_instructions: editInstructions,
            original_title: sourceTitle,
            keys: llmConfig.keys,
            provider: llmConfig.provider,
            model: llmConfig.model,
            audience: requestAudience,
            customContext: currentCustomContext(),
            sessionId: ensureChatSessionId(),
            jobId: makeJobId(),
            chatId: String(chatIdForGeneration),
          }),
          signal: controller.signal,
        });
        const { data, raw } = await parseResponse(res);
        const revisedSource = kind === 'diagram' ? data?.svg_code : kind === 'static_worksheet' ? data?.worksheet_html : data?.widget_html;

        if (res.ok && data?.status === 'ok' && revisedSource) {
          const downloadUrl = toPlayableMediaUrl(data.download_url);
          const downloadFilename = data.download_filename || (
            kind === 'diagram'
              ? svgFilenameFromTitle(`upcurved_edited_diagram_${sourceTitle}`)
              : htmlFilenameFromTitle(
                  `Edited ${artifactLabel(kind)}: ${sourceTitle}`,
                  kind === 'story' ? 'upcurved_story.html' : kind === 'static_worksheet' ? 'upcurved_static_worksheet.html' : 'upcurved_interactive_worksheet.html',
                )
          );
          const titlePrefix =
            kind === 'story'
              ? 'Edited Story'
              : kind === 'diagram'
              ? 'Edited Diagram'
              : kind === 'static_worksheet'
              ? 'Edited Static Worksheet'
              : 'Edited Interactive Worksheet';
          const mediaAttachment: import('@/types').MediaAttachment = {
            type: 'widget',
            artifactKind: kind as any,
            url: downloadUrl,
            widgetCode: revisedSource,
            worksheetId: kind === 'static_worksheet' ? String(data.worksheet_id || "") : undefined,
            title: `${titlePrefix}: ${sourceTitle}`,
            downloadFilename,
            generationDiagnostics: normalizeGenerationDiagnostics(data.generation_diagnostics),
          };
          await processAndAddMessage(`✅ ${kind === 'story' ? 'Story' : kind === 'diagram' ? 'Diagram' : kind === 'static_worksheet' ? 'Static worksheet' : 'Interactive worksheet'} edited successfully.`, false, mediaAttachment, chatIdForGeneration);
          setVideoUrl(null);
          setCurrentMediaMeta({ type: 'widget', artifactKind: kind, title: mediaAttachment.title, worksheetId: mediaAttachment.worksheetId });
          setWidgetHtml(revisedSource);
          setHtmlDownloadUrl(downloadUrl || null);
          setHtmlDownloadFilename(downloadFilename || null);
        } else {
          const errorBody = responseErrorBody(res, data, raw);
          await processAndAddMessage(formatGenerationError(`${artifactLabel(kind)} editing`, errorBody), false, undefined, chatIdForGeneration);
        }
      } else if (kind === 'quiz') {
        const originalQuiz = quotedMessage.quizData;
        if (!originalQuiz?.questions?.length) {
          toast({ title: t("toast.cannotEdit"), description: t("toast.quizJsonMissing"), duration: 4000 });
          return;
        }

        setQuizLoading(true);
        const controller = new AbortController();
        quizAbortRef.current = controller;
        const res = await apiFetch('/edit/quiz', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            original_quiz: originalQuiz,
            edit_instructions: editInstructions,
            num_questions: originalQuiz.questions?.length || 5,
            difficulty: 'medium',
            keys: llmConfig.keys,
            provider: llmConfig.provider,
            model: llmConfig.model,
            audience: requestAudience,
            customContext: currentCustomContext(),
            sessionId: ensureChatSessionId(),
            jobId: makeJobId(),
            chatId: String(chatIdForGeneration),
          }),
          signal: controller.signal,
        });
        const { data, raw } = await parseResponse(res);

        if (res.ok && data?.status === 'ok' && data?.quiz?.questions?.length) {
          const quizPayload = {
            ...data.quiz,
            downloadUrl: toPlayableMediaUrl(data.download_url),
            downloadFilename: data.download_filename,
            generationDiagnostics: normalizeGenerationDiagnostics(data.generation_diagnostics),
          };
          const quizTitle = (quizPayload?.title as string) || 'Edited Quiz';
          const quizMsgId = await processAndAddMessage('', false, undefined, String(chatIdForGeneration), {
            quizAnchor: true,
            quizTitle,
            quizData: quizPayload,
          });
          if (quizMsgId) {
            setQuizzesByChat(prev => ({
              ...prev,
              [String(chatIdForGeneration)]: {
                ...(prev[String(chatIdForGeneration)] || {}),
                [quizMsgId]: { data: quizPayload, index: 0, answers: [], score: null, selected: null, revealed: false }
              }
            }));
          }
        } else {
          const errorBody = responseErrorBody(res, data, raw);
          await processAndAddMessage(formatGenerationError('Quiz editing', errorBody), false, undefined, chatIdForGeneration);
        }
      } else {
        toast({ title: t("toast.unsupportedEdit"), description: t("toast.cannotEditTypeYet"), duration: 4000 });
      }

      setIsEditMode(false);
      setIsQuizMode(false);
      setQuotedMessage(null);
    } catch (err: any) {
      if (err?.name === "AbortError") {
        await processAndAddMessage(`⏹️ ${t("chat.msg.canceledEditing", { kind: artifactLabel(kind) })}`, false, undefined, chatIdForGeneration);
      } else {
        const msg = err?.message || "Request failed";
        const body = thrownErrorBody(err);
        const friendly = formatGenerationError(`${artifactLabel(kind)} editing`, body, msg);
        toast({ title: `${artifactLabel(kind)} edit failed`, description: msg, duration: 4000 });
        await processAndAddMessage(friendly, false, undefined, chatIdForGeneration);
      }
    } finally {
      setWidgetLoading(false);
      setQuizLoading(false);
      widgetAbortRef.current = null;
      quizAbortRef.current = null;
    }
  }



  // Handle video editing in edit mode
  async function handleEditVideo() {
    const selectedKind = quotedMessage?.artifactKind || normalizeArtifactKind(quotedMessage?.media, quotedMessage);
    if (selectedKind && selectedKind !== 'video') {
      await handleEditNonVideoArtifact(selectedKind);
      return;
    }

    if (!isEditMode || !quotedMessage?.media?.sceneCode) {
      toast({ title: t("toast.noVideoToEdit"), description: t("toast.selectVideoFirst"), duration: 4000 });
      return;
    }

    const editInstructions = query.trim();
    if (!editInstructions) {
      toast({ title: t("toast.enterEditInstructions"), description: t("toast.describeChanges"), duration: 4000 });
      return;
    }

    if (!ensureLlmKey("edit")) return;
    const requestAudience = audienceLevel === "auto" ? undefined : audienceLevel;

    // Cancel toggle if already busy
    if (busy && videoAbortRef.current) {
      videoAbortRef.current.abort();
      return;
    }

    stopPlayback();
    setBusy(true);
    setApiError(null);
    setWidgetHtml(null);
    setHtmlDownloadUrl(null);
    setHtmlDownloadFilename(null);
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
      await processAndAddMessage(`✏️ ${t("chat.msg.editPrefix", { instructions: editInstructions })}`, true, undefined, chatIdForGeneration);
      setQuery("");

      const llmConfig = buildLlmRequestConfig(apiKeys);

      const jobId = makeJobId();
      currentVideoJobId.current = jobId;
    setActiveVideoJobId(jobId);
      const sessionId = ensureChatSessionId();

      const body = {
        original_code: quotedMessage.media.sceneCode,
        edit_instructions: editInstructions,
        keys: llmConfig.keys,
        provider: llmConfig.provider,
        model: llmConfig.model,
        audience: requestAudience,
        customContext: currentCustomContext(),
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
        // An edit keeps the original video's name; the new artifact id keeps it distinct.
        setCurrentMediaMeta((prev) => ({ artifactId: data.artifact_id, gcsPath: data.gcs_path, type: 'video', artifactKind: 'video', title: prev?.title || editInstructions }));
        setSubtitleLang((data.lang as string) || undefined);

        const mediaAttachment: import('@/types').MediaAttachment = {
          type: 'video',
          artifactKind: 'video' as any,
          url: videoUrl,
          subtitleUrl: toPlayableMediaUrl(data.signed_subtitle_url),
          title: `Edited Video: ${editInstructions.slice(0, 30)}...`,
          artifactId: data.artifact_id,
          gcsPath: data.gcs_path,
          sceneCode: data.scene_code,
          generationDiagnostics: normalizeGenerationDiagnostics(
            data.generation_diagnostics,
          ),
        };

        await processAndAddMessage(`✅ ${t("chat.msg.edited", { kind: t("artifact.video") })}`, false, mediaAttachment, chatIdForGeneration);

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
        await processAndAddMessage(`❌ ${t("chat.msg.editFailed", { kind: t("artifact.video"), reason: msg })}`, false, undefined, chatIdForGeneration);
      }
    } catch (err: any) {
      console.error("Video edit error:", err);
      if (err?.name === "AbortError") {
        setApiError(null);
        await processAndAddMessage(`⏹️ ${t("chat.msg.canceledEditing", { kind: t("artifact.video") })}`, false, undefined, chatIdForGeneration);
        aborted = true;
      } else {
        const networkMsg = err?.message && /Failed to fetch|NetworkError|TypeError/i.test(err.message)
          ? "We couldn't reach the server. Check your connection and try again."
          : (err?.message || "Request failed");
        setApiError(networkMsg);
        await processAndAddMessage(`❌ ${t("chat.msg.error", { reason: networkMsg })}`, false, undefined, chatIdForGeneration);
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

  // Load the newest server page and reconcile it through the one canonical
  // message-ordering path. Historical messages never receive Date.now() as a
  // fallback, so reopening a chat cannot move them to the bottom.
  useEffect(() => {
    let cancelled = false;

    async function loadMessagesPage() {
      if (
        typeof activeChatId !== "string"
        || activeChatId.startsWith("local-")
        || activeChatId.startsWith("draft-")
      ) {
        const localMessages = activeChat.messages || [];
        const lastBotMessage = [...localMessages]
          .reverse()
          .find((message) => message.role === "bot");
        setActiveScript(lastBotMessage?.content || null);
        setIsPlaying(false);
        setProgress([0]);
        return;
      }

      try {
        const page = await apiListMessages(activeChatId, undefined, {
          limit: PAGE_SIZE,
        });
        if (cancelled) return;

        const cacheKey = String(activeChatId);
        const mapped = (page?.messages || []).map(mapApiMessage);
        const existing =
          messagesCache.current[cacheKey]
          || chats.find((chat) => String(chat.id) === cacheKey)?.messages
          || [];
        const merged = mapped.length
          ? mergeMessages(existing, mapped)
          : [...existing];

        messagesCache.current[cacheKey] = merged;
        setChats((previous) =>
          previous.map((chat) =>
            String(chat.id) === cacheKey
              ? { ...chat, messages: merged }
              : chat,
          ),
        );
        restoreQuizMessages(cacheKey, merged);

        const serverTimes = mapped
          .map((message) => message.createdAt)
          .filter((value): value is number => Number.isFinite(value));
        const before = serverTimes.length ? Math.min(...serverTimes) : undefined;
        setCursorByChat((previous) => ({ ...previous, [cacheKey]: before }));
        setHasMoreByChat((previous) => ({
          ...previous,
          [cacheKey]: Boolean(page?.has_more),
        }));

        const lastBotMessage = [...merged]
          .reverse()
          .find((message) => message.role === "bot");
        setActiveScript(lastBotMessage?.content || null);
        setIsPlaying(false);
        setProgress([0]);

        requestAnimationFrame(() => {
          const container = scrollContainerRef.current;
          if (container) container.scrollTop = container.scrollHeight;
        });
      } catch {
        // Keep the current local/cache view if the refresh fails.
      }
    }

    void loadMessagesPage();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChatId]);

  const loadOlderMessages = async () => {
    if (typeof activeChatId !== "string") return;
    const cacheKey = String(activeChatId);
    const before = cursorByChat[cacheKey];

    try {
      const page = await apiListMessages(cacheKey, undefined, {
        limit: PAGE_SIZE,
        before,
      });
      const mapped = (page?.messages || []).map(mapApiMessage);
      if (!mapped.length) {
        setHasMoreByChat((previous) => ({
          ...previous,
          [cacheKey]: false,
        }));
        return;
      }

      const current =
        messagesCache.current[cacheKey]
        || chats.find((chat) => String(chat.id) === cacheKey)?.messages
        || [];
      const merged = mergeMessages(current, mapped);
      messagesCache.current[cacheKey] = merged;
      setChats((previous) =>
        previous.map((chat) =>
          String(chat.id) === cacheKey
            ? { ...chat, messages: merged }
            : chat,
        ),
      );
      restoreQuizMessages(cacheKey, merged);

      const serverTimes = mapped
        .map((message) => message.createdAt)
        .filter((value): value is number => Number.isFinite(value));
      const newBefore = serverTimes.length
        ? Math.min(...serverTimes)
        : before;
      setCursorByChat((previous) => ({
        ...previous,
        [cacheKey]: newBefore,
      }));
      setHasMoreByChat((previous) => ({
        ...previous,
        [cacheKey]: Boolean(page?.has_more),
      }));
    } catch {
      // Keep the already loaded messages unchanged.
    }
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
  const sanitizeDownloadFilename = (name?: string, fallback = "upcurved_export.html") => {
    const cleaned = String(name || fallback)
      .trim()
      .replace(/[^\w.\-]+/g, "_")
      .replace(/_+/g, "_");
    if (/\.[a-z0-9]{2,6}$/i.test(cleaned)) return cleaned;
    const fallbackExtension = String(fallback).match(/(\.[a-z0-9]{2,6})$/i)?.[1] || ".html";
    return `${cleaned}${fallbackExtension}`;
  };

  const handleHtmlDownload = async (downloadUrl?: string, filename?: string) => {
    if (currentMediaMeta?.artifactKind === "static_worksheet" && widgetHtml) {
      try {
        const worksheetId = currentMediaMeta.worksheetId || "static_worksheet";
        const prepared = prepareStaticWorksheetHtml(widgetHtml, worksheetId);
        const blob = new Blob([prepared], { type: "text/html;charset=utf-8" });
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = sanitizeDownloadFilename(
          filename || "upcurved_static_worksheet.html",
          "upcurved_static_worksheet.html",
        );
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
        return;
      } catch (error) {
        console.error("Static worksheet HTML export failed", error);
      }
    }

    if (!downloadUrl) {
      toast({
        title: t("toast.downloadUnavailable"),
        description: t("toast.downloadUnavailable.body"),
        duration: 4000,
      });
      return;
    }

    try {
      const resolvedUrl = apiUrl(downloadUrl);
      const response = await fetch(resolvedUrl);

      if (!response.ok) {
        throw new Error(`Download failed: ${response.status}`);
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(
        blob.type ? blob : new Blob([blob], { type: currentMediaMeta?.artifactKind === "diagram" ? "image/svg+xml" : "text/html;charset=utf-8" })
      );

      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = sanitizeDownloadFilename(filename);
      document.body.appendChild(link);
      link.click();
      link.remove();

      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) {
      console.error("Artifact download failed", error);
      toast({
        title: t("toast.downloadFailed"),
        description: t("toast.downloadFailed.body"),
        duration: 5000,
      });
    }
  };

  const handleDiagramPngDownload = async () => {
    if (!widgetHtml || currentMediaMeta?.artifactKind !== "diagram") return;
    try {
      const blob = await svgToPngBlob(widgetHtml);
      const objectUrl = URL.createObjectURL(blob);
      const svgName = sanitizeDownloadFilename(
        htmlDownloadFilename || "upcurved_diagram.svg",
        "upcurved_diagram.svg",
      );
      const pngName = svgName.replace(/\.svg$/i, ".png");
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = pngName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error: any) {
      console.error("Diagram PNG export failed", error);
      toast({
        title: t("toast.pngExportFailed"),
        description: error?.message || "The diagram could not be converted to PNG.",
        duration: 5000,
      });
    }
  };

  const handleDownload = async () => {
    if (!videoUrl) return;

    // Lead with the prompt/episode title so a folder of downloads is readable, and
    // suffix the artifact id so separate generations never collide. A date stamp
    // alone produced upcurved_podcast_<today>.mp3 for everything made that day.
    let fileName = buildDownloadFilename({
      title: currentMediaMeta?.title,
      url: videoUrl,
      type: currentMediaMeta?.type === 'video' ? 'video' : 'audio',
      suffix: currentMediaMeta?.artifactId,
    });
    let downloadSource = videoUrl;

    try {
      const hasCaptions = Boolean(vttUrl || srtText || activeScript);
      const shouldBurnCaptions =
        currentMediaMeta?.type === 'video' &&
        isCaptionsOn &&
        hasCaptions;
      const shouldPackageAudioCaptions =
        currentMediaMeta?.type === 'audio' &&
        isCaptionsOn &&
        hasCaptions;

      // activeScript is not always subtitles -- it also holds the bot's plain chat
      // message (see setActiveScript(lastBotMessage?.content)). Prose has no timing
      // cues, so ffmpeg cannot probe it and fails with an opaque "Unable to open".
      // Prefer whichever source is actually timed.
      const hasTimingCues = (value?: string | null) =>
        Boolean(value && /\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->/.test(value));
      let subtitleText = hasTimingCues(activeScript)
        ? activeScript
        : hasTimingCues(srtText)
          ? srtText
          : undefined;

      // If captions are currently displayed from a generated blob URL, the backend
      // cannot fetch that URL directly, so send the caption text in the request.
      if (!subtitleText && vttUrl && /^blob:/i.test(vttUrl)) {
        try {
          const captionResponse = await fetch(vttUrl);
          if (captionResponse.ok) {
            subtitleText = await captionResponse.text();
          }
        } catch {}
      }

      if (shouldBurnCaptions) {
        toast({
          title: 'Preparing captioned video',
          description: 'Burning captions into the MP4. This may take a moment.',
          duration: 5000,
        });

        const captionedFilename = fileName.replace(/\.mp4$/i, '-captions.mp4');
        const burnResponse = await apiFetch('/api/media/burn-captions', {
          method: 'POST',
          body: JSON.stringify({
            video_url: videoUrl,
            subtitle_url: vttUrl && !/^blob:/i.test(vttUrl) ? vttUrl : undefined,
            subtitle_text: subtitleText,
            filename: captionedFilename,
            artifactId: currentMediaMeta?.artifactId,
            gcsPath: currentMediaMeta?.gcsPath,
            chatId: activeChatId != null ? String(activeChatId) : undefined,
          }),
        });

        if (!burnResponse.ok) {
          let detail = `caption burn failed: ${burnResponse.status}`;
          try {
            const payload = await burnResponse.json();
            detail = payload?.error || payload?.detail || payload?.message || detail;
          } catch {}
          throw new Error(detail);
        }

        const burnData = await burnResponse.json();
        downloadSource = apiUrl(burnData.download_url || burnData.signed_video_url || burnData.video_url);
        fileName = burnData.filename || captionedFilename;
      } else if (shouldPackageAudioCaptions) {
        toast({
          title: 'Preparing podcast package',
          description: 'Creating a ZIP with audio, captions, and transcript.',
          duration: 5000,
        });

        const packageFilename = fileName.replace(/\.[a-z0-9]+$/i, '-captions.zip');
        const packageResponse = await apiFetch('/api/media/audio-package', {
          method: 'POST',
          body: JSON.stringify({
            audio_url: videoUrl,
            subtitle_url: vttUrl && !/^blob:/i.test(vttUrl) ? vttUrl : undefined,
            subtitle_text: subtitleText,
            filename: packageFilename,
            artifactId: currentMediaMeta?.artifactId,
            gcsPath: currentMediaMeta?.gcsPath,
            chatId: activeChatId != null ? String(activeChatId) : undefined,
          }),
        });

        if (!packageResponse.ok) {
          let detail = `audio package failed: ${packageResponse.status}`;
          try {
            const payload = await packageResponse.json();
            detail = payload?.error || payload?.detail || payload?.message || detail;
          } catch {}
          throw new Error(detail);
        }

        const packageData = await packageResponse.json();
        downloadSource = apiUrl(packageData.download_url || packageData.signed_download_url);
        fileName = packageData.filename || packageFilename;
      }

      const response = await fetch(downloadSource);
      if (!response.ok) {
        throw new Error('Failed to fetch media');
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
      toast({
        title: 'Download started',
        description: shouldBurnCaptions
          ? 'Captioned video download initiated'
          : shouldPackageAudioCaptions
            ? 'Podcast package download initiated'
            : 'File download initiated',
      });
    } catch (error) {
      console.error('Download failed:', error);
      toast({
        title: 'Download failed',
        description: error instanceof Error ? error.message : 'Could not download the file',
        variant: 'destructive',
      });
    }
  };




  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      // Arrow keys belong to the caret while typing; only scrub otherwise.
      if (isTypingTarget(e.target)) return;
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

  // The backend's stage wins when it has one; the ramp is the fallback.
  // Whether the artifact pane has anything worth opening on a phone: a finished
  // artifact, or a generation in flight whose progress is worth watching.
  const hasArtifactToShow = Boolean(
    videoUrl || widgetHtml || busy || podcastLoading || widgetLoading || quizLoading
  );

  const videoPercent = jobProgress.percent ?? videoProgress;
  const generationPercent = busy
    ? videoPercent
    : widgetLoading
      ? widgetProgress
      : podcastProgress;

  // What the caption says while something is generating. During a video, this is
  // the actual stage — including "scene 3 of 6" — rather than one static line.
  const generationCaption = (() => {
    if (busy) {
      if (jobProgress.stage === "rendering" && jobProgress.total > 0) {
        return t("chat.stage.rendering", {
          done: Math.max(1, jobProgress.done),
          total: jobProgress.total,
        });
      }
      if (jobProgress.stage) return t(`chat.stage.${jobProgress.stage}`);
      return t("chat.rendering.video");
    }
    if (widgetLoading) {
      if (generationType === "diagram") return t("chat.rendering.diagram");
      if (generationType === "static_worksheet") return t("chat.rendering.staticWorksheet");
      return t("chat.rendering.widget");
    }
    return t("chat.rendering.podcast");
  })();

  return (
    <div className="h-screen flex bg-background">
      <AlertDialog
        open={modal.isOpen && modal.type !== "deleteAccount"}
        onOpenChange={(open) => !open && setModal({ isOpen: false, type: "", data: null })}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {modal.type === "logout" ? t("dialog.logout.title") : t("dialog.deleteChat.title")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {modal.type === "logout"
                ? t("dialog.logout.body")
                : t("dialog.deleteChat.body")}
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
      setHtmlDownloadUrl(null);
      setHtmlDownloadFilename(null);
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
        onOpenHelp={() => setHelpOpen(true)}
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
                  <Button variant="secondary" size="sm" onClick={loadOlderMessages}>{t("chat.loadOlder")}</Button>
                </div>
              )}
              {(activeChat as Chat).messages.length === 0 && typeof window !== 'undefined' && sessionStorage.getItem('app.forceBlank') === '1' ? (
                <div className="flex flex-col items-center justify-center h-full text-center">
                  <div className="space-y-4">
                    <div className={`w-16 h-16 rounded-full bg-gradient-to-br ${getThemeGradient(colorTheme)} flex items-center justify-center mx-auto`}>
                      <MessageSquare className="w-8 h-8 text-white" />
                    </div>
                    <h2 className="text-2xl font-semibold">Hello, {user.name}</h2>
                    <p className="text-muted-foreground">{t("chat.greeting")}</p>
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
                          {msg.media?.generationDiagnostics && (
                            <GenerationDiagnosticsPanel
                              diagnostics={msg.media.generationDiagnostics}
                            />
                          )}
                          {/* Copy button - appears on hover */}
                          {msg.media && msg.media.type === 'widget' && msg.media.widgetCode && (
                            <div
                              className={`mt-3 bg-card border rounded-lg p-3 cursor-pointer hover:bg-accent transition-colors ${busy ? 'opacity-50 pointer-events-none' : ''}`}
                              onClick={() => { if (!busy && !podcastLoading && !quizLoading && !widgetLoading) void openMediaFromMessage(msg); }}
                              title={normalizeArtifactKind(msg.media, msg) === "diagram" ? "Open diagram" : normalizeArtifactKind(msg.media, msg) === "static_worksheet" ? "Open static worksheet" : "Open interactive worksheet"}
                            >
                              <div className="flex items-center gap-3">
                                <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 bg-gradient-to-br ${getThemeGradient(colorTheme)}`}>
                                  <Zap className="w-5 h-5 text-white" />
                                </div>
                                <div className="flex-1 min-w-0">
                                  <p className="font-medium text-sm truncate">
                                    {msg.media.title ||
                                      (normalizeArtifactKind(msg.media, msg) === "diagram"
                                        ? t("chat.gen.diagram")
                                        : normalizeArtifactKind(msg.media, msg) === "static_worksheet"
                                          ? t("chat.gen.static_worksheet")
                                          : t("chat.gen.widget"))}
                                  </p>
                                  <p className="text-xs text-muted-foreground">
                                    {t("chat.card.openHint")}
                                  </p>
                                </div>
                                <ExternalLink className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                              </div>
                            </div>
                          )}
                          {/* Follow-up actions. Downloads live only in the right panel. */}
                          {msg.media && msg.media.type === 'audio' && msg.media.subtitleUrl && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute top-2 right-10 opacity-0 group-hover:opacity-100 h-7 w-7"
                              onClick={() => void handleQuizMediaDirect(msg)}
                              title={t("chat.quizFrom", { kind: t("artifact.podcast") })}
                              disabled={busy || podcastLoading || quizLoading || widgetLoading}
                            >
                              <Brain className="w-4 h-4" />
                            </Button>
                          )}

                          {msg.media && msg.media.type === 'video' && (
                            <>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="absolute top-2 right-16 opacity-0 group-hover:opacity-100 h-7 w-7"
                                onClick={() => {
                                  if (!msg.media?.subtitleUrl) {
                                    toast({ title: t("toast.noCaptions"), description: t("toast.noCaptions.body"), duration: 4000 });
                                    return;
                                  }
                                  void handleQuizMediaDirect(msg);
                                }}
                                title={t("chat.quizFrom", { kind: t("artifact.video") })}
                                disabled={busy || podcastLoading || quizLoading || widgetLoading}
                              >
                                <Brain className="w-4 h-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="absolute top-2 right-10 opacity-0 group-hover:opacity-100 h-7 w-7"
                                onClick={() => startEditArtifact(msg, index, 'video')}
                                title={t("chat.editVideo")}
                                disabled={busy || podcastLoading || quizLoading || widgetLoading}
                              >
                                <Pencil className="w-4 h-4" />
                              </Button>
                            </>
                          )}

                          {msg.media && msg.media.type === 'widget' && msg.media.widgetCode && (
                            <>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="absolute top-2 right-16 opacity-0 group-hover:opacity-100 h-7 w-7"
                                onClick={() => void handleQuizHtmlArtifactDirect(msg)}
                                title={t("chat.quizFrom", { kind: artifactLabel(normalizeArtifactKind(msg.media, msg)) })}
                                disabled={busy || podcastLoading || quizLoading || widgetLoading}
                              >
                                <Brain className="w-4 h-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="absolute top-2 right-10 opacity-0 group-hover:opacity-100 h-7 w-7"
                                onClick={() => startEditArtifact(msg, index, normalizeArtifactKind(msg.media, msg))}
                                title={t("chat.editArtifact", { kind: artifactLabel(normalizeArtifactKind(msg.media, msg)) })}
                                disabled={busy || podcastLoading || quizLoading || widgetLoading}
                              >
                                <Pencil className="w-4 h-4" />
                              </Button>
                            </>
                          )}

                          {msg.content && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 h-7 w-7"
                              onClick={() => copyToClipboard(msg.content, (msg as any).messageId || `bot-${index}`)}
                              title={t("chat.copyMessage")}
                            >
                              {copiedMessageId === ((msg as any).messageId || `bot-${index}`) ? (
                                <Check className="w-4 h-4" />
                              ) : (
                                <Copy className="w-4 h-4" />
                              )}
                            </Button>
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
                            title={t("chat.copyMessage")}
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

                    {/* If this message anchors a quiz, render the quiz card right after it.
                        The wrapper is a column: the diagnostics line belongs under the card,
                        not beside it — as a row, the two max-w-lg children shared the width
                        and squeezed the quiz. */}
                    {typeof activeChatId === 'string' && (msg as any).messageId && quizzesByChat[String(activeChatId)] && quizzesByChat[String(activeChatId)][String((msg as any).messageId)] && (
                      <div className="flex w-full flex-col items-start gap-2">
                        {(() => { const quiz = quizzesByChat[String(activeChatId)][String((msg as any).messageId)]; const quizId = String((msg as any).messageId); return (
                          <div className={`rounded-xl p-5 w-full max-w-lg bg-gradient-to-br ${getThemeGradient(colorTheme)} text-white shadow-lg`}>
                            {quiz.score == null ? (
                              <div>
                                <div className="flex items-start justify-between gap-3 mb-2">
                                  <h3 className="font-semibold flex items-center gap-2"><span>📝</span>{quiz.data.title || 'Quiz'}</h3>
                                  <div className="flex items-center gap-1 shrink-0">
                                    <Button
                                      variant="secondary"
                                      size="icon"
                                      className="h-7 w-7"
                                      onClick={() => startEditArtifact({ messageId: quizId, content: '', quizAnchor: true, quizData: quiz.data }, index, 'quiz', quiz.data)}
                                      title={t("chat.editQuiz")}
                                      disabled={busy || podcastLoading || quizLoading || widgetLoading}
                                    >
                                      <Pencil className="w-3 h-3" />
                                    </Button>
                                    {quiz.data.downloadUrl && (
                                      <Button
                                        variant="secondary"
                                        size="sm"
                                        className="h-7 text-xs"
                                        onClick={() => handleHtmlDownload(quiz.data.downloadUrl, quiz.data.downloadFilename || htmlFilenameFromTitle(quiz.data.title, "upcurved_quiz.html"))}
                                      >
                                        <Download className="w-3 h-3 mr-1" /> HTML
                                      </Button>
                                    )}
                                  </div>
                                </div>
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
                                <div className="flex items-start justify-between gap-3 mb-2">
                                  <h3 className="font-semibold flex items-center gap-2"><span>🏆</span>{t("chat.results")}</h3>
                                  <div className="flex items-center gap-1 shrink-0">
                                    <Button
                                      variant="secondary"
                                      size="icon"
                                      className="h-7 w-7"
                                      onClick={() => startEditArtifact({ messageId: quizId, content: '', quizAnchor: true, quizData: quiz.data }, index, 'quiz', quiz.data)}
                                      title={t("chat.editQuiz")}
                                      disabled={busy || podcastLoading || quizLoading || widgetLoading}
                                    >
                                      <Pencil className="w-3 h-3" />
                                    </Button>
                                    {quiz.data.downloadUrl && (
                                      <Button
                                        variant="secondary"
                                        size="sm"
                                        className="h-7 text-xs"
                                        onClick={() => handleHtmlDownload(quiz.data.downloadUrl, quiz.data.downloadFilename || htmlFilenameFromTitle(quiz.data.title, "upcurved_quiz.html"))}
                                      >
                                        <Download className="w-3 h-3 mr-1" /> HTML
                                      </Button>
                                    )}
                                  </div>
                                </div>
                                <p className="text-sm mb-1">Score: {quiz.score}/{quiz.data.questions.length}</p>
                                <p className="mb-4 font-medium">{quiz.score === quiz.data.questions.length ? 'Perfect score! Outstanding! 🎉' : quiz.score >= Math.ceil(quiz.data.questions.length * 0.8) ? 'Great job, almost perfect! ✨' : quiz.score >= Math.ceil(quiz.data.questions.length * 0.6) ? 'Nice work. keep practicing! 👍' : 'You can boost this score, give it another shot! 💪'}</p>
                                <Button onClick={() => retakeQuiz(quizId)} variant="secondary" className="w-full font-semibold">{t("chat.retakeQuiz")}</Button>
                              </div>
                            )}
                          </div>
                        ); })()}
                        {quizzesByChat[String(activeChatId)][String((msg as any).messageId)]?.data?.generationDiagnostics && (
                          <div className="w-full max-w-lg px-1">
                            <GenerationDiagnosticsPanel
                              diagnostics={quizzesByChat[String(activeChatId)][String((msg as any).messageId)].data.generationDiagnostics}
                            />
                          </div>
                        )}
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
                    Editing {artifactLabel(quotedMessage.artifactKind || normalizeArtifactKind(quotedMessage.media, quotedMessage))}
                  </div>
                  <p className="text-sm truncate">{quotedMessage.media?.title || quotedMessage.quizData?.title || 'Artifact'}</p>
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
              <div className="mb-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {uploadedFiles.map((file, index) => (
                  <div
                    key={`${file.name}-${file.lastModified}-${index}`}
                    className="flex min-w-0 items-center gap-2 rounded-lg bg-secondary px-2 py-2 text-sm"
                  >
                    <ImageAttachmentPreview file={file} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate">{file.name}</p>
                      <p className="text-[11px] text-muted-foreground">Image {index + 1} of {MAX_GENERATION_IMAGES}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeFile(index)}
                      className="ml-1 flex-shrink-0 text-muted-foreground hover:text-foreground"
                      aria-label={`Remove ${file.name || `image ${index + 1}`}`}
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div
              className="relative"
              onDragEnter={handleDragEnter}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              {isDraggingImages && (
                <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-md border-2 border-dashed border-primary bg-background/85 text-sm font-medium">
                  {t("chat.dropImages")}
                </div>
              )}
              <input
                ref={imageFileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                className="hidden"
                onChange={handleFileUpload}
                disabled={isEditMode || uploadedFiles.length >= MAX_GENERATION_IMAGES}
              />
              <Textarea
                ref={textareaRef}
                placeholder={
                  isEditMode
                    ? t("chat.placeholder.edit", {
                        kind: artifactLabel(
                          quotedMessage?.artifactKind ||
                            normalizeArtifactKind(quotedMessage?.media, quotedMessage)
                        ),
                      })
                    : uploadedFiles.length > 0
                    ? (uploadedFiles.length === 1
                        ? t("chat.placeholder.images.one")
                        : t("chat.placeholder.images.other", { count: uploadedFiles.length }))
                    : t("chat.placeholder")
                }
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onPaste={handleImagePaste}
                onKeyDown={handleKeyDown}
                rows={1}
                className={`min-h-[48px] resize-none pr-14 py-3 ${isEditMode ? "" : "pl-12"}`}
                disabled={false}
              />
              {!isEditMode && (
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="absolute left-1.5 top-1/2 h-8 w-8 -translate-y-1/2"
                  onClick={() => imageFileInputRef.current?.click()}
                  title={
                    uploadedFiles.length >= MAX_GENERATION_IMAGES
                      ? t("chat.maxImages", { count: MAX_GENERATION_IMAGES })
                      : t("chat.attachImage")
                  }
                  aria-label={t("chat.attachImage")}
                  disabled={uploadedFiles.length >= MAX_GENERATION_IMAGES}
                >
                  <Upload className="h-4 w-4" />
                </Button>
              )}
              <div className="absolute top-1/2 right-3 -translate-y-1/2 flex gap-1">
                {isEditMode ? (
                  <Button
                    size="icon"
                    variant="default"
                    className={`bg-gradient-to-r ${getThemeGradient(colorTheme)} text-white hover:opacity-90`}
                    onClick={() => void handleEditVideo()}
                    title={busy || widgetLoading || quizLoading ? "Stop editing" : "Apply edits"}
                    disabled={!query.trim()}
                  >
                    {busy ? <Square className="w-5 h-5" /> : <Pencil className="w-5 h-5" />}
                  </Button>
                ) : (
                  <Button
                    size="icon"
                    variant="default"
                    className={`bg-gradient-to-r ${getThemeGradient(colorTheme)} text-white hover:opacity-90`}
                    onClick={() => void handleSelectedGeneration()}
                    title={
                      anyGenerationLoading
                        ? t("chat.gen.stop", { label: t(`chat.gen.${generationType}`) })
                        : t("chat.gen.generate", { label: t(`chat.gen.${generationType}`) })
                    }
                    disabled={
                      !anyGenerationLoading &&
                      !query.trim() &&
                      uploadedFiles.length === 0
                    }
                  >
                    {anyGenerationLoading ? (
                      <Square className="w-5 h-5" />
                    ) : (
                      <Send className="w-5 h-5" />
                    )}
                  </Button>
                )}
              </div>
            </div>
            <div className="mt-2 flex justify-end">
              <div className="flex flex-wrap items-center justify-end gap-2">
                {!isEditMode && (
                  <label className="flex items-center gap-1.5">
                    <span className="text-xs text-muted-foreground">{t("chat.gen.label")}</span>
                    <select
                      aria-label={t("chat.gen.aria")}
                      // Hovering the closed control describes the current choice;
                      // hovering an option in the open list describes that one.
                      title={t(`chat.gen.${generationType}.desc`)}
                      value={generationType}
                      disabled={anyGenerationLoading}
                      onChange={(event) =>
                        setGenerationType(event.target.value as GenerationSelection)
                      }
                      className="h-7 rounded-md border border-input bg-background px-2 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
                    >
                      {GENERATION_SELECTIONS.map((selection) => (
                        <option
                          key={selection}
                          value={selection}
                          title={t(`chat.gen.${selection}.desc`)}
                        >
                          {t(`chat.gen.${selection}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <label className="flex items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">{t("chat.level.label")}</span>
                  <select
                    aria-label={t("chat.level.aria")}
                    title={t(`chat.level.${audienceLevel}.desc`)}
                    value={audienceLevel}
                    disabled={anyGenerationLoading}
                    onChange={(event) =>
                      setAudienceLevel(event.target.value as AudienceLevel)
                    }
                    className="h-7 max-w-[11rem] rounded-md border border-input bg-background px-2 text-xs text-foreground shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {AUDIENCE_LEVELS.map((level) => (
                      <option key={level} value={level} title={t(`chat.level.${level}.desc`)}>
                        {t(`chat.level.${level}`)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          </div>
        </div>

        <div
          className={`${
            mobileArtifactOpen
              ? "fixed inset-0 z-40 flex w-full bg-background pt-14"
              : "hidden"
          } md:static md:z-auto md:flex md:w-1/2 md:bg-transparent md:pt-0 flex-col p-6 space-y-4 h-screen overflow-y-auto`}
          ref={videoContainerRef}
        >
          <Card
            className="flex-grow bg-muted/50 border-border flex items-center justify-center aspect-video min-h-[200px] relative"
            onContextMenu={(e) => e.preventDefault()}
          >
            {widgetHtml ? (
              currentMediaMeta?.artifactKind === "diagram" ? (
                <DiagramFrame
                  svgCode={widgetHtml}
                  className="flex h-full w-full items-center justify-center overflow-auto rounded-xl bg-white p-3"
                  title={currentMediaMeta?.title || "Educational diagram"}
                />
              ) : currentMediaMeta?.artifactKind === "static_worksheet" ? (
                <StaticWorksheetFrame
                  worksheetHtml={widgetHtml}
                  worksheetId={currentMediaMeta?.worksheetId || "static_worksheet"}
                  userEmail={user.email}
                  className="w-full h-full rounded-xl border-0 bg-white"
                  title={currentMediaMeta?.title || "Static Worksheet"}
                />
              ) : (
                <WidgetFrame
                  widgetCode={widgetHtml}
                  className="w-full h-full rounded-xl border-0"
                  title={
                    currentMediaMeta?.artifactKind === "story"
                      ? t("chat.artifact.story")
                      : t("chat.gen.widget")
                  }
                />
              )
            ) : !videoUrl ? (
              <div className="text-center p-4">
                {busy || podcastLoading || widgetLoading ? (
                  <div className="flex flex-col items-center gap-3">
                    <div className="relative h-16 w-16">
                      <svg className="h-16 w-16 -rotate-90" viewBox="0 0 36 36">
                        <path className="text-muted stroke-current" strokeWidth="3" fill="none" d="M18 2 a 16 16 0 1 1 0 32 a 16 16 0 1 1 0 -32" opacity="0.2"/>
                        <path className="text-primary stroke-current" strokeWidth="3" fill="none" strokeLinecap="round"
                          d="M18 2 a 16 16 0 1 1 0 32 a 16 16 0 1 1 0 -32"
                          strokeDasharray={`${generationPercent}, 100`} />
                      </svg>
                      <div className="absolute inset-0 flex items-center justify-center text-sm font-medium">
                        {`${generationPercent}%`}
                      </div>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {generationCaption}
                    </p>
                  </div>
                ) : apiError ? (
                  <div className="flex flex-col items-center gap-2">
                    <svg viewBox="0 0 24 24" className="w-10 h-10 text-red-500" aria-hidden="true">
                      <path fill="currentColor" d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 14h-2v-2h2v2Zm0-4h-2V6h2v6Z"/>
                    </svg>
                    <p className="text-sm text-red-600 font-medium">{t("chat.generationFailed")}</p>
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
                        label={t("player.captions")}
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
                        label={t("player.captions")}
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

          {widgetHtml && htmlDownloadUrl && (
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleHtmlDownload(
                  htmlDownloadUrl,
                  htmlDownloadFilename || (currentMediaMeta?.artifactKind === "diagram" ? "upcurved_diagram.svg" : currentMediaMeta?.artifactKind === "static_worksheet" ? "upcurved_static_worksheet.html" : "upcurved_export.html"),
                )}
              >
                <Download className="w-4 h-4 mr-2" />
                {currentMediaMeta?.artifactKind === "diagram" ? "Download SVG" : "Download HTML"}
              </Button>
              {currentMediaMeta?.artifactKind === "diagram" && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void handleDiagramPngDownload()}
                >
                  <Download className="w-4 h-4 mr-2" />
                  Download PNG
                </Button>
              )}
            </div>
          )}

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
                  title={t("player.captions")}
                  disabled={!videoUrl || !vttUrl}
                >
                  <span className="font-bold text-xs">CC</span>
                </Button>
                <div className="flex items-center gap-0">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 p-0 leading-none"
                    title={t("player.slower")}
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
                    title={t("player.faster")}
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
                    className="h-9 w-9"
                    title={t("player.muteToggle")}
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
                    <Volume2 className="w-5 h-5 text-foreground" />
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
                    className="w-48"
                    disabled={!videoUrl}
                  />
                  {/* Download Button */}
                  <Button
                    variant="ghost"
                    size="icon"
                    title={currentMediaMeta?.type === "video" && isCaptionsOn ? "Download MP4 with burned-in captions" : currentMediaMeta?.type === "audio" && isCaptionsOn ? "Download audio, captions, and transcript ZIP" : "Download"}
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

        {/* Mobile: dismiss the overlay. Fixed so it stays put while the pane scrolls. */}
        {mobileArtifactOpen && (
          <button
            type="button"
            onClick={() => setMobileArtifactOpen(false)}
            className="fixed left-3 top-3 z-50 inline-flex items-center gap-2 rounded-full border border-border bg-background/95 px-3 py-1.5 text-sm font-medium shadow-sm backdrop-blur md:hidden"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            {t("chat.hideArtifact")}
          </button>
        )}

        {/* Mobile: the way in. Only offered when there is something to look at. */}
        {!mobileArtifactOpen && hasArtifactToShow && (
          <button
            type="button"
            onClick={() => setMobileArtifactOpen(true)}
            className={`fixed bottom-24 right-4 z-30 inline-flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-semibold text-white shadow-lg bg-gradient-to-r ${getThemeGradient(colorTheme)} md:hidden`}
          >
            <Eye className="h-4 w-4" aria-hidden="true" />
            {t("chat.viewArtifact")}
          </button>
        )}
      </div>
      {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} />}
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        generationTypes={GENERATION_SELECTIONS}
        levels={AUDIENCE_LEVELS}
        onSelectGeneration={(value) => setGenerationType(value)}
        onSelectLevel={(value) => setAudienceLevel(value)}
        onOpenHelp={() => setHelpOpen(true)}
        onNewChat={handleNewChat}
        disableGenerationChanges={anyGenerationLoading || isEditMode}
      />
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
          />
        </div>
      )}
      <AlertDialog open={storyConfigOpen} onOpenChange={setStoryConfigOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("story.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("story.description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-3">
            <div className="grid gap-1">
              <label className="text-sm font-medium">{t("story.mainCharacter")}</label>
              <select
                className="border rounded px-3 py-2 bg-background"
                value={storyHostChoice}
                onChange={(e) => setStoryHostChoice(e.target.value as any)}
              >
                <option value="auto">{t("chat.level.auto")}</option>
                <option value="scientist">{t("story.character.scientist")}</option>
                <option value="friendly_robot">{t("story.character.robot")}</option>
                <option value="animal_guide">{t("story.character.animal")}</option>
                <option value="explorer">{t("story.character.explorer")}</option>
                <option value="artist">{t("story.character.artist")}</option>
                <option value="athlete">{t("story.character.athlete")}</option>
              </select>
            </div>
            <div className="grid gap-1">
              <label className="text-sm font-medium">{t("story.theme")}</label>
              <select
                className="border rounded px-3 py-2 bg-background"
                value={storyThemeChoice}
                onChange={(e) => setStoryThemeChoice(e.target.value as any)}
              >
                <option value="auto">{t("chat.level.auto")}</option>
                <option value="space">{t("story.theme.space")}</option>
                <option value="jungle">{t("story.theme.jungle")}</option>
                <option value="ocean">{t("story.theme.ocean")}</option>
                <option value="city_lab">{t("story.theme.cityLab")}</option>
                <option value="sunset_farm">{t("story.theme.sunsetFarm")}</option>
                <option value="meadow">{t("story.theme.meadow")}</option>
              </select>
            </div>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void confirmStoryConfigAndGenerate()}>
              Generate Story
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {/* Chat switch confirmation dialog */}
      <AlertDialog open={showSwitchWarning} onOpenChange={(open) => { if (!open) cancelChatSwitch(); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{pendingChatSwitch === NEW_CHAT_SENTINEL ? t("dialog.newChat.title") : t("dialog.switchChat.title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingChatSwitch === NEW_CHAT_SENTINEL
                ? t("dialog.newChat.body")
                : t("dialog.switchChat.body")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={cancelChatSwitch}>{t("dialog.stay")}</AlertDialogCancel>
            <AlertDialogAction onClick={confirmChatSwitch}>{t("dialog.switch")}</AlertDialogAction>
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
