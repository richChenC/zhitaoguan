const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('desktopAPI', {
  selectDirectory: () => ipcRenderer.invoke('select-directory'),
  // Returns an array of selected workbook paths (possibly empty when cancelled).
  selectExcel: () => ipcRenderer.invoke('select-excel'),
  // Returns { folder, files, truncated } or null when cancelled.
  selectExcelFolder: () => ipcRenderer.invoke('select-excel-folder'),
  saveCoreImage: payload => ipcRenderer.invoke('save-core-image', payload),
  saveVisualizationImage: payload => ipcRenderer.invoke('save-visualization-image', payload),
  saveLedger: payload => ipcRenderer.invoke('save-ledger', payload),
  saveOfficeFile: payload => ipcRenderer.invoke('save-office-file', payload),
  saveProvenance: payload => ipcRenderer.invoke('save-provenance', payload),
  onDownloadStatus: callback => ipcRenderer.on('desktop-download-status', (_event, status) => callback(status)),
  openReportHeader: () => ipcRenderer.invoke('open-report-header'),
  saveReportHeader: payload => ipcRenderer.invoke('save-report-header', payload),
  // Returns the chosen folder path or null when cancelled.
  selectBackupDirectory: () => ipcRenderer.invoke('select-backup-directory'),
  // Returns the chosen .db file path or null when cancelled.
  selectBackupFile: () => ipcRenderer.invoke('select-backup-file'),
  openLocalDocument: relativePath => ipcRenderer.invoke('open-local-document', relativePath),
  openDocumentsFolder: () => ipcRenderer.invoke('open-documents-folder'),
  openSettingsWindow: section => ipcRenderer.invoke('open-settings-window', section),
  openVisualizationWindow: payload => ipcRenderer.invoke('open-visualization-window', payload),
  closeSettingsWindow: () => ipcRenderer.invoke('close-settings-window'),
  getWorkspaceReportScope: () => ipcRenderer.invoke('get-workspace-report-scope'),
  onSettingsSection: callback => ipcRenderer.on('settings-section', (_event, section) => callback(section))
});
