// desktop/preload.cjs
const { contextBridge, ipcRenderer } = require("electron");

function readArg(prefix) {
  const hit = process.argv.find((arg) => arg.startsWith(prefix));
  if (!hit) return "";
  return hit.slice(prefix.length);
}

const runtimeApiBaseUrl = readArg("--upcurved-api-base-url=");

contextBridge.exposeInMainWorld("desktop", {
  isDesktop: true,
  platform: process.platform,
  apiBaseUrl: runtimeApiBaseUrl,
  secureStore: {
    getApiKeys: (account) => ipcRenderer.invoke("secure-store:get-api-keys", account),
    setApiKeys: (account, payload) =>
      ipcRenderer.invoke("secure-store:set-api-keys", { account, payload }),
    clearApiKeys: (account) => ipcRenderer.invoke("secure-store:clear-api-keys", account),
  },
});
