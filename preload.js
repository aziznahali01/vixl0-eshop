const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  getGames: () => ipcRenderer.invoke("app:getGames"),

  getSettings: () => ipcRenderer.invoke("settings:get"),
  saveSettings: (settings) => ipcRenderer.invoke("settings:save", settings),
  chooseFolder: () => ipcRenderer.invoke("settings:chooseFolder"),

  enqueueDownload: (game) => ipcRenderer.invoke("downloads:enqueue", game),
  cancelDownload: (taskId) => ipcRenderer.invoke("downloads:cancel", taskId),
  getDownloadState: () => ipcRenderer.invoke("downloads:getState"),
  onDownloadState: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("downloads:state", listener);
    return () => ipcRenderer.removeListener("downloads:state", listener);
  }
});
