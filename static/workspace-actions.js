(() => {
  const toolbar = document.querySelector('#workspace .toolbar');
  const actions = document.querySelector('#workspace .workspace-actions');
  if (!toolbar || !actions) return;

  const spacer = document.createElement('span');
  spacer.className = 'toolbar-spacer';
  toolbar.append(spacer);
  while (actions.firstChild) toolbar.append(actions.firstChild);
  actions.remove();

  // Data rows no longer contain the deprecated data-point field.
  const table = document.querySelector('#workspace .table-panel table');
  const headers = table?.querySelectorAll('thead th');
  if (headers?.length >= 10) headers[8].remove();

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

  const compareTable = document.querySelector('#compare .comparison-table');
  const compareHeadRows = compareTable?.querySelectorAll('thead tr');
  const compareDetailHead = compareHeadRows?.[1];
  if (compareDetailHead && compareDetailHead.children.length >= 8) {
    compareDetailHead.children[7].remove();
    compareDetailHead.children[3].remove();
    if (compareHeadRows[0]?.children[3]) compareHeadRows[0].children[3].colSpan = 3;
    if (compareHeadRows[0]?.children[4]) compareHeadRows[0].children[4].colSpan = 3;
  }
  const cleanCompareRows = () => document.querySelectorAll('#compareRows tr').forEach(row => {
    if (row.children.length >= 12) { row.children[10].remove(); row.children[6].remove(); }
  });
  document.querySelector('#compareBtn')?.addEventListener('click', () => setTimeout(cleanCompareRows, 0));
  const compareRows = document.querySelector('#compareRows');
  if (compareRows) new MutationObserver(cleanCompareRows).observe(compareRows, {childList: true});
})();
