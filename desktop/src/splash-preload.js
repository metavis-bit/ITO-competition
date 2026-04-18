const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('ito', {
  onStatus: (handler) => {
    ipcRenderer.on('status:update', (_event, payload) => handler(payload));
  },
  openLogs: () => ipcRenderer.invoke('splash:open-logs'),
  quit: () => ipcRenderer.invoke('splash:quit'),
});
