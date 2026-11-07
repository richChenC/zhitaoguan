(() => {
  'use strict';
  const q = selector => document.querySelector(selector);
  const history = [];
  const severityLabels = {success:'操作完成', warning:'需要核对', error:'操作未完成', info:'提示'};
  const severityMarks = {success:'✓', warning:'!', error:'×', info:'i'};
  let historyFilter = 'all';
  let toastTimer, toastDismiss, notificationHost, activeRequests = 0;
  let activityTimer, activityHideTimer, requestActivityVisible = false;
  const requestActivityDelay = 320, requestActivityHideDelay = 180;
  const nativeFetch = window.fetch.bind(window);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let notificationModal, notificationFrame, modalStack = [], notificationTargets = [];
  let notificationAudioContext;
  function notificationSoundEnabled() {
    return localStorage.getItem('thimbleNotificationSound') !== 'false';
  }
  function notificationDuration() {
    const stored = localStorage.getItem('thimbleNotificationDuration');
    return ['3000','5000','0'].includes(stored) ? Number(stored) : 3000;
  }
  function playNotificationSound(type) {
    if (!notificationSoundEnabled() || !window.AudioContext) return;
    try {
      notificationAudioContext ||= new AudioContext();
      const context = notificationAudioContext;
      if (context.state === 'suspended') context.resume().catch(() => {});
      const oscillator = context.createOscillator(), gain = context.createGain();
      const frequencies = {success:660, warning:520, error:300, info:440};
      oscillator.type = 'sine';
      oscillator.frequency.value = frequencies[type] || frequencies.info;
      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(type === 'error' ? 0.045 : 0.028, context.currentTime + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.12);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + 0.13);
    } catch (_) { /* Audio is optional and must never interrupt an operation. */ }
  }
  function placeModalNotification(modal) {
    const host = notificationHost, actions = modal?.querySelector('.dialog-actions');
    if (!host || !modal) return;
    const modalBox = modal.getBoundingClientRect();
    const anchor = actions?.getBoundingClientRect() || modalBox;
    const minLeft = Math.max(16, modalBox.left + 16);
    const maxRight = Math.min(innerWidth - 16, modalBox.right - 16);
    const width = Math.min(510, Math.max(0, maxRight - minLeft));
    const minTop = Math.max(8, modalBox.top + 10);
    const maxBottom = Math.min(innerHeight - 8, modalBox.bottom - 10, actions ? anchor.top - 10 : Infinity);
    const availableHeight = Math.max(54, Math.min(180, maxBottom - minTop));
    host.style.width = `${width}px`;
    host.style.maxWidth = `calc(100vw - 32px)`;
    host.style.maxHeight = `${availableHeight}px`;
    host.style.setProperty('--notification-height', `${availableHeight}px`);
    const height = host.getBoundingClientRect().height;
    const left = Math.max(minLeft, Math.min(anchor.right - width, maxRight - width));
    const top = Math.max(minTop, maxBottom - height);
    host.style.left = `${left}px`;
    host.style.right = 'auto';
    host.style.top = `${top}px`;
    host.style.bottom = 'auto';
  }

  function trackModals(records) {
    modalStack = modalStack.filter(modal => modal.isConnected && modal.matches(':modal'));
    // Reused dialogs can open above siblings that appear later in DOM order.
    for (const record of records) {
      const modal = record.target;
      if (record.type !== 'attributes' || record.oldValue !== null || !modal.matches('dialog:modal')) continue;
      modalStack = modalStack.filter(item => item !== modal);
      modalStack.push(modal);
    }
    for (const modal of document.querySelectorAll('dialog:modal')) {
      if (!modalStack.includes(modal)) modalStack.push(modal);
    }
  }
  function refreshNotification() {
    notificationFrame = null;
    const host = notificationHost;
    if (!host?.classList.contains('show')) return;
    trackModals(modalObserver.takeRecords());
    const modal = modalStack.at(-1);
    if (notificationModal !== modal || (modal ? !modal.contains(host) : host.parentElement !== document.body)) {
      if (host.matches(':popover-open')) host.hidePopover();
      host.style.cssText = '';
      host.classList.toggle('in-modal', !!modal);
      host.setAttribute('popover', 'manual');
      if (modal) {
        const actions = modal.querySelector('.dialog-actions'), form = actions?.closest('form');
        const parent = form && modal.contains(form) ? form : modal;
        parent.insertBefore(host, actions && actions.parentElement === parent ? actions : parent.firstChild);
      } else document.body.append(host);
      notificationModal = modal;
    }
    const targets = modal ? [modal, modal.querySelector('.dialog-actions')].filter(Boolean) : [];
    if (targets.length !== notificationTargets.length || targets.some((target, index) => target !== notificationTargets[index])) {
      notificationSizes.disconnect();
      targets.forEach(target => notificationSizes.observe(target));
      notificationTargets = targets;
    }
    host.setAttribute('popover', 'manual');
    if (!host.matches(':popover-open')) host.showPopover();
    if (modal) placeModalNotification(modal);
  }
  function scheduleNotificationLayout() {
    if (notificationHost?.classList.contains('show') && !notificationFrame) {
      notificationFrame = requestAnimationFrame(refreshNotification);
    }
  }
  const notificationSizes = new ResizeObserver(scheduleNotificationLayout);
  const modalObserver = new MutationObserver(records => {
    trackModals(records);
    const changed = records.some(record => record.type === 'attributes' ? record.target.matches('dialog') :
      (notificationModal?.contains(record.target) && !notificationHost?.contains(record.target)) ||
      [...record.addedNodes, ...record.removedNodes].some(node => node.nodeType === 1 && (node.matches('dialog') || node.querySelector('dialog'))));
    if (changed) scheduleNotificationLayout();
  });
  modalObserver.observe(document.documentElement, {subtree:true, childList:true, attributes:true, attributeFilter:['open'], attributeOldValue:true});
  window.addEventListener('resize', scheduleNotificationLayout);
  document.addEventListener('scroll', scheduleNotificationLayout, true);

  const placeDialog = (dialog, left, top) => {
    const box = dialog.getBoundingClientRect();
    const visibleHeader=Math.min(180,box.width,innerWidth-16);
    dialog.style.left = `${Math.max(visibleHeader-box.width, Math.min(left, innerWidth-visibleHeader))}px`;
    dialog.style.top = `${Math.max(8, Math.min(top, Math.max(8, innerHeight-Math.min(box.height,80)-8)))}px`;
    scheduleNotificationLayout();
  };
  document.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('button,input,select,textarea,a,summary,[contenteditable]')) return;
    const handle = event.target.closest('.vw-record-head,.dialog-header,.modal-header,h2,h3');
    const dialog = handle?.closest('dialog[open]');
    if (!dialog || (!handle.matches('.vw-record-head,.dialog-header,.modal-header') &&
      handle !== dialog.querySelector('h2,h3'))) return;
    event.preventDefault();
    const box = dialog.getBoundingClientRect(), startX = event.clientX, startY = event.clientY;
    Object.assign(dialog.style, {position:'fixed',margin:'0',right:'auto',bottom:'auto',
      transform:'none',width:`min(${box.width}px, calc(100vw - 16px))`,boxSizing:'border-box'});
    placeDialog(dialog,box.left,box.top);
    dialog.dataset.dragging = 'true';
    const events = new AbortController();
    handle.setPointerCapture(event.pointerId);
    const stop = () => {
      events.abort(); delete dialog.dataset.dragging;
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    };
    document.addEventListener('pointermove',current=>{
      if (current.pointerId === event.pointerId) placeDialog(dialog,box.left+current.clientX-startX,box.top+current.clientY-startY);
    },{signal:events.signal});
    for (const name of ['pointerup','pointercancel','lostpointercapture']) {
      document.addEventListener(name,current=>{if(current.pointerId===event.pointerId)stop()},{signal:events.signal});
    }
    dialog.addEventListener('close',stop,{once:true,signal:events.signal});
    window.addEventListener('blur',stop,{once:true,signal:events.signal});
  });
  window.addEventListener('resize', () => {
    for (const dialog of document.querySelectorAll('dialog[open]')) {
      if (dialog.style.left) {
        const box=dialog.getBoundingClientRect();
        placeDialog(dialog,box.left,box.top);
      }
    }
  });

  function paintHistory() {
    const list = q('#feedbackHistory');
    if (!list) return;
    list.replaceChildren();
    const filtered = history.filter(item => historyFilter === 'all' || item.type === historyFilter);
    for (const item of filtered) {
      const row = document.createElement('li');
      row.dataset.type = item.type;
      row.dataset.unread = String(!item.read);
      const mark = document.createElement('b'), text = document.createElement('span'), time = document.createElement('time');
      mark.className = 'feedback-mark'; mark.textContent = severityMarks[item.type];
      mark.setAttribute('aria-label', severityLabels[item.type]);
      text.textContent = item.message;
      time.dateTime = new Date(item.time).toISOString();
      time.textContent = new Date(item.time).toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'});
      time.title = new Date(item.time).toLocaleString('zh-CN');
      if (item.count > 1) {
        const repeat = document.createElement('small'); repeat.className = 'feedback-repeat';
        repeat.textContent = `×${item.count}`; repeat.title = `连续收到 ${item.count} 次相同通知`;
        time.append(document.createElement('br'), repeat);
      }
      row.append(mark, text, time); list.append(row);
    }
    if (!filtered.length) {
      const empty = document.createElement('li'); empty.className = 'feedback-empty';
      empty.textContent = history.length ? '暂无此类通知' : '暂无操作通知'; list.append(empty);
    }
    const unread = history.filter(item => !item.read).length;
    q('#feedbackCount').textContent = unread > 99 ? '99+' : unread || '';
    q('#feedbackCount').hidden = !unread;
    q('#feedbackToggle').setAttribute('aria-label', `操作通知${unread ? `，${unread} 条未读` : ''}`);
    q('#feedbackSummary').textContent = history.length ? `最近 ${history.length} 条${unread ? ` · ${unread} 条未读` : ''}` : '本次会话';
    q('#feedbackClear').disabled = !history.length;
    for (const button of document.querySelectorAll('[data-feedback-filter]')) {
      button.setAttribute('aria-pressed', String(button.dataset.feedbackFilter === historyFilter));
    }
  }

  function notify(message, options = {}) {
    const host = notificationHost ||= q('#toast');
    if (!host) return;
    const requestedType = options.type || (/失败|错误|异常|无法|不能|不可|failure|error/i.test(message) ? 'error' : /请先|请选择|未选择|不匹配/.test(message) ? 'warning' : 'success');
    const type = Object.hasOwn(severityLabels, requestedType) ? requestedType : 'info';
    const now = Date.now(), previous = history[0], read = q('#feedbackDrawer')?.hidden === false;
    if (previous && previous.message === String(message) && previous.type === type && now - previous.time < 5000) {
      previous.count++; previous.time = now; previous.read = read;
    } else history.unshift({message:String(message), type, time:now, count:1, read});
    history.splice(60); paintHistory();
    if (options.sound !== false) playNotificationSound(type);
    if (options.historyOnly) return () => {};
    clearTimeout(toastTimer);
    host.replaceChildren(); host.dataset.type = type;
    host.setAttribute('role', type === 'error' ? 'alert' : 'status');
    host.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
    const mark = document.createElement('b'), text = document.createElement('span'), close = document.createElement('button');
    mark.className = 'feedback-mark';
    mark.textContent = ({success:'✓',warning:'!',error:'×',info:'i'}[type] || 'i');
    text.dataset.heading = severityLabels[type];
    text.textContent = message; close.type = 'button'; close.innerHTML = '<img src="/assets/icons/x.svg" alt="">';
    close.setAttribute('aria-label', '关闭通知'); close.title = '关闭通知';
    const dismiss = () => {
      if (toastDismiss !== dismiss) return;
      clearTimeout(toastTimer); cancelAnimationFrame(notificationFrame); notificationFrame = null;
      notificationSizes.disconnect(); notificationTargets = []; host.classList.remove('show');
      if (host.matches(':popover-open')) host.hidePopover();
    };
    toastDismiss = dismiss;
    close.onclick = toastDismiss; host.append(mark, text, close); host.classList.add('show');
    cancelAnimationFrame(notificationFrame);
    refreshNotification();
    scheduleNotificationLayout();
    const schedule = () => {
      if (toastDismiss !== dismiss || !host.classList.contains('show')) return;
      clearTimeout(toastTimer);
      const duration = options.duration ?? notificationDuration();
      if (duration > 0 && !host.matches(':hover') && !host.contains(document.activeElement)) toastTimer = setTimeout(dismiss, duration);
    };
    host.onmouseenter = () => clearTimeout(toastTimer);
    host.onmouseleave = schedule;
    if (!host.dataset.focusBound) {
      host.addEventListener('focusin', () => clearTimeout(toastTimer));
      host.addEventListener('focusout', () => queueMicrotask(() => host.onmouseleave?.()));
      host.dataset.focusBound = 'true';
    }
    schedule();
    return dismiss;
  }
  window.addEventListener('software-runtime-settings-changed',()=>notificationHost?.onmouseleave?.());

  function confirmAction(message, options = {}) {
    return new Promise(resolve => {
      const previous = document.activeElement, dialog = document.createElement('dialog');
      dialog.className = 'app-confirm interaction-confirm';
      dialog.dataset.danger = String(!!options.danger);
      dialog.innerHTML = `<form method="dialog"><h2 id="confirmTitle">${escape(options.title || '确认操作')}</h2><p id="confirmDescription"></p>${options.phrase ? '<label class="confirm-phrase">输入确认文字<input autocomplete="off" spellcheck="false" id="confirmPhrase"></label>' : ''}<div class="dialog-actions"><button value="cancel" autofocus>取消</button><button value="ok" class="${options.danger ? 'danger-action' : 'primary'}">${escape(options.confirmLabel || '确认')}</button></div></form>`;
      dialog.setAttribute('aria-labelledby', 'confirmTitle'); dialog.setAttribute('aria-describedby', 'confirmDescription');
      dialog.querySelector('p').textContent = message;
      const accept = dialog.querySelector('[value="ok"]'), input = dialog.querySelector('input');
      if (input) {
        input.placeholder = options.phrase; input.setAttribute('aria-label', `输入“${options.phrase}”确认`);
        accept.disabled = true; input.oninput = () => accept.disabled = input.value.trim() !== options.phrase;
      }
      dialog.querySelector('form').addEventListener('submit', event => {
        if (event.submitter === accept && accept.disabled) event.preventDefault();
      });
      dialog.addEventListener('close', () => { const accepted = dialog.returnValue === 'ok'; dialog.remove(); previous?.isConnected && previous.focus(); resolve(accepted); }, {once:true});
      document.body.append(dialog); dialog.showModal();
    });
  }

  async function busy(button, action, label = '处理中…') {
    if (button.disabled) return;
    const old = button.textContent;
    button.disabled = true; button.setAttribute('aria-busy', 'true'); button.textContent = label;
    try { return await action(); }
    finally { button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = old; }
  }
  window.appFeedback = {notify, confirm:confirmAction, busy, notificationDuration};

  // Track real request lifetimes; no synthetic percentages or background polling.
  window.fetch = async (...args) => {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    const tracked = /^(?:\/api\/|https?:\/\/[^/]+\/api\/)/.test(url);
    if (!tracked) return nativeFetch(...args);
    activeRequests++;
    clearTimeout(activityHideTimer);
    if (!requestActivityVisible && !activityTimer) {
      activityTimer = setTimeout(() => {
        activityTimer = null;
        if (activeRequests > 0) {
          requestActivityVisible = true;
          renderActivity();
        }
      }, requestActivityDelay);
    }
    renderActivity();
    try {
      const response = await nativeFetch(...args);
      setConnection(true);
      return response;
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      setConnection(false);
      // 网络层失败（Failed to fetch 等）统一转译，避免把浏览器黑话直接弹给用户；
      // AbortError 是页面主动取消（如切换范围），保留原样交给调用方判断。
      throw new Error('本地数据服务未响应，请确认软件服务已正常启动；若反复出现请重启软件');
    } finally {
      activeRequests = Math.max(0, activeRequests - 1);
      if (!activeRequests) {
        clearTimeout(activityTimer);
        activityTimer = null;
        if (requestActivityVisible) {
          activityHideTimer = setTimeout(() => {
            requestActivityVisible = false;
            renderActivity();
          }, requestActivityHideDelay);
        } else renderActivity();
      } else renderActivity();
    }
  };
  function setConnection(online) {
    const el = q('#localServiceState'); if (!el) return;
    el.dataset.online = String(online); el.textContent = online ? '本机服务已连接' : '本机连接中断';
  }
  function renderActivity() {
    document.body?.classList.toggle('network-busy', requestActivityVisible);
    const el = q('#requestActivity');
    if (el) {
      el.hidden = !requestActivityVisible;
      el.textContent = activeRequests > 1 ? `正在处理 ${activeRequests} 项请求` : '正在读取本机数据';
    }
  }

  function init() {
    // Repeated clicks on chart controls should not select the entire workspace text.
    document.addEventListener('mousedown', event => {
      if (event.detail > 1 && event.target.closest('button,summary,[role="tab"],svg [role="button"]')) event.preventDefault();
    });
    const nav = q('.app-nav'); nav.setAttribute('aria-label', '主要工作区');
    nav.querySelector('strong')?.remove();
    const settingsButton = nav.querySelector('[data-open-settings]');
    if(settingsButton){
      settingsButton.textContent = '';
      settingsButton.classList.add('nav-icon', 'nav-settings');
      settingsButton.setAttribute('aria-label', '软件设置'); settingsButton.title = '软件设置';
      settingsButton.innerHTML = '<span class="app-icon icon-settings" aria-hidden="true"></span>';
    }
    nav.querySelector('footer').innerHTML = '<div class="nav-utilities"></div><div class="nav-status"><span id="localServiceState" data-online="true" role="status">本机服务已连接</span><span id="requestActivity" role="status" aria-live="polite" hidden></span></div>';
    const utilities = nav.querySelector('.nav-utilities');
    utilities.insertAdjacentHTML('beforeend', '<button id="feedbackToggle" class="nav-icon" type="button" aria-label="操作通知" aria-expanded="false" title="操作通知"><span class="app-icon icon-notification" aria-hidden="true"></span><sup id="feedbackCount"></sup></button>');
    // User-fixed placement: keep settings at the upper-right, after notifications.
    if (settingsButton) utilities.append(settingsButton);
    const progress = document.createElement('div'); progress.id = 'networkProgress'; progress.setAttribute('aria-hidden', 'true'); document.body.append(progress);
    const drawer = document.createElement('section'); drawer.id = 'feedbackDrawer'; drawer.hidden = true; drawer.setAttribute('aria-label', '操作通知');
    drawer.innerHTML = '<div class="feedback-drawer-heading"><div><h2>操作通知</h2><small id="feedbackSummary"></small></div><button id="feedbackClear" type="button" aria-label="清除通知记录" title="清除通知记录"><img src="/assets/icons/trash-2.svg" alt=""></button><button id="feedbackClose" type="button" aria-label="关闭操作通知" title="关闭操作通知"><img src="/assets/icons/x.svg" alt=""></button></div><div class="feedback-filters" role="group" aria-label="通知分类"><button type="button" data-feedback-filter="all">全部</button><button type="button" data-feedback-filter="error">失败</button><button type="button" data-feedback-filter="warning">提醒</button><button type="button" data-feedback-filter="success">完成</button><button type="button" data-feedback-filter="info">信息</button></div><ul id="feedbackHistory" aria-label="通知记录"></ul>';
    document.body.append(drawer); q('#feedbackToggle').setAttribute('aria-controls', drawer.id); paintHistory();
    const toggle = show => {
      drawer.hidden = !show; q('#feedbackToggle').setAttribute('aria-expanded', String(show));
      if (show) { history.forEach(item => { item.read = true; }); paintHistory(); q('#feedbackClose').focus(); }
    };
    drawer.querySelectorAll('[data-feedback-filter]').forEach(button => { button.onclick = () => { historyFilter = button.dataset.feedbackFilter; paintHistory(); }; });
    q('#feedbackToggle').onclick = () => toggle(drawer.hidden);
    q('#feedbackClose').onclick = () => { toggle(false); q('#feedbackToggle').focus(); };
    q('#feedbackClear').onclick = () => { history.length = 0; paintHistory(); };
    const settings = document.createElement('section'); settings.className = 'panel software-settings-panel audit-settings';
    settings.innerHTML = '<div class="panel-title"><h2>数据操作审计</h2></div><div class="setting-row"><div><b>删除、恢复与永久删除记录</b><small>记录来自本机审计数据库，独立于回收站当前列表。</small></div><button id="openOperationAudit" type="button">查看审计记录</button></div>';
    const maintenancePane = q('#settingsMaintenancePane');
    const auditButton = settings.querySelector('#openOperationAudit');
    if (maintenancePane) maintenancePane.append(settings);
    if (auditButton) auditButton.onclick = () => {
      const dialog = document.createElement('dialog'); dialog.className = 'audit-dialog'; dialog.setAttribute('aria-label','数据操作审计');
      dialog.innerHTML = '<div id="operationAuditContent"></div><div class="dialog-actions"><button type="button">关闭</button></div>';
      dialog.querySelector('button').onclick = () => dialog.close();
      dialog.addEventListener('close', () => { dialog.remove(); auditButton.focus(); }, {once:true});
      document.body.append(dialog); dialog.showModal(); new window.OperationLogViewer(dialog.querySelector('#operationAuditContent')).render();
    };
    document.addEventListener('click', event => { if (!drawer.hidden && !drawer.contains(event.target) && !event.target.closest('#feedbackToggle')) toggle(false); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && !drawer.hidden) { toggle(false); q('#feedbackToggle').focus(); } });

    for (const [id, label] of Object.entries({site:'基地',unit:'机组',outage:'大修批次',analyst:'分析人员',thimble:'通道编号'})) {
      const control = q('#' + id), field = document.createElement('label'); field.className = 'workspace-filter';
      field.textContent = label; control.before(field); field.append(control); control.setAttribute('aria-label', label);
    }
    const summary = document.createElement('div'); summary.className = 'workspace-selection-status'; summary.setAttribute('role', 'status');
    q('#workspace .table-panel .panel-title').after(summary);
    const updateSelection = () => {
      const count = window.__thimbleState?.selectedIds.size || 0;
      summary.textContent = count ? `已选择 ${count} 条记录` : '未选择记录'; summary.dataset.selected = String(count > 0);
      const button = q('#btn-data-delete'); if (button) { button.disabled = !count; button.title = count ? `删除选中的 ${count} 条记录，可从回收站恢复` : '请先勾选需要删除的记录'; }
    };
    new MutationObserver(updateSelection).observe(q('#rows'), {childList:true, subtree:true, attributes:true, attributeFilter:['class']}); updateSelection();
    q('#workspace .toolbar').setAttribute('aria-label', '检测记录筛选');
    const clear = q('#clearRecordsBtn'); clear.textContent = '清空业务数据'; clear.title = '清空全部检测与维护业务数据，与当前筛选无关；保留账户、日志和恢复备份';
    const toolbar = q('#workspace .toolbar'), filters = document.createElement('div'), commands = document.createElement('div');
    filters.className = 'workspace-filters'; commands.className = 'workspace-commands';
    for (const field of toolbar.querySelectorAll('.workspace-filter')) filters.append(field);
    filters.append(q('#searchBtn'), q('#resetBtn'));
    for (const child of [...toolbar.children]) {
      if (child.matches('.toolbar-spacer,.toolbar-sep')) child.remove();
      else commands.append(child);
    }
    commands.append(clear); toolbar.append(filters, commands);
    // Some workspace actions mount after DOMContentLoaded.
    new MutationObserver(() => {
      for (const child of [...toolbar.children]) {
        if (child.matches('button')) commands.append(child);
        else if (child.matches('.toolbar-spacer,.toolbar-sep')) child.remove();
      }
    }).observe(toolbar, {childList:true});
    for (const [id, label] of Object.entries({prevBtn:'上一页',nextBtn:'下一页'})) {
      const button = q('#' + id); button.setAttribute('aria-label', label); button.title = label;
    }

    const scrollPositions = new Map(); let current = 'workspace';
    nav.addEventListener('click', event => {
      const button = event.target.closest('[data-view]'); if (!button) return;
      const main = q('main'); scrollPositions.set(current, main.scrollTop); current = button.dataset.view;
      requestAnimationFrame(() => { main.scrollTop = scrollPositions.get(current) || 0; });
    }, true);
    document.addEventListener('keydown', event => {
      if (event.target.closest('input,select,textarea,[contenteditable="true"]')) return;
      const row = event.target.closest('#rows tr[data-i], #stateRows tr[data-state-thimble]');
      if (row && event.target === row && ['Enter',' '].includes(event.key)) { event.preventDefault(); row.click(); }
      const marker = event.target.closest('#coreMap .path-marker');
      if (marker && ['Enter',' '].includes(event.key)) { event.preventDefault(); [...marker.querySelectorAll('.path-half')].find(part=>part.getClientRects().length)?.click(); }
      const tab = event.target.closest('[role="tab"]');
      const chip = event.target.closest('#analytics .pill,#analytics .cft-chip');
      if (chip && ['Enter',' '].includes(event.key)) { event.preventDefault(); chip.click(); }
      if (tab && ['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
        const tabs = [...tab.parentElement.querySelectorAll('[role="tab"]')].filter(el => !el.disabled);
        const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (tabs.indexOf(tab)+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
        event.preventDefault(); tabs[index]?.focus(); tabs[index]?.click();
      }
    });
    const labelRows = () => {
      q('#analytics')?.querySelectorAll('.pill,.cft-chip').forEach(chip => {
        chip.tabIndex = 0; chip.setAttribute('role', 'button');
        chip.setAttribute('aria-pressed', String(chip.classList.contains('active')));
      });
      q('#rows')?.querySelectorAll('tr[data-i]').forEach(row => { row.tabIndex = 0; row.setAttribute('aria-selected', String(row.classList.contains('selected'))); });
      q('#stateRows')?.querySelectorAll('tr[data-state-thimble]').forEach(row => row.tabIndex = 0);
      document.querySelectorAll('dialog:not([aria-label]):not([aria-labelledby])').forEach(dialog => { const title = dialog.querySelector('h2,h3'); if (title) dialog.setAttribute('aria-label', title.textContent); });
    };
    let frame;
    document.addEventListener('click', event => {
      if (event.target.closest('#analytics .pill,#analytics .cft-chip')) {
        cancelAnimationFrame(frame); frame = requestAnimationFrame(labelRows);
      }
    });
    new MutationObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(labelRows); }).observe(q('main'), {childList:true, subtree:true}); labelRows();
    renderActivity();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
