import { useState, useEffect } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LoginPage } from "./pages/Login";
import { SettingsPage } from "./pages/Settings";
import { ChatInterface } from "./pages/Chat";
import Landing from "./pages/Landing";
import type { User, ApiKeys, Theme, ColorTheme } from "./types";
import { getFirebaseAuth } from "./firebase";
import { onAuthStateChanged, setPersistence, browserLocalPersistence } from "firebase/auth";
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import { isDesktopLocalMode } from "./lib/runtime";
import { loadApiKeysForUser } from "./lib/secureKeys";
import { Analytics } from "@vercel/analytics/react";

const queryClient = new QueryClient();
const LOCAL_USER_KEY = "app.localUser";

const AppContent = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const desktopLocal = isDesktopLocalMode();
  const isPublicLandingRoute = location.pathname === "/home" || location.pathname === "/";
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [users, setUsers] = useState<User[]>([{
    name: "Demo User",
    email: "demo@user.com",
    password: "password",
    chats: []
  }]);
  // Persist theme/color per user email
  const themeKey = user?.email ? `app.theme.${user.email}` : null;
  const colorKey = user?.email ? `app.colorTheme.${user.email}` : null;
  const [theme, setTheme] = useState<Theme>(() => {
    try { if (themeKey) { const v = localStorage.getItem(themeKey); if (v === 'light' || v === 'dark') return v as Theme; } } catch {}
    return "dark";
  });
  const [colorTheme, setColorTheme] = useState<ColorTheme>(() => {
    try { if (colorKey) { const v = localStorage.getItem(colorKey); if (v === 'blue' || v === 'rose' || v === 'green' || v === 'orange') return v as ColorTheme; } } catch {}
    return "blue";
  });
  const [themeHydratedForEmail, setThemeHydratedForEmail] = useState<string | null>(null);

  // Include provider/model so Settings can optionally set them; "" means "auto"
  const [apiKeys, setApiKeys] = useState<ApiKeys>({
    gemini: "",
    claude: "",
    provider: "",
    model: "",
  });

  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(theme);
    // clear old theme-* classes
    [...(root.classList as any)].forEach((c: string) => c.startsWith("theme-") && root.classList.remove(c));
    root.classList.add(`theme-${colorTheme}`);
    // Prevent startup race: don't overwrite stored values before we've hydrated this user once.
    if (user?.email && themeHydratedForEmail === user.email) {
      try { if (themeKey) localStorage.setItem(themeKey, theme); } catch {}
      try { if (colorKey) localStorage.setItem(colorKey, colorTheme); } catch {}
    }
  }, [theme, colorTheme, themeKey, colorKey, user?.email, themeHydratedForEmail]);

  // Load persisted theme/color after user becomes available (initial mount or user switch)
  useEffect(() => {
    if (!user?.email) return;
    try {
      const tKey = `app.theme.${user.email}`;
      const cKey = `app.colorTheme.${user.email}`;
      const storedTheme = localStorage.getItem(tKey);
      const storedColor = localStorage.getItem(cKey);
      if (storedTheme === 'light' || storedTheme === 'dark') setTheme(storedTheme as Theme);
      if (storedColor && ['blue','rose','green','orange'].includes(storedColor)) setColorTheme(storedColor as ColorTheme);
    } catch {}
    setThemeHydratedForEmail(user.email);
  }, [user?.email]);

  // Load provider/model + API keys for active user (desktop secure storage or local fallback).
  useEffect(() => {
    let cancelled = false;
    async function hydrateApiKeys() {
      if (!user?.email) return;
      const loaded = await loadApiKeysForUser(user.email, apiKeys);
      if (!cancelled) {
        setApiKeys((prev) => ({
          ...prev,
          ...loaded,
        }));
      }
    }
    void hydrateApiKeys();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.email]);

  const setViewStr = (v: string) => {
    // Navigate based on view string
    if (v === 'landing' || v === 'home') {
      navigate('/home');
    } else if (v === 'login') {
      navigate('/login');
    } else if (v === 'chat') {
      navigate('/chat');
    } else if (v === 'settings') {
      navigate('/settings');
    }
  };

  const updateDisplayName = (nextName: string) => {
    const trimmed = String(nextName || "").trim();
    if (!trimmed) return;
    setUser((prev) => (prev ? { ...prev, name: trimmed } : prev));
    setUsers((prev) => prev.map((u) => (u.email === user?.email ? { ...u, name: trimmed } : u)));
    if (desktopLocal) {
      try {
        const email = user?.email || "local@upcurved.desktop";
        localStorage.setItem(LOCAL_USER_KEY, JSON.stringify({ name: trimmed, email }));
      } catch {}
    }
  };

  const resetLocalData = () => {
    if (!desktopLocal) return;
    const ok = window.confirm(
      "Reset all local desktop data? This removes local chats, media history, settings, and saved keys on this device."
    );
    if (!ok) return;
    try {
      Object.keys(localStorage).forEach((key) => {
        if (key.startsWith("app.")) localStorage.removeItem(key);
      });
    } catch {}
    try {
      sessionStorage.removeItem("app.forceBlank");
    } catch {}
    window.location.assign("/home");
  };

  // Persist local desktop profile so refresh keeps user context.
  useEffect(() => {
    if (!desktopLocal) return;
    try {
      if (!user) {
        localStorage.removeItem(LOCAL_USER_KEY);
        return;
      }
      localStorage.setItem(
        LOCAL_USER_KEY,
        JSON.stringify({
          name: user.name,
          email: user.email,
        })
      );
    } catch {}
  }, [desktopLocal, user]);

  // Auth bootstrap: local desktop mode or Firebase mode.
  useEffect(() => {
    if (desktopLocal) {
      try {
        const raw = localStorage.getItem(LOCAL_USER_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          const email = String(parsed?.email || "").trim();
          const name = String(parsed?.name || "").trim() || (email ? email.split("@")[0] : "User");
          if (email) {
            setUser({
              name,
              email,
              chats: [],
            });
            setUsers((prev) => {
              const idx = prev.findIndex((u) => u.email === email);
              if (idx >= 0) {
                const cloned = [...prev];
                cloned[idx] = { ...cloned[idx], name };
                return cloned;
              }
              return [...prev, { name, email, chats: [] }];
            });
          }
        } else {
          const guestEmail = "local@upcurved.desktop";
          const guestUser: User = {
            name: "Local User",
            email: guestEmail,
            chats: [],
          };
          setUser(guestUser);
          setUsers((prev) => {
            const idx = prev.findIndex((u) => u.email === guestEmail);
            if (idx >= 0) return prev;
            return [...prev, guestUser];
          });
          localStorage.setItem(
            LOCAL_USER_KEY,
            JSON.stringify({
              name: guestUser.name,
              email: guestUser.email,
            })
          );
        }
      } catch {}
      setBooting(false);
      return;
    }

    // Public landing should not initialize Firebase/auth listeners.
    if (isPublicLandingRoute) {
      setBooting(false);
      return;
    }

    const auth = getFirebaseAuth();
    // Ensure browser-local persistence (survives reloads)
    setPersistence(auth, browserLocalPersistence).catch(() => {});
    const unsub = onAuthStateChanged(auth, async (fbUser) => {
      try {
        if (fbUser) {
          const idToken = await fbUser.getIdToken();
          const email = fbUser.email || "unknown@example.com";
          // Always force blank greeting each login (ChatGPT behavior) until first user message.
          try { sessionStorage.setItem('app.forceBlank', '1'); } catch {}
          // Immediately load theme/color for this user to avoid flicker
          try {
            const tKey = `app.theme.${email}`;
            const cKey = `app.colorTheme.${email}`;
            const storedTheme = localStorage.getItem(tKey);
            const storedColor = localStorage.getItem(cKey);
            if (storedTheme === 'light' || storedTheme === 'dark') setTheme(storedTheme as Theme);
            if (storedColor && ['blue','rose','green','orange'].includes(storedColor)) setColorTheme(storedColor as ColorTheme);
          } catch {}
          // Set lightweight user object; chats live in `users` store
          setUser({
            name: fbUser.displayName || email.split('@')[0] || "User",
            email,
            uid: fbUser.uid,
            idToken,
            chats: [],
          });

          // Ensure the authenticated user exists in the global users list
          setUsers((prev) => {
            const idx = prev.findIndex((u) => u.email === email);
            if (idx >= 0) {
              // keep existing entry; make sure name is up-to-date
              const cloned = [...prev];
              cloned[idx] = { ...cloned[idx], name: fbUser.displayName || cloned[idx].name || email.split('@')[0] };
              return cloned;
            }
            // seed chats from local cache if present
            let cachedChats: any[] = [];
            try {
              const raw = localStorage.getItem(`app.chats.${email}`);
              if (raw) cachedChats = JSON.parse(raw);
            } catch {}
            return [...prev, { name: fbUser.displayName || email.split('@')[0] || "User", email, chats: Array.isArray(cachedChats) ? cachedChats : [] }];
          });
          // On refresh: preserve current URL - don't redirect
          // Only redirect if on root path and authenticated (first login)
          // Otherwise, preserve whatever URL they're on (e.g., /chat?id=xxx)
          const currentPath = location.pathname;
          if (currentPath === '/' && !location.search) {
            navigate('/chat', { replace: true });
          }
          // For all other paths (like /chat, /chat?id=xxx), do nothing - preserve them
        } else {
          // On logout: clear session flag so next login re-triggers greeting logic cleanly
          try { sessionStorage.removeItem('app.forceBlank'); } catch {}
          setUser(null);
          // Only redirect to home if not already there or on root
          const currentPath = location.pathname;
          if (currentPath !== '/home' && currentPath !== '/') {
            navigate('/home', { replace: true });
          } else if (currentPath === '/') {
            navigate('/home', { replace: true });
          }
        }
      } finally {
        setBooting(false);
      }
    });
    return () => unsub();
  }, [desktopLocal, isPublicLandingRoute, location.pathname, location.search, navigate]);

  if (booting) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin h-6 w-6 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <Routes>
      {/* Public routes (no auth required) */}
      <Route
        path="/home"
        element={
          desktopLocal ? (
            <Navigate to={`/chat${location.search}`} replace />
          ) : (
            <Landing setView={setViewStr} />
          )
        }
      />
      <Route
        path="/login"
        element={
          !user ? (
            <LoginPage
              setView={setViewStr}
              setUser={setUser}
              users={users}
              setUsers={setUsers}
            />
          ) : (
            <Navigate to={`/chat${location.search}`} replace />
          )
        }
      />

      {/* Protected routes (auth required) */}
      <Route
        path="/chat"
        element={
          user ? (
            <ChatInterface
              setView={setViewStr}
              user={user}
              setUser={setUser}
              theme={theme}
              setTheme={setTheme}
              colorTheme={colorTheme}
              setColorTheme={setColorTheme}
              users={users}
              setUsers={setUsers}
              apiKeys={apiKeys}
              setApiKeys={setApiKeys}
            />
          ) : (
            <Navigate to="/home" replace />
          )
        }
      />
      <Route
        path="/settings"
        element={
          user ? (
            <SettingsPage
              setView={setViewStr}
              user={user}
              apiKeys={apiKeys}
              setApiKeys={setApiKeys}
              onUpdateName={updateDisplayName}
              desktopLocal={desktopLocal}
              onResetLocalData={desktopLocal ? resetLocalData : undefined}
            />
          ) : (
            <Navigate to="/home" replace />
          )
        }
      />

      {/* Default redirects - only redirect if actually on root path */}
      <Route
        path="/"
        element={
          user ? (
            location.pathname === '/' ? (
              // Only redirect from root, preserve query params
              <Navigate to={`/chat${location.search}`} replace />
            ) : (
              // Not on root, don't redirect
              <Navigate to={location.pathname + location.search} replace />
            )
          ) : (
            <Navigate to="/home" replace />
          )
        }
      />
      {/* Catch-all: preserve current URL if already on chat route, otherwise redirect */}
      <Route
        path="*"
        element={
          user ? (
            location.pathname.startsWith('/chat') ? (
              // Already on chat route (with or without query params) - render ChatInterface directly
              <ChatInterface
                setView={setViewStr}
                user={user}
                setUser={setUser}
                theme={theme}
                setTheme={setTheme}
                colorTheme={colorTheme}
                setColorTheme={setColorTheme}
                users={users}
                setUsers={setUsers}
                apiKeys={apiKeys}
                setApiKeys={setApiKeys}
              />
            ) : (
              <Navigate to={`/chat${location.search}`} replace />
            )
          ) : (
            <Navigate to="/home" replace />
          )
        }
      />
    </Routes>
  );
};

const App = () => {
  const desktopLocal = isDesktopLocalMode();
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <div className="transition-colors duration-300">
          <BrowserRouter>
            <AppContent />
            {!desktopLocal && <Analytics />}
          </BrowserRouter>
        </div>
      </TooltipProvider>
    </QueryClientProvider>
  );
};

export default App;
