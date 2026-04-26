// API wrapper that injects Firebase ID token when available
import { isDesktopLocalMode } from "@/lib/runtime";

const RAW_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) || '';
const API_BASE_URL = RAW_API_BASE_URL.replace(/\/+$/, '');

export function apiUrl(path: string): string {
  if (!path) return path;
  if (/^https?:\/\//i.test(path)) return path;
  if (!API_BASE_URL) return path;
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalized}`;
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

export async function apiAppendMessage(chatId: string, msg: { message_id?: string; role: 'user'|'assistant'; content: string; media?: any; timestamp?: string }, model?: string) {
  // Support idempotency key for retries
  const idempotencyKey = crypto.randomUUID ? crypto.randomUUID() : `ik_${Date.now()}_${Math.random().toString(36).slice(2,8)}`;
  const headers: HeadersInit = { 'Idempotency-Key': idempotencyKey };
  const payload = { ...msg };
  if (!payload.timestamp) payload.timestamp = new Date().toISOString();

  // Model is stored in chat data, not URL
  const res = await apiFetch(`/api/chats/${encodeURIComponent(chatId)}`, {
    method: 'POST',
    body: JSON.stringify(payload),
    headers
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
}, signal?: AbortSignal) {
  const res = await apiFetch('/quiz/media', {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(`quiz generation failed: ${res.status}`);
  return res.json();
}
