class OperationLogViewer {
  constructor(container) { this.container = container; this.currentPage = 1; this.pageSize = 50; this.request = 0; }

  render() {
    this.container.innerHTML = '<div class="recycle-bin-panel"><div class="recycle-header"><h3>数据操作审计</h3><button id="log-refresh" type="button">刷新</button></div><div class="recycle-table-wrap"><table class="recycle-table"><thead><tr><th>编号</th><th>操作</th><th>范围</th><th>详情</th><th>记录数</th><th>操作人</th><th>时间</th><th>备注</th></tr></thead><tbody id="log-tbody"></tbody></table></div><div class="recycle-pagination" id="log-pagination"></div></div>';
    this.container.querySelector('#log-refresh').onclick = () => this.loadList(); this.loadList();
  }

  async loadList() {
    const request = ++this.request, host = this.container.querySelector('#log-tbody');
    host.setAttribute('aria-busy','true'); this.message('正在读取审计记录…');
    try {
      const data = await window.api(`/api/operation-logs?page=${this.currentPage}&size=${this.pageSize}`);
      if (request !== this.request || !this.container.isConnected) return;
      const pages = Math.max(1,Math.ceil(data.total/this.pageSize));
      if (this.currentPage > pages) { this.currentPage = pages; return this.loadList(); }
      this.renderTable(data.items); this.renderPagination(data.total);
    } catch (error) { if (request === this.request) this.message(`加载失败：${error.message}`, true); }
    finally { if (request === this.request) host.removeAttribute('aria-busy'); }
  }

  message(text, retry = false) {
    const host = this.container.querySelector('#log-tbody'), row = document.createElement('tr'), cell = row.insertCell();
    cell.colSpan = 8; cell.className = 'recycle-empty'; cell.textContent = text;
    if (retry) { const button = document.createElement('button'); button.textContent = '重试'; button.onclick = () => this.loadList(); cell.append(button); }
    host.replaceChildren(row); this.container.querySelector('#log-pagination').replaceChildren();
  }

  renderTable(items) {
    if (!items.length) { this.message('暂无数据操作审计记录'); return; }
    const labels = {soft_delete:'移入回收站',hard_delete:'永久删除',restore:'恢复数据',purge:'清空回收批次',state_delete:'删除管状态维护',state_direction_setting:'修改移位方向设置'};
    const scopeLabels = {tube_states:'所选管状态记录',state_preferences:'管状态识别设置'};
    const host = this.container.querySelector('#log-tbody'); host.replaceChildren();
    for (const item of items) {
      const row = host.insertRow();
      let detail=item.scope_detail||'/';
      if(item.operation_type==='state_delete'){
        try{const keys=JSON.parse(detail);detail=`${item.record_count} 条所选记录：${keys.map(key=>`${key.outage} 管${key.thimble_id}`).join('、')}`;}
        catch{detail=`${item.record_count} 条维护记录`;}
      }
      for (const value of [item.id,labels[item.operation_type]||item.operation_type,scopeLabels[item.scope]||item.scope,detail,item.record_count,item.operator,window.formatDateTime?.(item.created_at)||item.created_at,item.note||'/']) row.insertCell().textContent = value==null||value===''?'/':value;
    }
  }

  renderPagination(total) {
    const el = this.container.querySelector('#log-pagination'), pages = Math.max(1,Math.ceil(total/this.pageSize)); el.replaceChildren();
    const info = document.createElement('span'); info.textContent = `共 ${total} 条 · ${this.currentPage} / ${pages} 页`; el.append(info);
    for (const [text,delta,disabled] of [['上一页',-1,this.currentPage<=1],['下一页',1,this.currentPage>=pages]]) {
      const button = document.createElement('button'); button.textContent = text; button.disabled = disabled;
      button.onclick = () => { this.currentPage += delta; this.loadList(); }; el.append(button);
    }
  }
}
window.OperationLogViewer = OperationLogViewer;
