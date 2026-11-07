export const draftText = value => value == null || value === '' ? '/' : String(value);

export class ReportDraft {
  constructor() {
    this.cells = new Map();
    this.changes = new Map();
    this.history = [];
  }

  load(cells = []) {
    this.cells = new Map(cells.map(cell => [cell.key, {...cell}]));
  }

  remember() {
    this.history.push(new Map(this.changes));
    if (this.history.length > 100) this.history.shift();
  }

  reset() {
    if (this.changes.size) this.remember();
    this.changes.clear();
  }

  clear() {
    this.changes.clear();
    this.history = [];
  }

  undo() {
    if (!this.history.length) return false;
    this.changes = this.history.pop();
    return true;
  }

  sourceValue(cell) {
    return Object.hasOwn(cell, 'source_value') ? cell.source_value : cell.value;
  }

  change(key, input) {
    const cell = this.cells.get(key);
    if (!cell) throw new Error('当前单元格已变化，请刷新报告');
    let value = input;
    if (cell.type === 'number') {
      const token = String(input ?? '').trim();
      if (token === '' || token === '/') value = null;
      else {
        if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(token) || !Number.isFinite(Number(token))) {
          throw new Error('请输入有效数字；缺失值使用 /');
        }
        value = Number(token);
      }
    }
    const original = this.sourceValue(cell);
    const remove = value === original || draftText(value) === draftText(original);
    if (remove) {
      if (!this.changes.has(key)) return value;
      this.remember();
      this.changes.delete(key);
    } else {
      if (this.changes.has(key) && Object.is(this.changes.get(key), value)) return value;
      this.remember();
      this.changes.set(key, value);
    }
    return value;
  }

  restore(key) {
    if (!this.changes.has(key)) return;
    this.remember();
    this.changes.delete(key);
  }

  payload() {
    return [...this.changes.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => ({key, value}));
  }
}

export function mountReportEditor({host, preview, onApply, onError}) {
  const draft = new ReportDraft();
  let selected = '', enabled = false, activeEdit = null;
  host.innerHTML = `<div class="rc-editor-title"><strong>报告修改草稿</strong></div>
    <p class="rc-editor-empty">双击报告单元格可编辑</p>
    <div class="rc-draft-heading"><strong id="rcDraftCount">人工修改 0 项</strong><div>
      <button id="rcDraftUndo" type="button" disabled>撤销</button>
      <button id="rcDraftReset" type="button" disabled>全部恢复</button>
    </div></div>
    <div id="rcDraftChanges" class="rc-draft-changes"></div><p id="rcCellStatus" role="status" aria-live="polite"></p>`;
  const $ = id => host.querySelector('#' + id);
  const display = cell => draftText(draft.changes.has(cell.key) ? draft.changes.get(cell.key) : cell.value);
  const paintValue = (element, value) => {
    const lines = String(value).split('\n');
    element.replaceChildren();
    lines.forEach((line, index) => {
      if (index) element.append(document.createElement('br'));
      if (line) element.append(document.createTextNode(line));
    });
  };
  const setStatus = text => { $('rcCellStatus').textContent = text; };
  const findCell = key => [...preview.querySelectorAll('[data-edit-key]')].find(cell => cell.dataset.editKey === key);
  const finishEdit = (mode, {notify = true} = {}) => {
    if (!activeEdit) return;
    const edit = activeEdit;
    activeEdit = null;
    let value = edit.original;
    if (mode === 'save' && enabled) {
      try {
        value = edit.input.value;
        draft.change(edit.key, value);
      } catch (error) {
        mode = 'cancel';
        setStatus(error.message);
        onError?.(error);
      }
    }
    if (edit.cell.isConnected) paintValue(edit.cell, mode === 'cancel' ? edit.original : draftText(value));
    if (mode === 'save') {
      highlight();
      if (notify) changed();
    }
  };
  const renderChanges = () => {
    $('rcDraftCount').textContent = `人工修改 ${draft.changes.size} 项`;
    $('rcDraftUndo').disabled = !enabled || !draft.history.length;
    $('rcDraftReset').disabled = !enabled || !draft.changes.size;
    $('rcDraftChanges').replaceChildren();
    for (const {key, value} of draft.payload()) {
      const cell = draft.cells.get(key);
      const item = document.createElement('div');
      item.className = 'rc-draft-entry';
      const label = document.createElement('strong');
      label.textContent = cell?.label || key;
      const before = document.createElement('del');
      before.textContent = draftText(cell ? draft.sourceValue(cell) : null);
      const after = document.createElement('span');
      after.textContent = draftText(value);
      const actions = document.createElement('div');
      actions.className = 'rc-draft-entry-actions';
      const locate = document.createElement('button');
      locate.type = 'button';
      locate.textContent = '定位';
      locate.title = '定位到报告中的单元格';
      locate.onclick = () => select(key, {scroll: true});
      const restore = document.createElement('button');
      restore.type = 'button';
      restore.textContent = '还原';
      restore.title = '恢复该单元格原值';
      restore.disabled = !enabled;
      restore.onclick = () => {
        if (!enabled) return;
        draft.restore(key);
        const target = findCell(key);
        if (target) paintValue(target, display(cell));
        changed();
      };
      actions.append(locate, restore);
      item.append(label, before, after, actions);
      $('rcDraftChanges').append(item);
    }
  };
  const highlight = () => {
    preview.querySelectorAll('[data-edit-key]').forEach(cell => {
      const key = cell.dataset.editKey;
      cell.classList.toggle('rc-cell-active', key === selected);
      cell.classList.toggle('rc-cell-changed', draft.changes.has(key));
      cell.tabIndex = 0;
      cell.setAttribute('aria-label', draft.cells.get(key)?.label || '报告单元格');
      cell.setAttribute('aria-description', '双击编辑');
    });
  };
  const select = (key, {scroll = false} = {}) => {
    const cell = draft.cells.get(key);
    if (!cell || !enabled) return;
    selected = key;
    highlight();
    if (scroll) {
      const target = findCell(key);
      target?.scrollIntoView({block: 'center', inline: 'center', behavior: 'smooth'});
    }
  };
  const changed = () => {
    setStatus('正在同步报告草稿…');
    renderChanges();
    onApply();
  };
  preview.addEventListener('click', event => {
    const cell = event.target.closest('[data-edit-key]');
    if (cell && preview.contains(cell) && !event.target.closest('.rc-inline-editor')) select(cell.dataset.editKey);
  });
  const startEdit = cell => {
    const model = draft.cells.get(cell?.dataset.editKey);
    if (!cell || !model || !enabled || model.editable === false) return;
    if (activeEdit) finishEdit('save');
    select(model.key);
    const original = display(model);
    const input = document.createElement('textarea');
    input.className = 'rc-inline-editor';
    input.rows = Math.max(2, Math.min(8, original.split('\n').length));
    input.spellcheck = false;
    input.setAttribute('aria-label', model.label || '编辑报告单元格');
    input.value = original;
    activeEdit = {key: model.key, cell, input, original};
    cell.replaceChildren(input);
    input.addEventListener('keydown', event => {
      event.stopPropagation();
      if (event.key === 'Escape') {
        event.preventDefault();
        finishEdit('cancel');
      } else if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        finishEdit('save');
      }
    });
    input.addEventListener('blur', () => finishEdit('save'));
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    setStatus('');
  };
  preview.addEventListener('dblclick', event => {
    const cell = event.target.closest('[data-edit-key]');
    if (cell && preview.contains(cell)) {
      event.preventDefault();
      startEdit(cell);
    }
  });
  preview.addEventListener('keydown', event => {
    const cell = event.target.closest('[data-edit-key]');
    if (!cell || !preview.contains(cell)) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !activeEdit) {
      event.preventDefault();
      if (draft.undo()) changed();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      startEdit(cell);
    } else if (event.key === ' ') {
      event.preventDefault();
      select(cell.dataset.editKey);
    }
  });
  host.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !activeEdit) {
      event.preventDefault();
      if (draft.undo()) changed();
    }
  });
  $('rcDraftUndo').onclick = () => {
    if (enabled && draft.undo()) changed();
  };
  $('rcDraftReset').onclick = () => {
    if (!enabled) return;
    draft.reset();
    changed();
  };
  return {
    payload: () => draft.payload(),
    count: () => draft.changes.size,
    reset(message = '') {
      if (activeEdit) finishEdit('cancel', {notify: false});
      draft.clear();
      draft.load();
      selected = '';
      enabled = false;
      setStatus(message);
      renderChanges();
      highlight();
    },
    pending() {
      enabled = false;
      if (activeEdit) finishEdit('cancel', {notify: false});
      $('rcDraftUndo').disabled = true;
      $('rcDraftReset').disabled = true;
      $('rcDraftChanges').querySelectorAll('button').forEach(button => { button.disabled = true; });
    },
    sync(snapshot) {
      draft.load(snapshot.editable_cells || []);
      enabled = true;
      if (!draft.cells.has(selected)) selected = '';
      setStatus(draft.changes.size ? '修改仅作用于当前报告草稿，导出会写入审计记录' : '');
      renderChanges();
      highlight();
    }
  };
}
