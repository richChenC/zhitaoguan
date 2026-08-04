(() => {
  const $ = selector => document.querySelector(selector);
  const navImport = $('#importBtn');
  const duplicateImport = $('#openImportFlow');
  const navFooter = document.querySelector('.app-nav footer');
  if (navImport && duplicateImport) duplicateImport.remove();
  if (navFooter) navFooter.remove();

  const table = document.querySelector('.table-panel table');
  const dataPointHeader = [...(table?.querySelectorAll('thead th') || [])].find(cell => cell.textContent.trim() === '数据点');
  dataPointHeader?.remove();
  const pager = document.querySelector('.table-panel .pager');
  if (pager && !document.querySelector('#pageSize')) {
    pager.innerHTML = '<div class="pager-left"><label for="pageSize">每页显示</label><select id="pageSize"><option value="10">10</option><option value="20">20</option><option value="50" selected>50</option><option value="100">100</option></select><span>条</span></div><div class="pager-right"><button id="prevBtn">上一页</button><span id="pageInfo">1 / 1</span><button id="nextBtn">下一页</button></div>';
    $('#pageSize').addEventListener('change', event => window.workspaceSetPageSize?.(Number(event.target.value)));
    $('#prevBtn').addEventListener('click', () => window.workspaceMovePage?.(-1));
    $('#nextBtn').addEventListener('click', () => window.workspaceMovePage?.(1));
  }
  if (navImport) navImport.title = '导入检测文件夹或 Excel 数据';

  document.querySelector('#rows')?.addEventListener('click', () => {
    setTimeout(() => document.dispatchEvent(new CustomEvent('workspace-selection-settled')), 0);
  });
})();
