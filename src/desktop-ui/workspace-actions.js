(() => {
  const toolbar = document.querySelector('#workspace .toolbar');
  const actions = document.querySelector('#workspace .workspace-actions');
  if (!toolbar || !actions) return;

  const spacer = document.createElement('span');
  spacer.className = 'toolbar-spacer';
  toolbar.append(spacer);
  while (actions.firstChild) toolbar.append(actions.firstChild);
  actions.remove();

  const table = document.querySelector('#workspace .table-panel table');
  const headers = [...(table?.querySelectorAll('thead th') || [])];
  headers.find(header => header.textContent.trim() === '数据点')?.remove();

  const pager = document.querySelector('#workspace .pager');
  if (pager && !document.querySelector('#pageSize')) {
    const size = document.createElement('select');
    size.id = 'pageSize';
    size.setAttribute('aria-label', '每页显示条数');
    [20, 50, 100, 200, 500].forEach(value => {
      const option = document.createElement('option'); option.value = value; option.textContent = value; if (value === 100) option.selected = true; size.append(option);
    });
    const label = document.createElement('span'); label.className = 'page-size-label'; label.textContent = '每页';
    pager.insertBefore(label, pager.firstChild); pager.insertBefore(size, pager.children[1] || null);
    size.addEventListener('change', () => window.workspaceSetPageSize?.(Number(size.value)));
  }
  if (pager && !pager.querySelector('.workspace-pager-navigation')) {
    const settings = document.createElement('div'); settings.className = 'workspace-pager-settings';
    const range = document.createElement('span'); range.id = 'workspacePageRange'; range.setAttribute('role', 'status');
    const navigation = document.createElement('div'); navigation.className = 'workspace-pager-navigation';
    navigation.setAttribute('role', 'group'); navigation.setAttribute('aria-label', '检测记录翻页');
    settings.append(range);
    for (const id of ['.page-size-label', '#pageSize']) { const control = pager.querySelector(id); if (control) settings.append(control); }
    for (const [id, title] of [['prevBtn', '上一页'], ['pageInfo', '当前页 / 总页数'], ['nextBtn', '下一页']]) {
      const control = document.getElementById(id); control.title = title;
      if (control.tagName === 'BUTTON') control.setAttribute('aria-label', title);
      navigation.append(control);
    }
    pager.append(settings, navigation);
  }

  document.addEventListener('DOMContentLoaded', () => {
    const commands = toolbar.querySelector('.workspace-commands');
    const filters = toolbar.querySelector('.workspace-filters');
    if (!commands || !filters) return;
    const commandGroups = [
      ['data', '数据文件', ['openImportFlow', 'exportLedgerBtn', 'btn-recycle-bin']],
      ['danger', '危险操作', ['btn-data-delete', 'clearRecordsBtn']]
    ].map(([key, label, ids]) => {
      const group = document.createElement('div');
      group.className = 'workspace-command-group';
      group.dataset.commandGroup = key;
      group.setAttribute('role', 'group');
      group.setAttribute('aria-label', label);
      const caption = document.createElement('span');
      caption.className = 'workspace-command-caption';
      caption.textContent = label;
      group.append(caption);
      commands.append(group);
      return {group, ids};
    });
    const arrangeCommands = () => {
      for (const {group, ids} of commandGroups) for (const id of ids) {
        const button = document.getElementById(id);
        if (button && button.parentElement !== group) group.append(button);
      }
    };
    arrangeCommands();
    new MutationObserver(arrangeCommands).observe(commands, {childList:true});

    const tablePanel = document.querySelector('#workspace .table-panel');
    const columnModes = document.createElement('div');
    columnModes.className = 'workspace-column-modes';
    columnModes.setAttribute('role', 'group');
    columnModes.setAttribute('aria-label', '检测记录字段');
    columnModes.innerHTML = '<button type="button" data-workspace-columns="focus" title="显示管号、结论、深度、位置和维护信息">重点字段</button><button type="button" data-workspace-columns="all" title="显示全部原始表格字段">全部字段</button>';
    const tableActions = document.createElement('div');
    tableActions.className = 'workspace-table-actions';
    tableActions.append(tablePanel.querySelector('.selection-tools'), columnModes);
    tablePanel.querySelector('.panel-title').append(tableActions);
    const syncEmptyRowSpan = () => {
      const span = tablePanel.dataset.columns === 'all' ? 18 : 10;
      tablePanel.querySelectorAll('#rows td[colspan]').forEach(cell => {
        if (cell.colSpan !== span) cell.colSpan = span;
      });
    };
    const setColumns = mode => {
      tablePanel.dataset.columns = mode === 'all' ? 'all' : 'focus';
      columnModes.querySelectorAll('button').forEach(button =>
        button.setAttribute('aria-pressed', String(button.dataset.workspaceColumns === tablePanel.dataset.columns)));
      syncEmptyRowSpan();
      localStorage.setItem('thimble-workbench-columns', tablePanel.dataset.columns);
    };
    new MutationObserver(syncEmptyRowSpan).observe(tablePanel.querySelector('#rows'), {childList:true, subtree:true});
    columnModes.onclick = event => {
      const button = event.target.closest('[data-workspace-columns]');
      if (button) setColumns(button.dataset.workspaceColumns);
    };
    setColumns(localStorage.getItem('thimble-workbench-columns'));

    const scope = document.createElement('span');
    scope.id = 'workspaceFilterSummary';
    scope.className = 'workspace-scope-summary';
    scope.setAttribute('role', 'status');
    scope.setAttribute('aria-live', 'polite');
    commands.append(scope);
    const selection = document.querySelector('.workspace-selection-status');
    const heading = document.querySelector('#workspace .table-panel .panel-title');
    if (selection && heading) {
      selection.id = 'workspaceSelectionCount';
      heading.querySelector('div').append(selection);
    }
    const refresh = document.createElement('button');
    refresh.id = 'workspaceRefreshRecords';
    refresh.type = 'button';
    refresh.className = 'workspace-icon-button';
    refresh.title = '刷新检测记录';
    refresh.setAttribute('aria-label', refresh.title);
    refresh.onclick = async () => {
      refresh.disabled = true;
      refresh.setAttribute('aria-busy', 'true');
      try { await window.workspaceRefresh(); }
      catch (error) { window.toast(error.message, {type: 'error'}); }
      finally { refresh.disabled = false; refresh.removeAttribute('aria-busy'); }
    };
    commands.append(refresh);

    const updateScope = () => {
      const values = ['site', 'unit', 'outage', 'analyst', 'thimble'].map(id => {
        const field = document.getElementById(id);
        if (!field.value) return '';
        if (id === 'unit') return `${field.value}号机组`;
        if (id === 'thimble') return `通道 #${field.value}`;
        if (id === 'analyst') return `分析：${field.value}`;
        return field.selectedOptions?.[0]?.textContent || field.value;
      }).filter(Boolean);
      scope.textContent = values.join(' / ') || '全部检测记录';
      scope.title = scope.textContent;
      scope.dataset.filtered = String(values.length > 0);
      const loading = document.querySelector('#rows').getAttribute('aria-busy') === 'true';
      scope.dataset.loading = String(loading);
      toolbar.setAttribute('aria-busy', String(loading));
    };
    new MutationObserver(updateScope).observe(document.querySelector('#rows'), {
      childList: true, attributes: true, attributeFilter: ['aria-busy']
    });
    updateScope();
  }, {once: true});
})();
