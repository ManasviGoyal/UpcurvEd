// API wrapper that injects Firebase ID token when available
import { isDesktopLocalMode } from "@/lib/runtime";
import type { AudienceLevel } from "@/types";

const RAW_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) || '';
const DESKTOP_LOCAL_DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";


export class ApiRequestError extends Error {
  status: number;
  errorBody: any;
  rawBody: string;

  constructor(message: string, status: number, errorBody: any, rawBody: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.errorBody = errorBody;
    this.rawBody = rawBody;
  }
}

async function readResponseBody(res: Response): Promise<{ data: any; raw: string }> {
  const raw = await res.text().catch(() => "");
  try {
    return { data: raw ? JSON.parse(raw) : null, raw };
  } catch {
    return { data: null, raw };
  }
}

function messageFromErrorBody(fallback: string, data: any, raw: string): string {
  const detail = data?.error || data?.message || data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (detail !== undefined && detail !== null) return String(detail);
  if (raw && raw.trim()) return raw.trim().slice(0, 300);
  return fallback;
}

export async function throwApiError(res: Response, fallback: string): Promise<never> {
  const { data, raw } = await readResponseBody(res);
  const message = messageFromErrorBody(`${fallback}: ${res.status}`, data, raw);
  throw new ApiRequestError(message, res.status, data, raw);
}

function resolvedApiBaseUrl(): string {
  const runtimeDesktopBase = String(window?.desktop?.apiBaseUrl || "").trim();
  if (runtimeDesktopBase) return runtimeDesktopBase.replace(/\/+$/, "");
  const configured = RAW_API_BASE_URL.trim();
  if (configured) return configured.replace(/\/+$/, "");
  if (isDesktopLocalMode()) return DESKTOP_LOCAL_DEFAULT_API_BASE_URL;
  return "";
}

export function apiUrl(path: string): string {
  if (!path) return path;
  if (/^https?:\/\//i.test(path)) return path;
  const apiBase = resolvedApiBaseUrl();
  if (!apiBase) return path;
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${apiBase}${normalized}`;
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  let idToken: string | undefined;
  if (!isDesktopLocalMode()) {
    try {
      const { getFirebaseAuth } = await import("@/firebase");
      const auth = getFirebaseAuth();
      const user = auth.currentUser;
      idToken = user ? await user.getIdToken() : undefined;
    } catch {
      idToken = undefined;
    }
  }
  const headers = new Headers(init.headers || {});
  if (idToken) headers.set('Authorization', `Bearer ${idToken}`);

  if (isDesktopLocalMode()) {
    try {
      const raw = localStorage.getItem("app.localUser");
      if (raw) {
        const parsed = JSON.parse(raw);
        const userHint = String(parsed?.email || parsed?.name || "").trim();
        if (userHint) headers.set("X-Desktop-User", userHint);
      }
    } catch {}
  }

  // Add X-Session-ID header for rate limiting and audit
  try {
    const sessionId = localStorage.getItem('app.sessionId');
    if (sessionId) {
      headers.set('X-Session-ID', sessionId);
    }
  } catch {}

  if (!headers.has('Content-Type') && init.method && init.method !== 'GET') {
    headers.set('Content-Type', 'application/json');
  }
  const resolvedInput = typeof input === 'string' ? apiUrl(input) : input;
  return fetch(resolvedInput, { ...init, headers });
}

// Chat API helpers - model is stored in chat data, not URL
export async function apiListChats(params?: { limit?: number }) {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  const res = await apiFetch(`/api/chats${qs.toString() ? `?${qs.toString()}` : ''}`);
  if (!res.ok) throw new Error(`list chats failed: ${res.status}`);
  return res.json();
}

export async function apiCreateChat(body: { title?: string; model?: string; sessionId?: string; content?: string; timestamp?: string }) {
  // Support idempotency key for retries
  const idempotencyKey = crypto.randomUUID ? crypto.randomUUID() : `ik_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
  const headers: HeadersInit = { 'Idempotency-Key': idempotencyKey };
  const payload: any = { title: body.title || 'New Chat' };
  if (body.model) payload.model = body.model; // Model stored in chat document
  if (body.sessionId) payload.sessionId = body.sessionId;
  if (body.content) payload.content = body.content;
  if (body.timestamp) payload.timestamp = body.timestamp;

  const res = await apiFetch(`/api/chats`, {
    method: 'POST',
    body: JSON.stringify(payload),
    headers
  });
  if (!res.ok) throw new Error(`create chat failed: ${res.status}`);
  return res.json();
}

export async function apiGetChat(chatId: string, model?: string, params?: { limit?: number; before?: number }) {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.before) qs.set('before', String(params.before));
  // Model is stored in chat data, not URL
  const res = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}${qs.toString() ? `?${qs.toString()}` : ''}`);
  if (!res.ok) throw new Error(`get chat failed: ${res.status}`);
  return res.json();
}

export interface AppendMessageInput {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  media?: any;
  clientCreatedAt?: number;
  sequence?: number;
  quizAnchor?: boolean;
  quizTitle?: string;
  quizData?: any;
}

export interface ApiMessage {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt?: number;
  clientCreatedAt?: number;
  sequence?: number;
  media?: any;
  quizAnchor?: boolean;
  quizTitle?: string;
  quizData?: any;
}

export async function apiAppendMessage(
  chatId: string,
  msg: AppendMessageInput,
  model?: string,
): Promise<ApiMessage> {
  // The message ID is also the idempotency key. Retries therefore update the
  // same stored message instead of creating another message with a new order.
  const idempotencyKey = msg.message_id;
  const headers: HeadersInit = { 'Idempotency-Key': idempotencyKey };

  // Model is stored in chat data, not URL.
  const res = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}`, {
    method: 'POST',
    body: JSON.stringify(msg),
    headers,
  });
  if (!res.ok) throw new Error(`append message failed: ${res.status}`);
  return res.json();
}

// Refresh artifact signed URL(s)
export async function apiRefreshArtifact(params: { artifactId?: string; gcsPath?: string; subtitle?: boolean }) {
  const qs = new URLSearchParams();
  if (params.artifactId) qs.set('artifactId', params.artifactId);
  if (params.gcsPath) qs.set('gcsPath', params.gcsPath);
  if (params.subtitle) qs.set('subtitle', 'true');
  const res = await apiFetch(`/api/artifacts/refresh?${qs.toString()}`);
  if (!res.ok) throw new Error(`refresh artifact failed: ${res.status}`);
  return res.json();
}

export async function apiListMessages(chatId: string, model?: string, params?: { limit?: number; before?: number }) {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.before) qs.set('before', String(params.before));
  // Model is stored in chat data, not URL
  const res = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}/messages${qs.toString() ? `?${qs.toString()}` : ''}`);
  if (!res.ok) throw new Error(`list messages failed: ${res.status}`);
  return res.json(); // { messages: [...], has_more: boolean }
}

export async function apiDeleteChat(chatId: string, model?: string) {
  // Model is stored in chat data, not URL
  const res = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`delete chat failed: ${res.status}`);
  return res.json();
}

export async function apiRenameChat(chatId: string, title: string, model?: string) {
  // Model is stored in chat data, not URL
  const res = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`rename chat failed: ${res.status}`);
  return res.json();
}

// Toggle shareable state for a chat
export async function apiToggleShare(chatId: string, shareable: boolean) {
  const res = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}/share`, {
    method: 'PATCH',
    body: JSON.stringify({ shareable }),
  });
  if (!res.ok) throw new Error(`toggle share failed: ${res.status}`);
  return res.json(); // ChatItemOut including shareable + share_token
}

// Fetch a shared chat (public, no auth required). Use plain fetch so callers may skip auth.
export async function apiGetSharedChat(token: string) {
  const res = await fetch(apiUrl(`/api/share/${encodeURIComponent(token)}`));
  if (!res.ok) throw new Error(`get shared chat failed: ${res.status}`);
  return res.json(); // ChatDetailOut
}

// Delete user account and all associated data
export async function apiDeleteAccount() {
  const res = await apiFetch('/api/account', { method: 'DELETE' });
  if (!res.ok) throw new Error(`delete account failed: ${res.status}`);
  return res.json();
}

// Generate quiz from media transcript (video or podcast)
export async function apiQuiz(body: {
  transcript: string;
  sceneCode?: string;
  provider?: string;
  model?: string;
  provider_keys?: Record<string, string>;
  num_questions?: number;
  difficulty?: string;
  audience?: AudienceLevel;
}, signal?: AbortSignal) {
  const res = await apiFetch('/quiz/media', {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) await throwApiError(res, 'quiz generation failed');
  return res.json();
}

// Generate an interactive HTML widget for a topic
export async function apiWidget(body: {
  prompt: string;
  provider?: string;
  model?: string;
  keys?: Record<string, string>;
  chatId?: string;
  audience?: AudienceLevel;
}, signal?: AbortSignal) {
  const res = await apiFetch('/widget', {
    method: 'POST',
    body: JSON.stringify({
      prompt: body.prompt,
      provider: body.provider,
      model: body.model,
      keys: body.keys || {},
      chatId: body.chatId,
      audience: body.audience,
    }),
    signal,
  });
  if (!res.ok) await throwApiError(res, 'widget generation failed');
  return res.json(); // { ok, status, widget_html }
}
