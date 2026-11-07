// Load heavyweight workspaces on first use. The main workbench stays small and
// responsive while the feature modules retain their existing self-mounting API.
(() => {
  const modules = {
    analytics: '/modules/analytics/official-workspace.js?v=20261107-e3f',
    reports: '/modules/analysis-center.js?v=20261106-lazy',
  };
  const styles = {
    analytics: [
      '/modules/analytics/analytics.css?v=20261016a',
      '/analysis-center.css?v=20261107-tokens',
      '/visualization-workspace.css?v=20261101-plate-scope',
      '/status-change-workspace.css?v=20261101-redesign',
      '/visualization-windows.css?v=20261102',
    ],
    reports: [
      '/analysis-center.css?v=20261107-tokens',
      '/report-preview.css?v=20261107-tokens',
      '/report-workspace.css?v=20261023-report-center-workflow',
    ],
    settings: [
      '/import-quality.css?v=20261018a',
    ],
  };
  const pending = new Map();
  const pendingStyles = new Map();

  function loadStyle(source) {
    if (!pendingStyles.has(source)) {
      const existing = [...document.querySelectorAll('link[rel="stylesheet"]')]
        .find(link => link.href === new URL(source, location.href).href);
      if (existing) {
        pendingStyles.set(source, Promise.resolve());
      } else {
        pendingStyles.set(source, new Promise((resolve, reject) => {
          const link = document.createElement('link');
          link.rel = 'stylesheet';
          link.href = source;
          link.dataset.thimbleLazyStyle = 'true';
          link.addEventListener('load', resolve, {once: true});
          link.addEventListener('error', () => reject(new Error(`样式加载失败：${source}`)), {once: true});
          document.head.append(link);
        }));
      }
    }
    return pendingStyles.get(source);
  }

  function loadStyles(view) {
    return Promise.all((styles[view] || []).map(loadStyle));
  }

  async function load(view) {
    const source = modules[view];
    if (!source) return Promise.resolve();
    if (!pending.has(view)) {
      const promise = loadStyles(view).then(() => import(source)).catch(error => {
        pending.delete(view);
        const message = view === 'analytics'
          ? '数据可视化模块加载失败，请重试。'
          : '报告中心模块加载失败，请重试。';
        window.toast?.(`${message} ${error.message || error}`, {type: 'error'});
        throw error;
      });
      pending.set(view, promise);
    }
    return pending.get(view);
  }

  window.__thimbleLoadWorkspace = load;
  window.addEventListener('app-view-changed', event => {
    void load(event.detail?.view);
  });

  // Settings is a separate window and stays hidden until local authentication
  // resolves, so its audit styles can load without delaying the main workbench.
  if (document.documentElement.dataset.settingsWindow === 'true') void loadStyles('settings');

  // A saved startup view may already be active before this loader runs.
  for (const view of Object.keys(modules)) {
    if (document.querySelector(`#${view}.active`)) void load(view);
  }
})();
