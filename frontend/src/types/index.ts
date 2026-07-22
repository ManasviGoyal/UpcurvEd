// frontend/src/types/index.ts

export type ArtifactKind = 'video' | 'audio' | 'podcast' | 'story' | 'widget' | 'quiz';

export interface MediaAttachment {
  type: 'video' | 'audio' | 'widget';
  artifactKind?: ArtifactKind;     // distinguishes story/widget/video/audio for UI follow-up actions
  url?: string;                    // media URL, or downloadable HTML URL for widgets/stories
  subtitleUrl?: string;
  title?: string;
  artifactId?: string;
  gcsPath?: string;
  sceneCode?: string;
  scriptGcsPath?: string;
  widgetCode?: string;             // full HTML document for sandboxed iframe
  downloadFilename?: string;       // suggested filename for downloadable HTML exports
}

export interface QuizData {
  downloadUrl?: string;
  downloadFilename?: string;
  [key: string]: unknown;
}

export interface Message {
  role: 'user' | 'bot';
  content: string;
  media?: MediaAttachment;
  quizData?: QuizData;             // quiz JSON/result payload used for rendering + edit/download follow-ups
  createdAt?: number;
  messageId?: string;
}

export interface Chat {
  id: string | number;
  name: string;
  messages: Message[];
  sessionId?: string;
  shareable?: boolean;
  share_token?: string;
  updatedAt?: number;
  model?: string;
}

export interface User {
  name: string;
  email: string;
  password?: string;
  uid?: string;
  idToken?: string;
  chats: Chat[];
}

export type Provider = 'claude' | 'gemini' | 'openrouter' | '';

export interface ApiKeys {
  gemini: string;
  claude: string;
  openrouter: string;
  provider?: Provider;
  model?: string;
}

export type ColorTheme = 'blue' | 'rose' | 'green' | 'orange';
export type Theme = 'light' | 'dark';
