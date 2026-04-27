/// <reference types="vite/client" />

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
