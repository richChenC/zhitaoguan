(() => {
  const $ = selector => document.querySelector(selector);
  const navImport = $('#importBtn');
  const duplicateImport = $('#openImportFlow');
  const navFooter = document.querySelector('.app-nav footer');
  if (duplicateImport) duplicateImport.remove();
  if (navFooter) navFooter.remove();

  const metrics = document.querySelector('.metrics');
  if (metrics) metrics.remove();

  const tableTitle = document.querySelector('.table-panel .panel-title');
  if (tableTitle && !$('#pageSize')) {
    const control = document.createElement('label');
    control.className = 'page-size';
    control.innerHTML = '每页 <select id="pageSize"><option value="10">10</option><option value="20">20</option><option value="30">30</option><option value="40">40</option><option value="50" selected>50</option></select> 条';
    tableTitle.append(control);
    $('#pageSize').addEventListener('change', event => {
      window.workspaceSetPageSize?.(Number(event.target.value));
    });
  }

  const table = document.querySelector('.table-panel table');
  if (table) {
    const header = table.querySelector('thead tr');
    if (header && header.children.length > 9) header.children[8].remove();
  }

  if (navImport) navImport.title = '导入检测文件夹或 Excel 数据';

  document.querySelector('#rows')?.addEventListener('click', () => {
    setTimeout(() => document.dispatchEvent(new CustomEvent('workspace-selection-settled')), 0);
  });
})();
