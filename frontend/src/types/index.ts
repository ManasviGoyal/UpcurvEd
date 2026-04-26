// frontend/src/types/index.ts
export interface MediaAttachment {
  type: 'video' | 'audio';
  url: string;
  subtitleUrl?: string;
  title?: string;
  artifactId?: string;
  gcsPath?: string; // path inside bucket to allow refresh of signed URL
  sceneCode?: string; // scene.py code for video editing
  scriptGcsPath?: string; // GCS path to podcast script for persistent fallback
}

export interface Message {
  role: 'user' | 'bot';
  content: string;
  media?: MediaAttachment;
  // Optional server metadata for persistence and pagination
  createdAt?: number;        // ms epoch
  messageId?: string;        // server message_id
}

export interface Chat {
  id: string | number; // Firestore IDs are strings; keep number for legacy local items
  name: string;
  messages: Message[];
  sessionId?: string;   // client-generated unless returned by backend
  shareable?: boolean;  // whether chat is shareable
  share_token?: string; // share token for public access
  updatedAt?: number;   // timestamp in milliseconds
  model?: string;       // model used for this chat (stored in chat document)
}

export interface User {
  name: string;
  email: string;
  password?: string; // optional when using Google Sign-In
  uid?: string;      // Firebase UID
  idToken?: string;  // Firebase ID token (ephemeral)
  chats: Chat[];
}

export type Provider = 'claude' | 'gemini' | '';

export interface ApiKeys {
  gemini: string;
  claude: string;
  provider?: Provider;   // optional UI selection; "" -> auto by available key
  model?: string;        // optional model id, e.g. "claude-3-5-sonnet-latest"
}

export type ColorTheme = 'blue' | 'rose' | 'green' | 'orange';
export type Theme = 'light' | 'dark';
