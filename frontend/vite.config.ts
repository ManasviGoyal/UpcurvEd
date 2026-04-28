import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const devBackendTarget =
    process.env.VITE_API_BASE_URL ||
    process.env.VITE_DEV_BACKEND_TARGET ||
    "http://127.0.0.1:8000";

  return {
    server: {
      host: "::",
      port: 8080,
      proxy: {
        // forward API calls to FastAPI (dev only)
        "/echo": { target: devBackendTarget, changeOrigin: true },
        "/generate": { target: devBackendTarget, changeOrigin: true },
        "/edit": { target: devBackendTarget, changeOrigin: true },
        "/podcast": { target: devBackendTarget, changeOrigin: true },
        "/quiz": { target: devBackendTarget, changeOrigin: true },
        "/api": { target: devBackendTarget, changeOrigin: true },
        "/static": { target: devBackendTarget, changeOrigin: true },
        "/health": { target: devBackendTarget, changeOrigin: true },
        "/oauth": { target: devBackendTarget, changeOrigin: true },
        // if you later add websockets, use: "/ws": { target: "http://localhost:8000", ws: true }
      },
    },
    plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
  };
});
