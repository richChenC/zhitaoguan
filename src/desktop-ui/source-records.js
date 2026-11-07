(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, character =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const fields = [
    ['thimble_id','管号'],['position','堆芯位置'],['entry_no','序号'],
    ['source_indication','原始三字符'],['indication','当前结论'],['volts','幅值 (V)'],['degrees','相位 (°)'],
    ['percent','深度 (%)'],['location_raw','原始磨损位置'],['channel','测量通道'],
    ['filename','数据文件'],['calgroup','数据组'],['analyst','分析人员'],
    ['datapoint','数据点'],['comment','原始注释'],['measurement_type','测量类型'],
    ['report_path','RPT 来源'],['display_conclusion','统计结论'],['classification_basis','分类依据']
  ];
  window.openInspectionRecords = async ({unit, outage, thimble}) => {
    const match = /^([A-Z]+)(\d+)$/.exec(String(unit));
    const wholeOutage = thimble === undefined;
    if (!match || !outage || (!wholeOutage &&
      (!Number.isInteger(Number(thimble)) || Number(thimble)<1 || Number(thimble)>50))) return;
    const previous = document.activeElement;
    const dialog = document.createElement('dialog');
    dialog.className = 'vw-record-dialog source-record-dialog';
    dialog.setAttribute('aria-label', '原始检测记录');
    dialog.innerHTML = `<form method="dialog" class="vw-record-head"><h2>${escape(unit)} · ${escape(outage)} · ${wholeOutage?'全部通道':`通道 #${escape(thimble)}`}</h2><button value="cancel" type="submit" aria-label="关闭">关闭</button></form>
      <p class="vw-record-basis">原始检测记录 · 保留各来源行，不合并 NDD；可能多于统计采用行</p>
      <div class="vw-record-table" aria-live="polite"></div>
      <div class="vw-record-pager"><button type="button" data-prev>上一页</button><span role="status"></span><button type="button" data-next>下一页</button><button type="button" data-retry hidden>重试</button></div>`;
    document.body.append(dialog);
    dialog.addEventListener('close', () => {
      controller?.abort();
      dialog.remove();
      if (previous?.isConnected) previous.focus();
    }, {once:true});
    dialog.showModal();
    let page = 1, pages = 1, controller;
    const table = dialog.querySelector('.vw-record-table');
    const status = dialog.querySelector('[role=status]');
    const prev = dialog.querySelector('[data-prev]'), next = dialog.querySelector('[data-next]');
    const retry = dialog.querySelector('[data-retry]');
    const load = async () => {
      controller?.abort();
      const active = new AbortController();
      controller = active;
      prev.disabled = next.disabled = true;
      retry.hidden = true;
      table.setAttribute('aria-busy','true');
      table.textContent = '正在读取…';
      table.scrollTop = table.scrollLeft = 0;
      status.textContent = `第 ${page} 页 · 正在读取…`;
      const timeout = setTimeout(() => active.abort(new DOMException('读取超时，请重试', 'TimeoutError')), 20000);
      const query = new URLSearchParams({site:match[1],unit:match[2],outage,
        raw:'1',sources:'1',core:'0',page:String(page),size:'100'});
      if (!wholeOutage) query.set('thimble',String(thimble));
      try {
        const response = await fetch('/api/findings?' + query, {signal:active.signal});
        const result = await response.json();
        if (!response.ok) throw Error(result.error || '读取失败');
        if (!dialog.open || active.signal.aborted || controller !== active) return;
        if (!Array.isArray(result.items)) throw Error('记录格式异常，请重试');
        pages = Math.max(1, Number(result.pages) || 1);
        if (page > pages) {page = pages;return load();}
        table.innerHTML = `<table><thead><tr>${fields.map(([,label]) => `<th>${label}</th>`).join('')}</tr></thead><tbody>${result.items.map(row =>
          `<tr>${fields.map(([key]) => `<td>${escape(row[key] == null || row[key] === '' ? '/' : row[key])}</td>`).join('')}</tr>`
        ).join('') || `<tr><td colspan="${fields.length}">${wholeOutage?'本次大修':'该通道本轮'}无检测记录</td></tr>`}</tbody></table>`;
        status.textContent = `共 ${result.total} 条 · ${page} / ${pages} 页`;
        prev.disabled = page <= 1;
        next.disabled = page >= pages;
      } catch (error) {
        if (!dialog.open || controller !== active) return;
        if (active.signal.aborted && active.signal.reason?.name !== 'TimeoutError') return;
        table.textContent = `读取失败：${active.signal.reason?.name === 'TimeoutError' ? '读取超时，请重试' : error.message}`;
        status.textContent = `第 ${page} 页未读取`;
        prev.disabled = page <= 1;
        next.disabled = page >= pages;
        retry.hidden = false;
      } finally {
        clearTimeout(timeout);
        if (controller === active) table.setAttribute('aria-busy','false');
      }
    };
    prev.onclick = () => {if (page > 1) {page--;load();}};
    next.onclick = () => {if (page < pages) {page++;load();}};
    retry.onclick = load;
    await load();
  };
})();
