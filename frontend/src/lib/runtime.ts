export type AppMode = "cloud" | "desktop-local";

const RAW_MODE = String(import.meta.env.VITE_APP_MODE || "").trim().toLowerCase();

function envMode(): AppMode {
  return RAW_MODE === "desktop-local" ? "desktop-local" : "cloud";
}

export function isDesktopRuntime(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean(window.desktop?.isDesktop);
}

export function isDesktopLocalMode(): boolean {
  return envMode() === "desktop-local" || isDesktopRuntime();
}

export function getAppMode(): AppMode {
  return isDesktopLocalMode() ? "desktop-local" : "cloud";
}
