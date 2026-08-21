import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";
import fs from "fs";

// The owner/repo lives in the root package.json `repository` field — the standard place
// for it — so a rename or org move is a one-line change there, not a hunt through the UI
// code. Injected at build time; nothing reads it at runtime.
function releaseAssetsBaseUrl(): string {
  const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, "..", "package.json"), "utf8"));
  const url: string = pkg.repository?.url ?? "";
  const slug = url.replace(/^git\+/, "").replace(/\.git$/, "").split("github.com/")[1];
  if (!slug) {
    throw new Error(
      "Cannot derive the GitHub repo from package.json `repository.url`; " +
        "the landing page download links depend on it."
    );
  }
  return `https://github.com/${slug}/releases/latest/download`;
}

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const devBackendTarget =
    process.env.VITE_API_BASE_URL ||
    process.env.VITE_DEV_BACKEND_TARGET ||
    "http://127.0.0.1:8000";

  return {
    define: {
      __RELEASE_ASSETS_BASE__: JSON.stringify(releaseAssetsBaseUrl()),
    },
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
