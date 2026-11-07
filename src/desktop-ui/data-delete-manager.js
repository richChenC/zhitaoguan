// ============================================================
// DataDeleteManager - 数据删除管理器
// 支持 8 种删除粒度、风险分级、两步确认、冷静期、软删除、撤销、回收站
// ============================================================

class DataDeleteManager {
  constructor() {
    this.modal = null;
    this.toastTimer = null;
    window.addEventListener('data-restored', event => {
      const result=event.detail,button=document.querySelector('.ddm-toast-undo');
      if(!result?.batchId||button?.dataset.batch!==result.batchId)return;
      clearTimeout(this.toastTimer);
      button.closest('.ddm-toast').remove();
    });
  }

  // 风险等级配置
  riskConfig = {
    finding:      { level: 'low',      label: '低风险',   color: '#22c55e', steps: 1, cooldown: 0,  needInput: false, needCheckbox: false },
    selected:     { level: 'medium',   label: '中风险',   color: '#f59e0b', steps: 1, cooldown: 0,  needInput: false, needCheckbox: true  },
    tube_outage:  { level: 'medium',   label: '中风险',   color: '#f59e0b', steps: 1, cooldown: 0,  needInput: false, needCheckbox: true  },
    tube_all:     { level: 'medium',   label: '中风险',   color: '#f59e0b', steps: 1, cooldown: 0,  needInput: false, needCheckbox: true  },
    outage:       { level: 'high',     label: '高风险',   color: '#ef4444', steps: 2, cooldown: 0,  needInput: true,  needCheckbox: false },
    unit:         { level: 'veryhigh', label: '很高风险', color: '#dc2626', steps: 2, cooldown: 0,  needInput: true,  needCheckbox: false },
    site:         { level: 'extreme',  label: '极高风险', color: '#991b1b', steps: 2, cooldown: 30, needInput: true,  needCheckbox: false },
    all:          { level: 'extreme',  label: '极高风险', color: '#991b1b', steps: 2, cooldown: 60, needInput: true,  needCheckbox: false },
  };

  // 入口：打开删除确认
  async openDeleteConfirm(scope, data = {}) {
    if (this.opening || this.modal) return;
    this.opening = true;
    this.previousFocus = document.activeElement;
    const config = this.riskConfig[scope] || this.riskConfig.finding;
    try {
      const preview = await this.fetchPreview(scope, data);
      this.showStep1(scope, data, config, preview);
    } catch (error) {
      window.toast(`无法预览删除范围：${error.message}`, {type:'error'});
    } finally { this.opening = false; }
  }

  async fetchPreview(scope, data) {
      const result = await window.api('/api/data/delete-preview', {
        method: 'POST',
        body: JSON.stringify({ scope, data }),
      });
      if (!result.preview || !Number.isInteger(result.preview.total_records)) throw new Error('本机服务返回的影响范围无效');
      return result.preview;
  }

  // ===== 第 1 步：范围确认 =====
  showStep1(scope, data, config, preview) {
    const scopeLabel = this.getScopeLabel(scope, data);
    const totalRecords = preview.total_records || preview.findings || 0;
    const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

    this.closeModal();
    this.modal = document.createElement('dialog');
    this.modal.className = 'ddm-overlay';
    this.modal.setAttribute('aria-label', '数据删除确认');
    this.modal.innerHTML = `
      <div class="ddm-modal">
        <div class="ddm-header">
          <span class="ddm-title">数据删除确认</span>
          <span class="ddm-risk-badge" style="background:${config.color}">${config.label}</span>
        </div>
        <div class="ddm-body">
          <div class="ddm-scope-title">您即将删除以下范围的数据：</div>
          <div class="ddm-scope-card">
            <div class="ddm-scope-row">
              <span class="ddm-scope-label">删除范围</span>
              <span class="ddm-scope-value">${escape(scopeLabel)}</span>
            </div>
            ${data.siteName ? `<div class="ddm-scope-row"><span class="ddm-scope-label">基地</span><span class="ddm-scope-value">${escape(data.siteName)}</span></div>` : ''}
            ${data.unitName ? `<div class="ddm-scope-row"><span class="ddm-scope-label">机组</span><span class="ddm-scope-value">${escape(data.unitName)}</span></div>` : ''}
            ${data.outageName ? `<div class="ddm-scope-row"><span class="ddm-scope-label">大修批次</span><span class="ddm-scope-value">${escape(data.outageName)}</span></div>` : ''}
            ${data.tubeNumber ? `<div class="ddm-scope-row"><span class="ddm-scope-label">管号</span><span class="ddm-scope-value">${escape(data.tubeNumber)} 号</span></div>` : ''}
          </div>

          <div class="ddm-preview">
            <div class="ddm-preview-title">影响预估</div>
            <div class="ddm-preview-grid">
              <div class="ddm-preview-item">
                <div class="ddm-preview-num">${preview.findings || 0}</div>
                <div class="ddm-preview-label">检测记录</div>
              </div>
              <div class="ddm-preview-item">
                <div class="ddm-preview-num">${preview.tube_states || 0}</div>
                <div class="ddm-preview-label">管状态</div>
              </div>
              <div class="ddm-preview-item">
                <div class="ddm-preview-num">${preview.report_versions || 0}</div>
                <div class="ddm-preview-label">报告版本</div>
              </div>
              <div class="ddm-preview-item">
                <div class="ddm-preview-num">${preview.import_batches || 0}</div>
                <div class="ddm-preview-label">导入批次</div>
              </div>
            </div>
            <div class="ddm-preview-total">
              总计约 <strong style="color:${config.color}">${totalRecords}</strong> 条记录
            </div>
          </div>

          <div class="ddm-options">
            <div class="ddm-options-title">处理方式</div>
            <p class="ddm-option-tip">删除前自动备份，数据移入回收站，可恢复。原始资料文件保留。</p>
            ${config.needCheckbox ? `
            <label class="ddm-option-row ddm-confirm-check">
              <input type="checkbox" id="ddm-opt-confirm">
              <span style="color:#dc2626">我确认要删除以上数据</span>
            </label>` : ''}
          </div>

          <div class="ddm-warning">
            <div class="ddm-warning-icon">!</div>
            <div class="ddm-warning-text">
              <div class="ddm-warning-title">删除后数据将从当前视图中移除</div>
              <div class="ddm-warning-desc">
                数据移入回收站后可恢复；彻底删除请到回收站单独确认。
              </div>
            </div>
          </div>
        </div>
        <div class="ddm-footer">
          <button class="ddm-btn ddm-cancel" autofocus>取消</button>
          <button class="ddm-btn ddm-confirm ${config.level === 'extreme' || config.level === 'veryhigh' ? 'ddm-btn-danger' : ''}">
            ${config.steps === 2 ? '下一步，输入确认' : '确认删除'}
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(this.modal);
    this.modal.showModal();
    this.modal.addEventListener('cancel', event => { event.preventDefault(); if (!this.deleting) this.closeModal(); });

    const confirmBtn = this.modal.querySelector('.ddm-confirm');
    const confirmCheck = this.modal.querySelector('#ddm-opt-confirm');

    if (confirmCheck) {
      confirmBtn.disabled = true;
      confirmBtn.style.opacity = '0.5';
      confirmBtn.style.cursor = 'not-allowed';
      confirmCheck.addEventListener('change', (e) => {
        confirmBtn.disabled = !e.target.checked;
        confirmBtn.style.opacity = e.target.checked ? '1' : '0.5';
        confirmBtn.style.cursor = e.target.checked ? 'pointer' : 'not-allowed';
      });
    }

    confirmBtn.onclick = () => {
      if (confirmBtn.disabled) return;
      const options = this.collectOptions();
      if (config.steps === 2) {
        this.showStep2(scope, data, config, options, preview);
      } else {
        this.executeDelete(scope, data, options, preview);
      }
    };

    this.modal.querySelector('.ddm-cancel').onclick = () => this.closeModal();
    this.modal.addEventListener('click', (e) => { if (e.target === this.modal && !this.deleting) this.closeModal(); });
  }

  // ===== 第 2 步：输入确认 + 冷静期 =====
  showStep2(scope, data, config, options, preview) {
    const scopeLabel = this.getScopeLabel(scope, data).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const confirmPhrase = this.getConfirmPhrase(scope, data);
    const safePhrase = confirmPhrase.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

    this.modal.querySelector('.ddm-body').innerHTML = `
      <div class="ddm-step2">
        <button type="button" class="ddm-step2-back">&#8592; 返回修改</button>
        <div class="ddm-step2-header">
          <div class="ddm-step2-icon" style="color:${config.color}">!</div>
          <div class="ddm-step2-title">最终确认</div>
          <div class="ddm-step2-sub">此操作${options.soft ? '移入回收站' : '永久删除'}，请仔细核对</div>
        </div>
        <div class="ddm-step2-scope">
          <span style="color:#64748b">删除范围：</span>
          <strong>${scopeLabel}</strong>
          <span style="color:${config.color};margin-left:8px;">约 ${preview.total_records || 0} 条</span>
        </div>
        <div class="ddm-phrase-box">
          <div class="ddm-phrase-label">请完整输入以下文字以确认删除：</div>
          <div class="ddm-phrase-text">${safePhrase}</div>
          <input type="text" class="ddm-phrase-input" id="ddm-phrase-input"
                 placeholder="请输入上方文字..." autocomplete="off">
        </div>
        ${config.cooldown > 0 ? `
        <div class="ddm-cooldown">
          <div class="ddm-cooldown-text">
            为确保您已充分考虑，请等待
            <span class="ddm-cooldown-num" id="ddm-cooldown-num">${config.cooldown}</span> 秒
          </div>
          <div class="ddm-cooldown-bar">
            <div class="ddm-cooldown-fill" id="ddm-cooldown-fill" style="width:0%"></div>
          </div>
        </div>` : ''}
      </div>
    `;

    const confirmBtn = this.modal.querySelector('.ddm-confirm');
    confirmBtn.textContent = '确认删除';
    confirmBtn.disabled = true;
    confirmBtn.style.opacity = '0.5';
    confirmBtn.style.cursor = 'not-allowed';
    this.modal.querySelector('.ddm-cancel').textContent = '返回上一步';

    const input = this.modal.querySelector('#ddm-phrase-input');
    let cooldownPassed = config.cooldown <= 0;

    if (config.cooldown > 0) {
      let remaining = config.cooldown;
      const fill = this.modal.querySelector('#ddm-cooldown-fill');
      const num = this.modal.querySelector('#ddm-cooldown-num');
      this.cooldownTimer = setInterval(() => {
        remaining--;
        num.textContent = remaining;
        fill.style.width = ((config.cooldown - remaining) / config.cooldown * 100) + '%';
        if (remaining <= 0) {
          clearInterval(this.cooldownTimer);
          cooldownPassed = true;
          this._updateConfirmBtn(input, confirmBtn, confirmPhrase, cooldownPassed);
        }
      }, 1000);
    }

    input.addEventListener('input', () => {
      this._updateConfirmBtn(input, confirmBtn, confirmPhrase, cooldownPassed);
    });

    const goBack = () => this.showStep1(scope, data, config, preview);
    this.modal.querySelector('.ddm-step2-back').addEventListener('click', goBack);
    this.modal.querySelector('.ddm-cancel').onclick = goBack;

    confirmBtn.onclick = () => {
      if (confirmBtn.disabled) return;
      this.executeDelete(scope, data, options, preview);
    };
    input.focus();
  }

  _updateConfirmBtn(input, btn, phrase, cooldownPassed) {
    const match = input.value.trim() === phrase;
    const canConfirm = match && cooldownPassed;
    btn.disabled = !canConfirm;
    btn.style.opacity = canConfirm ? '1' : '0.5';
    btn.style.cursor = canConfirm ? 'pointer' : 'not-allowed';
  }

  getConfirmPhrase(scope, data) {
    const map = {
      outage: `确认删除${data.outageName || ''}大修数据`,
      unit: `我确认将${data.siteName || ''}${data.unitName || ''}机组检测记录移入回收站`,
      site: `我确认将${data.siteName || ''}基地检测记录移入回收站`,
      all: '我确认将全库检测记录移入回收站',
    };
    return map[scope] || '我确认将所选数据移入回收站';
  }

  getScopeLabel(scope, data) {
    const map = {
      finding: '单条检测记录',
      selected: `选中 ${data.count || 0} 条记录`,
      tube_outage: `${data.tubeNumber || ''}号管单次大修`,
      tube_all: `${data.tubeNumber || ''}号管历次检测及状态`,
      outage: '单次大修全部数据',
      unit: '单机组检测记录',
      site: '基地检测记录',
      all: '全库检测记录',
    };
    return map[scope] || scope;
  }

  collectOptions() {
    return {
      backup: true,
      soft: true,
      keepFiles: true,
      hardDelete: false,
    };
  }

  async executeDelete(scope, data, options, preview) {
    if (this.deleting) return;
    this.deleting = true;
    const btn = this.modal.querySelector('.ddm-confirm');
    const cancel = this.modal.querySelector('.ddm-cancel');
    const controls = [...this.modal.querySelectorAll('button,input')].map(el => [el,el.disabled]);
    controls.forEach(([el]) => el.disabled = true);
    btn.textContent = '删除中...';
    btn.disabled = true;
    cancel.disabled = true;
    this.modal.setAttribute('aria-busy','true');
    this.modal.querySelector('.ddm-operation-error')?.remove();

    try {
      const result = await window.api('/api/data/delete', {
        method: 'POST',
        body: JSON.stringify({ scope, data, options }),
      });

      if (Number.isInteger(result.deletedCount)) {
        this.closeModal();
        this.showResultToast(result, result.hardDelete !== true);
        window.dispatchEvent(new CustomEvent('data-deleted', {
          detail: { scope, data, result }
        }));
      } else {
        throw new Error(result.error || '本机服务返回的删除数量无效');
      }
    } catch (e) {
      const error = document.createElement('p'); error.className = 'ddm-operation-error'; error.setAttribute('role','alert');
      error.textContent = `删除失败：${e.message}`; this.modal.querySelector('.ddm-body').append(error);
      btn.textContent = '确认删除';
      btn.disabled = false;
    } finally {
      this.deleting = false; cancel.disabled = false;
      controls.forEach(([el,disabled]) => { if (el.isConnected) el.disabled = disabled; });
      this.modal?.removeAttribute('aria-busy');
    }
  }

  showResultToast(result, isSoftDelete) {
    const old = document.querySelector('.ddm-toast');
    if (old) old.remove();

    const toast = document.createElement('div');
    toast.className = 'ddm-toast';
    toast.setAttribute('role','status');
    let html = `
      <span class="ddm-toast-icon">&#10003;</span>
      <span class="ddm-toast-text">
        已${isSoftDelete ? '移入回收站' : '永久删除'} ${result.deletedCount} 条记录
      </span>
    `;
    if (isSoftDelete) {
      html += `<button class="ddm-toast-undo" data-batch="${result.batchId}">撤销删除</button>`;
    }
    html += `<button class="ddm-toast-close" aria-label="关闭通知" title="关闭通知">&#215;</button>`;
    toast.innerHTML = html;
    document.body.appendChild(toast);

    clearTimeout(this.toastTimer);
    const schedule = () => {
      if (!toast.isConnected) return;
      clearTimeout(this.toastTimer);
      const duration = window.appFeedback?.notificationDuration?.() ?? 3000;
      if (duration > 0 && !toast.matches(':hover') && !toast.contains(document.activeElement)) this.toastTimer = setTimeout(() => toast.remove(), duration);
    };
    schedule(); toast.onmouseenter = () => clearTimeout(this.toastTimer);
    toast.onmouseleave = schedule;
    toast.addEventListener('focusin', () => clearTimeout(this.toastTimer));
    toast.addEventListener('focusout', () => queueMicrotask(schedule));
    window.appFeedback?.notify(`已${isSoftDelete ? '移入回收站' : '永久删除'} ${result.deletedCount} 条记录`, {type:'success', historyOnly:true});

    toast.querySelector('.ddm-toast-close').addEventListener('click', () => toast.remove());

    const undoBtn = toast.querySelector('.ddm-toast-undo');
    if (undoBtn) {
      undoBtn.addEventListener('click', async () => {
        undoBtn.textContent = '恢复中...';
        undoBtn.disabled = true;
        clearTimeout(this.toastTimer);
        try {
          const r = await window.api('/api/recycle-bin/restore', {
            method: 'POST',
            body: JSON.stringify({ batchId: result.batchId }),
          });
          if (Number.isInteger(r.restoredCount)) {
            const message=r.alreadyRestored?'此批数据已恢复':`已恢复 ${r.restoredCount} 条记录`;
            toast.querySelector('.ddm-toast-text').textContent = message;
            undoBtn.remove();
            window.dispatchEvent(new CustomEvent('data-restored', { detail: r }));
            window.appFeedback?.notify(message, {type:'success', historyOnly:true});
          } else throw new Error('本机服务返回的恢复数量无效');
        } catch (e) {
          window.toast(`恢复失败：${e.message}`, {type:'error'});
          undoBtn.textContent = '重试恢复'; undoBtn.disabled = false;
        } finally { schedule(); }
      });
    }
  }

  closeModal() {
    clearInterval(this.cooldownTimer);
    if (this.modal) {
      this.modal.close();
      this.modal.remove();
      this.modal = null;
      if (this.previousFocus?.isConnected) this.previousFocus.focus();
    }
  }
}

// 全局单例
window.DataDeleteManager = DataDeleteManager;
window.dataDeleteMgr = new DataDeleteManager();
