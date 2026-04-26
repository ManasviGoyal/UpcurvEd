const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  isDesktop: true,
  platform: process.platform,
  secureStore: {
    getApiKeys: (account) => ipcRenderer.invoke("secure-store:get-api-keys", account),
    setApiKeys: (account, payload) =>
      ipcRenderer.invoke("secure-store:set-api-keys", { account, payload }),
    clearApiKeys: (account) => ipcRenderer.invoke("secure-store:clear-api-keys", account),
  },
});
