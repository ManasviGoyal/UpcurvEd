// frontend/src/types/index.ts

export type ArtifactKind = 'video' | 'audio' | 'podcast' | 'story' | 'widget' | 'quiz';

export interface MediaAttachment {
  type: 'video' | 'audio' | 'widget';
  artifactKind?: ArtifactKind;
  url?: string;
  subtitleUrl?: string;
  title?: string;
  artifactId?: string;
  gcsPath?: string;
  sceneCode?: string;
  scriptGcsPath?: string;
  widgetCode?: string;
  downloadFilename?: string;
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
  quizData?: QuizData;
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

export type {
  ApiKeys,
  Provider,
  ProviderId,
} from "../lib/providerConfig";

export type ColorTheme = 'blue' | 'rose' | 'green' | 'orange';
export type Theme = 'light' | 'dark';
