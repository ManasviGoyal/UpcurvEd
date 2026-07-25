// frontend/src/types/index.ts

export type ArtifactKind = 'video' | 'audio' | 'podcast' | 'story' | 'widget' | 'quiz';

export type GenerationQualityStatus =
  | 'standard'
  | 'full_quality'
  | 'recovered'
  | 'simplified'
  | 'completed_with_fallback'
  | 'failed';

export interface GenerationDiagnostics {
  quality_status: GenerationQualityStatus;
  provider?: string;
  model?: string;
  llm_calls?: number;
  total_scenes?: number;
  creative_scenes?: number;
  repaired_scenes?: number;
  plan_repaired_by_model?: boolean;
  simplified_scenes?: number;
  component_fallbacks?: number;
  recovery_stages?: string[];
  failure_stage?: string | null;
  summary?: string;
}

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
  generationDiagnostics?: GenerationDiagnostics;
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
  quizAnchor?: boolean;
  quizTitle?: string;
  quizData?: QuizData;
  createdAt?: number;
  clientCreatedAt?: number;
  sequence?: number;
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
