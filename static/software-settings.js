(()=>{
  const q=selector=>document.querySelector(selector);
  const qa=selector=>[...document.querySelectorAll(selector)];
  const panel=document.createElement('section');
  panel.className='panel software-settings-panel';
  panel.innerHTML=`
    <div class="panel-title"><div><h2>软件设置</h2><span>数据解析、Report 版本和本机行为</span></div><span class="settings-saved" id="settingsSaved">本机配置</span></div>
    <div class="software-settings-body">
      <div class="setting-row"><div><b>Report 使用策略</b><small>控制检测文件夹存在多个分析报告时的处理方式</small></div><select id="reportPolicy"><option value="manual">逐组人工确认</option><option value="latest">自动取每组最新</option><option value="all">全部使用</option></select></div>
      <div class="setting-row"><div><b>文件校验</b><small>生成标准 Excel 时保留 ECT 文件名、HeaderTube 和覆盖率校验</small></div><label class="setting-switch"><input id="strictValidation" type="checkbox" checked><span>启用</span></label></div>
      <div class="setting-row"><div><b>运行模式</b><small>离线模式使用本机数据库；在线模式仅用于连接已配置的数据服务</small></div><select id="runtimeMode"><option value="offline">离线模式</option><option value="online">在线模式</option></select></div>
      <div id="reportPolicyNote" class="setting-note"></div>
    </div>`;
  (q('#settings .settings-sections')||q('.settings-grid'))?.prepend(panel);

  const wizard=document.createElement('dialog');
  wizard.id='reportChoiceDialog';
  wizard.innerHTML=`<form method="dialog"><div class="wizard-head"><div><span id="reportWizardStep">Report 选择</span><h2 id="reportWizardTitle">选择分析报告</h2></div><button id="cancelReportWizard" value="cancel" type="button">取消</button></div><div class="wizard-progress" aria-hidden="true"><i id="reportWizardProgress"></i></div><div class="wizard-overview-head"><b>选择总览</b><span><i class="confirmed"></i>已确认 <i class="current"></i>当前 <i></i>未确认</span></div><div id="reportWizardOverview" class="wizard-overview" aria-label="Report 数据组选择总览"></div><p id="reportWizardContext"></p><div id="reportWizardOptions" class="wizard-options"></div><div class="wizard-actions"><span id="reportWizardSelection"></span><button id="previousReportChoice" class="wizard-nav" type="button" title="上一个数据组" aria-label="上一个数据组"><b>←</b> 上一个</button><button id="confirmReportChoice" class="primary wizard-nav" type="button">下一个 <b>→</b></button></div></form>`;
  document.body.appendChild(wizard);

  const policy=q('#reportPolicy'),picker=q('#reportPicker'),note=q('#reportPolicyNote'),saved=q('#settingsSaved');
  let wizardGroups=[],wizardIndex=0,wizardSelected=[],wizardConfirmed=new Set();
  window.__selectedReports=[];
  window.__reportSelectionComplete=false;
  policy.value=localStorage.getItem('thimbleReportPolicy')||'manual';
  q('#strictValidation').checked=localStorage.getItem('thimbleStrictValidation')!=='false';
  const runtimeMode=q('#runtimeMode');runtimeMode.value=localStorage.getItem('thimbleRuntimeMode')||'offline';

  function setSaved(){saved.textContent='已保存';setTimeout(()=>saved.textContent='本机配置',1200)}
  function applyPolicy(showSaved=false){
    const value=policy.value;
    localStorage.setItem('thimbleReportPolicy',value);
    picker.hidden=value!=='manual';
    note.textContent=value==='manual'?'扫描后按数据组逐个弹窗，由操作人员确认每一份 Report。':value==='latest'?'每个 TH 数据组自动使用修改时间最新的一份 Report。':'使用目录中的全部 Report，可能包含不同分析人员或历史版本。';
    window.__selectedReports=[];window.__reportSelectionComplete=value!=='manual';
    if(showSaved)setSaved();
  }
  policy.addEventListener('change',()=>applyPolicy(true));
  q('#strictValidation').addEventListener('change',event=>{localStorage.setItem('thimbleStrictValidation',String(event.target.checked));setSaved()});
  runtimeMode.addEventListener('change',event=>{localStorage.setItem('thimbleRuntimeMode',event.target.value);setSaved();document.body.dataset.runtimeMode=event.target.value});
  document.body.dataset.runtimeMode=runtimeMode.value;
  applyPolicy();

  const policyBanner=document.createElement('div');
  policyBanner.id='activeReportPolicy';policyBanner.className='active-report-policy';
  q('#importDialog .folder-picker')?.before(policyBanner);
  function refreshBanner(){
    const labels={manual:'逐组人工确认 Report',latest:'自动取每组最新 Report',all:'使用全部 Report'};
    policyBanner.innerHTML=`<b>当前策略</b><span>${labels[policy.value]}</span><button type="button" id="openSoftwareSettings">更改设置</button>`;
    q('#openSoftwareSettings').onclick=()=>{q('#importDialog').close();q('nav [data-view="settings"]').click()};
  }
  q('#importBtn')?.addEventListener('click',refreshBanner);q('#openImportFlow')?.addEventListener('click',refreshBanner);q('#openImportFlowCard')?.addEventListener('click',refreshBanner);

  function displayOutage(outage){return !outage||outage==='UNKNOWN'?'未识别大修':outage}
  function reportGroupKey(report){return `${displayOutage(report.outage)}|${report.group||'未知数据组'}`}
  function renderReportSummary(){
    const box=q('#reportOptions');box.className='report-options report-selection-summary';
    box.innerHTML=wizardGroups.map((group,index)=>{const selected=wizardSelected[index];return `<div class="report-summary-row"><b>${group.outage} · ${group.group}</b><span>${selected?.name||'未确认'}</span><small>${selected?.analysts?.join('、')||'未标明分析人员'} · ${selected?.records||0}条</small></div>`}).join('');
  }
  function renderWizardOverview(){const overview=q('#reportWizardOverview');overview.innerHTML=wizardGroups.map((group,index)=>`<button type="button" data-group-index="${index}" class="${wizardConfirmed.has(index)?'confirmed':''} ${index===wizardIndex?'current':''}" title="${index+1}. ${group.outage} · ${group.group}${wizardConfirmed.has(index)?'（已确认）':'（未确认）'}"><span>${wizardConfirmed.has(index)?'✓':index+1}</span></button>`).join('');qa('#reportWizardOverview button').forEach(button=>button.onclick=()=>{saveCurrentChoice();wizardIndex=+button.dataset.groupIndex;showWizardGroup()})}
  function confirmedCoverage(outage){const tubes=new Set();wizardConfirmed.forEach(index=>{if(wizardGroups[index]?.outage===outage)(wizardSelected[index]?.tubes||[]).forEach(tube=>tubes.add(tube))});return tubes}
  function showWizardGroup(){
    const group=wizardGroups[wizardIndex],options=q('#reportWizardOptions');
    q('#reportWizardStep').textContent=`Report 确认 ${wizardIndex+1} / ${wizardGroups.length}`;
    q('#reportWizardTitle').textContent=`${group.outage} · ${group.group}`;
    q('#reportWizardProgress').style.width=`${((wizardIndex+1)/wizardGroups.length)*100}%`;
    const coverage=confirmedCoverage(group.outage),missing=[...Array(50)].map((_,index)=>index+1).filter(tube=>!coverage.has(tube));
    q('#reportWizardContext').innerHTML=`该数据组发现 ${group.reports.length} 份可用 Report。<b>${group.outage} 已确认覆盖 ${coverage.size}/50 根管</b>${coverage.size&&missing.length?`<small title="${missing.join('、')}">尚缺 ${missing.length} 根</small>`:''}`;
    const savedPath=wizardSelected[wizardIndex]?.path;
    options.innerHTML=group.reports.map((report,index)=>`<label class="wizard-report-option"><input type="radio" name="wizardReport" value="${index}" ${(savedPath?report.path===savedPath:index===0)?'checked':''}><span><b>${report.name}</b><small>分析人员：${report.analysts?.join('、')||'未标明'} · <strong>${report.tube_count||0} 根管</strong> · ${report.records||0} 条结果 · ${report.indication_count||0} 条缺陷指示${report.duplicate_paths?.length?` · 已合并 ${report.duplicate_paths.length} 个相同副本`:''}</small><em title="${[report.path,...(report.duplicate_paths||[])].join('\n')}">${report.path}</em></span></label>`).join('');
    renderWizardOverview();
    q('#reportWizardSelection').textContent=`已确认 ${wizardConfirmed.size} / ${wizardGroups.length} 组`;
    q('#previousReportChoice').disabled=wizardIndex===0;
    q('#confirmReportChoice').innerHTML=wizardIndex===wizardGroups.length-1?'完成确认':'下一个 <b>→</b>';
    if(!wizard.open)wizard.showModal();
  }
  function finishWizard(){
    const missing=wizardGroups.map((_,index)=>index).filter(index=>!wizardConfirmed.has(index)||!wizardSelected[index]);
    if(missing.length){wizardIndex=missing[0];showWizardGroup();q('#reportWizardContext').textContent=`还有 ${missing.length} 个数据组未确认，已定位到第一处遗漏。`;return}
    wizard.close();window.__selectedReports=wizardSelected.map(report=>report.path);window.__reportSelectionComplete=true;renderReportSummary();
    q('#importStatus').textContent=`Report 确认完成：${wizardSelected.length} 个数据组，可以生成标准 Excel`;
    q('#exportFolderExcel').disabled=false;
  }
  function saveCurrentChoice(){const checked=q('#reportWizardOptions input:checked');if(!checked)return false;wizardSelected[wizardIndex]=wizardGroups[wizardIndex].reports[+checked.value];return true}
  q('#previousReportChoice').onclick=()=>{saveCurrentChoice();if(wizardIndex>0){wizardIndex-=1;showWizardGroup()}};
  q('#confirmReportChoice').onclick=()=>{if(!saveCurrentChoice()){q('#reportWizardContext').textContent='请选择一份 Report 后继续';return}wizardConfirmed.add(wizardIndex);if(wizardIndex<wizardGroups.length-1){wizardIndex+=1;showWizardGroup()}else finishWizard()};
  wizard.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'&&wizardIndex>0){event.preventDefault();q('#previousReportChoice').click()}else if(event.key==='ArrowRight'){event.preventDefault();q('#confirmReportChoice').click()}});
  q('#cancelReportWizard').onclick=()=>{wizard.close();window.__reportSelectionComplete=false;q('#importStatus').textContent=`已取消：尚有 ${wizardGroups.length-wizardConfirmed.size} 个数据组未确认`;q('#exportFolderExcel').disabled=true};

  async function startReportWizard(){
    const path=q('#importPath').value.trim(),box=q('#reportOptions');if(!path){q('#importStatus').textContent='请先选择检测文件夹';return}
    box.className='report-options empty';box.textContent='正在扫描 Report...';q('#importStatus').textContent='正在识别数据组和 Report 版本...';q('#exportFolderExcel').disabled=true;
    try{
      const response=await fetch('/api/report-options',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})}),data=await response.json();if(!response.ok)throw new Error(data.error||'Report 扫描失败');
      const valid=data.reports.filter(report=>!report.error),groupMap=new Map();valid.forEach(report=>{const key=reportGroupKey(report);if(!groupMap.has(key))groupMap.set(key,{outage:displayOutage(report.outage),group:report.group||'未知数据组',reports:[]});groupMap.get(key).reports.push(report)});
      wizardGroups=[...groupMap.values()];wizardIndex=0;wizardSelected=[];wizardConfirmed=new Set();window.__selectedReports=[];window.__reportSelectionComplete=false;
      if(!wizardGroups.length)throw new Error('目录中没有找到可用的 Report*.rpt');
      renderReportSummary();showWizardGroup();
    }catch(error){box.className='report-options empty';box.textContent=error.message;q('#importStatus').textContent=error.message}
  }
  q('#scanReports').onclick=startReportWizard;

  q('#selectFolderBtn').onclick=async()=>{
    if(window.desktopAPI){const path=await window.desktopAPI.selectDirectory();if(path){q('#importPath').value=path;window.__selectedReports=[];window.__reportSelectionComplete=policy.value!=='manual';q('#reportOptions').className='report-options empty';q('#reportOptions').textContent='尚未扫描';if(policy.value==='manual')startReportWizard();else q('#importStatus').textContent='文件夹已选择，可直接生成标准 Excel'}}
    else{q('#importPath').readOnly=false;q('#importPath').focus()}
  };

  q('#exportFolderExcel').onclick=async event=>{
    event.preventDefault();const path=q('#importPath').value.trim(),status=q('#importStatus'),mode=policy.value;if(!path){status.textContent='请先选择检测文件夹';return}
    if(mode==='manual'&&!window.__reportSelectionComplete){status.textContent='请先逐组确认全部 Report';startReportWizard();return}
    const reports=mode==='manual'?window.__selectedReports:null;q('#parseProgress').classList.add('active');status.textContent=mode==='manual'?'正在解析已确认的 Report...':mode==='latest'?'正在自动选择每组最新 Report...':'正在解析目录中的全部 Report...';
    try{const response=await fetch('/api/export-folder-excel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,reports,report_policy:mode})}),data=await response.json();if(!response.ok)throw new Error(data.error||'文件夹处理失败');q('#excelImportPath').value=data.file_path;status.innerHTML=`已生成 ${data.rows} 条记录、${data.groups} 个数据组：<a href="${data.download_url}">${data.filename}</a><small>${data.file_path}</small>`}catch(error){status.textContent=error.message}finally{q('#parseProgress').classList.remove('active')}
  };

  q('#runImport').onclick=async event=>{
    event.preventDefault();
    const path=q('#importPath').value.trim(),status=q('#importStatus'),mode=policy.value;
    if(!path){status.textContent='请先选择检测文件夹';return}
    if(mode==='manual'&&!window.__reportSelectionComplete){status.textContent='请先逐组确认全部 Report';startReportWizard();return}
    const reports=mode==='manual'?window.__selectedReports:null;
    q('#parseProgress').classList.add('active');
    status.textContent=mode==='manual'?`正在导入已确认的 ${reports.length} 份 Report...`:'正在按当前策略导入 Report...';
    try{
      const response=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,reports})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||'写入数据库失败');
      status.textContent=`入库完成：${data.reports} 份报告，新增 ${data.inserted} 条，跳过 ${data.skipped} 条`;
      location.reload();
    }catch(error){status.textContent=error.message}
    finally{q('#parseProgress').classList.remove('active')}
  };
})();
(function(){
  function installSeveritySettings(){
    const host=document.querySelector('#settings .settings-sections')||document.querySelector('#settings')||document.querySelector('.settings-grid');
    if(!host||document.querySelector('#severitySettings'))return;
    const panel=document.createElement('section');panel.id='severitySettings';panel.className='panel software-settings-panel';
    panel.innerHTML='<div class="panel-title"><div><h2>二维管板严重度</h2><span>按同一管的最大磨损比例显示单一颜色，不改变原始数据</span></div></div><div class="software-settings-body"><label class="severity-control"><span>无缺陷 · 白色</span><input id="severityNoneColor" type="color" value="#ffffff"></label><label class="severity-control"><span data-severity-label="low">一级</span><input id="severityLowColor" type="color" value="#79b98c"></label><label class="severity-control"><span data-severity-label="mid">二级</span><input id="severityMidColor" type="color" value="#e5a83b"></label><label class="severity-control"><span data-severity-label="high">三级</span><input id="severityHighColor" type="color" value="#df4b45"></label><label class="severity-control"><span>二级起始比例 (%)</span><input id="severityMidThreshold" type="number" min="0" max="100" value="20"></label><label class="severity-control"><span>三级起始比例 (%)</span><input id="severityHighThreshold" type="number" min="0" max="100" value="40"></label></div>';
    host.append(panel);
    if(!localStorage.getItem('thimbleSeveritySettingsVersion')){localStorage.setItem('thimbleSeverityMidThreshold','20');localStorage.setItem('thimbleSeverityHighThreshold','40');localStorage.setItem('thimbleSeveritySettingsVersion','2')}
    const keys=['NoneColor','LowColor','MidColor','HighColor','MidThreshold','HighThreshold'];
    const cssVars={NoneColor:'--severity-none',LowColor:'--severity-low',MidColor:'--severity-mid',HighColor:'--severity-high'};
    const refreshLabels=()=>{const get=selector=>document.querySelector(selector),mid=Math.max(0,Math.min(100,Number(get('#severityMidThreshold')?.value||20))),high=Math.max(mid,Math.min(100,Number(get('#severityHighThreshold')?.value||40)));get('[data-severity-label="low"]').textContent=`一级 · 0 至 ${mid}%`;get('[data-severity-label="mid"]').textContent=`二级 · ${mid} 至 ${high}%`;get('[data-severity-label="high"]').textContent=`三级 · ${high}% 以上`};
    keys.forEach(key=>{const el=document.querySelector('#severity'+key),saved=localStorage.getItem('thimbleSeverity'+key);if(saved)el.value=saved;if(cssVars[key])document.documentElement.style.setProperty(cssVars[key],el.value);el.addEventListener('input',()=>{localStorage.setItem('thimbleSeverity'+key,el.value);if(cssVars[key])document.documentElement.style.setProperty(cssVars[key],el.value);refreshLabels();window.drawCore?.(state.items.filter(item=>state.selectedIds.has(item.id)))})});refreshLabels();
  }
  document.addEventListener('DOMContentLoaded',installSeveritySettings);setTimeout(installSeveritySettings,0);setTimeout(installSeveritySettings,120);
})();

(function(){
    function installSettingsPage(){
    const nav=document.querySelector('nav .nav-group');
    if(!nav)return;
    let button=nav.querySelector('[data-view="settings"]');
    if(!button){button=document.createElement('button');button.type='button';button.dataset.view='settings';button.className='nav-settings';button.textContent='软件设置';nav.append(button)}
    let view=document.querySelector('#settings');
    if(!view){view=document.createElement('section');view.id='settings';view.className='view';view.innerHTML='<div class="settings-page-heading"><span class="eyebrow">APPLICATION SETTINGS</span><h1>软件设置</h1><p>运行模式、导入策略、数据校验与二维管板显示。</p></div><div class="settings-sections"></div>';document.querySelector('main').append(view)}
    const sections=view.querySelector('.settings-sections');
    document.querySelectorAll('.software-settings-panel').forEach(panel=>sections.append(panel));
    const server=document.querySelector('#states .server-panel');if(server)sections.append(server);
    button.onclick=()=>{document.querySelectorAll('nav button,.view').forEach(item=>item.classList.remove('active'));button.classList.add('active');view.classList.add('active')};
  }
  document.addEventListener('DOMContentLoaded',()=>setTimeout(installSettingsPage,0));setTimeout(installSettingsPage,30);
})();
