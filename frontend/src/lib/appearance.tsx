// Appearance settings for the public pages (landing + setup guide).
//
// These pages are not part of the signed-in app, so they do not use the per-user
// theme stored by App.tsx. They used to hard-code "dark between 6 PM and 6 AM" with
// no way to override it; that behaviour is now the `auto` mode, and a visitor can
// pin light or dark instead.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type AppearanceMode = "auto" | "light" | "dark";

const APPEARANCE_STORAGE_KEY = "app.appearance";
const REDUCE_MOTION_STORAGE_KEY = "app.reduceMotion";

// Dark from 6 PM to 6 AM — the original rule, kept as the default.
const DARK_FROM_HOUR = 18;
const DARK_UNTIL_HOUR = 6;

function isNightNow(): boolean {
  const hour = new Date().getHours();
  return hour >= DARK_FROM_HOUR || hour < DARK_UNTIL_HOUR;
}

function readMode(): AppearanceMode {
  try {
    const stored = localStorage.getItem(APPEARANCE_STORAGE_KEY);
    if (stored === "auto" || stored === "light" || stored === "dark") return stored;
  } catch {
    // Storage blocked; fall through to the default.
  }
  return "auto";
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function readReduceMotion(): boolean {
  try {
    const stored = localStorage.getItem(REDUCE_MOTION_STORAGE_KEY);
    if (stored === "1") return true;
    if (stored === "0") return false;
  } catch {
    // Storage blocked; fall through to the OS preference.
  }
  // No explicit choice yet: respect the operating-system setting.
  return prefersReducedMotion();
}

type AppearanceContextValue = {
  mode: AppearanceMode;
  setMode: (next: AppearanceMode) => void;
  /** Resolved from `mode` — what the page should actually paint. */
  isDark: boolean;
  reduceMotion: boolean;
  setReduceMotion: (next: boolean) => void;
};

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<AppearanceMode>(readMode);
  const [night, setNight] = useState<boolean>(isNightNow);
  const [reduceMotion, setReduceMotionState] = useState<boolean>(readReduceMotion);

  useEffect(() => {
    if (mode !== "auto") return;
    // A page left open across 6 PM should switch over without a reload.
    const timer = window.setInterval(() => setNight(isNightNow()), 60_000);
    setNight(isNightNow());
    return () => window.clearInterval(timer);
  }, [mode]);

  const setMode = useCallback((next: AppearanceMode) => {
    setModeState(next);
    try {
      localStorage.setItem(APPEARANCE_STORAGE_KEY, next);
    } catch {
      // Storage blocked; the choice still applies for this session.
    }
  }, []);

  const setReduceMotion = useCallback((next: boolean) => {
    setReduceMotionState(next);
    try {
      localStorage.setItem(REDUCE_MOTION_STORAGE_KEY, next ? "1" : "0");
    } catch {
      // Storage blocked; the choice still applies for this session.
    }
  }, []);

  const value = useMemo<AppearanceContextValue>(
    () => ({
      mode,
      setMode,
      isDark: mode === "auto" ? night : mode === "dark",
      reduceMotion,
      setReduceMotion,
    }),
    [mode, setMode, night, reduceMotion, setReduceMotion]
  );

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

/** Falls back to the stored values when rendered outside the provider. */
export function useAppearance(): AppearanceContextValue {
  const context = useContext(AppearanceContext);
  if (context) return context;

  const mode = readMode();
  return {
    mode,
    setMode: () => {},
    isDark: mode === "auto" ? isNightNow() : mode === "dark",
    reduceMotion: readReduceMotion(),
    setReduceMotion: () => {},
  };
}
