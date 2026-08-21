/// <reference types="vite/client" />

/** Injected by vite.config.ts from the root package.json `repository` field. */
declare const __RELEASE_ASSETS_BASE__: string;

interface DesktopBridge {
  isDesktop: boolean;
  platform: string;
  apiBaseUrl?: string;
  secureStore?: {
    getApiKeys: (account: string) => Promise<any>;
    setApiKeys: (account: string, payload: any) => Promise<{ ok: boolean; reason?: string }>;
    clearApiKeys: (account: string) => Promise<{ ok: boolean; reason?: string }>;
  };
}

interface Window {
  desktop?: DesktopBridge;
}
