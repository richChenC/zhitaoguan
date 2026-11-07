(() => {
  'use strict';
  const nativeFetch = window.fetch.bind(window);
  const loginURL = reason => {
    const query=new URLSearchParams({next:location.pathname+location.search});
    if(reason)query.set('reason',reason);
    return '/login.html?'+query;
  };
  const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('thimble-local-session') : null;
  const goLogin = reason => location.replace(loginURL(typeof reason==='string'?reason:'expired'));
  let principal = null;
  window.fetch = async (input, options = {}) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    if (url.origin !== location.origin) throw new Error('离线正式版禁止访问外部地址');
    const method = String(options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method !== 'GET' && method !== 'HEAD' && url.pathname.startsWith('/api/')
        && !url.pathname.startsWith('/api/auth/') && url.pathname !== '/api/settings/state-direction') {
      await window.statePreferences?.settled();
    }
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : {}));
    if (method !== 'GET' && method !== 'HEAD') headers.set('X-Thimble-Request', '1');
    const response = await nativeFetch(input, {...options,headers});
    if (response.status === 401 && !url.pathname.startsWith('/api/auth/')) goLogin('expired');
    return response;
  };
  async function api(path, data) {
    const response = await window.fetch(path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || '本地服务暂不可用');
    return value;
  }
  const can = permission => !!principal?.permissions.includes(permission);
  const roleNames = {admin:'系统管理员',importer:'数据导入员',editor:'数据编辑员',reviewer:'审核员',reporter:'报告用户',viewer:'只读用户'};
  const roleTasks = {
    admin:'管理账户与角色、专业设置、备份恢复和安全审计。',
    importer:'查询现有数据并导入检测数据；不负责维护结论或系统配置。',
    editor:'编辑检测记录并维护指套管状态；不负责账户管理和审核。',
    reviewer:'复核数据、处理审核事项并查看操作审计。',
    reporter:'查看检测数据、数据可视化并导出报告。',
    viewer:'只读查看检测数据、状态和分析结果。'
  };
  const permissionNames = {
    'data.read':'查询数据','data.import':'导入数据','data.edit':'编辑检测记录','state.write':'维护管状态',
    'review.write':'审核数据','export.create':'导出报告和数据','audit.read':'查看操作审计',
    'backup.manage':'管理备份','database.restore':'恢复数据库','data.delete':'删除与回收站恢复',
    'data.purge':'永久删除','settings.manage':'管理专业设置','users.manage':'管理本地账户'
  };
  const roleHelp = {admin:'账户、权限、备份和系统维护',importer:'检测数据导入与查询',editor:'检测记录编辑与管状态维护',reviewer:'数据复核与操作审计',reporter:'报告查看与结果导出',viewer:'业务数据只读查阅'};
  const currentRoles = () => (principal?.roles || []).map(role=>roleNames[role]||role).join(' / ');
  window.localAccount = {
    can,get user(){return principal},
    invalidateSession(reason='expired'){
      principal=null;channel?.postMessage({type:'logout',reason});goLogin(reason);
    }
  };
  function el(tag, text, attrs = {}) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,value);
    return node;
  }
  function button(text, action) {const node=el('button',text,{type:'button'});node.addEventListener('click',action);return node;}
  function field(form, label, name, type = 'text') {
    const row = el('label',label), input = el('input',undefined,{name,type});
    row.append(input);form.append(row);return input;
  }
  function roleGuide(parent,codes=Object.keys(roleNames)) {
    const section=el('details',undefined,{class:'account-role-guide'}),grid=el('div',undefined,{class:'account-role-grid'});
    section.append(el('summary','岗位职责说明'),grid);
    for(const code of codes){
      const card=el('article',undefined,{class:'account-role-card'});
      card.append(el('b',roleNames[code]||code),el('span',roleTasks[code]||roleHelp[code]||''));grid.append(card);
    }
    parent.append(section);
  }
  function message(error) {window.toast?.(error.message || String(error),{type:'error'});}
  async function logout() {
    await api('/api/auth/logout',{});channel?.postMessage('logout');goLogin();
  }
  function accountDialog() {
    if(document.querySelector('.local-account-dialog[open]'))return;
    const dialog=el('dialog',undefined,{class:'local-account-dialog'}), form=el('form');
    dialog.setAttribute('aria-label','账户');
    form.append(el('h2','当前账户'),el('p',`${principal.display_name} · ${principal.username}`,{class:'account-dialog-identity'}),el('p',currentRoles(),{class:'account-dialog-role'}),el('p',(principal.roles||[]).map(role=>roleTasks[role]).filter(Boolean).join(' '),{class:'account-dialog-role'}));
    const old=field(form,'当前密码','current_password','password'), password=field(form,'新密码（至少 6 位）','password','password'), confirm=field(form,'确认新密码','confirm','password');
    old.autocomplete='current-password';password.autocomplete=confirm.autocomplete='new-password';
    for (const input of [old,password,confirm]) {input.required=true;input.maxLength=128;}
    password.minLength=confirm.minLength=6;
    const status=el('p','',{class:'auth-message',role:'status'}), actions=el('menu'), save=el('button','修改密码',{type:'submit'});
    const preferences=button('账户与权限',()=>{dialog.close();window.openSoftwareSettings?.('accounts');});
    actions.append(button('关闭',()=>dialog.close()),preferences,button('退出登录',()=>logout().catch(message)),save);form.append(status,actions);dialog.append(form);document.body.append(dialog);
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});
    form.addEventListener('submit',async event=>{
      event.preventDefault();save.disabled=true;
      try {
        if(password.value!==confirm.value) throw new Error('两次输入的新密码不一致');
        await api('/api/auth/password',{current_password:old.value,password:password.value});
        channel?.postMessage('logout');goLogin();
      } catch(error) {status.textContent=error.message;save.disabled=false;}
    });
    dialog.showModal();old.focus();
  }
  const guarded = [
    ['#importBtn,#openImportFlow,#openImportFlowCard,#runImport,#selectExcelBtn,#selectExcelFolderBtn','data.import'],
    ['#saveTubeState,#batchApplyStates,[data-state-save]','state.write'],
    ['#exportBtn,#exportFolderExcel,#exportCorePng,#exportExcel,[data-export-report]','export.create'],
    ['[data-open-delete],#deleteDataBtn,#deleteFiltered','data.delete'],
    ['#clearData,#clearDatabase,#deduplicateBtn,[data-run-dedup]','data.purge'],
    ['#createBackup,#restoreBackup','backup.manage'],
  ];
  document.addEventListener('dblclick',event=>{
    if(event.target instanceof Element&&event.target.closest('#rows [data-edit-field]')&&!can('data.edit')){
      event.preventDefault();event.stopImmediatePropagation();message(new Error('当前岗位只能查看检测记录，不能编辑'));
    }
  },true);
  document.addEventListener('click',event=>{
    if (!(event.target instanceof Element)) return;
    for(const [selector,permission] of guarded) {
      if(event.target.closest(selector) && !can(permission)) {event.preventDefault();event.stopImmediatePropagation();message(new Error('当前账户没有此操作权限'));return;}
    }
  },true);
  function markPermissions() {
    const utilities=document.querySelector('.app-nav .nav-utilities');
    if(principal && utilities && !document.querySelector('#localAccountButton')) {
      const displayName=principal.display_name||principal.username;
      const initials=Array.from(displayName.trim()).slice(0,2).join('')||principal.username.slice(0,2).toUpperCase();
      const account=button('',accountDialog);
      account.id='localAccountButton';account.classList.add('account-identity');
      account.title=`${displayName} · ${principal.username}\n${currentRoles()} · 已登录`;
      account.setAttribute('aria-label',`${displayName}，已登录账户`);
      const avatar=el('span',initials,{class:'account-avatar','aria-hidden':'true'});
      const summary=el('span',undefined,{class:'account-summary'});
      summary.append(el('b',displayName,{class:'account-name'}));
      const accountStatus=el('small',undefined,{class:'account-status'});
      accountStatus.append(el('i',undefined,{'aria-hidden':'true'}),document.createTextNode('已登录'));
      summary.append(accountStatus);account.append(avatar,summary);
      utilities.prepend(account);
    }
    const tabRules=[
      ['#settingsRulesTab','settings.manage'],
      ['#settingsImportTab',null],
      ['#settingsMaintenanceTab',null],
    ];
    for(const [selector,permission] of tabRules){
      const tab=document.querySelector(selector);if(!tab)continue;
      const allowed=selector==='#settingsImportTab'?(can('data.import')||can('settings.manage'))
        :selector==='#settingsMaintenanceTab'?['audit.read','backup.manage','database.restore','data.purge'].some(can)
        :can(permission);
      tab.hidden=!allowed;tab.disabled=!allowed;tab.setAttribute('aria-hidden',String(!allowed));
      if(!allowed&&tab.getAttribute('aria-selected')==='true')document.querySelector('#settingsDataTab')?.click();
    }
    for(const jump of document.querySelectorAll('[data-settings-jump]')){
      const target=jump.dataset.settingsJump;
      const allowed=target==='settingsImportPane'?(can('data.import')||can('settings.manage'))
        :target==='settingsRulesPane'?can('settings.manage')
        :target==='settingsMaintenancePane'?['audit.read','backup.manage','database.restore','data.purge'].some(can)
        :true;
      jump.hidden=!allowed;
    }
    for(const [selector,permission] of guarded) document.querySelectorAll(selector).forEach(node=>{
      if(!can(permission)) {
        if(node.getAttribute('aria-disabled')!=='true')node.setAttribute('aria-disabled','true');
        if('disabled' in node && !node.disabled)node.disabled=true;
        if(node.title!=='当前账户没有此操作权限')node.title='当前账户没有此操作权限';
      }
    });
  }
  async function mountAdmin(parent) {
    const panel=el('section',undefined,{class:'panel local-account-panel',id:'localAccountsPanel'});
    const heading=el('header',undefined,{class:'account-panel-heading'}),headingCopy=el('div');
    headingCopy.append(el('h3','账户与角色管理'),el('p','管理账户、岗位与密码'));
    const count=el('span','读取中',{class:'account-count',id:'localAccountCount'});heading.append(headingCopy,count);panel.append(heading);
    const storageLink=button('查看数据库位置',()=>window.openSoftwareSettings?.('settingsDataPane'));
    storageLink.classList.add('account-storage-link');
    const storageNote=el('div',undefined,{class:'account-storage-note'});
    storageNote.append(el('span','本机 SQLite · 无云同步 · 密码加盐保存 · 备份包含账户'),storageLink);
    panel.append(storageNote);
    roleGuide(panel);
    const layout=el('div',undefined,{class:'account-manager-layout'}),directory=el('section',undefined,{class:'account-directory'}),directoryHeading=el('header');
    directoryHeading.append(el('b','账户目录'));
    const refreshButton=button('刷新',()=>refresh().catch(showStatus));refreshButton.classList.add('account-refresh');directoryHeading.append(refreshButton);
    const roster=el('div',undefined,{'data-account-roster':'','aria-label':'账户列表'});
    directory.append(directoryHeading,roster);layout.append(directory);
    const editor=el('section',undefined,{class:'account-editor'}),editorHeading=el('header'),editorTitle=el('div');
    editorTitle.append(el('b','账户资料'),el('small','用户名创建后不可修改'));
    const form=el('form');
    let users=[],definitions=[],selectedId='';
    const discardDialog=el('dialog',undefined,{class:'local-account-dialog account-discard-dialog'}),discardForm=el('form');
    discardForm.append(el('h2','放弃未保存更改？'),el('p','当前账户资料尚未保存。放弃后无法恢复这些输入内容。'));
    const discardActions=el('menu'),keepEditing=el('button','继续编辑',{type:'button'}),discardEdits=el('button','放弃更改',{type:'button'});
    discardActions.append(keepEditing,discardEdits);discardForm.append(discardActions);discardDialog.append(discardForm);document.body.append(discardDialog);
    let discardDecision=null;
    const confirmDiscard=()=>new Promise(resolve=>{discardDecision=resolve;discardDialog.showModal();});
    keepEditing.addEventListener('click',()=>{discardDialog.close();const resolve=discardDecision;discardDecision=null;resolve?.(false);});
    discardEdits.addEventListener('click',()=>{discardDialog.close();const resolve=discardDecision;discardDecision=null;resolve?.(true);});
    discardDialog.addEventListener('cancel',event=>{event.preventDefault();discardDialog.close();const resolve=discardDecision;discardDecision=null;resolve?.(false);});
    const startNew=button('新建账户',async()=>{if(isDirty()&&!await confirmDiscard())return;selectedId='';renderSelection();username.focus();});
    startNew.classList.add('account-new');editorHeading.append(editorTitle,startNew);
    editor.append(editorHeading,form);layout.append(editor);panel.append(layout);
    const username=field(form,'用户名（建议姓名完整拼音，创建后不可更改）','username'), display=field(form,'显示名称','display_name'), password=field(form,'密码（至少 6 位）','password','password');
    const confirmPassword=field(form,'确认密码','confirm_password','password');
    username.required=display.required=true;username.minLength=2;username.maxLength=64;username.pattern='[a-zA-Z0-9][a-zA-Z0-9_.\\-]{1,63}';username.autocomplete='username';display.maxLength=80;display.autocomplete='name';password.maxLength=confirmPassword.maxLength=128;password.minLength=confirmPassword.minLength=6;password.autocomplete=confirmPassword.autocomplete='new-password';
    const roles=el('fieldset'), activeLabel=el('label','启用账户'), active=el('input',undefined,{type:'checkbox'});activeLabel.append(active);form.append(roles,activeLabel);
    activeLabel.classList.add('account-active-label');
    const actions=el('div',undefined,{class:'account-form-actions'}),status=el('p','',{class:'auth-message',role:'status','aria-live':'polite'}),submit=el('button','创建账户',{type:'submit'});
    const discardButton=button('放弃编辑',()=>renderSelection());discardButton.classList.add('account-discard');discardButton.hidden=true;
    submit.classList.add('primary');actions.append(status,discardButton,submit);form.append(actions);parent.append(panel);
    const setStatus=(text,state='')=>{status.textContent=text;status.dataset.state=state;};
    const showStatus=error=>setStatus(error?.message||String(error),'error');
    let baseline=null;
    function formState(){return{username:username.value,display_name:display.value,roles:[...roles.querySelectorAll('input:checked')].map(node=>node.value).sort(),active:active.checked,password:password.value,confirm:confirmPassword.value};}
    function isDirty(){return !!baseline&&JSON.stringify(formState())!==JSON.stringify(baseline);}
    function updateDirty(){const dirty=isDirty();discardButton.hidden=!dirty;if(dirty)setStatus('有未保存更改，请保存或放弃后再切换账户。','dirty');}
    async function chooseAccount(id){if(id===selectedId)return;if(isDirty()&&!await confirmDiscard())return;selectedId=id;renderSelection();}
    function renderSelection() {
      const user=users.find(item=>item.id===selectedId);
      username.value=user?.username||'';username.readOnly=!!user;display.value=user?.display_name||'';password.value=confirmPassword.value='';password.required=confirmPassword.required=!user;active.checked=user?!!user.active:true;
      display.closest('label').hidden=!user;display.required=!!user;
      submit.textContent=user?'保存账户变更':'创建账户';
      setStatus(user?'密码留空则保留原密码；保存后该账户的现有会话将立即失效。':'设置初始密码，用户首次登录后可自行修改。');
      for (const check of roles.querySelectorAll('input')) check.checked=(user?.roles||['viewer']).includes(check.value);
      roster.querySelectorAll('[data-account-id]').forEach(row=>row.setAttribute('aria-current',String(row.dataset.accountId===selectedId)));
      startNew.setAttribute('aria-pressed',String(!user));
      baseline=formState();discardButton.hidden=true;
    }
    async function refresh() {
      if(isDirty()&&!await confirmDiscard())return;
      refreshButton.disabled=true;
      try{
        const data=await api('/api/auth/users');users=data.users;definitions=data.roles;
        if(!users.some(user=>user.id===selectedId))selectedId='';
        roles.replaceChildren(el('legend','岗位角色（可多选）'));
        for(const role of definitions) {
          const label=el('label'),check=el('input',undefined,{type:'checkbox',value:role.code}),copy=el('span');
          copy.append(el('b',role.label),el('small',roleHelp[role.code]||'按职责授予业务权限'));label.append(check,copy);roles.append(label);
        }
        count.textContent=`${users.length} 个账户 · ${users.filter(user=>user.active).length} 个启用`;
        roster.replaceChildren(...users.map(user=>{
          const row=button('',()=>chooseAccount(user.id));row.classList.add('account-roster-row');row.dataset.accountId=user.id;row.setAttribute('aria-current',String(user.id===selectedId));
          const state=el('span',user.active?'启用':'已停用',{class:'account-state'});state.dataset.active=String(!!user.active);
          row.append(el('span',user.display_name),el('small',user.username),state);return row;
        }));
        renderSelection();
      }catch(error){setStatus(`无法读取账户目录：${error.message}`,'error');throw error;}
      finally{refreshButton.disabled=false;}
    }
    username.addEventListener('input',()=>{if(!selectedId)display.value=username.value.trim().toLowerCase();});
    form.addEventListener('input',updateDirty);form.addEventListener('change',updateDirty);
    password.addEventListener('input',()=>{confirmPassword.required=password.required||!!password.value;});
    form.addEventListener('submit',async event=>{
      event.preventDefault();submit.disabled=true;setStatus('正在保存账户变更…');
      try {
        const id=selectedId;
        const data={display_name:id?display.value.trim():username.value.trim().toLowerCase(),roles:[...roles.querySelectorAll('input:checked')].map(node=>node.value),active:active.checked};
        if(!data.roles.length)throw new Error('请至少分配一个岗位角色');
        if(password.value){if(password.value!==confirmPassword.value)throw new Error('两次输入的新密码不一致');data.password=password.value;}
        const saved=await api(id?'/api/auth/users/update':'/api/auth/users',id?{...data,id}:{...data,username:username.value.trim()});
        window.dispatchEvent(new Event('local-accounts-changed'));
        if(id===principal.id) {channel?.postMessage('logout');goLogin();return;}
        if(!id)selectedId=saved.user_id||'';
        renderSelection();
        await refresh();setStatus('账户已保存，变更已生效。','success');
      } catch(error) {showStatus(error);} finally {submit.disabled=false;}
    });
    await refresh();
  }
  async function mountAudit(parent) {
    const panel=el('section',undefined,{class:'panel local-account-panel',id:'localSecurityAudit'});
    const heading=el('header',undefined,{class:'account-panel-heading'}),copy=el('div');
    copy.append(el('h3','安全审计'),el('p','查看登录、账户变更、权限拒绝、数据操作与导出记录。'));
    heading.append(copy);panel.append(heading);
    const tabs=el('div',undefined,{class:'account-audit-tabs',role:'tablist','aria-label':'审计记录类型'});
    const status=el('p','选择记录类型读取最近记录。',{class:'account-audit-empty',role:'status','aria-live':'polite'});
    const body=el('div',undefined,{class:'account-audit-body',id:'accountAuditBody'}),sources=[
      ['events','安全事件','/api/security/events'],['exports','导出记录','/api/security/exports'],['migrations','数据库版本','/api/schema-migrations']
    ];
    const eventNames={admin_setup:'初始化管理员',login:'登录',logout:'退出登录',user_create:'创建账户',user_update:'修改账户',password_change:'修改密码',permission_denied:'权限拒绝',request:'业务操作',database_restore:'恢复数据库'};
    function formatDate(value){return window.formatDateTime?.(value)||(value||'—');}
    function renderRows(items,key){
      if(!items.length){body.replaceChildren(el('p','当前没有相关记录。',{class:'account-audit-empty'}));return;}
      const wrap=el('div',undefined,{class:'account-audit-wrap'}),table=el('table',undefined,{class:'account-audit-table'}),head=el('thead'),headerRow=el('tr');
      const columns=key==='events'?['时间','操作账户','事件','结果','对象']:key==='exports'?['时间','操作账户','文件或资源','大小','SHA-256']:['版本','名称','校验值'];
      columns.forEach(label=>headerRow.append(el('th',label)));head.append(headerRow);table.append(head);
      const rows=el('tbody');
      for(const item of items.slice(0,200)){
        const row=el('tr');
        const values=key==='events'?[formatDate(item.created_at),item.operator,eventNames[item.event_type]||item.event_type,item.outcome==='success'?'成功':item.outcome==='failed'?'失败':item.outcome,item.resource||'—']
          :key==='exports'?[formatDate(item.created_at),item.operator,item.resource,`${Math.max(0,Number(item.size_bytes)||0).toLocaleString()} 字节`,item.sha256]
          :[item.version,item.name||'数据库结构升级',item.checksum||'—'];
        values.forEach(value=>row.append(el('td',String(value??'—'))));rows.append(row);
      }
      table.append(rows);wrap.append(table);body.replaceChildren(wrap);
    }
    async function load(key){
      const source=sources.find(item=>item[0]===key);status.textContent='正在读取…';
      try{const result=await api(source[2]),items=result.items||[];status.textContent=`最近 ${items.length} 条记录${items.length>=200?'（最多显示 200 条）':''}`;renderRows(items,key);}
      catch(error){status.textContent=error.message;body.replaceChildren();}
    }
    for(const [key,label] of sources){
      let tab;
      tab=button(label,()=>{tabs.querySelectorAll('[role=tab]').forEach(node=>node.setAttribute('aria-selected',String(node===tab)));load(key);});
      tab.id=`accountAuditTab-${key}`;tab.setAttribute('role','tab');tab.setAttribute('aria-controls',body.id);tab.setAttribute('aria-selected',String(key==='events'));tab.tabIndex=key==='events'?0:-1;tabs.append(tab);
    }
    tabs.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      const items=[...tabs.querySelectorAll('[role=tab]')],active=items.findIndex(tab=>tab.getAttribute('aria-selected')==='true');
      const next=event.key==='Home'?0:event.key==='End'?items.length-1:(active+(event.key==='ArrowRight'?1:-1)+items.length)%items.length;
      event.preventDefault();items[next].focus();items[next].click();items[next].tabIndex=0;items.forEach((tab,index)=>{if(index!==next)tab.tabIndex=-1;});
    });
    panel.append(tabs,status,body);parent.append(panel);await load('events');
  }
  async function mountBackupPolicy(parent) {
    const panel=el('section',undefined,{class:'panel local-account-panel',id:'localBackupPolicy'});
    panel.append(el('h3','自动备份保留策略'),el('p','启动、导入和删除前自动创建 SQLite 一致性快照及 SHA-256 清单。仅清理登记的自动备份，手工备份、升级备份和恢复前安全备份保留。'));
    const form=el('form'),keep=field(form,'保留最近自动备份数量（5–200）','automatic_keep','number');keep.min=5;keep.max=200;keep.required=true;
    const submit=el('button','保存策略',{type:'submit'}),status=el('p','',{class:'auth-message',role:'status'});form.append(submit,status);panel.append(form);parent.append(panel);
    let savedKeep=String((await api('/api/backup-policy')).automatic_keep);
    keep.value=savedKeep;
    window.addEventListener('backup-policy-changed',async event=>{
      if(!event.detail?.settingsRemote)return;
      try{
        const latest=String((await api('/api/backup-policy')).automatic_keep);
        if(keep.value===savedKeep)keep.value=latest;
        else status.textContent='备份策略已在其他窗口更新，保留当前未保存的编辑。';
        savedKeep=latest;
      }catch(error){status.textContent=error.message}
    });
    form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try {const result=await api('/api/backup-policy',{automatic_keep:Number(keep.value)});savedKeep=String(result.automatic_keep);keep.value=savedKeep;status.textContent='保留策略已保存';window.dispatchEvent(new Event('backup-policy-changed'));}catch(error){status.textContent=error.message;}finally{submit.disabled=false;}});
  }
  const ready=new Promise(resolve=>document.readyState==='loading'?document.addEventListener('DOMContentLoaded',resolve,{once:true}):resolve());
  Promise.all([api('/api/auth/me'),ready]).then(async ([data])=>{
    principal=data.user;markPermissions();
    const link=el('link',undefined,{rel:'stylesheet',href:'/local-auth.css'});document.head.append(link);
    let permissionsFrame=0;
    const permissionTargets=guarded.map(([selector])=>selector).join(',')+
      ',#settingsRulesTab,#settingsImportTab,#settingsMaintenanceTab,[data-settings-jump],.app-nav .nav-utilities';
    const needsPermissionCheck=node=>node instanceof Element &&
      (node.matches(permissionTargets)||!!node.querySelector(permissionTargets));
    new MutationObserver(records=>{
      if(!records.some(record=>record.type==='attributes'
        ? record.target.matches(permissionTargets)
        : [...record.addedNodes].some(needsPermissionCheck)))return;
      if(!permissionsFrame)permissionsFrame=requestAnimationFrame(()=>{permissionsFrame=0;markPermissions();});
    }).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});
    const parent=document.querySelector('#settingsAccountsPane');
    if(parent && document.body.dataset.window==='settings') {
      const card=el('section',undefined,{class:'panel local-account-panel',id:'currentAccountPanel'});
      card.append(el('h3','当前账户'));
      const details=el('dl',undefined,{class:'account-profile'});
      for(const [label,value] of [['显示名称',principal.display_name],['用户名',principal.username],['角色',currentRoles()],['登录状态','已登录']]){
        const row=el('div');row.append(el('dt',label),el('dd',value));details.append(row);
      }
      const permissionList=el('div',undefined,{class:'account-permissions','aria-label':'当前账户权限'});
      for(const permission of principal.permissions||[])permissionList.append(el('span',permissionNames[permission]||permission));
      card.append(details,button('账户安全与退出',accountDialog));
      if(!can('users.manage'))card.append(el('h4','当前账户可执行'),permissionList);
      parent.append(card);
      if(!can('users.manage'))roleGuide(card,principal.roles||[]);
      if(can('users.manage'))await mountAdmin(parent);
      if(can('users.manage') && window.desktopAPI?.factoryReset) {
        const host=document.querySelector('#settingsMaintenancePane');
        const panel=el('section',undefined,{class:'panel local-account-panel',id:'factoryResetPanel'});
        panel.append(el('h3','恢复出厂设置'),el('p','清除本机账户、检测数据和设置。原数据库、已有备份及导出文件保留。'));
        const reset=button('恢复出厂设置',async()=>{
          reset.disabled=true;
          try {await window.desktopAPI.factoryReset();} catch(error) {message(error);} finally {reset.disabled=false;}
        });
        panel.append(reset);host?.append(panel);
      }
      if(can('audit.read'))await mountAudit(document.querySelector('#settingsMaintenancePane'));
      if(can('backup.manage'))await mountBackupPolicy(document.querySelector('#settingsMaintenancePane')||parent);
    }
    window.dispatchEvent(new CustomEvent('local-account-ready',{detail:principal}));
  }).catch(error=>{
    if(error.message.includes('登录')||document.documentElement.hasAttribute('data-startup-pending'))goLogin();
    else message(error);
  });
  channel?.addEventListener('message',event=>{
    if(event.data==='logout'||event.data?.type==='logout'){
      principal=null;goLogin(event.data?.reason||'expired');
    }
  });
  window.addEventListener('local-accounts-changed',async event=>{
    if(!principal||!event.detail?.settingsRemote)return;
    try{principal=(await api('/api/auth/me')).user;markPermissions()}
    catch(error){goLogin()}
  });
  window.addEventListener('focus',()=>{if(principal)api('/api/auth/me').catch(goLogin);});
})();
