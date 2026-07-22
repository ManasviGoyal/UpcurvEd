// frontend/src/types/index.ts
export interface MediaAttachment {
  type: 'video' | 'audio' | 'widget';
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

export interface Message {
  role: 'user' | 'bot';
  content: string;
  media?: MediaAttachment;
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
