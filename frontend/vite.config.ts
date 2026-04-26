import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    port: 8080,
    proxy: {
      // forward API calls to FastAPI (dev only)
      "/echo":    { target: "http://backend:8000", changeOrigin: true },
      "/generate":{ target: "http://backend:8000", changeOrigin: true },
      "/edit":    { target: "http://backend:8000", changeOrigin: true },
    "/podcast": { target: "http://backend:8000", changeOrigin: true },
  "/quiz":    { target: "http://backend:8000", changeOrigin: true },
      "/api":     { target: "http://backend:8000", changeOrigin: true },
      "/static":  { target: "http://backend:8000", changeOrigin: true },
      "/health":  { target: "http://backend:8000", changeOrigin: true },
  "/oauth":   { target: "http://backend:8000", changeOrigin: true },
      // if you later add websockets, use: "/ws": { target: "http://localhost:8000", ws: true }
    },
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
