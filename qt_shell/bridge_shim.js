/* Electron contextBridge 的 Qt 等价实现（前端零改动）。
 *
 * 在 DocumentCreation 注入，同步挂上 window.desktopAPI；QWebChannel 异步
 * 就绪前把调用排入队列。20 个方法与 preload.cjs 一一对应。
 *
 * 大二进制（Uint8Array / ArrayBuffer）在 JS 侧转 base64，避免 QWebChannel
 * 把 TypedArray 序列化成百万级数字的 JSON 数组。
 */
(function () {
  'use strict';
  if (window.desktopAPI) return;

  var ready = false;
  var bridge = null;
  var pending = [];
  var downloadListeners = [];
  var sectionListeners = [];
  var initAttempts = 0;

  function toBase64(value) {
    var u8;
    if (value instanceof Uint8Array) u8 = value;
    else if (value instanceof ArrayBuffer) u8 = new Uint8Array(value);
    else if (ArrayBuffer.isView(value)) u8 = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    else return null;
    var chunk = 0x8000;
    var parts = [];
    for (var i = 0; i < u8.length; i += chunk) {
      parts.push(String.fromCharCode.apply(null, u8.subarray(i, i + chunk)));
    }
    return btoa(parts.join(''));
  }

  function encodePayload(payload) {
    if (!payload || typeof payload !== 'object') return payload;
    var out = {};
    for (var key in payload) {
      if (!Object.prototype.hasOwnProperty.call(payload, key)) continue;
      var value = payload[key];
      if (value instanceof Uint8Array || value instanceof ArrayBuffer || ArrayBuffer.isView(value)) {
        var encoded = toBase64(value);
        out[key] = { __qt_b64__: encoded };
      } else {
        out[key] = value;
      }
    }
    return out;
  }

  function emit(listeners, payload) {
    for (var i = 0; i < listeners.length; i += 1) {
      try { listeners[i](payload); } catch (e) { /* 单个监听器异常不影响其他 */ }
    }
  }

  function flushOne(item) {
    var envelope;
    try {
      envelope = JSON.stringify({
        method: item.name,
        payload: encodePayload(item.payload),
        href: location.href
      });
    } catch (e) {
      item.reject(e);
      return;
    }
    bridge.invoke(envelope, function (raw) {
      try {
        var parsed = (typeof raw === 'string') ? JSON.parse(raw) : raw;
        if (parsed && parsed.__qt_error__) { item.reject(new Error(parsed.__qt_error__)); return; }
        item.resolve(parsed && Object.prototype.hasOwnProperty.call(parsed, 'value') ? parsed.value : parsed);
      } catch (e) { item.reject(e); }
    });
  }

  function invoke(name, payload) {
    return new Promise(function (resolve, reject) {
      var item = { name: name, payload: payload, resolve: resolve, reject: reject };
      if (ready) flushOne(item); else pending.push(item);
    });
  }

  /* main.cjs:431-438 —— 直接读当前页面 DOM，零往返 */
  function workspaceReportScope() {
    var result = { scope: {}, records: [] };
    ['site', 'unit', 'outage'].forEach(function (id) {
      var el = document.getElementById(id);
      result.scope[id] = el ? (el.value || '') : '';
    });
    try {
      var state = window.__thimbleState;
      var selected = state && state.selectedRecords;
      if (selected && typeof selected.values === 'function') {
        Array.from(selected.values()).forEach(function (row) {
          result.records.push({
            id: row.id, site_code: row.site_code, unit_id: row.unit_id, outage: row.outage
          });
        });
      }
    } catch (e) { /* 页面尚未初始化时返回空记录 */ }
    return result;
  }

  var api = {
    selectDirectory: function () { return invoke('select-directory'); },
    selectExcel: function () { return invoke('select-excel'); },
    selectExcelFolder: function () { return invoke('select-excel-folder'); },
    saveCoreImage: function (p) { return invoke('save-core-image', p); },
    saveVisualizationImage: function (p) { return invoke('save-visualization-image', p); },
    saveLedger: function (p) { return invoke('save-ledger', p); },
    saveOfficeFile: function (p) { return invoke('save-office-file', p); },
    saveProvenance: function (p) { return invoke('save-provenance', p); },
    saveReportHeader: function (p) { return invoke('save-report-header', p); },
    openReportHeader: function () { return invoke('open-report-header'); },
    selectBackupDirectory: function () { return invoke('select-backup-directory'); },
    selectBackupFile: function () { return invoke('select-backup-file'); },
    factoryReset: function () { return invoke('factory-reset'); },
    openLocalDocument: function (p) { return invoke('open-local-document', p); },
    openDocumentsFolder: function () { return invoke('open-documents-folder'); },
    openSettingsWindow: function (section) { return invoke('open-settings-window', section); },
    openVisualizationWindow: function (p) { return invoke('open-visualization-window', p); },
    closeSettingsWindow: function () { return invoke('close-settings-window'); },
    getWorkspaceReportScope: function () { return Promise.resolve(workspaceReportScope()); },
    onDownloadStatus: function (cb) {
      if (typeof cb === 'function') downloadListeners.push(cb);
    },
    onSettingsSection: function (cb) {
      if (typeof cb === 'function') sectionListeners.push(cb);
    }
  };
  Object.defineProperty(window, 'desktopAPI', { value: api, writable: false, configurable: false });
  /* 仅供启动冒烟测试：验证渲染进程 <-> Python 的 QWebChannel 往返 */
  window.__qtChannelProbe = function () { return invoke('__qt_ping'); };

  function connectSignals() {
    if (bridge.downloadStatus && typeof bridge.downloadStatus.connect === 'function') {
      bridge.downloadStatus.connect(function (raw) {
        var payload = (typeof raw === 'string') ? JSON.parse(raw) : raw;
        emit(downloadListeners, payload);
      });
    }
    if (bridge.settingsSection && typeof bridge.settingsSection.connect === 'function') {
      bridge.settingsSection.connect(function (section) { emit(sectionListeners, section); });
    }
  }

  function init() {
    initAttempts += 1;
    if (typeof QWebChannel === 'undefined' || !window.qt || !window.qt.webChannelTransport) {
      if (initAttempts < 400) setTimeout(init, 25);
      return;
    }
    try {
      new QWebChannel(window.qt.webChannelTransport, function (channel) {
        bridge = channel.objects.desktop;
        if (!bridge || typeof bridge.invoke !== 'function') {
          setTimeout(init, 50);
          return;
        }
        connectSignals();
        ready = true;
        window.__qtBridgeReady = true;
        var queued = pending.splice(0);
        queued.forEach(flushOne);
      });
    } catch (e) {
      if (initAttempts < 400) setTimeout(init, 50);
    }
  }
  init();
})();
