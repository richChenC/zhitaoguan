(() => {
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const toolbar = $('#workspace .toolbar');
  const rows = $('#rows');
  if (!toolbar || !rows) return;

  const progress = document.createElement('div');
  progress.id = 'networkProgress';
  progress.setAttribute('aria-hidden', 'true');
  document.body.append(progress);

  const selectionBar = document.createElement('div');
  selectionBar.className = 'selection-action-bar';
  selectionBar.innerHTML = '<div><span id="selectionText">未选择记录</span><small id="selectionScope">勾选记录后可同步到二维和三维</small></div><div class="selection-actions"><button id="selectPageBtn" type="button">全选本页</button><button id="clearSelectionBtn" type="button" disabled>取消选择</button><button id="openSelection3dBtn" type="button" class="primary" disabled>三维查看</button></div>';
  toolbar.after(selectionBar);

  function selectedRows() { return $$('#rows tr[data-i]').filter(row => row.querySelector('input[type=checkbox]')?.checked); }
  function updateSelection() {
    const selected = selectedRows(), all = $$('#rows tr[data-i]');
    $('#selectionText').textContent = selected.length ? `已选择 ${selected.length} 条记录` : '未选择记录';
    $('#selectionScope').textContent = selected.length === 1 ? '可直接定位对应指套管' : selected.length > 1 ? '缺陷将在二维和三维中同时显示' : '勾选记录后可同步到二维和三维';
    $('#clearSelectionBtn').disabled = !selected.length;
    $('#openSelection3dBtn').disabled = !selected.length;
    $('#selectPageBtn').disabled = !all.length;
    $('#selectPageBtn').textContent = all.length && selected.length === all.length ? '取消本页' : '全选本页';
  }

  function setAll(checked) {
    $$('#rows tr[data-i] input[type=checkbox]').forEach(input => { if (input.checked !== checked) input.click(); });
    updateSelection();
  }

  $('#selectPageBtn').onclick = () => {
    const all = $$('#rows tr[data-i] input[type=checkbox]');
    setAll(!all.length || !all.every(input => input.checked));
  };
  $('#clearSelectionBtn').onclick = () => setAll(false);
  $('#openSelection3dBtn').onclick = () => {
    const selected = selectedRows();
    document.querySelector('[data-view="threeD"]')?.click();
    if (selected.length === 1) {
      const cells = selected[0].children;
      window.dispatchEvent(new CustomEvent('three-focus-tube', { detail: { outage: cells[1]?.textContent.trim(), unit: Number(cells[2]?.textContent.trim()), thimble: Number(cells[3]?.textContent.replace(/\D/g, '')) } }));
    }
  };

  rows.addEventListener('click', () => setTimeout(updateSelection, 0));
  new MutationObserver(updateSelection).observe(rows, { childList: true });
  updateSelection();

  let pending = 0;
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    pending += 1; document.body.classList.add('network-busy');
    try { return await nativeFetch(...args); }
    finally { pending -= 1; if (!pending) document.body.classList.remove('network-busy'); }
  };

  $$('.app-nav [data-view]').forEach(button => button.addEventListener('click', () => {
    $$('.app-nav [data-view]').forEach(item => item.removeAttribute('aria-current'));
    button.setAttribute('aria-current', 'page');
  }));
  $('.app-nav [data-view].active')?.setAttribute('aria-current', 'page');

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.activeElement?.matches('#workspace input')) document.activeElement.blur();
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f' && $('#workspace').classList.contains('active')) {
      event.preventDefault(); $('#thimble')?.focus();
    }
  });
})();
