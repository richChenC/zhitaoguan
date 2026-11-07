class RecycleBinManager {
  constructor(container) {
    this.container = container;
    this.currentPage = 1;
    this.pageSize = 20;
    this.request = 0;
    this.pending = new Set();
  }

  render() {
    this.container.innerHTML = '<div class="recycle-bin-panel"><div class="recycle-header"><h3>数据回收站</h3><button id="recycle-refresh" type="button">刷新</button></div><div class="recycle-table-wrap"><table class="recycle-table"><thead><tr><th>删除范围</th><th>记录数</th><th>删除时间</th><th>备份文件</th><th>操作</th></tr></thead><tbody id="recycle-tbody"></tbody></table></div><div class="recycle-pagination" id="recycle-pagination"></div></div>';
    this.container.querySelector('#recycle-refresh').onclick = () => this.loadList();
    this.loadList();
  }

  async loadList() {
    const request = ++this.request;
    const tbody = this.container.querySelector('#recycle-tbody');
    tbody.setAttribute('aria-busy', 'true'); this.message('正在加载回收站…');
    try {
      const data = await window.api(`/api/recycle-bin/list?page=${this.currentPage}&size=${this.pageSize}`);
      if (request !== this.request || !this.container.isConnected) return;
      const pages = Math.max(1, Math.ceil(data.total / this.pageSize));
      if (this.currentPage > pages) { this.currentPage = pages; return this.loadList(); }
      this.renderTable(data.items); this.renderPagination(data.total);
    } catch (error) { if (request === this.request) this.message(`加载失败：${error.message}`, true); }
    finally { if (request === this.request) tbody.removeAttribute('aria-busy'); }
  }

  message(text, retry = false) {
    const tbody = this.container.querySelector('#recycle-tbody');
    const row = document.createElement('tr'), cell = row.insertCell();
    cell.colSpan = 5; cell.className = 'recycle-empty'; cell.textContent = text; cell.setAttribute('role', 'status');
    if (retry) { const button = document.createElement('button'); button.textContent = '重试'; button.onclick = () => this.loadList(); cell.append(button); }
    tbody.replaceChildren(row); this.container.querySelector('#recycle-pagination').replaceChildren();
  }

  renderTable(items) {
    if (!items?.length) { this.message('回收站为空'); return; }
    const tbody = this.container.querySelector('#recycle-tbody'); tbody.replaceChildren();
    for (const item of items) {
      const row = tbody.insertRow(); row.dataset.id = item.id;
      for (const value of [item.scope_label || item.scope, item.record_count, item.deleted_at, item.backup_file || '未生成备份文件']) {
        const cell = row.insertCell(); cell.textContent = value; cell.title = String(value);
      }
      const cell = row.insertCell();
      for (const [label, cls, action] of [['恢复','btn-restore',()=>this.restoreOne(item.id)],['彻底删除','btn-purge',()=>this.purgeOne(item.id)]]) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
        button.className = `btn-link ${cls}`; button.dataset.id = item.id; button.disabled = this.pending.has(item.id); button.onclick = action; cell.append(button);
      }
    }
  }

  async mutate(batchId, purge) {
    if (this.pending.has(batchId)) return;
    this.pending.add(batchId);
    this.container.querySelectorAll('button[data-id]').forEach(button => { if (button.dataset.id === batchId) button.disabled = true; });
    try {
      const data = await window.api(`/api/recycle-bin/${purge ? 'purge' : 'restore'}`, {method:'POST', body:JSON.stringify({batchId})});
      const count = purge ? data.purgedCount : data.restoredCount;
      if (!Number.isInteger(count)) throw new Error('本地服务返回的记录数量无效，请刷新核对');
      window.toast(purge ? `已彻底删除 ${count} 条记录` : data.alreadyRestored?'此批数据已恢复':`已恢复 ${count} 条记录`);
      if (!purge) window.dispatchEvent(new CustomEvent('data-restored', {detail:data}));
      await this.loadList();
    } catch (error) { window.toast(error.message, {type:'error'}); }
    finally {
      this.pending.delete(batchId);
      this.container.querySelectorAll('button[data-id]').forEach(button => { if (button.dataset.id === batchId) button.disabled = false; });
    }
  }

  async restoreOne(batchId) {
    if (await window.appFeedback.confirm('恢复后，这批检测数据会重新参与查询、统计和报告。', {title:'恢复这批数据',confirmLabel:'恢复数据'})) await this.mutate(batchId, false);
  }

  async purgeOne(batchId) {
    if (await window.appFeedback.confirm('这批数据将从回收站永久删除，无法再恢复。原有备份文件不会被删除。', {title:'永久删除这批数据',danger:true,phrase:'永久删除',confirmLabel:'永久删除'})) await this.mutate(batchId, true);
  }

  renderPagination(total) {
    const el = this.container.querySelector('#recycle-pagination'), pages = Math.max(1, Math.ceil(total / this.pageSize));
    el.replaceChildren();
    const info = document.createElement('span'); info.textContent = `共 ${total} 批 · ${this.currentPage} / ${pages} 页`; el.append(info);
    for (const [label, delta, disabled] of [['上一页',-1,this.currentPage<=1],['下一页',1,this.currentPage>=pages]]) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.disabled = disabled;
      button.onclick = () => { this.currentPage += delta; this.loadList(); }; el.append(button);
    }
  }
}
window.RecycleBinManager = RecycleBinManager;
