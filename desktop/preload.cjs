const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('desktopAPI', {
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  selectExcel: () => ipcRenderer.invoke('select-excel'),
  saveCoreImage: payload => ipcRenderer.invoke('save-core-image', payload)
});
