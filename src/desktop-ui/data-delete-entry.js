// ============================================================
// 数据删除入口 & 回收站 & 操作日志
// 在工作台工具栏注入删除操作入口
// ============================================================

(() => {
  function addDeleteToolbarButtons() {
    const toolbar = document.querySelector('#workspace .toolbar');
    if (!toolbar) return;
    if (document.querySelector('#btn-data-delete')) return;

    const sep = document.createElement('span');
    sep.className = 'toolbar-sep';
    toolbar.appendChild(sep);

    // 批量删除按钮
    const batchBtn = document.createElement('button');
    batchBtn.id = 'btn-data-delete';
    batchBtn.className = 'btn btn-ghost';
    batchBtn.textContent = '删除所选';
    batchBtn.title = '删除选中的检测记录';
    batchBtn.addEventListener('click', () => {
      const selected = getSelectedFindings();
      if (!selected.length) {
        window.toast('请先勾选需要删除的记录', {type:'warning'});
        return;
      }
      if (!window.dataDeleteMgr) {
        window.toast('删除管理器未加载，请重新打开软件', {type:'error'});
        return;
      }
      window.dataDeleteMgr.openDeleteConfirm('selected', {
        findingIds: selected,
        count: selected.length,
      });
    });
    toolbar.appendChild(batchBtn);

    // 回收站入口
    const recycleBtn = document.createElement('button');
    recycleBtn.id = 'btn-recycle-bin';
    recycleBtn.className = 'btn btn-ghost';
    recycleBtn.textContent = '回收站';
    recycleBtn.title = '查看已删除的数据，可恢复或彻底删除';
    recycleBtn.addEventListener('click', openRecycleBinDialog);
    toolbar.appendChild(recycleBtn);
  }

  function getSelectedFindings() {
    return [...(window.__thimbleState?.selectedIds || [])]
      .filter(id => Number.isInteger(id) && id > 0);
  }

  // 回收站弹窗
  function openRecycleBinDialog() {
    const existing = document.querySelector('#recycle-bin-dialog');
    if (existing) { existing.remove(); return; }

    const previousFocus = document.activeElement;
    const overlay = document.createElement('dialog');
    overlay.id = 'recycle-bin-dialog';
    overlay.className = 'ddm-overlay';
    overlay.setAttribute('aria-label', '数据回收站');
    overlay.style.alignItems = 'flex-start';
    overlay.style.paddingTop = '5vh';
    overlay.innerHTML = `
      <div class="ddm-modal" style="width:800px;max-width:95vw;">
        <div class="ddm-header">
          <span class="ddm-title">数据回收站</span>
          <span class="recycle-tip">误删可恢复；永久删除需单独确认</span>
        </div>
        <div class="ddm-body" style="padding:0;">
          <div id="recycle-content" style="min-height:300px;">
            <div style="padding:40px;text-align:center;color:#94a3b8;">加载中...</div>
          </div>
        </div>
        <div class="ddm-footer">
          <button class="ddm-btn ddm-cancel" id="recycle-close-btn">关闭</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);
    overlay.showModal();
    const closed = new AbortController();
    overlay.addEventListener('close', () => { closed.abort(); overlay.remove(); previousFocus?.isConnected && previousFocus.focus(); }, {once:true});

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.close();
    });
    overlay.querySelector('#recycle-close-btn').addEventListener('click', () => overlay.close());

    // 初始化回收站管理器
    if (window.RecycleBinManager) {
      const container = overlay.querySelector('#recycle-content');
      const rb = new RecycleBinManager(container);
      rb.render();
      // 恢复或删除后刷新数据
      window.addEventListener('data-restored', () => rb.loadList(), {signal:closed.signal});
    }
  }

  // 页面就绪后注入按钮
  function tryInject() {
    addDeleteToolbarButtons();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', tryInject);
  } else {
    tryInject();
  }

  // 主工作区用 History API 切换视图；监听导航事件即可，避免永久轮询。
  const scheduleInject = () => setTimeout(tryInject, 300);
  let lastHref = location.href;
  const checkNavigation = () => {
    if (location.href === lastHref) return;
    lastHref = location.href;
    scheduleInject();
  };
  const originalPushState = history.pushState;
  const originalReplaceState = history.replaceState;
  history.pushState = function (...args) {
    const result = originalPushState.apply(this, args);
    checkNavigation();
    return result;
  };
  history.replaceState = function (...args) {
    const result = originalReplaceState.apply(this, args);
    checkNavigation();
    return result;
  };
  window.addEventListener('popstate', checkNavigation);

  // 暴露到全局
  window.openRecycleBin = openRecycleBinDialog;
})();
