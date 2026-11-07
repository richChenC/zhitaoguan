(()=>{
  const q=selector=>document.querySelector(selector);
  const qa=selector=>[...document.querySelectorAll(selector)];
  const escapeImportHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const analystNames=report=>[...new Set((report?.analysts||[]).map(name=>String(name||'').trim()).filter(Boolean))];
  const analystTone=name=>{let hash=0;for(const char of String(name||''))hash=(hash*31+char.charCodeAt(0))>>>0;return hash%6};
  const analystMarkup=report=>{
    const names=analystNames(report);
    return names.length?names.map(name=>`<span class="analyst-chip analyst-tone-${analystTone(name)}">${escapeImportHtml(name)}</span>`).join(''):
      '<span class="analyst-chip analyst-unlisted">未标明分析人员</span>';
  };
  const startProgress=(status,label,details={})=>window.startImportProgress?.(status,label,details);
  const updateProgress=(label,details={})=>window.updateImportProgress?.(label,details);
  const stopProgress=()=>window.stopImportProgress?.();
  let operationStarted=0,overallPercent=0;
  const waitForOperator=async action=>{
    const started=Date.now();
    try{return await action()}
    finally{operationStarted+=Date.now()-started}
  };
  const showOverall=(percent,label,meta='')=>{
    if(Number.isFinite(percent))overallPercent=Math.max(overallPercent,Math.min(100,percent));
    const elapsed=Math.max(0,(Date.now()-operationStarted)/1000);
    const details=window.importProgressDetails({percent:overallPercent,stage:label,completed:0,total:null,unit:'行',
      elapsed_seconds:elapsed,remaining_seconds:overallPercent>0?elapsed*(100-overallPercent)/overallPercent:null});
    updateProgress(label,{...details,meta});
  };
  const importRequest=(url,body,prefix='',options={})=>window.runImportRequest(url,body,task=>{
    if(options.signal?.aborted)return;
    const details=window.importProgressDetails(task);
    const range=options.range||[0,100];
    showOverall(task.percent==null?null:range[0]+(range[1]-range[0])*task.percent/100,
      prefix?`${prefix} · ${details.label}`:details.label,details.meta);
  },options);
  function showResult(status,outcome,title,lines=[],metrics=null,notices=[],meta={}){
    status.dataset.outcome=outcome;
    const headline=outcome==='failed'||/导入失败|处理失败/.test(title)?'导入失败':/部分完成/.test(title)?'部分完成':/取消/.test(title)?'已取消':/无新增数据|没有待导入/.test(title)?'无需新增':/标准 Excel 已生成/.test(title)?'Excel 已生成':'导入完成';
    const summary=metrics?`<div class="import-result-grid">${metrics.map(([label,value])=>`<div><b>${excelEscape(value)}</b><span>${excelEscape(label)}</span></div>`).join('')}</div>`:'';
    const details=lines.length?`<details class="import-result-details"><summary>查看文件明细 · ${lines.length}</summary><ul>${lines.map(line=>`<li>${excelEscape(line)}</li>`).join('')}</ul></details>`:'';
    const visibleNotices=notices.length?notices:metrics?[]:[title];
    const batchIds=[...new Set((meta.batchIds||[]).filter(Boolean).map(Number))];
    const actions=batchIds.length||meta.logPath||outcome==='failed'?`<div class="import-result-actions">${batchIds.map(id=>`<button type="button" data-import-batch="${id}">查看批次详情 #${id}</button>`).join('')}<button type="button" data-service-log>查看服务日志</button></div>`:'';
    status.innerHTML=`<div class="import-result-heading"><b>${headline}</b></div>${summary}${visibleNotices.length?`<p class="import-result-summary">${visibleNotices.map(excelEscape).join(' · ')}</p>`:''}<span class="import-result-accessible">${excelEscape(title)}</span>${details}${actions}`;
    status.querySelectorAll('[data-import-batch]').forEach(button=>button.onclick=()=>openImportDiagnostics(Number(button.dataset.importBatch)));
    status.querySelector('[data-service-log]')?.addEventListener('click',()=>openServiceLog());
    window.toast?.(title,{type:outcome==='failed'?'error':outcome==='success'?'success':'warning',historyOnly:!!status.closest('dialog[open]')});
  }
  function diagnosticDialog(title, body) {
    const previous=document.activeElement;
    const dialog=document.createElement('dialog');
    dialog.className='import-diagnostic-dialog';
    dialog.innerHTML=`<form method="dialog"><div class="wizard-head"><div><span>导入诊断</span><h2>${escapeImportHtml(title)}</h2></div></div><div class="import-diagnostic-body"></div><div class="dialog-actions"><button value="cancel">关闭</button></div></form>`;
    dialog.querySelector('.import-diagnostic-body').append(body);
    dialog.addEventListener('close',()=>{dialog.remove();if(previous?.isConnected)previous.focus()},{once:true});
    document.body.append(dialog);dialog.showModal();return dialog;
  }
  function importRecoveryHint(code,message='') {
    if(/disk is full|磁盘空间不足/i.test(message))return '释放数据库和导出目录所在磁盘的空间后，重试未完成文件。';
    if(/locked|占用|permission|拒绝访问/i.test(message))return '关闭占用文件的程序，检查文件与目录的读写权限后重试。';
    if(/HASH|CONFIRM|CHANGED/.test(code))return '来源文件可能已变化，请重新扫描文件夹并确认 Report 后再导入。';
    if(code==='MAPPING_ERROR')return '核对机组、通道编号和原始堆芯位置；已入库记录可在数据工作台修改。';
    if(/INVALID_SCOPE|MISMATCH/.test(code))return '核对机组、大修、管号及字段映射，修正源文件后重新添加并导入。';
    if(/PARSE|READ|MISSING|ECT_REFERENCE|IMPORT_FAILED/.test(code))return '检查来源文件是否完整、格式是否正确、关联文件是否齐全；修正后重试。仍失败时导出审计清单并保留服务日志。';
    if(/DUPLICATE/.test(code))return '核对是否为重复采集或重复导入；跨组重复请在导入审计中复核，保留原始文件。';
    if(code==='BLANK_INDICATION')return '有幅值、相位、磨损深度、测量通道或磨损位置的缺失三字符记录列为 WAR 候选；这些字段全部为空或 / 时自动记为 NDD。';
    return '对照原始报告核查该项；确认后修正来源数据或在对应业务界面修改。';
  }
  function mappingDiagnostic(item) {
    const hint=item.mapping_hint;
    if(!hint)return '';
    const position=escapeImportHtml(hint.raw_position||'空值');
    const candidate=hint.position_tube==null
      ? `原位置 ${position} 在此机组管板图中没有对应通道，需核对原始数据。`
      : `若原位置 ${position} 正确，对应通道编号为 ${escapeImportHtml(hint.position_tube)}。`;
    return `<div class="mapping-diagnostic"><b>${escapeImportHtml(hint.unit)}号机 · 原通道 ${escapeImportHtml(hint.tube)} · 原位置 ${position}</b><span>若通道编号正确，对应堆芯位置为 ${escapeImportHtml(hint.expected_position)}。</span><span>${candidate}</span><small>两种结果均依据奇偶机组管板映射，请对照原始记录判断。</small>${hint.outage?'<button type="button" data-mapping-locate>查看对应检测记录</button>':''}</div>`;
  }
  async function openImportDiagnostics(batchId) {
    const body=document.createElement('div');
    body.textContent=`正在读取批次 #${batchId} 的校验明细…`;
    const dialog=diagnosticDialog(`批次 #${batchId}`,body);
    let page=1,busy=false;
    async function load(){
      if(busy)return;
      busy=true;
      body.querySelectorAll('button').forEach(button=>button.disabled=true);
      try{
      const data=await window.api(`/api/data-quality?batch_id=${encodeURIComponent(batchId)}&page=${page}&size=50`);
      if(!dialog.isConnected)return;
      const issues=data.issues||[],batch=(data.batches||[]).find(row=>Number(row.id)===batchId);
      const total=data.totals?.issues??issues.length,pages=Math.max(1,Math.ceil(total/50));
      const batchSummary=batch?`<div class="import-diagnostic-metrics"><span><b>${batch.rows_parsed||0}</b>解析通过</span><span><b>${batch.rows_inserted||0}</b>新增</span><span><b>${batch.rows_skipped||0}</b>重复跳过</span><span><b>${batch.error_count||0}</b>错误</span></div>`:'';
      body.innerHTML=`<div class="import-diagnostic-summary"><b>${batch?.status==='failed'?'导入失败':'导入批次'} #${batchId}</b><span>${escapeImportHtml(batch?.source_path||'')}</span><small>${escapeImportHtml(batch?.note||'')} · 校验问题 ${total} 项（含错误与提醒）</small>${batchSummary}</div><p>错误表示该行未入库；提醒表示记录已入库但需要复核。已入库记录可在数据工作台修改，未入库行需修正源文件后重试。误导入可在本页导出审计清单或回滚批次；该批次自动写入的管状态会一起回滚。如有后续修改，回滚会整体取消，不会部分回滚。</p>${issues.length?`<ol start="${(page-1)*50+1}" class="import-diagnostic-issues">${issues.map(item=>`<li data-severity="${item.severity==='error'?'error':'warning'}"><b>${item.severity==='error'?'错误':'提醒'} · ${escapeImportHtml(item.code||'异常')}</b><span>${escapeImportHtml(item.message||'未提供原因')}</span><small>${escapeImportHtml(item.source_path||'')}${item.sheet_name?` · ${escapeImportHtml(item.sheet_name)}`:''}${item.row_number?` · 第 ${escapeImportHtml(item.row_number)} 行`:''}${item.field_name?` · 字段 ${escapeImportHtml(item.field_name)}`:''}</small>${mappingDiagnostic(item)}<span class="import-recovery-hint">${escapeImportHtml(importRecoveryHint(item.code||'',item.message||''))}</span></li>`).join('')}</ol>`:'<p class="empty">该批次没有记录校验问题。</p>'}<div class="import-result-actions"><button type="button" data-diag-prev ${page<=1?'disabled':''}>上一页</button><span>${page} / ${pages} · ${total} 项</span><button type="button" data-diag-next ${page>=pages?'disabled':''}>下一页</button><button type="button" data-diag-export>导出完整审计清单</button></div><p data-diag-status role="status"></p>`;
      body.querySelector('[data-diag-prev]').onclick=()=>{page--;load()};
      body.querySelector('[data-diag-next]').onclick=()=>{page++;load()};
      body.querySelectorAll('[data-mapping-locate]').forEach((button)=>{
        const item=issues[[...body.querySelectorAll('.import-diagnostic-issues>li')].indexOf(button.closest('li'))];
        button.onclick=async()=>{
          button.disabled=true;
          try{await window.locateMappingRecords(item.mapping_hint);dialog.close();q('#importDialog[open]')?.close()}
          catch(error){body.querySelector('[data-diag-status]').textContent=error.message;button.disabled=false}
        };
      });
      body.querySelector('[data-diag-export]').onclick=async event=>{
        const button=event.currentTarget;button.disabled=true;
        try{
          const file=await window.api('/api/data-quality/export',{method:'POST',body:JSON.stringify({batch_id:batchId})});
          if(!dialog.isConnected)return;
          const link=document.createElement('a');link.href=file.download_url;link.download=file.filename;link.textContent='重新保存';
          let saving=false;
          const save=async()=>{
            if(saving)return;
            saving=true;
            try{
              const result=await window.saveGeneratedOfficeFile(file);
              if(!dialog.isConnected)return;
              const message=result.status==='saved'?'已保存审计清单。':result.status==='cancelled'?'已取消保存。':'已发起下载。';
              body.querySelector('[data-diag-status]')?.replaceChildren(document.createTextNode(message+' '),link);
            }catch(error){
              if(dialog.isConnected)body.querySelector('[data-diag-status]')?.replaceChildren(document.createTextNode(`保存失败：${error.message}。 `),link);
            }finally{saving=false}
          };
          link.onclick=event=>{event.preventDefault();save()};
          await save();
        }catch(error){if(dialog.isConnected)body.querySelector('[data-diag-status]').textContent=`导出失败：${error.message}，请重试。`}
        finally{button.disabled=false}
      };
      }catch(error){
        body.replaceChildren(document.createTextNode(`读取批次详情失败：${error.message} `));
        const retry=document.createElement('button');retry.type='button';retry.textContent='重新读取';retry.onclick=load;body.append(retry);
      }finally{busy=false}
    }
    await load();
  }
  async function openServiceLog() {
    const body=document.createElement('div');
    body.textContent='正在读取本地服务日志…';
    const dialog=diagnosticDialog('本地服务日志',body);
    try{
      const data=await window.api('/api/logs/recent?limit=160');
      if(!dialog.isConnected)return;
      const pre=document.createElement('pre');pre.className='import-service-log';pre.textContent=(data.lines||[]).join('\n')||(data.error?`日志暂时无法读取：${data.error}`:'暂无服务日志');
      body.replaceChildren(document.createElement('p'));body.firstChild.textContent=`日志文件：${data.path||'本地服务日志'}`;body.append(pre);
    }catch(error){body.textContent=`读取服务日志失败：${error.message}`}
  }
  const logPanel=document.createElement('section');
  logPanel.className='panel software-settings-panel';
  logPanel.innerHTML='<div class="panel-title"><h2>运行日志</h2></div><div class="setting-row"><div><b>本地服务日志</b><small>查看导入、数据库与文件处理的错误记录。</small></div><button type="button" id="openServiceLog">查看服务日志</button></div>';
  q('#settingsMaintenancePane')?.append(logPanel);
  logPanel.querySelector('button').onclick=openServiceLog;
  const panel=document.createElement('section');
  panel.className='panel software-settings-panel';panel.id='importSettingsPanel';
  panel.innerHTML=`
    <div class="panel-title"><h2>文件解析</h2><span class="settings-saved" id="settingsSaved" role="status" aria-live="polite">自动保存</span></div>
    <div class="software-settings-body">
      <div class="setting-row"><label for="reportPolicy"><b>RPT 选择策略</b><small>手动逐组选择，或预选修改时间最新版本后逐组确认</small></label><select id="reportPolicy"><option value="manual">手动选择 RPT</option><option value="auto_latest">预选最新并逐组确认</option></select></div>
      <div id="reportPolicyNote" class="setting-note"></div>
    </div>`;
  q('#settingsImportPane')?.append(panel);

  const wizard=document.createElement('dialog');
  wizard.id='reportChoiceDialog';
  wizard.innerHTML=`<form method="dialog"><div class="wizard-head"><div><span id="reportWizardStep">Report 选择</span><h2 id="reportWizardTitle">选择分析报告</h2></div><button id="cancelReportWizard" value="cancel" type="button">取消</button></div><div class="wizard-progress" aria-hidden="true"><i id="reportWizardProgress"></i></div><div class="wizard-overview-head"><b>选择总览</b><span><i class="confirmed"></i>已确认 <i class="current"></i>当前 <i></i>未确认</span></div><div id="reportWizardOverview" class="wizard-overview" aria-label="Report 数据组选择总览"></div><p id="reportWizardContext"></p><div id="reportWizardOptions" class="wizard-options"></div><div class="wizard-actions"><span id="reportWizardSelection"></span><button id="previousReportChoice" class="wizard-nav" type="button" title="上一个数据组" aria-label="上一个数据组"><b>←</b> 上一个</button><button id="confirmReportChoice" class="primary wizard-nav" type="button">下一个 <b>→</b></button></div></form>`;
  document.body.appendChild(wizard);

  const policy=q('#reportPolicy'),picker=q('#reportPicker'),note=q('#reportPolicyNote'),saved=q('#settingsSaved'),importDialog=q('#importDialog');
  let wizardGroups=[],wizardIndex=0,wizardSelected=[],wizardConfirmed=new Set(),wizardPath='',importBusy=false,scanCandidates=[],activeImportMode='excel',rptExcelPath='';
  importDialog.dataset.importMode=activeImportMode;
  function reportConfirmation(){return {confirmed:window.__reportSelectionComplete,candidates:scanCandidates.map(({path,sha256,sum_sha256})=>({path,sha256,sum_sha256}))}}
  window.__selectedReports=[];
  window.__reportSelectionComplete=false;
  const storedPolicy=localStorage.getItem('thimbleReportPolicy');
  policy.value=storedPolicy==='auto_latest'?'auto_latest':'manual';
  if(storedPolicy!==policy.value)localStorage.setItem('thimbleReportPolicy',policy.value);
  let activePolicy=policy.value,deferredPolicy=null;
  localStorage.setItem('thimbleStrictValidation','true');
  localStorage.setItem('thimbleRuntimeMode','offline');
  document.body.dataset.runtimeMode='offline';

  function setSaved(){saved.textContent='已保存';saved.dataset.state='success'}
  function invalidateRptExcel(){
    rptExcelPath='';
    q('#rptConversionResult').hidden=true;
  }
  function applyPolicy(showSaved=false){
    const value=policy.value;
    localStorage.setItem('thimbleReportPolicy',value);
    if(importBusy){deferredPolicy=value;policy.value=activePolicy;return}
    activePolicy=value;
    if(picker)picker.hidden=false;
    note.textContent= value==='auto_latest' ? '按文件修改时间预选每组最新 RPT；检查后仍需逐组确认，才能生成 Excel。' : '扫描后由你为每个数据组手动选择一份 RPT，并逐组确认。';
    wizardGroups=[];wizardPath='';scanCandidates=[];invalidateRptExcel();
    window.__selectedReports=[];window.__reportSelectionComplete=false;
    const summary=q('#reportOptions');
    if(summary){summary.className='report-options empty';summary.textContent=showSaved?'选择策略已更新，请重新扫描并确认 Report':'选择文件夹后扫描并确认 Report'}
    if(showSaved)setSaved();
    if(q('#activeReportPolicy'))refreshBanner();
  }
  policy.addEventListener('change',()=>{applyPolicy(true);syncImportActions();window.dispatchEvent(new Event('report-policy-changed'))});
  window.addEventListener('storage',event=>{
    if(event.key!=='thimbleReportPolicy')return;
    const value=event.newValue==='auto_latest'?'auto_latest':'manual';
    if(event.newValue!==value)localStorage.setItem('thimbleReportPolicy',value);
    if(policy.value!==value){policy.value=value;applyPolicy(false);syncImportActions()}
  });
  applyPolicy();

  function syncImportActions(){
    const manualIncomplete=!window.__reportSelectionComplete;
    const policyMount=q('#rptPolicyMount');if(policyMount)policyMount.hidden=false;
    qa('#selectFolderBtn, #scanReports, #runImport, #selectExcelBtn, #selectExcelFolderBtn, #excelFileList button, #importReportPolicy, #excelImportTab, #rptImportTab').forEach(button=>{button.disabled=importBusy});
    const run=q('#runImport');
    const pending=excelQueue.filter(item=>item.status!=='done');
    const reportReady=window.__reportSelectionComplete&&wizardPath===q('#importPath').value.trim();
    const rptItem=rptExcelPath&&excelQueue.find(item=>item.path.toLowerCase()===rptExcelPath.toLowerCase());
    if(run){
      if(activeImportMode==='rpt'){
        run.disabled=importBusy||!reportReady||rptItem?.status==='done';
        run.textContent=!reportReady?'确认全部 Report 后导入':rptItem?.status==='done'?'导入已完成':rptItem?'继续导入标准 Excel':'生成 Excel 并导入';
      }else if(pending.length){
        run.disabled=importBusy;
        run.textContent=pending.some(item=>['failed','skipped'].includes(item.status))?'重试未完成文件':'开始导入';
      }else{
        run.disabled=true;
        run.textContent=activeImportMode==='rpt'?'确认全部 Report 后导入':'添加 Excel 后开始导入';
      }
    }
    if(q('#exportFolderExcel'))q('#exportFolderExcel').disabled=importBusy||manualIncomplete||!reportReady;
    const hint=q('#importActionHint');
    if(hint)hint.textContent=activeImportMode==='rpt'
      ?!reportReady?'逐组确认 Report 后即可生成 Excel 并导入。':rptItem?.status==='done'?'本次 RPT 已完成转换和入库。':rptItem?'标准 Excel 已保存，继续导入时无需重新转换。':'已确认全部 Report，点击后自动保存标准 Excel 并导入数据库。'
      :pending.length?`队列有 ${pending.length} 个待处理文件，开始后会逐个校验并显示进度。`:excelQueue.length?'队列中的文件已全部处理完成。':'添加 Excel 文件后即可开始导入。';
    const cancel=q('#importDialog button[value="cancel"]');if(cancel)cancel.disabled=importBusy;
    importDialog.setAttribute('aria-busy',String(importBusy));importDialog.dataset.busy=String(importBusy);
  }
  function setImportBusy(busy){
    importBusy=busy;
    if(!busy&&deferredPolicy!==null){policy.value=deferredPolicy;deferredPolicy=null;applyPolicy(false)}
    syncImportActions();
    if(!busy&&deferredSource!==null){const value=deferredSource;deferredSource=null;applySourceDirectory(value)}
  }
  function setImportMode(mode){
    activeImportMode=mode==='rpt'?'rpt':'excel';
    importDialog.dataset.importMode=activeImportMode;
    const excel=activeImportMode==='excel';
    q('#excelImportPanel').hidden=!excel;
    q('#rptImportPanel').hidden=excel;
    q('#excelImportTab').setAttribute('aria-selected',String(excel));
    q('#excelImportTab').tabIndex=excel?0:-1;
    q('#rptImportTab').setAttribute('aria-selected',String(!excel));
    q('#rptImportTab').tabIndex=excel?-1:0;
    syncImportActions();
  }
  q('#excelImportTab').onclick=()=>setImportMode('excel');
  q('#rptImportTab').onclick=()=>setImportMode('rpt');
  qa('#excelImportTab,#rptImportTab').forEach((tab,index)=>tab.onkeydown=event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const target=event.key==='Home'?0:event.key==='End'?1:(index+1)%2;
    const next=target===0?'excel':'rpt';
    setImportMode(next);
    q(next==='excel'?'#excelImportTab':'#rptImportTab').focus();
  });
  function beginImportTask(status,label,details={}){operationStarted=Date.now();overallPercent=0;delete status.dataset.outcome;setImportBusy(true);startProgress(status,label,{percent:0,...details})}
  function endImportTask(){stopProgress();setImportBusy(false)}
  importDialog.addEventListener('cancel',event=>{if(!importBusy)return;event.preventDefault();q('#importStatus').textContent='当前任务仍在处理中，请等待完成后再关闭'});

  const policyBanner=document.createElement('div');
  policyBanner.id='activeReportPolicy';policyBanner.className='active-report-policy';
  q('#rptPolicyMount')?.append(policyBanner);
  function refreshBanner(){
    policyBanner.innerHTML=`<label><b>RPT 选择</b><select id="importReportPolicy" aria-label="RPT 选择策略"><option value="manual">手动选择 RPT</option><option value="auto_latest">预选最新并逐组确认</option></select></label><span class="active-report-policy-hint">${policy.value==='auto_latest'?'按修改时间预选，仍需逐组确认':'为每个数据组手动选择一份'}</span>`;
    const selector=q('#importReportPolicy');
    selector.value=policy.value;
    selector.onchange=()=>{policy.value=selector.value;policy.dispatchEvent(new Event('change',{bubbles:true}))};
  }
  let deferredSource=null;
  function applySourceDirectory(value){
    if(importBusy){deferredSource=value;return}
    const input=q('#importPath');
    if(!input||input.value&&input.value!==input.dataset.settingsDefault)return;
    if(input.value!==value){input.value=value;applyPolicy(false);syncImportActions()}
    input.dataset.settingsDefault=value;
  }
  for(const type of ['data-source-settings-loaded','data-source-settings-changed']){
    window.addEventListener(type,event=>{
      if(event.detail?.profile)applySourceDirectory(String(event.detail.profile.source_directory||''));
    });
  }
  q('#importBtn')?.addEventListener('click',refreshBanner);q('#openImportFlow')?.addEventListener('click',refreshBanner);q('#openImportFlowCard')?.addEventListener('click',refreshBanner);

  function displayOutage(outage){return !outage||outage==='UNKNOWN'?'未识别大修':outage}
  function reportGroupKey(report){return `${report.site_code}|${report.unit_id}|${displayOutage(report.outage)}|${report.group||'未知数据组'}`}
  function renderReportSummary(){
    const box=q('#reportOptions');box.className='report-options report-selection-summary';
    box.innerHTML=wizardGroups.map((group,index)=>{
      const selected=wizardSelected[index],analysts=selected?analystMarkup(selected):'<span class="analyst-chip analyst-unlisted">未确认</span>';
      return `<div class="report-summary-row"><b>${escapeImportHtml(group.outage)} · ${escapeImportHtml(group.group)}</b><span class="report-summary-analysts">${analysts}</span><small title="${escapeImportHtml(selected?.path||'')}">${escapeImportHtml(selected?.name||'尚未确认')} · ${selected?.records||0} 条结果${selected?.modified_at?` · 修改于 ${escapeImportHtml(selected.modified_at.replace('T',' '))}`:''}</small></div>`;
    }).join('');
    q('#scanReports').textContent=window.__reportSelectionComplete?'修改 Report 选择':'继续 Report 选择';
  }
  function renderWizardOverview(){const overview=q('#reportWizardOverview');overview.innerHTML=wizardGroups.map((group,index)=>`<button type="button" data-group-index="${index}" class="${wizardConfirmed.has(index)?'confirmed':''} ${index===wizardIndex?'current':''}" title="${index+1}. ${group.outage} · ${group.group}${wizardConfirmed.has(index)?'（已确认）':'（未确认）'}"><span>${wizardConfirmed.has(index)?'✓':index+1}</span></button>`).join('');qa('#reportWizardOverview button').forEach(button=>button.onclick=()=>{saveCurrentChoice();wizardIndex=+button.dataset.groupIndex;showWizardGroup()})}
  function latestReport(group){
    return [...group.reports].sort((a,b)=>
      Number(b.modified_ns||0)-Number(a.modified_ns||0)||
      String(b.name).localeCompare(String(a.name),undefined,{numeric:true})||
      String(b.path).localeCompare(String(a.path)))[0];
  }
  function autoSelectLatest(){
    wizardSelected=wizardGroups.map(latestReport);
    wizardConfirmed=new Set();window.__reportSelectionComplete=false;
  }
  function confirmedCoverage(outage){const tubes=new Set();wizardConfirmed.forEach(index=>{if(wizardGroups[index]?.outage===outage)(wizardSelected[index]?.tubes||[]).forEach(tube=>tubes.add(tube))});return tubes}
  function showWizardGroup(){
    const group=wizardGroups[wizardIndex],options=q('#reportWizardOptions');
    q('#reportWizardStep').textContent=`Report 确认 ${wizardIndex+1} / ${wizardGroups.length}`;
    q('#reportWizardTitle').textContent=`${group.outage} · ${group.group}`;
    q('#reportWizardProgress').style.width=`${((wizardIndex+1)/wizardGroups.length)*100}%`;
    const coverage=confirmedCoverage(group.outage),missing=[...Array(50)].map((_,index)=>index+1).filter(tube=>!coverage.has(tube));
    q('#reportWizardContext').innerHTML=`该数据组发现 ${group.reports.length} 份可用 Report。<b>${group.outage} 已确认覆盖 ${coverage.size}/50 根管</b>${coverage.size&&missing.length?`<small title="${missing.join('、')}">尚缺 ${missing.length} 根</small>`:''}`;
    const savedPath=wizardSelected[wizardIndex]?.path;
    options.innerHTML=group.reports.map((report,index)=>{
      const paths=[report.path,...(report.duplicate_paths||[])].join('\n');
      return `<label class="wizard-report-option"><input type="radio" name="wizardReport" value="${index}" ${savedPath&&report.path===savedPath?'checked':''}><span><b class="wizard-analyst-heading">分析人员 ${analystMarkup(report)}</b><strong class="wizard-report-name">${escapeImportHtml(report.name)}</strong><small><strong>${report.tube_count||0} 根管</strong> · ${report.records||0} 条结果 · ${report.indication_count||0} 条缺陷指示${report.duplicate_paths?.length?` · 已合并 ${report.duplicate_paths.length} 个相同副本`:''}</small>${report.blank_indication?.count?`<em class="report-data-warning">三字符缺失 ${report.blank_indication.count} 条，涉及 ${report.blank_indication.tubes} 根管；入库前必须处理</em>`:''}<em title="${escapeImportHtml(paths)}">${escapeImportHtml(report.path)}</em></span></label>`;
    }).join('');
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
    if(!rptExcelPath)q('#importStatus').textContent=`Report 确认完成：${wizardSelected.length} 个数据组，可以生成标准 Excel`;
    q('#exportFolderExcel').disabled=false;
    syncImportActions();
  }
  function saveCurrentChoice(){const checked=q('#reportWizardOptions input:checked');if(!checked)return false;const selected=wizardGroups[wizardIndex].reports[+checked.value];if(wizardSelected[wizardIndex]?.path!==selected.path){wizardConfirmed.delete(wizardIndex);invalidateRptExcel()}wizardSelected[wizardIndex]=selected;return true}
  q('#reportWizardOptions').addEventListener('change',()=>{wizardConfirmed.delete(wizardIndex);window.__reportSelectionComplete=false;invalidateRptExcel();syncImportActions();renderWizardOverview()});
  q('#previousReportChoice').onclick=()=>{saveCurrentChoice();if(wizardIndex>0){wizardIndex-=1;showWizardGroup()}};
  q('#confirmReportChoice').onclick=()=>{if(!saveCurrentChoice()){q('#reportWizardContext').textContent='请选择一份 Report 后继续';return}wizardConfirmed.add(wizardIndex);if(wizardIndex<wizardGroups.length-1){wizardIndex+=1;showWizardGroup()}else finishWizard()};
  wizard.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'&&wizardIndex>0){event.preventDefault();q('#previousReportChoice').click()}else if(event.key==='ArrowRight'){event.preventDefault();q('#confirmReportChoice').click()}});
  function preserveWizardAndClose(){
    saveCurrentChoice();
    const complete=wizardGroups.length>0&&wizardGroups.every((_,index)=>wizardConfirmed.has(index)&&wizardSelected[index]);
    window.__selectedReports=wizardSelected.filter(Boolean).map(report=>report.path);window.__reportSelectionComplete=complete;
    renderReportSummary();wizard.close();syncImportActions();
    if(!rptExcelPath)q('#importStatus').textContent=complete?`Report 选择已保留：${wizardSelected.length} 个数据组，可随时重新打开修改`:`Report 选择已保留：已确认 ${wizardConfirmed.size} / ${wizardGroups.length} 组，可稍后继续`;
  }
  q('#cancelReportWizard').onclick=preserveWizardAndClose;
  wizard.addEventListener('cancel',event=>{event.preventDefault();preserveWizardAndClose()});

  async function startReportWizard(forceScan=false){
    const path=q('#importPath').value.trim(),box=q('#reportOptions');if(!path){q('#importStatus').textContent='请先选择检测文件夹';return}
    if(!forceScan&&wizardGroups.length&&wizardPath===path){wizardIndex=0;showWizardGroup();return}
    invalidateRptExcel();
    box.className='report-options empty';box.textContent='正在扫描 Report...';q('#exportFolderExcel').disabled=true;
    beginImportTask(q('#importStatus'),'正在扫描 Report', {meta:'正在识别数据组和报告版本'});
    let ready=false;
    try{
      const data=await importRequest('/api/report-options',{path});
      const valid=data.reports.filter(report=>!report.error),failed=data.reports.filter(report=>report.error),groupMap=new Map();scanCandidates=valid;valid.forEach(report=>{const key=reportGroupKey(report);if(!groupMap.has(key))groupMap.set(key,{outage:displayOutage(report.outage),group:report.group||'未知数据组',reports:[]});groupMap.get(key).reports.push(report)});
       wizardGroups=[...groupMap.values()];wizardIndex=0;wizardSelected=[];wizardConfirmed=new Set();wizardPath=path;rptExcelPath='';window.__selectedReports=[];window.__reportSelectionComplete=false;
      if(!wizardGroups.length){
        const message=document.createElement('p'),button=document.createElement('button');
        message.textContent=failed.length
          ? `发现 ${failed.length} 份 RPT，但解析失败，不能转换。${failed.map(report=>`${report.path}：${report.error}`).join('；')}`
          : '未找到可识别的原始 RPT 数据组。请选择包含 TH数字I数字CAL数字 文件夹的原始检测目录，且 RPT 应位于数据组内；若目录只有 Excel，请使用“添加文件夹内 Excel”。';
        button.type='button';button.textContent='切换到 Excel 文件夹导入';
        button.onclick=()=>{setImportMode('excel');q('#selectExcelFolderBtn')?.click()};
        box.className='report-options empty';box.replaceChildren(message,button);
        q('#importStatus').textContent=failed.length?`发现 ${failed.length} 份 RPT 解析失败，请查看原因。`:'未找到原始 RPT 数据组；请检查所选文件夹，或切换到 Excel 导入。';
        q('#scanReports').textContent='重新扫描 RPT';
        return;
      }
      if(policy.value==='auto_latest')autoSelectLatest();
      renderReportSummary();
      if(failed.length){
        const warning=document.createElement('p');
        warning.className='report-data-warning';
        warning.textContent=`另有 ${failed.length} 份 RPT 解析失败，不会被转换：${failed.map(report=>`${report.path}：${report.error}`).join('；')}`;
        box.prepend(warning);
      }
      ready=true;
    }catch(error){box.className='report-options empty';box.textContent=error.message;q('#importStatus').textContent=error.message;q('#scanReports').textContent='重新扫描 RPT'}
    finally{endImportTask()}
    if(ready){
      if(policy.value==='auto_latest'){
        q('#importStatus').textContent=`已为 ${wizardSelected.length} 个数据组预选最新 RPT，请逐组检查并确认。`;
        showWizardGroup();
      }else showWizardGroup();
    }
  }
  q('#scanReports').onclick=()=>startReportWizard(false);

  q('#selectFolderBtn').onclick=async()=>{
    if(window.desktopAPI){let path=null;setImportBusy(true);beginImportTask(q('#importStatus'),'正在打开文件夹选择窗口');try{path=await window.desktopAPI.selectDirectory()}catch(error){q('#importStatus').textContent=error.message||'文件夹选择窗口打开失败'}finally{endImportTask()}if(path){q('#importPath').value=path;wizardGroups=[];wizardSelected=[];wizardConfirmed=new Set();wizardPath='';rptExcelPath='';window.__selectedReports=[];window.__reportSelectionComplete=false;q('#rptConversionResult').hidden=true;q('#reportOptions').className='report-options empty';q('#reportOptions').textContent='尚未扫描';q('#scanReports').textContent='扫描并确认';syncImportActions();await startReportWizard(true)}else if(!q('#importPath').value)q('#importStatus').textContent='尚未选择文件夹'}
    else{q('#importPath').readOnly=false;q('#importPath').focus()}
  };

  q('#exportFolderExcel').onclick=async event=>{
    event.preventDefault();
    try{await generateRptExcel()}
    catch(error){showResult(q('#importStatus'),'failed',`标准 Excel 生成失败：${error.message}`,[],null,[],{batchIds:error.batchId?[error.batchId]:[],logPath:error.details?.log_path})}
  };

  // 第 2 步：解析结果 Excel 多文件队列 + 字段映射向导（.xls/.xlsx/.xlsm）
  const EXCEL_FIELD_ORDER=['电站名称','大修号','机组号','通道编号','在堆芯内的位置','幅值','相位','磨损深度','三字码','测量通道','磨损位置','探头类型','分析人员','数据','数据组','RPT来源','数据流水号','数据点','liss区域大小','备注','堵管移位信息','记录编号'];
  const EXCEL_REQUIRED_FIELDS=['通道编号'];
  const EXCEL_MEASURE_FIELDS=['幅值','三字码'];
  const excelQueue=[];
  const excelBaseName=value=>String(value||'').split(/[\\/]/).pop()||String(value||'');
  const excelEscape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const alignFailedQueueItem=host=>{
    const failedItem=host?.querySelector('.excel-file-chip.failed');
    if(!failedItem)return;
    const listRect=host.getBoundingClientRect(),rowRect=failedItem.getBoundingClientRect();
    if(rowRect.bottom>listRect.bottom)host.scrollTop+=rowRect.bottom-listRect.bottom;
    else if(rowRect.top<listRect.top)host.scrollTop-=listRect.top-rowRect.top;
  };
  function renderExcelQueue(){
    const host=q('#excelFileList'),input=q('#excelImportPath');
    if(!host)return;
    if(!host.dataset.failureObserver&&typeof ResizeObserver==='function'){
      host.dataset.failureObserver='true';
      new ResizeObserver(()=>requestAnimationFrame(()=>alignFailedQueueItem(host))).observe(host);
    }
    const summary=q('#excelQueueSummary'),pending=excelQueue.filter(item=>item.status!=='done').length,done=excelQueue.length-pending,failed=excelQueue.filter(item=>['failed','skipped'].includes(item.status)).length;
    if(summary)summary.textContent=excelQueue.length?`${excelQueue.length} 个文件 · ${done} 个完成 · ${pending} 个待处理${failed?` · ${failed} 个需复核`:''}`:'尚未添加文件';
    const hint=q('#importActionHint');
    if(hint)hint.textContent=excelQueue.length?(pending?`队列有 ${pending} 个待处理文件，开始后会逐个校验并显示进度。`:'队列中的文件已全部处理完成。'):activeImportMode==='rpt'?'逐组确认 Report 后，点击“生成 Excel 并导入”完成转换和入库。':'添加 Excel 文件后即可开始导入。';
    if(!excelQueue.length){host.className='excel-file-list empty';host.textContent='尚未选择文件';if(input){input.value='';input.placeholder='尚未选择 Excel 文件'}syncImportActions();return}
    host.className='excel-file-list';
    if(input){input.value=excelQueue.length===1?excelQueue[0].path:'';input.placeholder=`已选 ${excelQueue.length} 个文件`}
    host.innerHTML=excelQueue.map((item,index)=>{const status=item.status||'pending',labels={pending:'待导入',active:'处理中',done:'已完成',failed:'失败',skipped:'已取消'},label=labels[status]||'待导入';return `<div class="excel-file-chip ${status}" title="${excelEscape(item.path)}"><span class="excel-queue-state" aria-label="${label}"></span><span class="excel-file-name">${excelEscape(excelBaseName(item.path))}</span><small>${excelEscape(item.note||label)}</small><button type="button" data-map="${index}" title="设置字段映射" aria-label="设置 ${excelEscape(excelBaseName(item.path))} 的字段映射">映射</button><button type="button" data-remove="${index}" title="从队列移除" aria-label="从队列移除 ${excelEscape(excelBaseName(item.path))}">×</button></div>`}).join('');
    requestAnimationFrame(()=>alignFailedQueueItem(host));
    qa('#excelFileList [data-remove]').forEach(button=>button.onclick=()=>{const [removed]=excelQueue.splice(Number(button.dataset.remove),1);if(removed?.path.toLowerCase()===rptExcelPath.toLowerCase())invalidateRptExcel();renderExcelQueue()});
    qa('#excelFileList [data-map]').forEach(button=>button.onclick=()=>openExcelMappingWizard(excelQueue[Number(button.dataset.map)]));
    syncImportActions();
  }
  function addExcelFiles(paths,options={}){
    let added=0;
    for(const value of paths||[]){
      if(typeof value!=='string'||!value.trim())continue;
      const clean=value.trim();
      if(excelQueue.some(item=>item.path.toLowerCase()===clean.toLowerCase()))continue;
      excelQueue.push({path:clean,status:'',note:options.sourceInfo?`RPT 转换 · ${options.sourceInfo.rows} 条记录`:'待导入',sourceInfo:options.sourceInfo||null});
      added+=1;
    }
    renderExcelQueue();
    return added;
  }
  function renderRptConversion(data){
    const host=q('#rptConversionResult'),errors=data.errors||[],missing=data.blank_indication?.count||0;
    const warnings=data.errors?.length||0;
    host.innerHTML=`<div class="rpt-conversion-heading"><b>标准 Excel 已生成</b><a href="${escapeImportHtml(data.download_url)}" download="${escapeImportHtml(data.filename)}" title="另存为 Excel">${escapeImportHtml(data.filename||'另存为 Excel')}</a></div><p data-rpt-save-status role="status" hidden></p><p>${data.rows||0} 条检测记录 · 已确认 ${window.__selectedReports.length} 组 Report · 扫描 ${data.groups||0} 个目录组 · ${data.tubes||0} 根管</p><p class="rpt-state-note">原始 RPT 未提供管状态：Excel 状态栏以 / 表示无记录，本次不会修改管状态。</p>${missing?`<p class="rpt-warning-note">可处理的三字符缺失 ${missing} 条：导入时会暂停。全空或全 / 的记录会自动记为 NDD，不会批量改为 WAR${data.blank_indication?.ndd_count?`（本次 ${data.blank_indication.ndd_count} 条）`:''}。</p>`:''}${warnings?`<details class="rpt-warning-details"><summary>转换中发现 ${warnings} 项解析或来源校验异常</summary><ul>${errors.map(error=>`<li>${escapeImportHtml(error.file||error.report||'来源文件')}：${escapeImportHtml(error.message||error.reason||'需核对')}</li>`).join('')}</ul></details>`:'<p class="rpt-clean-note">转换检查未发现 Report 解析或来源引用异常。</p>'}`;
    const link=host.querySelector('.rpt-conversion-heading a'),status=host.querySelector('[data-rpt-save-status]');
    let saving=false;
    link.onclick=async event=>{
      event.preventDefault();if(saving)return;saving=true;link.setAttribute('aria-disabled','true');
      status.hidden=false;status.dataset.outcome='pending';status.textContent='正在保存 Excel…';
      try{
        const result=await window.saveGeneratedOfficeFile(data);
        if(!host.contains(link))return;
        status.dataset.outcome=result.status;
        status.textContent=result.status==='saved'?`Excel 已保存：${result.path}`:result.status==='cancelled'?'已取消另存为；生成的 Excel 仍保留在导入队列。':'已发起 Excel 下载。';
      }catch(error){
        if(host.contains(link)){status.dataset.outcome='failed';status.textContent=`Excel 保存失败：${error.message}。可点击文件名重试，导入队列不受影响。`;}
      }finally{saving=false;link.removeAttribute('aria-disabled');}
    };
    host.hidden=false;
  }
  async function generateRptExcel({automatic=false}={}){
    const path=q('#importPath').value.trim(),status=q('#importStatus'),mode=policy.value;
    if(!path)throw new Error('请先选择原始检测文件夹');
    if(!window.__reportSelectionComplete||wizardPath!==path)throw new Error('请先逐组确认全部 Report');
    const reports=window.__selectedReports||[],ownTask=!importBusy;
    if(ownTask)beginImportTask(status,automatic?'步骤 1/2 · 正在生成标准 Excel':'正在生成标准 Excel',{meta:`已确认 ${reports.length} 份 Report`});
    try{
      const data=await importRequest('/api/export-folder-excel',{path,reports,report_policy:mode,report_confirmation:reportConfirmation()},'',{range:automatic?[0,15]:[0,100]});
      const sourceInfo={kind:'rpt',filename:data.filename,rows:data.rows||0,groups:reports.length,tubes:data.tubes||0,
        blankIndications:data.blank_indication?.count||0,errors:data.errors||[]};
      addExcelFiles([data.file_path],{sourceInfo});
      rptExcelPath=data.file_path;
      syncImportActions();
      renderRptConversion(data);
      if(!automatic)showResult(status,data.errors?.length?'warning':'success',`标准 Excel 已生成：${data.rows} 条检测记录、${reports.length} 组已确认 Report（扫描 ${data.groups} 个目录组）${data.errors?.length?`，${data.errors.length} 项解析或来源异常`:''}`);
      return data;
    }finally{if(ownTask)endImportTask()}
  }
  function openExcelMappingWizard(item){return new Promise(resolve=>{
    if(!item)return resolve(null);
    const ownTask=!importBusy;
    if(ownTask)beginImportTask(q('#importStatus'),'正在检查字段映射');
    const mappingRange=ownTask?[0,100]:[overallPercent,overallPercent];
    const dialog=document.createElement('dialog');
    dialog.className='excel-mapping-dialog';
    dialog.innerHTML='<form method="dialog"><div class="wizard-head"><div><span>字段映射向导</span><h2>'+excelEscape(excelBaseName(item.path))+'</h2></div></div><div class="excel-mapping-controls"><label>工作表<select id="mappingSheet"></select></label><label>表头行<input id="mappingHeaderRow" type="number" min="1" value="1"></label><span id="mappingHint">自动识别未通过时，请手动指定“机组号”“通道编号”以及“幅值”或“三字码”列；汇总表、异常清单不能作为缺陷明细导入。</span></div><div class="excel-mapping-grid" id="mappingGrid"></div><div class="indication-warning-actions"><span id="mappingError"></span><button value="cancel" type="button">取消</button><button id="mappingConfirm" value="default" class="primary" type="button">按此映射导入</button></div></form>';
    document.body.append(dialog);
    const sheetSelect=dialog.querySelector('#mappingSheet'),headerInput=dialog.querySelector('#mappingHeaderRow'),grid=dialog.querySelector('#mappingGrid'),errorLabel=dialog.querySelector('#mappingError');
    let inspect=null;
    const readController=new AbortController();
    const close=result=>{readController.abort();if(ownTask)endImportTask();else stopProgress();dialog.close();dialog.remove();resolve(result)};
    dialog.querySelector('[value="cancel"]').onclick=()=>close(null);
    dialog.addEventListener('cancel',event=>{event.preventDefault();close(null)});
    const renderGrid=()=>{
      const sheet=inspect.sheets.find(entry=>entry.name===sheetSelect.value)||inspect.sheets[0];
      const columns=(sheet&&sheet.columns)||[];
      const mapping=(sheet&&sheet.mapping)||{};
      const sheetScope=/^[A-Z]{1,2}\d{3}$/.test(String(sheet?.name||'').trim().toUpperCase());
      grid.innerHTML=EXCEL_FIELD_ORDER.map(field=>{const detected=mapping[field],selected=detected==null?'':detected+1,required=EXCEL_REQUIRED_FIELDS.includes(field)||EXCEL_MEASURE_FIELDS.includes(field);return '<label class="mapping-row'+(required?' required':'')+'"><span>'+field+(required?' *':'')+'</span><select data-field="'+field+'"><option value="">不导入</option>'+columns.map(column=>'<option value="'+column.column+'"'+(Number(column.column)===Number(selected)?' selected':'')+'>第 '+column.column+' 列'+(column.header?' · '+excelEscape(column.header):'')+'</option>').join('')+'</select></label>'}).join('')+(sheetScope?'<p class="mapping-scope-hint">此工作表名为 '+excelEscape(sheet.name)+'，软件会自动识别大修号和机组，无需再选择机组列。</p>':'');
    };
    const confirm=dialog.querySelector('#mappingConfirm');
    confirm.disabled=true;
    errorLabel.textContent='正在读取工作表…';
    dialog.setAttribute('aria-busy','true');
    updateProgress(`正在读取工作表 · ${excelBaseName(item.path)}`,{meta:'分析表头与字段结构'});
    importRequest('/api/import-excel-inspect',{path:item.path},excelBaseName(item.path),{signal:readController.signal,range:mappingRange}).then(data=>{
      if(!dialog.isConnected)return;
      if(!data.sheets){errorLabel.textContent=data.error||'表头检查失败';return}
      inspect=data;
      sheetSelect.innerHTML=data.sheets.map(sheet=>'<option value="'+excelEscape(sheet.name)+'">'+excelEscape(sheet.name)+(sheet.recognized?'':'（未识别为数据表）')+' · '+sheet.max_row+' 行</option>').join('');
      const preferred=data.sheets.find(sheet=>sheet.recognized)||data.sheets[0];
      if(preferred){sheetSelect.value=preferred.name;headerInput.value=String(preferred.header_row||1)}
      renderGrid();
      errorLabel.textContent='';confirm.disabled=!preferred;
    }).catch(error=>{errorLabel.textContent=error.message}).finally(()=>{if(dialog.isConnected){dialog.setAttribute('aria-busy','false');stopProgress()}});
    sheetSelect.onchange=()=>{const sheet=inspect&&inspect.sheets.find(entry=>entry.name===sheetSelect.value);if(sheet)headerInput.value=String(sheet.header_row||1);renderGrid()};
    dialog.querySelector('#mappingConfirm').onclick=()=>{
      const columns={},missing=[];
      grid.querySelectorAll('select').forEach(select=>{const value=select.value?Number(select.value):null;columns[select.dataset.field]=value;if(!value&&EXCEL_REQUIRED_FIELDS.includes(select.dataset.field))missing.push(select.dataset.field)});
      const sheetScope=/^[A-Z]{1,2}\d{3}$/.test(String(sheetSelect.value||'').trim().toUpperCase());
      if(!sheetScope&&!columns['机组号'])missing.unshift('机组号');
      if(missing.length){errorLabel.textContent='必须指定：'+missing.join('、');return}
      if(!columns['幅值']&&!columns['三字码']){errorLabel.textContent='必须至少指定“幅值”或“三字码”列';return}
      item.mapping={sheet:sheetSelect.value,header_row:Number(headerInput.value)||1,columns};
      if(item.status==='done'){item.status='';item.note='映射已修改，待导入'}
      renderExcelQueue();
      close(true);
    };
    dialog.showModal();
  })}
  async function importExcelOne(item,prefix='',range=[0,100]){
    const body={path:item.path};
    if(item.mapping)body.mapping=item.mapping;
    const data=await importRequest('/api/import-excel',body,prefix,{range});
    if(data.requires_indication_decision){
      stopProgress();
      const decision=await waitForOperator(()=>window.resolveIndicationWarnings(data));
      if(!['review','fill_war'].includes(decision))return null;
      const remaining=[overallPercent,range[1]];
      showOverall(overallPercent,decision==='fill_war'?'正在批量确认 WAR 并写入数据库':'正在保留原始空值并写入数据库');
      const confirmedData=await importRequest('/api/import-excel',{path:item.path,blank_indication_policy:decision,mapping:item.mapping||null},prefix,{range:remaining});
      return {...confirmedData,indication_decision:decision,indication_review_count:data.blank_indication?.count||0};
    }
    return {...data,indication_review_count:data.blank_indication?.count||0};
  }
  function stateImportSummary(data){
    const summary=data.state_recognition;
    if(!summary)return '';
    if(!(summary.applied||summary.pending||summary.skipped))return '；本批未包含管状态记录，现有管状态未修改';
    return `；管状态自动写入 ${summary.applied||0} 条，待核对 ${summary.pending||0} 条`;
  }
  async function importExcelItems(items,{range=[0,100],label='Excel'}={}){
    const pending=items.filter(item=>item.status!=='done');
    const totals={source:0,parsed:0,inserted:0,updated:0,skipped:0,files:0,failed:0,cancelled:0,invalid:0,states:0,review:0,blankIndications:0,nddAuto:0,warCandidate:0,rptErrors:0};
    const details=[];
    const failureMeta={batchIds:[],logPath:''};
    try{
      for(let index=0;index<pending.length;index+=1){
        const item=pending[index],start=range[0]+(range[1]-range[0])*index/pending.length,end=range[0]+(range[1]-range[0])*(index+1)/pending.length,inspectEnd=start+(end-start)*.12;
        item.status='active';item.note='正在检查表头...';renderExcelQueue();
        showOverall(start,`正在读取文件 · ${excelBaseName(item.path)}`,`文件 ${index+1} / ${pending.length}`);
        try{
          const filePrefix=`文件 ${index+1} / ${pending.length} · ${excelBaseName(item.path)}`;
          const inspect=await importRequest('/api/import-excel-inspect',{path:item.path},filePrefix,{range:[start,inspectEnd]});
          const recognized=(inspect.sheets||[]).filter(sheet=>sheet.recognized);
          if(!recognized.length&&!item.mapping){
            item.note='等待字段映射';renderExcelQueue();stopProgress();
            const mapped=await waitForOperator(()=>openExcelMappingWizard(item));
            if(!mapped){item.status='skipped';item.note='已取消（未完成字段映射）';totals.cancelled+=1;details.push(`${excelBaseName(item.path)}：${item.note}`);continue}
          }
          item.note='正在导入...';renderExcelQueue();
          const data=await importExcelOne(item,filePrefix,[inspectEnd,end]);
          if(!data){item.status='skipped';item.note='已取消，未入库';totals.cancelled+=1;details.push(`${excelBaseName(item.path)}：${item.note}`);continue}
          if(data.batch_id)failureMeta.batchIds.push(data.batch_id);
          const invalid=data.invalid_count??data.invalid_rows?.length??0;
          const applied=data.state_recognition?.applied||0;
          const review=Math.max(data.error_count||0,invalid)+(data.state_recognition?.pending||0)+(item.sourceInfo?.errors?.length||0)+(data.indication_decision==='review'?data.indication_review_count||0:0);
          const sourceInfo=item.sourceInfo;
          const blankCount=sourceInfo?.blankIndications??data.indication_review_count??0;
          const blankHandling=data.indication_decision==='fill_war'?'已按确认批次标记为 WAR':data.indication_decision==='review'?'已保留空值，待人工核对':blankCount?'需确认处理':'无三字符缺失';
          const rptNote=sourceInfo?`；RPT 转换 ${sourceInfo.rows} 条/${sourceInfo.groups} 组；管状态未提供，Excel 状态栏留空且未改状态${sourceInfo.errors?.length?`；来源/解析异常 ${sourceInfo.errors.length} 项`:''}`:'';
          const nddCount=data.blank_indication?.ndd_count||0;
          const indicationNote=(blankCount||nddCount)?`；三字符候选 ${blankCount} 条（${blankHandling}）${nddCount?`；全空/全 / 自动记为 NDD ${nddCount} 条`:''}`:'';
          item.status='done';item.stateSummary=data.state_recognition||null;item.note=`${data.inserted||data.updated||applied?'导入成功':'无新增数据'}：新增 ${data.inserted} 条${data.updated?`，更新 ${data.updated} 条`:''}，重复跳过 ${data.skipped} 条${stateImportSummary(data)}${invalid?`；无效行 ${invalid} 条`:''}`;
          totals.parsed+=data.parsed||0;totals.inserted+=data.inserted||0;totals.skipped+=data.skipped||0;totals.files+=1;
          totals.source+=data.source_total||data.parsed||0;
          totals.nddAuto+=data.ndd_auto||data.blank_indication?.ndd_count||0;
          totals.warCandidate+=data.war_candidate||data.blank_indication?.count||0;
          totals.updated+=data.updated||0;totals.invalid+=invalid;totals.states+=applied;totals.review+=review;totals.blankIndications+=blankCount;
          totals.rptErrors+=sourceInfo?.errors?.length||0;
          const sheetCount=(data.sheets||[]).length;
          details.push(`${excelBaseName(item.path)}：解析 ${data.parsed}、新增 ${data.inserted}、跳过 ${data.skipped}${data.updated?`、更新 ${data.updated}`:''}${sheetCount>1?`（${sheetCount} 张数据表）`:''}${stateImportSummary(data)}${invalid?`；无效行 ${invalid} 条`:''}${rptNote}${indicationNote}${review?`；待核对 ${review} 项`:''}`);
        }catch(error){item.status='failed';item.note=`导入失败：${error.message}`;totals.failed+=1;if(error.batchId)failureMeta.batchIds.push(error.batchId);if(error.details?.log_path)failureMeta.logPath=error.details.log_path;details.push(`${excelBaseName(item.path)}：${item.note}`)}
        finally{
          renderExcelQueue();
          showOverall(end,`已处理 ${index+1} / ${pending.length} 个文件`,`${totals.inserted} 条新增 · ${totals.failed} 个失败`);
        }
      }
      const hasReview=totals.review||totals.invalid||totals.rptErrors;
      const outcome=totals.failed||totals.cancelled||hasReview?'warning':'success';
      const title=totals.failed===pending.length?'导入失败':totals.cancelled===pending.length?'导入已取消':
        totals.failed||totals.cancelled||hasReview?'部分完成':totals.inserted||totals.updated||totals.states?'导入成功':'无新增数据（重复记录已跳过）';
      const resultPrefix=label==='RPT 转 Excel'?'RPT 转换并导入完成':'Excel 导入完成';
      const notices=[];
      if(totals.source||totals.parsed)notices.push(`源记录 ${totals.source} 条，解析通过 ${totals.parsed} 条`);
      const stateTotals=items.filter(item=>item.status==='done').reduce((sum,item)=>({applied:sum.applied+(item.stateSummary?.applied||0),pending:sum.pending+(item.stateSummary?.pending||0)}),{applied:0,pending:0});
      if(stateTotals.applied||stateTotals.pending)notices.push(`管状态自动写入 ${stateTotals.applied} 条，待核对 ${stateTotals.pending} 条`);
      if(totals.blankIndications&&details.some(line=>line.includes('已保留空值，待人工核对')))notices.push('已保留空值，待人工核对');
      if(totals.blankIndications&&details.some(line=>line.includes('已按确认批次标记为 WAR')))notices.push('已按确认批次标记为 WAR');
      if(totals.invalid)notices.push(`${totals.invalid} 条无效记录未入库，请查看批次详情，修正后重新添加文件`);
      if(totals.review)notices.push('校验问题与处理建议见批次详情；记录保存在本机导入审计中');
      if(totals.failed){
        notices.push(`${totals.failed} 个文件失败，可展开查看原因`);
        const firstFailure=pending.find(item=>item.status==='failed');
        if(firstFailure)notices.push(firstFailure.note);
      }
      if(totals.cancelled)notices.push(`${totals.cancelled} 个文件已取消`);
      const resultMetrics=[['新增',totals.inserted]];
      if(totals.updated)resultMetrics.push(['更新',totals.updated]);
      if(totals.skipped)resultMetrics.push(['重复跳过',totals.skipped]);
      if(totals.nddAuto)resultMetrics.push(['自动 NDD',totals.nddAuto]);
      if(totals.warCandidate)resultMetrics.push(['WAR 候选',totals.warCandidate]);
      if(totals.review)resultMetrics.push(['待核对',totals.review]);
      if(totals.invalid)resultMetrics.push(['无效',totals.invalid]);
      if(totals.failed)resultMetrics.push(['失败文件',totals.failed]);
      showResult(q('#importStatus'),totals.failed===pending.length?'failed':outcome,
        `${resultPrefix} · ${title}：${totals.files} 个文件，新增 ${totals.inserted} 条${totals.updated?`，更新 ${totals.updated} 条`:''}，跳过重复 ${totals.skipped} 条${totals.states?`，管状态 ${totals.states} 条`:''}${totals.blankIndications?`，三字符缺失 ${totals.blankIndications} 条`:''}${totals.invalid?`，无效行 ${totals.invalid} 条`:''}${totals.review?`，待核对 ${totals.review} 项`:''}${totals.failed?`，失败 ${totals.failed} 个`:''}${totals.cancelled?`，取消 ${totals.cancelled} 个`:''}`,details,
        resultMetrics,notices,failureMeta);
      if(totals.files){
        try{if(window.workspaceRefresh)await window.workspaceRefresh();else location.reload()}
        catch(error){
          const status=q('#importStatus'),warning=document.createElement('p');
          warning.className='import-refresh-warning';warning.setAttribute('role','alert');
          warning.textContent=`数据已入库，但界面刷新失败：${error.message}。无需重复导入，请关闭导入窗口后重新加载数据。`;
          status.dataset.outcome='warning';
          const details=status.querySelector('.import-result-details');
          if(details)details.before(warning);else status.append(warning);
          window.toast(warning.textContent,{type:'warning',historyOnly:!!status.closest('dialog[open]')});
        }
      }
      return totals;
    }catch(error){showResult(q('#importStatus'),'failed',`处理失败：${error.message}`,[],null,[],{batchIds:error.batchId?[error.batchId]:[],logPath:error.details?.log_path});return null}
  }
  q('#selectExcelBtn').onclick=async()=>{
    if(!window.desktopAPI?.selectExcel){q('#importStatus').textContent='请在本地桌面软件中选择 Excel';return}
    setImportBusy(true);beginImportTask(q('#importStatus'),'正在选择 Excel 文件',{meta:'请选择一个或多个 .xls / .xlsx / .xlsm 文件'});
    try{
      const paths=await window.desktopAPI.selectExcel();
      if(Array.isArray(paths)&&paths.length){const added=addExcelFiles(paths);q('#importStatus').textContent=`已加入 ${added} 个 Excel 文件`}
    }catch(error){q('#importStatus').textContent=error.message||'Excel 选择窗口打开失败'}
    finally{endImportTask()}
  };
  q('#selectExcelFolderBtn').onclick=async()=>{
    if(!window.desktopAPI?.selectExcelFolder){q('#importStatus').textContent='请在本地桌面软件中选择文件夹';return}
    setImportBusy(true);beginImportTask(q('#importStatus'),'正在读取文件夹',{meta:'正在查找 Excel 工作簿'});
    try{
      const result=await window.desktopAPI.selectExcelFolder();
      if(!result)return;
      if(!result.files.length){q('#importStatus').textContent='所选文件夹中没有找到 .xls / .xlsx / .xlsm 文件';return}
      const added=addExcelFiles(result.files);
      q('#importStatus').textContent=`已加入 ${added} 个 Excel 文件${result.truncated?`（文件夹内文件较多，仅加载前 ${result.files.length} 个）`:''}`;
    }catch(error){q('#importStatus').textContent=error.message||'文件夹选择窗口打开失败'}
    finally{endImportTask()}
  };
  renderExcelQueue();

  q('#runImport').onclick=async event=>{
    event.preventDefault();
    if(importBusy)return;
    const path=q('#importPath').value.trim(),status=q('#importStatus');
    const reportReady=window.__reportSelectionComplete&&wizardPath===path;
    if(activeImportMode==='rpt'&&reportReady){
      beginImportTask(status,'RPT 导入 · 准备生成标准 Excel',{meta:`已确认 ${window.__selectedReports.length} 份 Report`});
      try{
        const workbook=rptExcelPath?{file_path:rptExcelPath}:await generateRptExcel({automatic:true});
        const item=excelQueue.find(entry=>entry.path.toLowerCase()===String(workbook.file_path).toLowerCase());
        if(!item)throw new Error('标准 Excel 已生成，但没有加入待导入队列');
        if(item.status==='done')return;
        if(!item.sourceInfo?.rows)throw new Error('已保存标准 Excel，但所选 Report 没有可导入的检测记录，请检查转换异常清单');
        await importExcelItems([item],{range:[15,100],label:'RPT 转 Excel'});
      }catch(error){showResult(status,'failed',`RPT 转换或导入失败：${error.message}`,[],null,[],{batchIds:error.batchId?[error.batchId]:[],logPath:error.details?.log_path})}
      finally{endImportTask()}
      return;
    }
    if(activeImportMode==='rpt'){showResult(status,'warning','请先逐组确认全部 Report');return}
    const pending=excelQueue.filter(item=>item.status!=='done');
    if(!pending.length){showResult(status,'success','当前没有待导入的 Excel 文件');return}
    beginImportTask(status,`正在校验并写入 ${pending.length} 个 Excel 文件`);
    try{await importExcelItems(pending)}
    finally{endImportTask()}
  };
})();
if(document.body.dataset.window==='settings')(function installStateHistory(){
  const host=document.querySelector('#states');
  if(!host)return;
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels={normal:'正常',plugged:'堵管',shifted:'移位',replaced:'换管'};
  const panel=document.createElement('details');
  panel.className='import-quality';panel.id='stateAudit';
  panel.innerHTML='<summary>状态修改记录</summary><div class="iq-toolbar"><span>最近 200 次操作 · 处理记录按该次检查后生效</span><button type="button" title="刷新修改记录" aria-label="刷新修改记录">&#8635;</button></div><div class="ac-table-wrap" id="stateAuditRows"></div>';
  host.append(panel);
  function describe(raw){if(!raw)return '无记录';const row=JSON.parse(raw);return `${row.is_deleted?'已撤销 · ':''}${labels[row.state]||row.state} · ${row.offset_mm} mm${row.note?` · ${row.note}`:''}`}
  async function refresh(){
    if(!panel.open)return;
    const rows=panel.querySelector('#stateAuditRows');
    try{const response=await fetch('/api/state-history'),data=await response.json();if(!response.ok)throw new Error(data.error||'记录读取失败');
      rows.innerHTML='<table><thead><tr><th>时间</th><th>操作人员</th><th>大修 / 机组 / 管号</th><th>操作</th><th>修改前</th><th>修改后</th></tr></thead><tbody>'+data.items.map(row=>`<tr><td>${escape(window.formatDateTime?.(row.created_at)||row.created_at)}</td><td>${escape(row.operator)}</td><td>${escape(row.outage)} / ${row.unit_id} / #${row.thimble_id}</td><td>${({create:'录入',update:'修改',revoke:'撤销'})[row.action]||escape(row.action)}</td><td>${escape(describe(row.before_json))}</td><td>${escape(describe(row.after_json))}</td></tr>`).join('')+(data.items.length?'':'<tr><td colspan="6" class="empty">暂无修改记录</td></tr>')+'</tbody></table>';
    }catch(error){rows.textContent=error.message}
  }
  panel.addEventListener('toggle',refresh);panel.querySelector('button').onclick=refresh;
  window.addEventListener('tube-state-changed',refresh);
})();
if(document.body.dataset.window==='settings')(function(){
  function installSeveritySettings(){
    const host=document.querySelector('#settingsImportPane');
    if(!host||document.querySelector('#severitySettings'))return;
    const panel=document.createElement('section');panel.id='severitySettings';panel.className='panel software-settings-panel';
    panel.innerHTML='<div class="panel-title"><div><h2>二维管板严重度</h2><span>按同一管的最大磨损比例显示单一颜色，不改变原始数据</span></div></div><div class="software-settings-body"><div class="severity-section-title">颜色分级</div><label class="severity-control"><span>无缺陷 · 白色</span><input id="severityNoneColor" type="color" value="#ffffff"></label><label class="severity-control"><span data-severity-label="low">一级</span><input id="severityLowColor" type="color" value="#79b98c"></label><label class="severity-control"><span data-severity-label="mid">二级</span><input id="severityMidColor" type="color" value="#e5a83b"></label><label class="severity-control"><span data-severity-label="high">三级</span><input id="severityHighColor" type="color" value="#df4b45"></label><div class="severity-section-title">关注与极限阈值</div><label class="severity-control"><span>关注起始比例 (%)</span><input id="severityMidThreshold" type="number" min="0" max="100" value="30"></label><label class="severity-control"><span>极限起始比例 (%)</span><input id="severityHighThreshold" type="number" min="0" max="100" value="50"></label><label class="severity-control severity-toggle"><span>图表数值标注</span><input id="severityPointLabels" type="checkbox"><small>在趋势与分布图数据点旁显示数值</small></label><div class="setting-note" id="severityThresholdNote">关注阈值控制二级起点，极限阈值控制三级起点；管板颜色、严重度统计和分析参考线会立即更新。它们仅用于显示和分析，不是维修或验收判据。图表悬浮提示保留通道、位置、轮次、深度和状态。</div></div>';
    host.append(panel);
    if(!localStorage.getItem('thimbleSeveritySettingsVersion')){
      localStorage.setItem('thimbleSeverityMidThreshold','30');localStorage.setItem('thimbleSeverityHighThreshold','50');localStorage.setItem('thimbleSeveritySettingsVersion','3');
    }else if(localStorage.getItem('thimbleSeveritySettingsVersion')==='2'){
      // v2→v3：默认水位 20/40 上调为 30/50（与台账业务水位对齐）；用户已自定义的阈值保留不动。
      if(localStorage.getItem('thimbleSeverityMidThreshold')==='20')localStorage.setItem('thimbleSeverityMidThreshold','30');
      if(localStorage.getItem('thimbleSeverityHighThreshold')==='40')localStorage.setItem('thimbleSeverityHighThreshold','50');
      localStorage.setItem('thimbleSeveritySettingsVersion','3');
    }
    const keys=['NoneColor','LowColor','MidColor','HighColor','MidThreshold','HighThreshold'];
    const cssVars={NoneColor:'--severity-none',LowColor:'--severity-low',MidColor:'--severity-mid',HighColor:'--severity-high'};
    const refreshLabels=()=>{const get=selector=>document.querySelector(selector),{midThreshold:mid,highThreshold:high}=window.appSettings.severity();get('[data-severity-label="low"]').textContent=`一级 · 0 至 ${mid}%`;get('[data-severity-label="mid"]').textContent=`二级 · ${mid} 至 ${high}%`;get('[data-severity-label="high"]').textContent=`三级 · ${high}% 以上`;get('#severityThresholdNote').textContent=`当前关注阈值 ${mid}% / 极限阈值 ${high}%；管板颜色、严重度统计和分析参考线会立即更新。它们仅用于显示和分析，不是维修或验收判据。图表悬浮提示保留通道、位置、轮次、深度和状态。`};
    const labelToggle=document.querySelector('#severityPointLabels');
    if(labelToggle){labelToggle.checked=localStorage.getItem('thimbleSeverityPointLabels')==='1';labelToggle.addEventListener('change',()=>{localStorage.setItem('thimbleSeverityPointLabels',labelToggle.checked?'1':'0');window.dispatchEvent(new CustomEvent('severity-settings-changed'));});}
    const renderSeverity=()=>{
      const settings=window.appSettings.severity();
      const values={NoneColor:settings.none,LowColor:settings.low,MidColor:settings.mid,HighColor:settings.high,MidThreshold:settings.midThreshold,HighThreshold:settings.highThreshold};
      keys.forEach(key=>{const el=document.querySelector('#severity'+key);if(document.activeElement!==el)el.value=String(values[key]);if(cssVars[key])document.documentElement.style.setProperty(cssVars[key],values[key])});
      labelToggle.checked=settings.pointLabels;refreshLabels();
    };
    keys.forEach(key=>{
      const el=document.querySelector('#severity'+key);
      el.addEventListener('input',()=>{
        const mid=document.querySelector('#severityMidThreshold'),high=document.querySelector('#severityHighThreshold');
        mid.setCustomValidity('');high.setCustomValidity('');
        if(!el.checkValidity()||el.value==='')return;
        const current=window.appSettings.severity();
        const nextMid=key==='MidThreshold'?Number(el.value):current.midThreshold;
        const nextHigh=key==='HighThreshold'?Number(el.value):current.highThreshold;
        if(key.endsWith('Threshold')&&nextMid>nextHigh){
          el.setCustomValidity('关注阈值不能大于极限阈值');el.reportValidity();return;
        }
        localStorage.setItem('thimbleSeverity'+key,el.value);
        refreshLabels();window.dispatchEvent(new Event('severity-settings-changed'));
      });
      el.addEventListener('change',()=>{if(!el.checkValidity()||el.value===''){el.setCustomValidity('');el.value=localStorage.getItem('thimbleSeverity'+key)||String(window.appSettings.severity()[key==='MidThreshold'?'midThreshold':'highThreshold'])}});
    });
    window.addEventListener('severity-settings-changed',renderSeverity);renderSeverity();
  }
  installSeveritySettings();
  const nddColorControl=document.querySelector('#severityNoneColor');
  if(nddColorControl)nddColorControl.closest('label').querySelector('span').textContent='NDD';
})();

if(document.body.dataset.window==='settings')(function installDatabaseDeduplication(){
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const fields=[['outage','大修'],['unit_id','机组'],['thimble_id','通道'],['position','堆芯位置'],['entry_no','入口'],['indication','三字符'],['volts','幅值'],['degrees','相位'],['percent','磨损深度'],['location','磨损位置'],['channel','测量通道'],['datapoint','数据点'],['uid','UID'],['filename','数据文件'],['calgroup','数据组'],['analyst','分析人员']];
  function parse(value){try{return JSON.parse(value||'{}')}catch{return {}}}
  function record(title,payload,id,label='记录'){return `<section class="duplicate-side"><header><b>${title}</b><span>${label} #${escape(id??'/')}</span></header><dl>${fields.map(([key,name])=>`<div><dt>${name}</dt><dd title="${escape(payload[key])}">${escape(payload[key]??'/')}</dd></div>`).join('')}</dl></section>`}
  function comparisons(items){return items.map(item=>{const kept=parse(item.kept_payload_json),duplicate=parse(item.payload_json),source=item.source_path||duplicate.report_path||'';return `<article class="duplicate-pair"><div class="duplicate-pair-head"><strong>${item.action==='removed'?'已清理库内重复':'重复导入已拦截'}</strong><span>${escape(window.formatDateTime?.(item.detected_at)||item.detected_at)} · ${escape(item.reason)}</span></div><div class="duplicate-pair-grid">${record('数据库保留记录 A',kept,item.kept_finding_id)}${record('本次重复导入 B',duplicate,item.id,'审计')}</div><p><b>导入来源：</b>${escape(source||'未记录')}<br>判定依据：大修、机组、通道、入口、指示数据、数据文件、数据组、UID 和 Datapoint 等业务字段完全一致；来源路径和导入时间不参与判断。这里的 ECT 名称是报告引用的数据文件字段，并不表示 ECT 内产生了两条记录。</p></article>`}).join('')}
  function mount(){
    const host=document.querySelector('#settingsMaintenancePane');if(!host||document.querySelector('#databaseDedup'))return;
    const panel=document.createElement('section');panel.id='databaseDedup';panel.className='panel software-settings-panel';panel.innerHTML=`<div class="panel-title"><div><h2>数据库去重</h2><span>仅删除业务字段完全一致的记录，不合并不同入口、UID 或数据点</span></div><button id="scanDuplicates" type="button">刷新状态</button></div><div class="dedup-summary"><div><span>有效检测记录</span><strong id="dedupFindingCount">读取中…</strong></div><div><span>当前待清理</span><strong id="dedupCurrentCount">读取中…</strong></div><div><span>累计拦截导入</span><strong id="dedupDuplicateCount">读取中…</strong></div><div class="dedup-live-status"><i></i><span id="dedupStatus">正在读取去重状态</span></div><button id="runDeduplicate" class="primary" type="button">执行去重</button></div><div id="duplicateRecords" class="duplicate-records empty">正在读取去重信息...</div>`;host.append(panel);
    const records=panel.querySelector('#duplicateRecords'),runButton=panel.querySelector('#runDeduplicate');
    async function load(run=false){
      records.className='duplicate-records empty';records.textContent=run?'正在备份并清理完全重复记录...':'正在读取去重信息...';runButton.disabled=run;
      try{const response=await fetch(run?'/api/deduplicate':'/api/duplicates',run?{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}:undefined),data=await response.json();if(!response.ok)throw new Error(data.error||'去重操作失败');panel.querySelector('#dedupFindingCount').textContent=data.findings;panel.querySelector('#dedupCurrentCount').textContent=data.current_duplicates;panel.querySelector('#dedupDuplicateCount').textContent=data.duplicates;panel.querySelector('#dedupStatus').textContent=run?(data.removed?`本次移除 ${data.removed} 条，${data.before} → ${data.after}`:'扫描完成，当前没有待清理记录'):`状态已更新 · ${new Date().toLocaleTimeString('zh-CN',{hour12:false})}`;records.className='duplicate-records';records.innerHTML=data.items.length?comparisons(data.items):'<div class="empty">没有重复记录审计信息</div>';if(run)window.toast?.(data.removed?`已移除 ${data.removed} 条完全重复记录，去重前数据库已备份`:'扫描完成，当前数据库没有完全重复记录')}catch(error){records.className='duplicate-records empty';records.textContent=error.message;panel.querySelector('#dedupStatus').textContent='去重失败';window.toast?.(error.message)}finally{runButton.disabled=false}
    }
    panel.querySelector('#scanDuplicates').onclick=()=>load(false);runButton.onclick=async()=>{
      const count=Number(panel.querySelector('#dedupCurrentCount').textContent);
      const message=Number.isFinite(count)&&count>0
        ?`确认执行去重？将清理 ${count} 条业务字段完全一致的记录。\n执行前会自动生成去重前备份，可在备份列表中找回。`
        :'确认执行去重？将扫描并清理业务字段完全一致的记录（当前显示无待清理项），执行前会自动生成去重前备份。';
      if(window.appFeedback?.confirm?!await window.appFeedback.confirm(message,{title:'执行数据库去重',confirmLabel:'执行去重'}):!window.confirm(message))return;
      load(true);
    };window.addEventListener('database-cleared',()=>load(false));load(false);
  }
  mount();
})();

if(document.body.dataset.window==='settings')(function installAnalysisRules(){
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const fmtTol=v=>(Number(v)||0).toString();
  function mount(){
    const host=document.querySelector('#settingsRulesPane');if(!host||document.querySelector('#analysisRulesPanel'))return;
    const panel=document.createElement('section');panel.id='analysisRulesPanel';panel.className='panel software-settings-panel';
    panel.innerHTML=`<div class="panel-title"><div><h2>对比规则版本</h2><span>仅用于历次大修结果的缺陷位置匹配。</span></div></div>
      <div class="software-settings-body">
       <div class="ar-compact-note">修改规则不会改变原始检测数据、单次报告或已导出的文件。</div>
       <div class="ar-active" id="arActiveRule"><b>当前生效</b><span>读取中…</span></div>
       <div class="ar-list-head"><b>历史版本</b><button id="arRefresh" type="button">刷新</button></div>
       <div class="ar-list" id="arRuleList"></div>
       <div class="ar-new">
        <div class="ar-new-heading"><b>建立新版本</b><span>新版本建立后立即生效，旧版本保留用于追溯。</span></div>
        <div class="setting-row"><div><b>新规则名称</b><small>用于报告和审计记录</small></div><input id="arName" type="text" placeholder="例如：2026 秋检容差调整"></div>
        <div class="setting-row"><div><b>匹配容差 (mm)</b><small>轴向位置允许的最大偏差，范围 0.001–5 mm</small></div><input id="arTolerance" type="number" min="0.001" max="5" step="0.001" value="0.01"></div>
        <div class="setting-row"><div><b>备注</b><small>填写调整依据，便于复核</small></div><input id="arNote" type="text" placeholder="例如：依据 2026 秋检复核结果调整"></div>
        <div id="arError" class="setting-note"></div><button id="arCreate" class="primary" type="button">建立并激活新版本</button>
       </div>
      </div>`;
    host.append(panel);
    const activeBox=panel.querySelector('#arActiveRule'),list=panel.querySelector('#arRuleList'),err=panel.querySelector('#arError');
    err.setAttribute('role','alert');
    for(const [id,label] of [['arName','新规则名称'],['arTolerance','匹配容差 (mm)'],['arNote','备注']])panel.querySelector('#'+id).setAttribute('aria-label',label);
    panel.querySelector('#arName').required=true;
    panel.querySelector('#arTolerance').required=true;
    panel.querySelector('#arTolerance').closest('.setting-row').querySelector('small').textContent='轴向位置匹配允许的最大偏差；大于 0，且不超过 5 mm';
    async function load(){
      try{
        const res=await fetch('/api/analysis-rules'),data=await res.json();if(!res.ok)throw new Error(data.error||'读取规则失败');
        const a=data.active||data.defaults||{};
        activeBox.innerHTML=`<b>当前生效</b><span>v${escape(a.version??0)} · ${escape(a.name||'初始规则')} · 容差 ${fmtTol(a.match_tolerance_mm)} mm</span><small>${escape(a.created_by||'')}${a.created_at?(' · '+escape(window.formatDateTime?.(a.created_at)||a.created_at)):''}</small>${a.note?`<small>${escape(a.note)}</small>`:''}`;
        list.innerHTML=(data.items||[]).map(r=>`<div class="ar-rule-row ${r.is_active?'active':''}"><b>v${escape(r.version)} ${escape(r.name)}</b><span>容差 ${fmtTol(r.match_tolerance_mm)} mm${r.is_active?' · 当前生效':''}</span><small>${escape(r.created_by||'')}${r.created_at?(' · '+escape(window.formatDateTime?.(r.created_at)||r.created_at)):''}</small>${r.note?`<small>${escape(r.note)}</small>`:''}</div>`).join('')||'<div class="empty">暂无历史版本</div>';
      }catch(e){activeBox.innerHTML=`<b>读取失败</b><span>${escape(e.message)}</span>`;list.innerHTML=''}
    }
    panel.querySelector('#arRefresh').onclick=load;
    window.addEventListener('analysis-rules-changed',event=>{if(event.detail?.settingsRemote)load()});
    const create=panel.querySelector('#arCreate');
    create.onclick=async()=>{
      if(create.disabled)return;
      err.textContent='';
      const nameInput=panel.querySelector('#arName'),tolerance=panel.querySelector('#arTolerance');
      nameInput.setCustomValidity(nameInput.value.trim()?'':'请输入规则名称');
      nameInput.oninput=()=>nameInput.setCustomValidity('');
      if(!nameInput.reportValidity()||!tolerance.reportValidity())return;
      const name=nameInput.value.trim(),tol=tolerance.value,note=panel.querySelector('#arNote').value.trim();
      await window.appFeedback.busy(create,async()=>{
        try{
          const data=await window.api('/api/analysis-rules',{method:'POST',body:JSON.stringify({name,match_tolerance_mm:tol,note})});
          nameInput.value='';panel.querySelector('#arNote').value='';
          window.toast?.(`已建立并激活规则 v${data.version}：${data.name}`);await load();
          window.dispatchEvent(new Event('analysis-rules-changed'));
        }catch(e){err.textContent=e.message}
      },'正在建立…');
    };
    load();
  }
  mount();
})();

if(document.body.dataset.window==='settings')(function installBackupRestore(){
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const KB=bytes=>bytes==null?'/':(bytes<1024?bytes+' B':bytes<1048576?(bytes/1024).toFixed(1)+' KB':(bytes/1048576).toFixed(2)+' MB');
  const kindLabel=item=>item.kind_label||({manual:'手动备份',exported:'导出备份',safety:'恢复前备份',auto:'自动备份',legacy:'历史备份（未登记）'}[item.kind]||(String(item.kind).startsWith('auto:')?'自动备份':'其他备份'));
  const dialog=document.createElement('dialog');dialog.id='restoreDialog';dialog.className='restore-dialog';
  dialog.innerHTML='<form method="dialog"><div class="wizard-head"><div><span>恢复数据库</span><h2>确认从备份恢复</h2></div><button id="restoreCancel" value="cancel" type="button">取消</button></div><div class="restore-danger"><b>⚠ 高风险操作</b><p>恢复将<strong>覆盖当前数据库的全部数据</strong>（检测记录、管状态、报告导出记录、对比规则等）。恢复前系统会自动创建一份当前库的备份作为安全网，请确认以下信息无误后再继续。</p></div><dl class="restore-compare"><div><dt>当前数据库</dt><dd id="restoreCurrent">读取中…</dd></div><div><dt>将恢复的备份</dt><dd id="restoreBackup">/</dd></div><div><dt>安全备份</dt><dd>恢复前自动创建至默认备份目录，可再恢复回去</dd></div></dl><label class="restore-check"><input type="checkbox" id="restoreAck"> 我已理解：此操作覆盖当前数据，且恢复前会自动创建安全备份。</label><div class="wizard-actions"><span id="restoreMsg"></span><button id="restoreConfirm" class="primary danger" type="button" disabled>确认恢复</button></div><input type="hidden" id="restorePath"></form>';
  document.body.appendChild(dialog);
  function mount(){
    const host=document.querySelector('#settingsMaintenancePane');if(!host||document.querySelector('#backupPanel'))return;
    const panel=document.createElement('section');panel.id='backupPanel';panel.className='panel software-settings-panel';
    panel.innerHTML='<div class="panel-title"><div><h2>数据库备份与恢复</h2><span>整库在线备份（WAL 安全）；恢复前自动创建安全备份</span></div></div><div class="software-settings-body"><div class="backup-summary" id="backupSummary"><div><span>读取中…</span><strong>--</strong></div></div><div class="backup-actions"><button id="backupNow" class="primary" type="button">立即备份（默认目录）</button><button id="backupToFolder" type="button">备份到指定文件夹…</button><button id="backupRefresh" type="button">刷新列表</button></div><div class="backup-list-head"><b>备份列表</b><span>点击「恢复」前需二次确认</span></div><div class="backup-list" id="backupList"></div></div>';
    host.prepend(panel);
    const summary=panel.querySelector('#backupSummary'),list=panel.querySelector('#backupList'),msg=dialog.querySelector('#restoreMsg');
    let backupListRequest=0;
    async function load(){
      const request=++backupListRequest;
      try{
        const res=await fetch('/api/backups'),data=await res.json();if(!res.ok)throw new Error(data.error||'读取备份失败');
        if(request!==backupListRequest)return false;
        const c=data.current||{};
        summary.innerHTML=`<div><span>当前数据库</span><strong>${KB(data.db_size_bytes)}</strong></div><div><span>有效检测记录</span><strong>${c.findings??'/'}</strong></div><div><span>覆盖大修</span><strong>${c.outages??'/'}</strong></div><div><span>备份目录</span><strong class="backup-dir" title="${escape(data.dir)}">${escape(data.dir)}</strong></div>`;
        list.innerHTML=(data.items||[]).map(it=>`<div class="backup-row"><div class="backup-info"><b>${escape(it.name)}</b><small>${escape(window.formatDateTime?.(it.created_at)||it.created_at)} · ${escape(kindLabel(it))}</small>${it.note?`<small>${escape(it.note)}</small>`:''}</div><div class="backup-meta"><span>${KB(it.size_bytes)}</span>${it.sha256?`<span title="${escape(it.sha256)}">${escape(it.sha256.slice(0,12))}…</span>`:''}</div><button class="backup-restore" type="button" data-path="${escape(it.path)}">恢复</button></div>`).join('')||'<div class="empty">暂无备份</div>';
        list.querySelectorAll('.backup-restore').forEach(btn=>btn.onclick=()=>openRestore(btn.dataset.path));
        return true;
      }catch(e){
        if(request!==backupListRequest)return false;
        summary.innerHTML=`<div><span>读取失败</span><strong class="backup-dir">${escape(e.message)}</strong></div>`;
        list.replaceChildren();return false;
      }
    }
    let backupBusy=false;
    const backupButtons=[panel.querySelector('#backupNow'),panel.querySelector('#backupToFolder')];
    async function backup(toFolder){
      if(backupBusy)return;
      backupBusy=true;backupButtons.forEach(button=>{button.disabled=true;button.setAttribute('aria-busy','true')});
      const button=backupButtons[toFolder?1:0],label=button.textContent;button.textContent='正在备份…';
      try{
        let target;
        if(toFolder){
          if(!window.desktopAPI?.selectBackupDirectory)throw new Error('请在本地桌面软件中使用此功能');
          target=await window.desktopAPI.selectBackupDirectory();if(!target)return;
        }
        const data=await window.api('/api/backup',{method:'POST',body:JSON.stringify({note:toFolder?'导出备份':'软件设置手动备份',...(target?{target}:{})})});
        const refreshed=await load();
        window.toast?.(refreshed?`已创建备份：${data.path||data.name}`:`备份已创建：${data.path||data.name}。列表刷新失败，请刷新列表，无需重复备份。`,{type:refreshed?'success':'warning'});
      }catch(e){window.toast?.(e.message,{type:'error'})}
      finally{backupBusy=false;button.textContent=label;backupButtons.forEach(el=>{el.disabled=false;el.removeAttribute('aria-busy')})}
    }
    panel.querySelector('#backupNow').onclick=()=>backup(false);
    panel.querySelector('#backupToFolder').onclick=()=>backup(true);
    panel.querySelector('#backupRefresh').onclick=load;
    let restoreRequest=0,validated=false,restoring=false,previousFocus;
    const ack=dialog.querySelector('#restoreAck'),confirm=dialog.querySelector('#restoreConfirm'),cancel=dialog.querySelector('#restoreCancel');
    msg.setAttribute('role','status');dialog.setAttribute('aria-label','确认从备份恢复');
    const updateConfirm=()=>{confirm.disabled=restoring||!validated||!ack.checked};
    async function openRestore(path){
      if(restoring||dialog.open)return;
      const request=++restoreRequest;validated=false;previousFocus=document.activeElement;
      msg.dataset.state='loading';msg.textContent='正在校验备份…';ack.checked=false;ack.disabled=true;updateConfirm();
      dialog.querySelector('#restoreCurrent').textContent='读取中…';
      dialog.querySelector('#restoreBackup').textContent=path;
      dialog.querySelector('#restorePath').value=path;dialog.showModal();cancel.focus();
      try{
        const data=await window.api('/api/backups');
        const item=(data.items||[]).find(it=>it.path===path),c=data.current||{};
        if(!item)throw new Error('备份已不存在，请刷新列表后重新选择');
        const checked=await window.api('/api/backup-validate',{method:'POST',body:JSON.stringify({path})});
        if(request!==restoreRequest||!dialog.open)return;
        if(!Number.isInteger(checked.findings))throw new Error('备份校验结果无效，请重新选择');
        dialog.querySelector('#restoreCurrent').textContent=`${c.findings??'/'} 条记录 · ${c.outages??'/'} 次大修`;
        dialog.querySelector('#restoreBackup').textContent=`${item.name} · ${checked.findings} 条记录 · ${(window.formatDateTime?.(item.created_at)||item.created_at||'')}`;
        validated=true;ack.disabled=false;msg.dataset.state='success';msg.textContent='校验通过，请核对后确认。';updateConfirm();
      }catch(e){if(request===restoreRequest&&dialog.open){msg.dataset.state='error';msg.textContent=`无法恢复：${e.message}`}}
    }
    ack.onchange=updateConfirm;
    cancel.onclick=()=>{if(!restoring)dialog.close()};
    dialog.addEventListener('cancel',event=>{if(restoring)event.preventDefault()});
    dialog.addEventListener('close',()=>{restoreRequest++;validated=false;previousFocus?.isConnected&&previousFocus.focus()});
    dialog.querySelector('form').onsubmit=event=>event.preventDefault();
    confirm.onclick=async()=>{
      if(confirm.disabled||restoring||!validated)return;
      restoring=true;updateConfirm();ack.disabled=true;cancel.disabled=true;
      dialog.setAttribute('aria-busy','true');msg.dataset.state='loading';msg.textContent='正在恢复…';
      try{
        const data=await window.api('/api/restore',{method:'POST',body:JSON.stringify({path:dialog.querySelector('#restorePath').value})});
        restoring=false;dialog.close();
        window.toast?.(`已从 ${data.restored_from} 恢复；安全备份：${data.safety_backup}`);
        if(data.login_required){window.localAccount.invalidateSession('restore');return;}
        window.dispatchEvent(new Event('database-cleared'));
        try{if(window.workspaceRefresh)await window.workspaceRefresh();else location.reload()}
        catch(error){window.toast?.(`数据库已恢复，但界面刷新失败：${error.message}。无需重复恢复，请重新加载数据。`,{type:'warning'})}
        await load();
      }catch(e){msg.dataset.state='error';msg.textContent=e.message}
      finally{restoring=false;ack.disabled=!validated;cancel.disabled=false;dialog.removeAttribute('aria-busy');updateConfirm()}
    };
    load();
  }
  mount();
})();

if(document.body.dataset.window!=='settings'){
  window.openSoftwareSettings=section=>{
    const pane=({data:'settingsDataPane',import:'settingsImportPane',rules:'settingsRulesPane',accounts:'settingsAccountsPane',maintenance:'settingsMaintenancePane',docs:'settingsDataPane'})[section]||section||'settingsDataPane';
    return window.desktopAPI?.openSettingsWindow(pane)?.catch(error=>window.toast?.(error.message||'设置窗口打开失败',{type:'error'}));
  };
}
if(document.body.dataset.window==='settings')(function installSettingsWorkspace(){
  const q=selector=>document.querySelector(selector);
  const tabs=[...document.querySelectorAll('.settings-nav [data-settings-pane]')];
  function selectPane(id,focus=false){
    if(!tabs.some(tab=>tab.dataset.settingsPane===id))return;
    tabs.forEach(tab=>{
      const selected=tab.dataset.settingsPane===id;
      tab.classList.toggle('active',selected);
      tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;
      const pane=document.getElementById(tab.dataset.settingsPane);if(pane)pane.hidden=!selected;
      if(selected&&focus)tab.focus();
      if(selected)window.dispatchEvent(new CustomEvent('settings-pane-changed',{detail:{id}}));
    });
    q('#settings .settings-sections').scrollTop=0;
    if(q('#settings').classList.contains('active'))q('main').scrollTop=0;
  }
  tabs.forEach((tab,index)=>{
    tab.addEventListener('click',()=>selectPane(tab.dataset.settingsPane));
    tab.addEventListener('keydown',event=>{
      let next;
      if(event.key==='ArrowDown'||event.key==='ArrowRight')next=(index+1)%tabs.length;
      if(event.key==='ArrowUp'||event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;
      if(event.key==='Home')next=0;
      if(event.key==='End')next=tabs.length-1;
      if(next!==undefined){event.preventDefault();selectPane(tabs[next].dataset.settingsPane,true)}
    });
  });
  document.querySelectorAll('[data-settings-jump]').forEach(button=>button.addEventListener('click',()=>{
    const id=button.dataset.settingsJump;
    if(tabs.some(tab=>tab.dataset.settingsPane===id))selectPane(id,true);
  }));
  window.openSettingsSection=id=>{
    if(id==='settingsDocsPane')id='settingsDataPane';
    if(window.desktopAPI?.openSettingsWindow && document.body.dataset.window!=='settings'){
      window.desktopAPI.openSettingsWindow(id);
      return;
    }
    q('nav [data-view="settings"]')?.click();
    const pane=q('#'+id)?.closest('.settings-pane');
    selectPane(pane?.id||id);
  };
  window.openSoftwareSettings=section=>window.openSettingsSection(({data:'settingsDataPane',import:'settingsImportPane',rules:'settingsRulesPane',accounts:'settingsAccountsPane',maintenance:'settingsMaintenancePane',docs:'settingsDataPane'})[section]||section||'settingsDataPane');
  window.desktopAPI?.onSettingsSection?.(section=>selectPane(section==='settingsDocsPane'?'settingsDataPane':section));
  document.addEventListener('click',event=>{
    if(event.target.closest('[data-open-dedup]'))selectPane('settingsMaintenancePane');
  },true);

  const source=q('#serverRoot'),saveSource=q('#saveSourceDirectory');
  const sourceStatus=q('#sourceDirectorySaveStatus');
  const refresh=q('#refreshDataSource'),validate=q('#validateDataSource'),dbStatus=q('#dataSourceStatus'),copyPath=q('#copyDataSourcePath');
  let baseline=null,saving=false,loading=false,validating=false,formRevision=0,reloadPending=false;
  function drainReload(){
    if(reloadPending&&!loading&&!saving&&!validating){reloadPending=false;load()}
  }
  function setStatus(element,text,state='neutral'){element.textContent=text;element.dataset.state=state}
  function readProfile(){return {...baseline,source_directory:source.value.trim()}}
  function profileChanged(){return !!baseline&&JSON.stringify(readProfile())!==JSON.stringify(baseline)}
  function synchronizeActions(){
    const dirty=profileChanged();
    saveSource.disabled=saving||!baseline||!dirty;
    refresh.disabled=loading||saving||validating;validate.disabled=loading||validating||saving;
    if(saving)return;
    if(baseline&&source.value.trim()!==baseline.source_directory&&!['loading','error'].includes(sourceStatus.dataset.state))setStatus(sourceStatus,'来源路径尚未保存','dirty');
  }
  function profileValue(value){
    return {server_url:String(value?.server_url||''),timeout_seconds:Number(value?.timeout_seconds??10),source_directory:String(value?.source_directory||'')};
  }
  function renderActive(active){
    const activePath=String(active?.path||'');
    q('#dataSourcePath').textContent=activePath||'未返回数据库位置';
    q('#dataSourcePath').title=activePath;
    if(copyPath){
      copyPath.disabled=!activePath;
      copyPath.dataset.path=activePath;
      copyPath.textContent='复制路径';
    }
    const size=Number(active?.size_bytes);
    q('#dataSourceSize').textContent=Number.isFinite(size)?size<1048576?`${(size/1024).toFixed(1)} KB`:`${(size/1048576).toFixed(2)} MB`:'/';
    const local=active?.mode==='local'&&active?.engine==='sqlite';
    setStatus(q('#dataSourceMode'),local?(active.exists?'本地使用中':'文件不可用'):'状态异常',local&&active.exists?'success':'error');
    if(!local)setStatus(dbStatus,'当前存储状态异常，请检查本地服务。','error');
    else setStatus(dbStatus,active.exists?'所有业务数据保存在此本地数据库。':'未找到数据库文件，请检查实际路径。',active.exists?'neutral':'error');
  }
  async function request(url,options){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
    try{
      const response=await fetch(url,{...options,signal:controller.signal,headers:{'Content-Type':'application/json',...(options?.headers||{})}});
      let data;try{data=await response.json()}catch{throw new Error('本地服务未返回有效数据，请刷新重试')}
      if(!response.ok)throw new Error(data.error||data.message||'设置操作失败');
      return data;
    }catch(error){
      if(error.name==='AbortError')throw new Error('本地服务响应超时，请稍后重试');
      throw error;
    }finally{clearTimeout(timer)}
  }
  async function load(){
    if(loading||saving||validating){reloadPending=true;return}
    const revision=formRevision;loading=true;synchronizeActions();
    setStatus(dbStatus,'正在读取本地数据库状态…','loading');
    try{
      const data=await request('/api/settings/data-source');
      renderActive(data.active);
      window.dispatchEvent(new CustomEvent('data-source-settings-loaded',{detail:data}));
      if(!baseline||revision===formRevision&&!profileChanged()){
        baseline=profileValue(data.profile);if(revision===formRevision)source.value=baseline.source_directory;
        setStatus(sourceStatus,baseline.source_directory?'已保存文件来源。':'文件来源与数据库存储相互独立');
        if(data.warnings?.length)setStatus(sourceStatus,data.warnings.join(' '),'error');
      }
    }catch(error){
      setStatus(dbStatus,`读取失败：${error.message}`,'error');
      setStatus(q('#dataSourceMode'),'状态不可用','error');
      if(!baseline)setStatus(sourceStatus,'配置未读取，仍可临时选择文件夹扫描。','error');
    }finally{loading=false;synchronizeActions();drainReload()}
  }
  function edited(){
    formRevision++;
    if(baseline)setStatus(sourceStatus,profileChanged()?'来源路径尚未保存':'文件来源已保存。',profileChanged()?'dirty':'neutral');
    synchronizeActions();
  }
  source.addEventListener('input',edited);source.addEventListener('change',edited);
  async function persist(){
    if(!baseline||saving)return;
    const sourceDirectory=source.value.trim();
    const revision=formRevision;saving=true;synchronizeActions();
    const button=saveSource,label=button.textContent;button.textContent='保存中…';button.setAttribute('aria-busy','true');
    setStatus(sourceStatus,'正在保存到本地配置…','loading');
    try{
      const current=await request('/api/settings/data-source');
      const payload={...profileValue(current.profile),source_directory:sourceDirectory};
      const data=await request('/api/settings/data-source',{method:'POST',body:JSON.stringify({profile:payload})});
      baseline=profileValue(data.profile);
      if(formRevision===revision)source.value=baseline.source_directory;
      renderActive(data.active);
      setStatus(sourceStatus,'文件来源已保存。','success');
      window.dispatchEvent(new CustomEvent('data-source-settings-changed',{detail:data}));
    }catch(error){setStatus(sourceStatus,`保存失败：${error.message}`,'error')}
    finally{saving=false;button.textContent=label;button.removeAttribute('aria-busy');synchronizeActions();drainReload()}
  }
  saveSource.onclick=persist;
  refresh.onclick=load;
  validate.onclick=async()=>{
    if(loading||validating||saving)return;
    validating=true;synchronizeActions();validate.setAttribute('aria-busy','true');validate.textContent='正在校验…';setStatus(dbStatus,'正在执行本地数据库完整性校验…','loading');
    try{
      const data=await request('/api/settings/data-source/validate',{method:'POST',body:JSON.stringify({target:'local'})});
      renderActive(data.active);setStatus(dbStatus,data.message||(data.ok?'本地数据库校验通过。':'本地数据库校验未通过。'),data.ok?'success':'error');
      setStatus(q('#dataSourceMode'),data.ok?'本地使用中 · 校验通过':'本地校验失败',data.ok?'success':'error');
    }catch(error){setStatus(dbStatus,`校验失败：${error.message}`,'error')}
    finally{validating=false;validate.textContent='校验数据库';validate.removeAttribute('aria-busy');synchronizeActions();drainReload()}
  };
  copyPath?.addEventListener('click',async()=>{
    const value=copyPath.dataset.path||q('#dataSourcePath')?.textContent||'';
    if(!value||value==='未返回数据库位置')return;
    try{
      await navigator.clipboard.writeText(value);
      copyPath.textContent='已复制';
      setStatus(dbStatus,'数据库路径已复制到剪贴板。','success');
      setTimeout(()=>{if(copyPath.isConnected)copyPath.textContent='复制路径'},1500);
    }catch{
      setStatus(dbStatus,'无法访问剪贴板，请直接选中文件位置复制。','error');
    }
  });
  window.addEventListener('database-cleared',()=>{load()});
  window.addEventListener('data-source-settings-changed',event=>{if(event.detail?.settingsRemote)load()});
  const initialPane=new URLSearchParams(location.search).get('section');
  selectPane(initialPane&&tabs.some(tab=>tab.dataset.settingsPane===initialPane)?initialPane:'settingsDataPane');
  synchronizeActions();load();
})();

if(document.body.dataset.window==='settings')(function installPreferenceSettings(){
  const q=selector=>document.querySelector(selector);
  const defaults={
    theme:'light',
    density:'standard',
    motion:'full',
    startup:'workspace',
    remember:true,
    shift:'1',
    importPolicy:'manual',
    notificationDuration:'3000',
    notificationSound:true,
  };
  const keys={
    theme:'thimbleAppearance',
    density:'thimbleUiDensity',
    motion:'thimbleReduceMotion',
    startup:'thimbleStartupView',
    remember:'thimbleRememberView',
    lastView:'thimbleLastView',
    shift:'thimble-state-default-shift-direction',
    importPolicy:'thimbleReportPolicy',
    notificationDuration:'thimbleNotificationDuration',
    notificationSound:'thimbleNotificationSound',
  };
  const valid=(value,allowed,fallback)=>allowed.includes(value)?value:fallback;
  const read=()=>({
    theme:valid(localStorage.getItem(keys.theme),['light','dark'],defaults.theme),
    density:valid(localStorage.getItem(keys.density),['standard','compact'],defaults.density),
    motion:localStorage.getItem(keys.motion)==='true'?'reduced':defaults.motion,
    startup:valid(localStorage.getItem(keys.startup),['workspace','threeD','analytics','reports','states'],defaults.startup),
    remember:localStorage.getItem(keys.remember)!=='false',
    shift:valid(localStorage.getItem(keys.shift),['1','-1','pending'],defaults.shift),
    importPolicy:valid(localStorage.getItem(keys.importPolicy),['manual','auto_latest'],defaults.importPolicy),
    notificationDuration:valid(localStorage.getItem(keys.notificationDuration),['3000','5000','0'],defaults.notificationDuration),
    notificationSound:localStorage.getItem(keys.notificationSound)!=='false',
  });
  const write=(name,value)=>{
    const key=keys[name];
    if(name==='motion')localStorage.setItem(key,value==='reduced'?'true':'false');
    else if(name==='remember')localStorage.setItem(key,String(Boolean(value)));
    else if(name==='notificationSound')localStorage.setItem(key,String(Boolean(value)));
    else localStorage.setItem(key,String(value));
  };
  const applyBody=preferences=>{
    if(window.appAppearance)window.appAppearance.setTheme(preferences.theme,{persist:false});
    else document.documentElement.dataset.theme=preferences.theme;
    document.body.dataset.uiDensity=preferences.density;
    document.body.dataset.reduceMotion=preferences.motion==='reduced'?'true':'false';
  };
  const syncReportPolicy=value=>{
    const reportPolicy=q('#reportPolicy');
    if(reportPolicy&&reportPolicy.value!==value){
      reportPolicy.value=value;
      reportPolicy.dispatchEvent(new Event('change',{bubbles:true}));
    }
  };
  const render=preferences=>{
    const fields={
      '#settingsDensity':preferences.density,
      '#settingsMotion':preferences.motion,
      '#settingsStartupView':preferences.remember?'last':preferences.startup,
      '#settingsShiftDirection':preferences.shift,
      '#settingsImportPolicy':preferences.importPolicy,
      '#settingsNotificationDuration':preferences.notificationDuration,
    };
    Object.entries(fields).forEach(([selector,value])=>{const element=q(selector);if(element)element.value=value});
    const remember=q('#settingsRememberView');if(remember)remember.checked=preferences.remember;
    const startupHint=q('#settingsStartupHint');
    if(startupHint)startupHint.textContent=preferences.remember?'下次启动恢复最后使用的主工作区':'下次启动打开所选工作区';
    const sound=q('#settingsNotificationSound');if(sound)sound.checked=preferences.notificationSound;
    document.querySelectorAll('[data-theme-choice]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.themeChoice===preferences.theme)));
    applyBody(preferences);
  };
  function mount(){
    const pane=q('#settingsPreferencesPane');if(!pane||pane.dataset.bound==='true')return;
    pane.dataset.bound='true';
    const saved=q('#preferencesSaved'),status=q('#preferencesStatus');
    let timer=0;
    const flash=(message='已保存到本机')=>{
      if(status){status.textContent=message;status.dataset.state='success'}
      if(saved){saved.textContent='已保存';saved.dataset.state='success';clearTimeout(timer);timer=setTimeout(()=>{saved.textContent='自动保存';saved.dataset.state='';},1800)}
    };
    const persist=async(name,value,message)=>{
      if(name==='shift'){
        try{await window.statePreferences.set(value)}
        catch(error){render(read());return}
      }else write(name,value);
      const next=read();applyBody(next);
      if(name==='theme')window.appAppearance?.setTheme(next.theme);
      if(name==='importPolicy')syncReportPolicy(next.importPolicy);
      flash(message);
      window.dispatchEvent(new CustomEvent('software-preferences-changed',{detail:next}));
    };
    const bind=(selector,name,transform,message)=>{
      const element=q(selector);if(!element)return;
      element.addEventListener('change',()=>persist(name,transform(element),message));
    };
    bind('#settingsDensity','density',element=>element.value,'显示密度已更新');
    pane.querySelectorAll('[data-theme-choice]').forEach(button=>button.addEventListener('click',()=>{
      persist('theme',button.dataset.themeChoice,button.dataset.themeChoice==='dark'?'已切换夜间模式':'已切换日间模式');
      render(read());
    }));
    bind('#settingsMotion','motion',element=>element.value,'交互动画设置已更新');
    q('#settingsStartupView')?.addEventListener('change',event=>{
      const value=event.currentTarget.value;
      if(value!=='last')write('startup',value);
      persist('remember',value==='last',value==='last'?'下次启动恢复上次工作区':'下次启动打开所选工作区');
      render(read());
    });
    bind('#settingsShiftDirection','shift',element=>element.value,'移位方向默认值已更新');
    bind('#settingsImportPolicy','importPolicy',element=>element.value,'RPT 选择策略已更新');
    bind('#settingsNotificationDuration','notificationDuration',element=>element.value,'通知自动隐藏时间已更新');
    q('#settingsNotificationSound')?.addEventListener('change',event=>persist('notificationSound',event.currentTarget.checked,event.currentTarget.checked?'已开启通知提示音':'已关闭通知提示音'));
    const remember=q('#settingsRememberView');
    remember?.addEventListener('change',()=>{
      persist('remember',remember.checked,remember.checked?'已开启记住上次工作区':'已关闭记住上次工作区');
      render(read());
    });
    q('#resetPreferences')?.addEventListener('click',async()=>{
      const confirmed=window.appFeedback?.confirm?await window.appFeedback.confirm('恢复本页默认设置？数据库、检测数据和报告文件不会改变。',{title:'恢复设置默认值',confirmLabel:'恢复默认'}):true;
      if(!confirmed)return;
      if(window.statePreferences.writable){
        try{await window.statePreferences.set(defaults.shift)}
        catch(error){return}
      }
      Object.entries(defaults).filter(([name])=>name!=='shift').forEach(([name,value])=>write(name,value));
      localStorage.removeItem(keys.lastView);
      const next=read();render(next);syncReportPolicy(next.importPolicy);flash('已恢复本页默认设置');
      window.dispatchEvent(new CustomEvent('software-preferences-changed',{detail:next}));
    });
    render(read());
  }
  mount();
  window.addEventListener('settings-pane-changed',mount);
  window.addEventListener('state-direction-changed',()=>render(read()));
  window.addEventListener('report-policy-changed',()=>render(read()));
  window.addEventListener('appearance-theme-changed',event=>{
    document.querySelectorAll('[data-theme-choice]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.themeChoice===event.detail.theme)));
  });
  window.addEventListener('storage',event=>{
    if(Object.values(keys).includes(event.key))render(read());
  });
})();
