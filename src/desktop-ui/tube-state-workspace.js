(()=>{
  const root=document.querySelector('#states'),form=document.querySelector('#stateForm');
  if(!root||!form)return;
  const q=id=>document.getElementById(id);
  const names={D:'大亚湾',L:'岭澳',H:'红沿河',N:'宁德',F:'防城港',Y:'阳江',T:'台山',C:'苍南',P:'惠州',LF:'陆丰'};
  const labels={normal:'正常',plugged:'堵管',shifted:'移位',replaced:'换管'};
  const statePaint=window.thimbleStateColors||{
    labels,
    uniqueEvents:events=>['plugged','shifted','replaced'].filter(event=>Array.isArray(events)&&events.includes(event)),
    background:events=>events.length===1&&events[0]==='normal'?'#e5f3eb':'#f4f7f9',
    edge:events=>events.length===1&&events[0]==='normal'?'#4b9b78':'#aeb9bf',
    ink:events=>events.length===1&&events[0]==='normal'?'#286b56':'#526575',
    label:events=>events.length?events.map(event=>labels[event]).join(' · '):'未维护'
  };
  const rowEvents=row=>{
    if(Array.isArray(row?.events)&&row.events.length)return row.events;
    if(row?.state&&row.state!=='normal')return [row.state];
    return row?.state==='normal'?['normal']:[];
  };
  const manualScopeKey='thimble-state-manual-scopes';
  const shiftDirectionKey='thimble-state-default-shift-direction';
  const readShiftDirection=()=>{
    const value=localStorage.getItem(shiftDirectionKey);
    return value==='-1'||value==='pending'||value==='1'?value:'1';
  };
  const shiftDirectionLabel=value=>value==='-1'?'负向（−）':value==='pending'?'留待核对':'正向（+）';
  const signedDetectedOffset=(row,direction)=>{
    if(!row||row.unsigned_offset_mm==null||direction==='pending'||!direction)return '';
    return String(Number(direction)*Number(row.unsigned_offset_mm));
  };
  const summaryOffset=record=>{
    if(!rowEvents(record).includes('shifted'))return '/';
    if(record.offset_confirmed===0)return record.unsigned_offset_mm!=null?
      `${record.unsigned_offset_mm}（方向待核对）`:'距离待核对';
    if(record.offset_mm==null)return record.unsigned_offset_mm!=null?
      `${record.unsigned_offset_mm}（方向待核对）`:'距离未注明';
    return `${record.offset_mm>0?'+':''}${record.offset_mm}`;
  };
  let manualScopes=[],legacyScopes=[];
  try{legacyScopes=JSON.parse(localStorage.getItem(manualScopeKey)||'[]').filter(row=>row?.site&&row?.unit_id&&row?.outage)}catch{legacyScopes=[]}
  let records=[],pendingRecords=[];
  const reviewPending=document.createElement('button');reviewPending.type='button';reviewPending.id='stateReviewPending';reviewPending.className='state-review-entry';reviewPending.hidden=true;reviewPending.setAttribute('aria-label','查看待核对的导入状态');
  reviewPending.innerHTML='<span class="state-review-mark" aria-hidden="true">!</span><span>待核对</span><b data-review-count>0</b>';
  const scopeStatus=document.createElement('span');scopeStatus.id='stateScopeStatus';scopeStatus.setAttribute('role','status');
  const scope=document.createElement('div');scope.className='state-scope';
  scope.innerHTML='<label>基地<select id="stateSite" aria-label="状态维护基地"></select></label>';
  const manageScopes=document.createElement('button');manageScopes.type='button';manageScopes.id='stateManageScopes';manageScopes.className='state-scope-manage';manageScopes.textContent='新增大修';manageScopes.title='手动新增没有检测数据的大修范围';manageScopes.setAttribute('aria-label',manageScopes.title);
  for(const id of ['stateUnit','stateOutage'])q(id).setAttribute('form','stateForm');
  scope.append(q('stateUnit').closest('label'),q('stateOutage').closest('label'),manageScopes);
  const layout=root.querySelector('.state-maintenance-layout'),editor=root.querySelector('.state-panel'),list=root.querySelector('.state-table-panel');
  root.prepend(scope);
  const actions=document.createElement('div');actions.className='state-bulk-actions';
  actions.innerHTML='<div class="state-bulk-buttons"><section class="state-action-group state-action-primary" aria-label="维护表数据导入与导出"><h3>维护表文件</h3><div class="state-action-row state-file-actions"><div class="state-import-group"><label for="stateImport">导入维护表</label><button type="button" id="stateImport" title="选择 Excel、CSV 或 Word 维护资料；确认预览后才写入">选择文件</button><small>预览确认后才写入</small></div><div class="state-export-group"><label for="stateExportFormat">导出维护表</label><div><select id="stateExportFormat" aria-label="维护表格导出格式"><option value="xlsx">Excel 明细及历次汇总</option><option value="summary">Excel 历次统计</option><option value="docx">Word 维护统计</option></select><button type="button" id="stateExport" disabled title="选择完整范围后导出维护表">导出</button></div><small>按当前基地、机组和大修生成</small></div></div><span id="stateExportResult" class="state-export-result" role="status"></span></section><section class="state-action-group state-action-secondary" aria-label="批量维护"><h3>批量维护</h3><div class="state-action-row"><button type="button" id="stateAllNormal" disabled title="预览未维护管；已有记录、历史堵管和待核对状态会跳过">补齐正常</button><label class="state-default-direction">移位<select id="stateDefaultShiftDirection" aria-label="无符号移位默认方向"><option value="1">默认正向（+）</option><option value="-1">默认负向（−）</option><option value="pending">方向待核对</option></select></label></div></section><span id="stateBulkScope" class="state-bulk-scope" aria-hidden="true"></span><input type="file" id="stateImportFile" accept=".xlsx,.xls,.xlsm,.csv,.docx" hidden></div><span id="stateBulkHint" class="state-bulk-hint" role="status"></span>';
  const controls=document.createElement('div');controls.className='state-controls';
  scope.before(controls);controls.append(scope,actions);scope.append(scopeStatus);
  const summaryHeading=document.createElement('div');summaryHeading.className='state-summary-heading';
  summaryHeading.innerHTML='<div><b>状态概览</b><span>本次维护 · 50 根</span></div><span id="stateSummaryMeta">请选择完整范围</span>';
  summaryHeading.append(reviewPending);
  controls.append(summaryHeading);
  const summaryStrip=document.createElement('div');summaryStrip.className='state-summary-strip';summaryStrip.setAttribute('aria-label','当前大修状态统计');
  summaryStrip.innerHTML=[
    ['maintained','已维护'],['missing','未维护'],['normal','正常'],
    ['plugged','堵管'],['shifted','移位'],['replaced','换管'],
  ].map(([key,label])=>`<button type="button" class="state-summary-item" data-tone="${key}" title="查看${label}明细"><i class="state-summary-icon state-summary-icon-${key}" aria-hidden="true"></i><div class="state-summary-copy"><span>${label}</span><small data-summary-rate="${key}">—</small></div><b data-summary-value="${key}">—</b></button>`).join('');
  controls.append(summaryStrip);
  summaryStrip.addEventListener('click',event=>{
    const button=event.target.closest('.state-summary-item');
    if(!button||button.disabled)return;
    const {outage,unit_id}=transferScope(),key=button.dataset.tone;
    const current=new Map(records.filter(row=>row.outage===outage&&Number(row.unit_id)===unit_id).map(row=>[Number(row.thimble_id),row]));
    const rows=Array.from({length:50},(_,index)=>({tube:index+1,record:current.get(index+1)})).filter(({record})=>
      key==='maintained'?Boolean(record):key==='missing'?!record:key==='normal'?
        Boolean(record&&(rowEvents(record).length===0||rowEvents(record).includes('normal')||record.state==='normal')):
        Boolean(record&&rowEvents(record).includes(key)));
    const escape=displayTableCell,dialog=document.createElement('dialog');
    dialog.className='vw-record-dialog state-summary-dialog';
    dialog.setAttribute('aria-label',`${button.querySelector('.state-summary-copy span').textContent}明细`);
    dialog.innerHTML=`<form method="dialog" class="vw-record-head"><h2>${escape(outage)} · ${escape(button.querySelector('.state-summary-copy span').textContent)} · ${rows.length} 根</h2><button value="cancel" type="submit" aria-label="关闭">关闭</button></form><p class="vw-record-basis">本次维护记录；历史有效状态见管板。</p><div class="vw-record-table"><table><thead><tr><th>管号</th><th>本次状态</th><th>移位 (mm)</th><th>原始备注</th><th>来源</th><th></th></tr></thead><tbody>${rows.map(({tube,record})=>`<tr><td>#${tube}</td><td>${escape(record?(record.event_label||statePaint.label(rowEvents(record))):'未维护')}</td><td>${escape(summaryOffset(record))}</td><td class="source-note">${escape(record?.note||'/')}</td><td class="source-note">${escape(record?.source||'/')}</td><td><button type="button" data-summary-tube="${tube}">查看管号</button></td></tr>`).join('')||'<tr><td colspan="6">本次没有此类记录</td></tr>'}</tbody></table></div>`;
    document.body.append(dialog);
    dialog.querySelectorAll('[data-summary-tube]').forEach(link=>link.onclick=()=>{
      const tube=Number(link.dataset.summaryTube);
      dialog.close();
      window.stateMaintenance.edit({...current.get(tube),outage,unit_id,thimble_id:tube});
      editor.scrollIntoView({block:'nearest'});
      q('stateThimble').focus();
    });
    dialog.addEventListener('close',()=>{dialog.remove();button.focus()},{once:true});
    dialog.showModal();
  });
  const stateGuide=document.createElement('details');stateGuide.className='state-meaning-guide';
  stateGuide.innerHTML='<summary>状态口径与维护规则</summary><div><div class="state-meaning-lines"><p><b>正常</b>：有明确维护依据；无记录不视为正常，也不解除历史堵管。</p><p><b>堵管</b>：同基地、同机组持续有效，明确换管后结束旧管状态。</p><p><b>移位</b>：明确正负号优先；无符号距离采用默认方向或留待核对，距离不明时不换算位置。</p><p><b>换管</b>：进入新管代次；同次复合处理需确认换管前后顺序。</p></div><p>批量处理须预览确认；重复资料、范围不明和历史生效时间不明的记录保留待核对。奇偶机组的管号映射可能不同，按当前机组核对。</p></div>';
  controls.append(stateGuide);
  const importStatus=document.createElement('div');importStatus.id='stateImportStatus';importStatus.className='state-import-status';importStatus.hidden=true;
  const importSpinner=document.createElement('span');importSpinner.className='state-import-spinner';importSpinner.setAttribute('aria-hidden','true');
  const importTrack=document.createElement('span');importTrack.className='state-import-track';importTrack.setAttribute('aria-hidden','true');const importFill=document.createElement('i');importTrack.append(importFill);
  const importMessage=document.createElement('span');importMessage.className='state-import-message';importMessage.setAttribute('role','status');importMessage.setAttribute('aria-live','polite');
  const importEta=document.createElement('span');importEta.className='state-import-eta';
  const retryImport=document.createElement('button');retryImport.type='button';retryImport.textContent='重新识别';retryImport.hidden=true;
  importStatus.append(importSpinner,importMessage,importTrack,importEta,retryImport);controls.after(importStatus);
  const defaultDirectionSelect=q('stateDefaultShiftDirection');
  if(defaultDirectionSelect){
    defaultDirectionSelect.value=readShiftDirection();
    defaultDirectionSelect.title='与设置中的无符号移位默认方向同步；明确正负号优先，已确认的历史记录保持原值';
    defaultDirectionSelect.onchange=async()=>{
      try{await window.statePreferences.set(defaultDirectionSelect.value)}
      catch(error){defaultDirectionSelect.value=readShiftDirection();return}
      syncDefaultOffsetAction?.();
      window.toast(`已记住无符号移位默认方向：${shiftDirectionLabel(defaultDirectionSelect.value)}`);
    };
  }
  let importStartedAt=0,importTimer=0,importPercent=null,latestImportMessage='',importTiming='';
  const duration=seconds=>{const n=Math.ceil(seconds);return n<60?`${n}秒`:`${Math.floor(n/60)}分${n%60}秒`};
  const importFeedback=(message,kind='progress',percent=null,timing='')=>{
    latestImportMessage=message;
    importStatus.hidden=false;importStatus.dataset.kind=kind;importMessage.textContent=message;retryImport.hidden=kind!=='error';
    importSpinner.hidden=kind!=='progress';importTrack.hidden=kind!=='progress';importTrack.classList.toggle('indeterminate',kind==='progress'&&!Number.isFinite(percent));
    importTiming=timing;
    if(kind==='progress'&&!importStartedAt){importStartedAt=Date.now();importTimer=window.setInterval(()=>importFeedback(latestImportMessage,'progress',importPercent,importTiming),1000)}
    importPercent=Number.isFinite(percent)?Math.max(0,Math.min(100,percent)):null;
    importFill.style.width=importPercent===null?'35%':`${importPercent}%`;importStatus.setAttribute('aria-busy',String(kind==='progress'));
    importEta.textContent=kind==='progress'?(timing||`已用 ${duration((Date.now()-importStartedAt)/1000)}${importPercent&&importPercent>0?` · 预计剩余 ${duration((Date.now()-importStartedAt)/1000*(100-importPercent)/importPercent)}`:' · 正在估算剩余时间'}`):'';
    if(kind!=='progress'&&importTimer){clearInterval(importTimer);importTimer=0;importStartedAt=0;importPercent=null}
  };
  const showTaskProgress=task=>{
    const details=window.importProgressDetails(task);
    importFeedback(`${details.label} · ${details.meta}${Number.isFinite(details.percent)?` · ${Math.floor(details.percent)}%`:''}`,'progress',details.percent,details.timing);
  };
  let transferBusy=false;
  const transferScope=()=>{const outage=q('stateOutage').value,unit_id=Number(q('stateUnit').value),site=q('stateSite').value;if(!site||!outage||!unit_id)throw Error('请先选择完整维护范围：基地、机组和大修');return {site,outage,unit_id}};
  const openScopeManager=()=>{
    if(transferBusy)return;
    const dialog=document.createElement('dialog');dialog.className='state-scope-dialog';dialog.setAttribute('aria-label','新增大修范围');
    dialog.innerHTML='<form method="dialog"><div class="state-preview-head"><h2>新增大修范围</h2><p>选择基地和机组，填写大修编号后即可逐管录入；已有历史大修可在上方直接选择。</p></div><div class="state-scope-form"><label>基地<select id="manualScopeSite"></select></label><label>机组<select id="manualScopeUnit"></select></label><label>大修编号<input id="manualScopeOutage" maxlength="5" placeholder="如 F103" autocomplete="off"></label></div><p class="state-scope-format">编号规则：基地字母 + 机组号 + 两位序号，例如 F103、LF198。范围保存在当前数据库中，不会创建检测记录。</p><div class="state-legacy-scopes" hidden><span></span><button type="button">导入到当前数据库</button></div><p class="state-scope-error" role="alert"></p><div class="dialog-actions"><button value="cancel">关闭</button><button type="button" id="manualScopeAdd" class="primary">添加并使用</button></div></form>';
    const siteSelect=dialog.querySelector('#manualScopeSite'),unitSelect=dialog.querySelector('#manualScopeUnit'),outageInput=dialog.querySelector('#manualScopeOutage'),error=dialog.querySelector('.state-scope-error');
    const allSites=unique([...Object.keys(names),...scopes().map(row=>row.site).filter(Boolean)]);
    fill(siteSelect,allSites,'选择基地');for(const option of siteSelect.options)if(option.value)option.textContent=`${names[option.value]||option.value}（${option.value}）`;
    fill(unitSelect,Array.from({length:9},(_,i)=>i+1),'选择机组');
    siteSelect.value=q('stateSite').value||'';unitSelect.value=q('stateUnit').value||'';
    const legacy=dialog.querySelector('.state-legacy-scopes');
    const add=dialog.querySelector('#manualScopeAdd'),close=dialog.querySelector('[value=cancel]');
    let scopeBusy=false,savedScope=null;
    const setScopeBusy=busy=>{
      scopeBusy=busy;add.disabled=busy;close.disabled=busy;
      for(const input of [siteSelect,unitSelect,outageInput])input.disabled=busy||!!savedScope;
      legacy.querySelector('button').disabled=busy;
      dialog.setAttribute('aria-busy',String(busy));
    };
    dialog.addEventListener('cancel',event=>{if(scopeBusy)event.preventDefault()});
    dialog.querySelector('form').addEventListener('submit',event=>{if(scopeBusy)event.preventDefault()});
    outageInput.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();add.click()}});
    if(legacyScopes.length){
      legacy.hidden=false;legacy.querySelector('span').textContent=`发现 ${legacyScopes.length} 条旧版本本机范围，请确认是否导入当前数据库。`;
      legacy.querySelector('button').onclick=async event=>{
        if(scopeBusy)return;
        setScopeBusy(true);error.textContent='';
        try{
          for(const row of legacyScopes)await api('/api/states/scopes',{method:'POST',body:JSON.stringify(row)});
          localStorage.removeItem(manualScopeKey);legacyScopes=[];legacy.hidden=true;
          const refreshed=await loadStates();
          if(!refreshed){error.textContent='旧版本大修范围已保存，但列表刷新失败。无需重复导入，请关闭窗口后重新加载维护列表。';return}
          window.toast('旧版本大修范围已导入当前数据库');
        }catch(exception){error.textContent=`导入未完成：${exception.message}`}
        finally{setScopeBusy(false)}
      };
    }
    add.onclick=async()=>{
      if(scopeBusy)return;
      const site=siteSelect.value,unit_id=Number(unitSelect.value),outage=outageInput.value.trim().toUpperCase();
      if(!site||!unit_id){error.textContent='请先选择基地和机组';return}
      if(!/^[A-Z]{1,2}[1-9]\d{2}$/.test(outage)){error.textContent='大修编号格式应为 F103、LF198 等';return}
      const match=outage.match(/^([A-Z]{1,2})([1-9])\d{2}$/);
      if(match[1]!==site||Number(match[2])!==unit_id){error.textContent='大修编号中的基地或机组与当前选择不一致';return}
      setScopeBusy(true);error.textContent='';
      try{
        if(!savedScope)savedScope=await api('/api/states/scopes',{method:'POST',body:JSON.stringify({site,unit_id,outage})});
        const refreshed=await loadStates();
        if(!refreshed){
          error.textContent=`${outage} 已保存，但列表刷新失败。无需重复添加，请重新加载后使用。`;
          add.textContent='重新加载并使用';return;
        }
        q('stateSite').value=site;sync('site');q('stateUnit').value=String(unit_id);sync();q('stateOutage').value=outage;resetDetails();
        window.toast(`${savedScope.created?'已添加':'已选择'} ${outage}，现在可以逐管录入维护状态`);dialog.close('added');
      }catch(exception){error.textContent=savedScope?`${outage} 已保存，加载未完成：${exception.message}。无需重复添加。`:exception.message;if(savedScope)add.textContent='重新加载并使用'}
      finally{setScopeBusy(false)}
    };
    document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  };
  let disabledBeforeBusy=null;
  const operationBusy=busy=>{
    root.setAttribute('aria-busy',String(busy));root.classList.toggle('state-operation-busy',busy);
    if(busy&&!disabledBeforeBusy){
      disabledBeforeBusy=new Map();
      for(const control of root.querySelectorAll('select,input,textarea,button')){
        if(control.closest('dialog'))continue;disabledBeforeBusy.set(control,control.disabled);control.disabled=true;
      }
    }else if(!busy&&disabledBeforeBusy){
      for(const [control,disabled] of disabledBeforeBusy)if(control.isConnected)control.disabled=disabled;
      disabledBeforeBusy=null;
    }
  };
  const stateScopeSummary=()=>{
    const site=q('stateSite').value,unit=q('stateUnit').value,outage=q('stateOutage').value;
    const selected=records.filter(row=>row.outage===outage&&String(row.unit_id)===String(unit));
    const maintained=selected.length,missing=Math.max(0,50-maintained);
    const pendingTotal=pendingRecords.length+records.filter(row=>row.needs_review).length;
    const counts={maintained,missing,normal:0,plugged:0,shifted:0,replaced:0};
    for(const row of selected){
      const events=Array.isArray(row.events)&&row.events.length?row.events:[row.state];
      if(events.includes('plugged'))counts.plugged++;
      if(events.includes('shifted'))counts.shifted++;
      if(events.includes('replaced'))counts.replaced++;
      if(events.length===0||events.includes('normal')||row.state==='normal')counts.normal++;
    }
    for(const [key,value] of Object.entries(counts)){
      const target=summaryStrip.querySelector(`[data-summary-value="${key}"]`);
      if(target)target.textContent=site&&unit&&outage?String(value):'—';
      const rate=summaryStrip.querySelector(`[data-summary-rate="${key}"]`);
      if(rate)rate.textContent=site&&unit&&outage?`${(Number(value)/50*100).toFixed(0)}%`:'—';
      const button=target?.closest('button');
      if(button){
        const label=button.querySelector('.state-summary-copy span').textContent,valid=Boolean(site&&unit&&outage);
        button.disabled=transferBusy||!valid;
        button.title=valid?`查看${label}明细`:'请先选择基地、机组和大修';
        button.setAttribute('aria-label',valid?`${label} ${value} 根，查看明细`:`${label}，请先选择维护范围`);
      }
    }
    summaryStrip.classList.toggle('is-empty',!site||!unit||!outage);
    const text=site&&unit&&outage?`${names[site]||site} · ${unit}号机组 · ${outage}`:'尚未选择基地、机组和大修';
    const bulkScope=q('stateBulkScope');if(bulkScope)bulkScope.textContent=text;
    q('stateSummaryMeta').textContent=site&&unit&&outage?`${outage} · 已维护 ${maintained}/50`:'请选择完整范围';
    q('stateBulkHint').textContent='';
    const valid=Boolean(site&&unit&&outage);
    q('stateAllNormal').textContent=valid?(missing?`补齐正常（${missing}）`:'本次已维护完成'):'补齐正常';
    q('stateAllNormal').dataset.complete=String(valid&&!missing);
    for(const id of ['stateAllNormal','stateExport']){const button=q(id);if(button){button.dataset.scopeDisabled=String(!valid);button.disabled=transferBusy;button.title=valid?(id==='stateAllNormal'?`先预览再确认；${missing?`预计检查 ${missing} 根未维护管，历史堵管和待核对状态会列出并跳过`:'本次已维护完成，可查看维护记录'}`:`导出当前 ${text}；格式在左侧选择`):'第一步：先选择基地、机组和大修'}}
    q('stateExportFormat').disabled=transferBusy;
    reviewPending.querySelector('[data-review-count]').textContent=String(pendingTotal);
    reviewPending.hidden=pendingTotal===0;
    reviewPending.setAttribute('aria-label',`查看导入待核对清单，共 ${pendingTotal} 条`);
    reviewPending.title=`查看 ${pendingTotal} 条导入待核对状态`;
    q('stateScopeStatus').textContent=valid?`${text} · 已维护 ${maintained}/50 根`:'请选择维护范围';
  };
  async function transfer(button,task){if(transferBusy)return;transferBusy=true;operationBusy(true);try{await task()}catch(error){window.toast(error.message,{type:'error'})}finally{transferBusy=false;operationBusy(false);render()}}
  async function applyRows(rows,only_unmaintained=false,reveal=false,onProgress=null,extra={}){
    const payload={rows,confirmed:true,only_unmaintained,...extra};
    const result=onProgress?await window.runImportRequest('/api/states/batch',payload,onProgress):await api('/api/states/batch',{method:'POST',body:JSON.stringify(payload)});
    window.dispatchEvent(new Event('tube-state-changed'));
    if(reveal)for(const id of ['stateFilterSite','stateFilterOutage','stateFilterUnit','stateFilterType','stateFilterSearch'])if(q(id))q(id).value='';
    const refreshed=await loadStates();
    if(refreshed&&reveal)window.stateMaintenance.edit(rows[0]);
    const changed=Number(result.changed||0),skipped=Number(result.skipped||0);
    window.toast(refreshed?`批量处理完成：更新 ${changed} 根，跳过 ${skipped} 根已有记录、历史堵管或待核对的管`:`已保存 ${changed} 根维护记录，但列表刷新失败。请重新加载，无需重复导入或保存。`,{type:refreshed?'success':'warning'});
    return {...result,refresh_failed:!refreshed};
  }
  q('stateAllNormal').onclick=()=>transfer(q('stateAllNormal'),async()=>{
    const scope=transferScope(),rows=Array.from({length:50},(_,i)=>({...scope,thimble_id:i+1,state:'normal',offset_mm:0,note:'人工批量确认正常'}));
    const preview=await api('/api/states/batch-preview',{method:'POST',body:JSON.stringify({rows,only_unmaintained:true})});
    const blocked=(preview.skipped_rows||[]).filter(row=>row.reason!=='本次已有维护记录');
    const reasons=[...new Set(blocked.map(row=>row.reason))].map(reason=>`${reason}：${blocked.filter(row=>row.reason===reason).map(row=>`${row.thimble_id}号`).join('、')}`).join('；');
    const detail=reasons?`本次未维护但不能自动补齐：${reasons}。请逐管核对。`:'';
    if(!preview.affected){await window.appFeedback.confirm(`${scope.outage} · ${scope.unit_id}号机组：没有可补齐的管。${detail||'本次管状态均已有记录。'}`,{title:'补齐正常预览',confirmLabel:'知道了'});return}
    if(!await window.appFeedback.confirm(`${scope.outage} · ${scope.unit_id}号机组：将确认 ${preview.affected} 根为正常。${detail}仅在已确认这些管本次正常时继续。`,{title:'补齐未维护管为正常',confirmLabel:`确认 ${preview.affected} 根`}))return;
    await applyRows(rows,true,false,null,{revision:preview.revision});
  });
  q('stateExport').onclick=()=>transfer(q('stateExport'),async()=>{
    const scope=transferScope(),format=q('stateExportFormat').value;
    const file=await api('/api/states/export',{method:'POST',body:JSON.stringify({...scope,format})});
    const result=q('stateExportResult');
    const save=async()=>{
      const saved=await window.saveGeneratedOfficeFile(file);
      window.toast(saved.status==='saved'?`管状态文件已保存：${saved.path}`:saved.status==='cancelled'?'已取消保存管状态文件':'管状态文件已生成，正在保存',{type:saved.status==='saved'?'success':'info'});
    };
    if(result){
      const retry=document.createElement('button');retry.type='button';retry.className='state-export-link';retry.textContent='保存已生成的文件';
      retry.onclick=()=>transfer(retry,save);
      result.replaceChildren(document.createTextNode('已生成 '),document.createTextNode(file.filename+' · '),retry);
    }
    await save();
  });
  q('stateImport').onclick=()=>{q('stateImportFile').value='';q('stateImportFile').click()};
  async function reviewRows(preview,title='管状态导入预览',applyLabel='确认导入'){
    const dialog=document.createElement('dialog');dialog.className='state-import-preview';dialog.setAttribute('aria-label',title);
    dialog.innerHTML='<div class="state-preview-head"><h2></h2><p></p></div><div class="state-preview-tools"><label><input type="checkbox" aria-label="全选识别结果" checked>全选本页</label><span role="status"></span></div><div class="table-wrap"><table><thead><tr><th>选择</th><th>基地 / 大修</th><th>机组</th><th>管号</th><th>状态</th><th>位移(mm)</th><th>备注</th><th>来源</th></tr></thead><tbody></tbody></table></div><form method="dialog" class="dialog-actions"><button value="cancel" autofocus>取消</button><button value="apply" class="primary"></button></form>';
    dialog.querySelector('h2').textContent=title;
    const sites=new Set(preview.rows.map(row=>row.outage.match(/^[A-Z]+/)?.[0])),outages=new Set(preview.rows.map(row=>row.outage));
    const conflictCount=preview.rows.filter(row=>row.existing_status).length;
    dialog.querySelector('.state-preview-head p').textContent=preview.rows.length?`已识别 ${sites.size} 个基地、${outages.size} 次大修。${conflictCount?`发现 ${conflictCount} 条已有维护记录，默认不导入；如需更新，请明确勾选对应管。`:''}备注可编辑；复合处理及换管顺序须核对。`:'未识别到可应用的明确维护记录，请查看未自动应用项。';
    const apply=dialog.querySelector('[value=apply]');apply.textContent=applyLabel;
    const all=dialog.querySelector('[aria-label="全选识别结果"]'),entries=[];
    all.parentElement.lastChild.textContent=preview.pending?'全选':'全选新增记录';
    const sync=()=>{const selected=entries.filter(e=>e.check.checked),keys=selected.map(e=>[e.row.outage,e.row.unit_id,e.row.thimble_id].join('|'));all.checked=selected.length>0;all.indeterminate=selected.length>0&&selected.length<entries.length;apply.disabled=!selected.length||new Set(keys).size!==keys.length||selected.some(e=>e.stateSelect&&(!e.stateSelect.value||e.stateSelect.value==='shifted'&&!e.manualOffset.checkValidity()));dialog.querySelector('.state-preview-tools [role=status]').textContent=`识别 ${entries.length} 条 · 已选 ${selected.length} 条 · 已有 ${conflictCount} 条（逐条确认更新） · 未注明方向 ${selected.filter(e=>e.direction&&!e.direction.value).length} 条${new Set(keys).size!==keys.length?' · 同管请选择一条':''}`};
    const missing=preview.rows.filter(row=>row.offset_mm==null&&row.unsigned_offset_mm!=null);
    let batchDirection;
    if(missing.length){
      const label=document.createElement('label');label.className='state-import-direction';label.textContent='批量确认位移方向';
      batchDirection=document.createElement('select');batchDirection.setAttribute('aria-label','确认原表移位方向');
      batchDirection.innerHTML='<option value="1">采用正向（+）</option><option value="-1">采用负向（−）</option><option value="">留待核对（不写入方向）</option><option value="skip">跳过未注明方向的记录</option>';
      batchDirection.value=readShiftDirection();
      label.append(batchDirection);dialog.querySelector('.state-preview-tools').append(label);
      batchDirection.onchange=()=>{
        if(batchDirection.value==='1'||batchDirection.value==='-1'||batchDirection.value===''){
          window.statePreferences.set(batchDirection.value||'pending').catch(()=>{});
          if(defaultDirectionSelect)defaultDirectionSelect.value=batchDirection.value||'pending';
        }
        for(const entry of entries.filter(e=>e.direction)){
          if(batchDirection.value==='skip')entry.check.checked=false;
          else entry.direction.value=batchDirection.value;
          entry.updateOffset();
        }
        sync();
      };
    }
    if(preview.warnings?.length){
      const details=document.createElement('details');details.className='state-preview-warnings';const summary=document.createElement('summary');summary.textContent=`${preview.warnings.length} 项未自动应用`;
      details.append(summary);for(const warning of preview.warnings){const p=document.createElement('p');p.textContent=warning;details.append(p)}dialog.querySelector('.table-wrap').before(details);
    }
    const sourceSummary=value=>{
      const groups=new Map();
      for(const line of [...new Set(String(value||'').split(/\r?\n/).map(item=>item.trim()).filter(Boolean))]){
        const parts=line.split(' · '),file=(parts.shift()||'').replaceAll('\\','/').split('/').pop(),context=parts.join(' · ');
        if(!groups.has(file))groups.set(file,[]);
        if(context&&!groups.get(file).includes(context))groups.get(file).push(context);
      }
      return [...groups].map(([file,contexts])=>{
        const locations=contexts.slice(0,2).join('、');
        return `${file||'来源未注明'}${locations?` · ${locations}${contexts.length>2?` 等 ${contexts.length} 处`:''}`:''}`;
      }).join('；');
    };
    for(const [index,row] of preview.rows.entries()){
      const tr=document.createElement('tr'),check=document.createElement('input');check.type='checkbox';check.checked=!row.recognition_id&&!row.existing_status;check.disabled=row.existing_status==='revoked';check.setAttribute('aria-label',`导入 ${row.outage} 管${row.thimble_id}`);tr.insertCell().append(check);check.onchange=sync;
      for(const value of [`${names[row.outage.match(/^[A-Z]+/)?.[0]]||''} ${row.outage}`.trim(),row.unit_id,row.thimble_id])tr.insertCell().textContent=value;
      const stateCell=tr.insertCell(),offsetCell=tr.insertCell();let direction,stateSelect,manualOffset,updateOffset=()=>{};
      const previewEvents=rowEvents(row),previewActive=statePaint.uniqueEvents(previewEvents);
      stateCell.textContent=row.event_label||statePaint.label(previewEvents)||labels[row.state]||'待核对';
      stateCell.dataset.events=previewActive.join(',');
      stateCell.dataset.state=previewActive.length===1?previewActive[0]:(row.state||'unknown');
      stateCell.dataset.composite=String(previewActive.length>1);
      stateCell.style.background=statePaint.background(previewEvents);
      stateCell.style.borderColor=statePaint.edge(previewEvents);
      stateCell.style.color=statePaint.ink(previewEvents);
      if(previewEvents.includes('replaced')&&previewEvents.length>1)stateCell.textContent+=`（${({before_replacement:'其他处理在换管前',after_replacement:'其他处理在换管后'}[row.replacement_stage]||'换管顺序待核对')}）`;
      if(row.needs_review||row.review_reason)stateCell.dataset.review='true';
      stateCell.title=row.event_label||labels[row.state]||'待核对';
      const note=document.createElement('textarea');note.rows=2;note.value=row.note||'';note.setAttribute('aria-label',`${row.outage} 管${row.thimble_id}备注`);
      if(!row.state){
        stateSelect=document.createElement('select');stateSelect.setAttribute('aria-label',`${row.outage} 管${row.thimble_id}确认状态`);stateSelect.add(new Option('待核对',''));
        for(const [value,label] of Object.entries(labels))stateSelect.add(new Option(label,value));
        stateCell.replaceChildren(stateSelect);
        manualOffset=document.createElement('input');manualOffset.type='number';manualOffset.min='-1000';manualOffset.max='1000';manualOffset.step='any';manualOffset.placeholder=row.unsigned_offset_mm!=null?`${row.unsigned_offset_mm} mm（按默认方向）`:'未注明，可空';manualOffset.setAttribute('aria-label',`${row.outage} 管${row.thimble_id}确认位移`);
        offsetCell.append(manualOffset);manualOffset.hidden=true;
        stateSelect.onchange=()=>{
          manualOffset.hidden=stateSelect.value!=='shifted';
          if(stateSelect.value==='shifted'&&manualOffset.value===''&&row.unsigned_offset_mm!=null){
            manualOffset.value=signedDetectedOffset(row,readShiftDirection());
          }
          sync();
        };manualOffset.oninput=sync;
      }else if(row.offset_mm==null&&row.unsigned_offset_mm!=null){
        const amount=document.createElement('span');amount.textContent=`${row.unsigned_offset_mm} mm`;
        direction=document.createElement('select');direction.setAttribute('aria-label',`${row.outage} 管${row.thimble_id}位移方向`);direction.innerHTML='<option value="">原表未注明</option><option value="1">正向 +</option><option value="-1">负向 −</option>';
        direction.value=readShiftDirection()==='pending'?'':readShiftDirection();
        updateOffset=()=>{
          const detail=direction.value?`${Number(direction.value)>0?'+':'−'}${row.unsigned_offset_mm} mm`:`${row.unsigned_offset_mm} mm（方向待确认）`;
          amount.textContent=detail;sync();
        };
        direction.onchange=updateOffset;offsetCell.append(amount,direction);
      }else offsetCell.textContent=(row.events?.includes('shifted')||row.state==='shifted')?(row.offset_mm==null?'未注明':`${row.offset_mm>0?'+':''}${row.offset_mm}`):'/';
      tr.insertCell().append(note);
      const sourceCell=tr.insertCell();sourceCell.className='state-source-cell';sourceCell.textContent=sourceSummary(row.source);sourceCell.title=row.source||'';
      if(row.existing_status){
        tr.dataset.importConflict=row.existing_status;
        const conflict=document.createElement('p');conflict.className='state-import-conflict';
        conflict.textContent=row.existing_status==='revoked'?'已有记录已撤销；导入不会自动恢复。':row.existing_status==='same'?`数据库已有相同记录：${row.existing_state}；默认跳过。`:`与数据库记录不同：当前 ${row.existing_state}${row.existing_offset_mm!=null?` ${row.existing_offset_mm} mm`:''}；默认跳过，勾选即确认更新。`;
        conflict.title=row.existing_note?`数据库备注：${row.existing_note}`:conflict.textContent;
        sourceCell.append(conflict);
        if(row.existing_status==='different'&&row.existing_note){
          const details=document.createElement('details'),summary=document.createElement('summary'),note=document.createElement('p');
          summary.textContent='查看数据库备注';note.textContent=row.existing_note;
          details.append(summary,note);sourceCell.append(details);
        }
      }
      if(row.review_reason){
        const reason=document.createElement('p');reason.className='state-review-reason';reason.textContent=row.review_reason;
        if(row.expected_state)reason.textContent+=`；已有：${row.expected_state.is_deleted?'已撤销':labels[row.expected_state.state]}${row.expected_state.state==='shifted'?(row.expected_state.offset_confirmed===0?'（距离或方向未明确）':` ${row.expected_state.offset_mm} mm`):''}`;
        sourceCell.append(reason);
      }
      entries.push({row,check,direction,note,updateOffset,stateSelect,manualOffset,tr});
      if(preview.rows.length>1000&&(index+1)%200===0){
        importFeedback(`正在准备预览 · ${index+1} / ${preview.rows.length} 条 · ${Math.floor((index+1)/preview.rows.length*100)}%`,'progress',(index+1)/preview.rows.length*100);
        await new Promise(resolve=>requestAnimationFrame(resolve));
      }
    }
    const pageSize=100,pageCount=Math.max(1,Math.ceil(entries.length/pageSize));
    const pager=document.createElement('div');pager.className='state-preview-pagination';pager.hidden=pageCount<=1;
    pager.innerHTML='<button type="button" aria-label="上一页识别结果" title="上一页">‹</button><span role="status"></span><button type="button" aria-label="下一页识别结果" title="下一页">›</button>';
    let previewPage=1;
    const [previous,next]=pager.querySelectorAll('button');
    const renderPage=()=>{
      dialog.querySelector('tbody').replaceChildren(...entries.slice((previewPage-1)*pageSize,previewPage*pageSize).map(entry=>entry.tr));
      pager.querySelector('span').textContent=`第 ${previewPage} / ${pageCount} 页 · 共 ${entries.length} 条`;
      previous.disabled=previewPage===1;next.disabled=previewPage===pageCount;
      dialog.querySelector('.table-wrap').scrollTop=0;
    };
    previous.onclick=()=>{previewPage--;renderPage()};
    next.onclick=()=>{previewPage++;renderPage()};
    dialog.querySelector('.table-wrap').after(pager);renderPage();
    if(preview.rows.length>1000)importFeedback(`预览已准备完成 · ${entries.length} 条记录，请核对后确认。`,'review');
    all.onchange=()=>{const checked=all.checked;entries.forEach(e=>{if(!e.check.disabled)e.check.checked=checked&&!e.row.existing_status});sync()};sync();
    if(preview.pending){
      const dismiss=document.createElement('button');dismiss.type='button';dismiss.textContent='忽略所选';dismiss.className='danger-outline';
      dialog.querySelector('.dialog-actions').prepend(dismiss);
      dismiss.onclick=async()=>{const chosen=entries.filter(e=>e.check.checked);if(!chosen.length)return;
        if(!await window.appFeedback.confirm(`忽略所选 ${chosen.length} 条识别结果？原始检测备注仍保留。`,{title:'忽略识别结果',confirmLabel:'确认忽略'}))return;
        dismiss.disabled=true;try{await api('/api/states/dismiss-recognition',{method:'POST',body:JSON.stringify({confirmed:true,ids:chosen.map(e=>e.row.recognition_id)})});dialog.close('dismiss')}catch(error){window.toast(error.message,{type:'error'});dismiss.disabled=false}};
    }
    document.body.append(dialog);
    const choice=await new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue),{once:true});dialog.showModal()});
    const accepted=choice==='apply';
    const rows=accepted?entries.filter(e=>e.check.checked).map(e=>{
      const selectedState=e.stateSelect?.value||e.row.state;
      const offset=e.stateSelect?(selectedState==='shifted'?(e.manualOffset.value===''?null:Number(e.manualOffset.value)):0):e.direction?(e.direction.value?Number(e.direction.value)*e.row.unsigned_offset_mm:null):e.row.offset_mm;
      return {...e.row,state:selectedState,offset_mm:offset,note:originalStateNote(e.note,e.row.note),...(e.row.existing_status&&e.row.existing_status!=='revoked'?{overwrite_existing:true}:{})};
    }):[];
    dialog.remove();if(choice==='dismiss')await loadStates();return rows;
  }
  reviewPending.onclick=()=>transfer(reviewPending,async()=>{
    const fresh=await api('/api/states');
    const preview={rows:fresh.pending||[],pending:true,warnings:[]};
    const rows=await reviewRows(preview,'数据导入状态核对','确认维护');
    if(rows.length)await applyRows(rows,false,true);
  });
  async function supplementScopes(preview){
    const dialog=document.createElement('dialog');dialog.className='state-import-preview state-scope-preview';dialog.setAttribute('aria-label','补充未识别的大修编号');
    dialog.innerHTML='<div class="state-preview-head"><h2>补充大修编号</h2><p></p></div><div class="state-scope-fields"></div><form method="dialog" class="dialog-actions"><button value="cancel">取消</button><button value="skip">仅使用已识别记录</button><button value="apply" class="primary">继续识别</button></form>';
    dialog.querySelector('p').textContent=`已自动识别 ${preview.rows.length} 条。以下工作表有明确的维护信息，但未注明完整大修编号。`;
    dialog.querySelector('[value=skip]').hidden=!preview.rows.length;
    const inputs=preview.missing_scopes.map(group=>{
      const label=document.createElement('label'),caption=document.createElement('span'),input=document.createElement('input');
      caption.textContent=`${group.title} · ${group.rows} 条${group.site?` · ${names[group.site]||group.site}`:''}${group.unit_id?` · ${group.unit_id}号机组`:''}`;
      input.placeholder=group.site&&group.unit_id?`${group.site}${group.unit_id}XX`:'如 F102';input.maxLength=5;input.setAttribute('aria-label',`${group.title}大修编号`);
      label.append(caption,input);dialog.querySelector('.state-scope-fields').append(label);return {group,input};
    });
    const apply=dialog.querySelector('[value=apply]'),valid=()=>inputs.every(({group,input})=>{
      const value=input.value.trim().toUpperCase();
      return /^[A-Z]{1,2}[1-9]\d{2}$/.test(value)&&(!group.site||value.match(/^[A-Z]+/)[0]===group.site)&&(!group.unit_id||Number(value.match(/\d/)[0])===Number(group.unit_id));
    });
    inputs.forEach(({input})=>input.oninput=()=>apply.disabled=!valid());apply.disabled=true;
    document.body.append(dialog);
    const choice=await new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue),{once:true});dialog.showModal()});
    const overrides=choice==='apply'?Object.fromEntries(inputs.map(({group,input})=>[group.key,input.value.trim().toUpperCase()])):choice==='skip'?{}:null;
    dialog.remove();return overrides;
  }
  let lastImportFile;
  async function importFile(file){return transfer(q('stateImport'),async()=>{
    lastImportFile=file;const button=q('stateImport'),label=button.textContent;retryImport.hidden=true;button.textContent='正在读取…';root.setAttribute('aria-busy','true');
    try{
      if(file.size>12_000_000)throw Error('状态表格不可超过 12 MB');
      importFeedback(`正在读取 ${file.name}…`);
      const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('无法读取表格，请检查文件是否可访问'));reader.onabort=()=>reject(Error('文件读取已中断，请重试'));reader.onprogress=event=>{if(event.lengthComputable)importFeedback(`正在读取 ${file.name} · ${Math.round(event.loaded/event.total*100)}%`,'progress',event.loaded/event.total*100)};reader.readAsDataURL(file)});
      const recognize=async(scope_overrides={})=>{
        button.textContent='正在识别…';importFeedback(`正在识别 ${file.name} 的基地、机组、大修和维护记录…`);
        try{return await window.runImportRequest('/api/states/import-preview',{filename:file.name,content,scope_overrides},showTaskProgress,{signal:AbortSignal.timeout(90000)})}
        catch(error){if(error.name==='TimeoutError')throw Error('识别超时，请重试或将表格拆分后导入');if(error instanceof TypeError)throw Error('无法连接本地服务，请检查连接状态后重试');throw error}
      };
      let preview=await recognize();
      if(preview.missing_scopes?.length){
        importFeedback(`${file.name}：已识别 ${preview.rows.length} 条，另有工作表需要补充大修编号。`,'review');
        const overrides=await supplementScopes(preview);if(overrides===null){importFeedback('已取消导入，未写入维护记录。','cancel');return}
        if(Object.keys(overrides).length)preview=await recognize(overrides);
      }
      button.textContent='等待确认…';root.setAttribute('aria-busy','false');
      importFeedback(`${file.name}：识别到 ${preview.rows.length} 条，${preview.warnings?.length||0} 项需核查。${preview.rows.length?'请在预览中确认。':'本次未写入数据。'}`,'review');
      const rows=await reviewRows(preview);
      if(rows.length){
        button.textContent='正在保存…';importFeedback(`正在保存 ${rows.length} 条维护记录…`);
        const result=await applyRows(rows,false,true,showTaskProgress,{import_revision:preview.revision});importFeedback(`${file.name}：已导入 ${result.changed} 条维护记录。${result.refresh_failed?'列表刷新失败，请重新加载，无需重复导入。':'导入完成 100%。'}`,result.refresh_failed?'review':'success');
      }else importFeedback(preview.rows.length?'已取消导入，未写入维护记录。':`${file.name}：没有可导入记录，请核查表内管号、状态和大修信息。`,'cancel');
    }catch(error){importFeedback(`${file.name}：${error.message}`,'error');throw error}
    finally{q('stateImportFile').value='';button.textContent=label;root.setAttribute('aria-busy','false')}
  })}
  retryImport.onclick=()=>{if(lastImportFile&&!transferBusy)importFile(lastImportFile)};
  q('stateImportFile').onchange=()=>{const file=q('stateImportFile').files[0];if(file)importFile(file)};
  const picker=document.createElement('section');picker.className='panel state-tube-panel';
  picker.innerHTML='<div class="panel-title"><div><h2>管板</h2><span>点击管号查看或选择</span></div></div><div id="stateTubeGrid" class="state-tube-grid"></div><div class="state-grid-legend"><span>未维护</span><span data-state="normal">正常</span><span data-state="plugged">堵管</span><span data-state="shifted">移位</span><span data-state="replaced">换管</span><span data-composite="true">复合处理</span></div>';
  layout.prepend(picker);root.insertBefore(list,layout.nextSibling);
  editor.querySelector('h2').textContent='管状态处理';
  editor.querySelector('.panel-title span').textContent='选择管号后编辑并保存';
  const help=document.createElement('p');help.id='stateRule';help.className='state-rule';help.setAttribute('role','status');
  q('stateType').closest('label').after(help);
  q('stateOffset').closest('label').id='stateOffsetLabel';
  q('stateOffsetLabel').firstChild.textContent='有符号轴向位移（mm）';
  const useDefaultOffset=document.createElement('button');useDefaultOffset.type='button';useDefaultOffset.id='stateUseDefaultOffset';useDefaultOffset.className='state-use-default-offset';useDefaultOffset.hidden=true;
  useDefaultOffset.title='将识别到的无符号距离按上方默认方向填入；待核对时不会猜测方向';
  q('stateOffsetLabel').append(useDefaultOffset);
  const syncDefaultOffsetAction=()=>{
    const unsigned=Number(q('stateOffset').dataset.unsignedOffset),direction=readShiftDirection();
    const available=q('stateType').value==='shifted'&&q('stateOffset').value===''&&Number.isFinite(unsigned)&&unsigned>=0;
    useDefaultOffset.hidden=!available;
    useDefaultOffset.textContent=direction==='pending'?'设置方向':`套用 ${direction==='-1'?'−':'+'}${unsigned} mm`;
    useDefaultOffset.title=direction==='pending'?'先在批量操作栏选择默认方向，再套用已识别距离':'将已识别的无符号距离按默认方向填入';
  };
  useDefaultOffset.onclick=()=>{
    const direction=readShiftDirection();
    if(direction==='pending'){window.toast('默认方向设为“留待核对”；请先在批量操作栏选择正向或负向。',{type:'warning'});q('stateDefaultShiftDirection')?.focus();return}
    q('stateOffset').value=signedDetectedOffset({unsigned_offset_mm:q('stateOffset').dataset.unsignedOffset},direction);
    q('stateOffset').dispatchEvent(new Event('input',{bubbles:true}));
    syncDefaultOffsetAction();
    window.toast(`已填入 ${q('stateOffset').value} mm；保存后才会写入维护记录。`);
  };
  const noteTools=document.createElement('div');noteTools.className='state-note-tools';noteTools.innerHTML='<button type="button" id="stateRecognizeNote" title="从粘贴的维护说明识别状态及距离">识别维护说明</button><button type="button" id="stateGenerateNote" title="根据当前管状态和位移生成备注">生成备注</button>';
  q('stateNote').before(noteTools);
  q('stateNote').placeholder='可粘贴原始维护说明，如“割管移位（切除42mm）”';
  const sourceLabel=document.createElement('label');sourceLabel.className='wide';sourceLabel.textContent='来源';
  const sourceInput=document.createElement('textarea');sourceInput.id='stateSource';sourceInput.readOnly=true;sourceInput.rows=2;sourceLabel.append(sourceInput);q('stateNote').closest('label').after(sourceLabel);
  const sourceDetails=document.createElement('details');sourceDetails.className='state-source-details';
  const sourceSummary=document.createElement('summary');sourceSummary.textContent='来源资料';
  sourceLabel.before(sourceDetails);sourceDetails.append(sourceSummary,sourceLabel);
  for(const [before,label] of [[q('stateThimble').closest('label'),'管号与处理'],[q('stateNote').closest('label'),'维护依据']]){
    const heading=document.createElement('h3');heading.className='state-field-heading';heading.textContent=label;before.before(heading);
  }
  function setOriginal(record){q('stateNote').value=record?.note||'';q('stateNote').dataset.originalNote=record?.note||'';q('stateSource').value=record?.source||'';q('stateSource').dataset.originalNote=record?.source||'';q('stateOffset').dataset.unsignedOffset=record?.unsigned_offset_mm??'';q('stateOffset').placeholder=record?.unsigned_offset_mm!=null?`${record.unsigned_offset_mm} mm（方向未注明）`:'未注明，可空';syncDefaultOffsetAction();window.tubeLifecycle?.edit(record)}
  let noteEditRevision=0;
  for(const type of ['input','change'])root.addEventListener(type,event=>{
    if(event.target.closest('#stateForm,.state-scope'))noteEditRevision++;
  });
  const noteEditSnapshot=()=>JSON.stringify([...root.querySelectorAll('#stateForm input,#stateForm select,#stateForm textarea,.state-scope select')]
    .map(control=>[control.id,control.value,control.checked,control.dataset.originalNote,control.dataset.unsignedOffset]));
  q('stateRecognizeNote').onclick=async()=>{
    const button=q('stateRecognizeNote');if(button.disabled)return;button.disabled=true;
    try{
      const scope=transferScope(),thimble_id=Number(q('stateThimble').value);if(!thimble_id)throw Error('请先选择管号');
      const revision=noteEditRevision,editorSnapshot=noteEditSnapshot();
      const stillCurrent=()=>revision===noteEditRevision&&editorSnapshot===noteEditSnapshot();
      const staleMessage='编辑内容或维护范围已变化，已忽略旧识别结果。当前输入已保留，请重新识别。';
      const snapshot=records.find(r=>r.outage===scope.outage&&r.unit_id===scope.unit_id&&r.thimble_id===thimble_id);
      const preview=await api('/api/states/recognize-note',{method:'POST',body:JSON.stringify({...scope,thimble_id,note:originalStateNote(q('stateNote')),source:originalStateNote(q('stateSource'))})});
      if(!stillCurrent()){window.toast(staleMessage,{type:'info'});return}
      const rows=await reviewRows(preview,'维护说明识别','填入编辑区');if(!rows.length)return;
      if(!stillCurrent()){window.toast(staleMessage,{type:'info'});return}
      q('stateType').value=rows[0].state;q('stateOffset').value=rows[0].offset_mm;setOriginal({...rows[0],updated_at:snapshot?.updated_at??null});rule();
    }catch(error){window.toast(error.message,{type:'error'})}finally{button.disabled=false}
  };
  q('stateGenerateNote').onclick=()=>{
    try{
      const scope=transferScope(),tube=Number(q('stateThimble').value);if(!tube)throw Error('请先选择管号');
      const shifted=window.tubeLifecycle?.hasShift()??q('stateType').value==='shifted';if(shifted&&!q('stateOffset').reportValidity())throw Error('位移量无效');
      const processing=window.tubeLifecycle?.payload(),eventLabel=processing?.events.length?processing.events.map(event=>labels[event]).join(' · '):labels[q('stateType').value];
      const stage=processing?.events.includes('replaced')&&processing.events.length>1?`；${({before_replacement:'其他处理在换管前',after_replacement:'其他处理在换管后'}[processing.replacement_stage]||'换管顺序待核对')}`:'';
      const offset=Number(q('stateOffset').value),distance=q('stateOffset').value!==''?` ${offset>=0?'+':''}${offset} mm`:q('stateOffset').dataset.unsignedOffset?` ${q('stateOffset').dataset.unsignedOffset} mm（方向未注明）`:'（距离未注明）',note=`${scope.outage} · 通道${String(tube).padStart(3,'0')}：${eventLabel}${shifted?distance:'（人工确认）'}${stage}`;
      if(!q('stateNote').value.includes(note))q('stateNote').value+=`${q('stateNote').value?'\n':''}${note}`;
    }catch(error){window.toast(error.message,{type:'error'})}
  };
  const timing=document.createElement('div');timing.className='state-timing';timing.textContent='生效：本次检查后；历史检测记录保留。';
  form.append(timing);
  const reset=document.createElement('button');reset.type='button';reset.id='stateReset';reset.textContent='取消编辑';
  const footer=document.createElement('div');footer.className='state-form-actions';
  footer.append(reset,form.querySelector('button[type=submit]'));form.append(footer);
  const syncFormAvailability=()=>{
    const selected=Boolean(q('stateOutage').value&&q('stateUnit').value&&Number(q('stateThimble').value));
    const batchActive=Boolean(q('lifecycleBatchMode')?.checked);
    const submit=form.querySelector('button[type=submit]');
    if(submit){submit.dataset.selectionDisabled=String(!selected);submit.disabled=transferBusy||!selected||batchActive;submit.title=batchActive?'当前处于批量选择模式；关闭后才能保存单管':'保存当前管状态及维护说明'}
    reset.disabled=transferBusy||!selected;reset.title=selected?'清空当前编辑内容':'当前没有正在编辑的管号';
    q('stateRecognizeNote').disabled=transferBusy||!selected;q('stateGenerateNote').disabled=transferBusy||!selected;
    if(q('lifecycleHistory'))q('lifecycleHistory').disabled=transferBusy||!selected;
  };
  list.querySelector('h2').textContent='已维护记录';
  list.querySelector('.panel-title span').textContent='可行内修改；撤销只撤销维护记录，不删除检测数据';
  const rules={normal:'按常规流程比较；未填写维护记录不能视为已确认正常。',plugged:'堵管持续有效，直到明确记录换管；保留检测数据，但历次自动对比将转为待人工核查。',shifted:'移位距离可留空；距离或方向未明确时不自动换算位置。明确后仅与下一次相邻大修比较。',replaced:'换新管并建立新生命周期，不删除历史。处理后的首次检查不与换管前缺陷比较；本次检查结果仍可与此前合法历史比较。'};
  function rule(){if(window.tubeLifecycle){window.tubeLifecycle.sync();return}const shifted=q('stateType').value==='shifted';q('stateOffsetLabel').hidden=!shifted;q('stateOffset').required=false;q('stateOffset').disabled=!shifted;q('stateRule').textContent=rules[q('stateType').value];}
  function render(){
    const outage=q('stateOutage').value,unit=q('stateUnit').value,tube=Number(q('stateThimble').value);
    q('stateScopeStatus').textContent=outage?`${names[q('stateSite').value]||q('stateSite').value} · ${unit}号机组 · ${outage}`:'请选择维护范围';
    q('stateTubeGrid').replaceChildren(...Array.from({length:50},(_,i)=>{
      const number=i+1,record=records.find(r=>r.outage===outage&&String(r.unit_id)===unit&&r.thimble_id===number);
      const button=document.createElement('button');button.type='button';button.dataset.tube=number;button.dataset.state=record?.state||'unknown';button.dataset.row=Math.ceil(number/10);button.classList.toggle('selected',tube===number);button.disabled=transferBusy;button.setAttribute('aria-pressed',String(tube===number));
      const events=rowEvents(record),activeEvents=statePaint.uniqueEvents(events);
      const composite=activeEvents.length>1;
      const status=record?(record.event_label||statePaint.label(events)):'未维护';
      const distance=events.includes('shifted')?(record.offset_mm!=null?`${record.offset_mm>0?'+':''}${record.offset_mm} mm`:record.unsigned_offset_mm!=null?`${record.unsigned_offset_mm} mm（方向未注明）`:'距离未注明'):'';
      const detail=`${number}号管 · ${status}${distance?` · ${distance}`:''}`;
      button.title=detail;button.setAttribute('aria-label',detail);
      button.dataset.composite=String(composite);
      button.dataset.events=activeEvents.join(',');
      button.dataset.review=String(Boolean(record?.needs_review));
      button.style.background=record?statePaint.background(events):statePaint.colors?.missing?.fill||'#f4f7f9';
      button.style.borderColor=statePaint.edge(events);
      button.style.color=statePaint.ink(events);
      const b=document.createElement('b'),small=document.createElement('small');b.textContent=String(number).padStart(2,'0');small.textContent=status;button.append(b,small);
      const tooltip=document.createElement('span');tooltip.className='state-tube-tooltip';tooltip.setAttribute('role','tooltip');tooltip.textContent=distance?`移位距离：${distance}`:status;button.append(tooltip);
      button.onclick=()=>{if(!q('stateSite').value||!q('stateUnit').value||!q('stateOutage').value){window.toast('请先选择基地、机组和大修，再选择管号',{type:'warning'});q(!q('stateSite').value?'stateSite':!q('stateUnit').value?'stateUnit':'stateOutage').focus();return}q('stateThimble').value=number;q('stateThimble').dispatchEvent(new Event('input',{bubbles:true}));q('stateType').value=record?.state||'normal';q('stateOffset').value=record?.offset_mm??'';setOriginal(record);rule();render()};return button;
    }));
    window.tubeLifecycle?.refresh();stateScopeSummary();syncFormAvailability();
  }
  function scopes(){const list=[...(state.overview?.combinations||[]),...manualScopes,...records.map(row=>({...row,site:row.outage.match(/^[A-Z]+/)?.[0]}))];return [...new Map(list.map(row=>[[row.site,row.unit_id,row.outage].join('|'),row])).values()]}
  function sync(changed=''){
    const list=scopes(),site=q('stateSite');
    refill('stateSite',list.map(x=>x.site),'选择基地');
    if(changed==='site'){q('stateUnit').value='';q('stateOutage').value='';}
    if(changed==='unit')q('stateOutage').value='';
    const units=list.filter(x=>x.site===site.value);
    refill('stateUnit',units.map(x=>x.unit_id),'选择机组');
    if(!q('stateUnit').value&&units.length)q('stateUnit').value=String(units[0].unit_id);
    const outages=units.filter(x=>String(x.unit_id)===q('stateUnit').value);
    refill('stateOutage',outages.map(x=>x.outage),'选择大修');
    if(!q('stateOutage').value&&outages.length)q('stateOutage').value=unique(outages.map(x=>x.outage)).at(-1);
    for(const option of site.options)if(option.value)option.textContent=`${names[option.value]||option.value}（${({P:'HZ',C:'CN'}[option.value]||option.value)}）`;
    for(const option of q('stateOutage').options)if(option.value){const match=option.value.match(/(\d{2})$/);option.textContent=match?`${option.value}（第${Number(match[1])}次大修）`:option.value}
    render();
  }
  for(const id of ['stateSite','stateUnit','stateOutage','stateExportFormat'])q(id).addEventListener('change',()=>q('stateExportResult').replaceChildren());
  for(const event of ['tube-state-changed','database-cleared','data-imported','data-deleted','data-restored'])window.addEventListener(event,()=>q('stateExportResult').replaceChildren());
  q('stateSite').onchange=()=>{sync('site');resetDetails()};q('stateUnit').onchange=()=>{sync('unit');resetDetails()};q('stateOutage').onchange=()=>{resetDetails();render()};
  manageScopes.onclick=openScopeManager;
  function resetDetails(){q('stateThimble').value='';q('stateType').value='normal';q('stateOffset').value='';setOriginal(null);rule();render()}
  q('stateReset').onclick=resetDetails;q('stateType').onchange=()=>{rule();syncDefaultOffsetAction()};q('stateOffset').addEventListener('input',syncDefaultOffsetAction);q('stateThimble').addEventListener('input',()=>{
    const record=records.find(r=>r.outage===q('stateOutage').value&&String(r.unit_id)===q('stateUnit').value&&r.thimble_id===Number(q('stateThimble').value));
    q('stateType').value=record?.state||'normal';q('stateOffset').value=record?.offset_mm??'';setOriginal(record);rule();render();
  });
  window.addEventListener('storage',event=>{
    if(event.key!=='thimble-state-default-shift-direction')return;
    if(defaultDirectionSelect)defaultDirectionSelect.value=readShiftDirection();
    syncDefaultOffsetAction?.();
  });
  window.addEventListener('state-direction-changed',()=>{
    if(defaultDirectionSelect)defaultDirectionSelect.value=readShiftDirection();
    syncDefaultOffsetAction?.();
  });
  window.addEventListener('tube-edit-mode-changed',syncFormAvailability);
  window.stateMaintenance={scopes,overview(){sync()},setBusy(value){transferBusy=Boolean(value);operationBusy(transferBusy);if(!transferBusy)render()},reset(){resetDetails()},records(items,pending=[],savedScopes=[]){records=items;pendingRecords=pending;manualScopes=savedScopes;sync()},edit(item){const stored=records.find(r=>r.outage===item.outage&&r.unit_id===Number(item.unit_id)&&r.thimble_id===Number(item.thimble_id));item={...item,updated_at:Object.hasOwn(item,'updated_at')?item.updated_at:stored?.updated_at??null};q('stateSite').value=item.outage.match(/^[A-Z]+/)?.[0]||'';sync('site');q('stateUnit').value=String(item.unit_id);sync();q('stateOutage').value=item.outage;q('stateThimble').value=item.thimble_id||'';q('stateType').value=item.state||'normal';q('stateOffset').value=item.offset_mm??'';setOriginal(item);rule();render()},saved(){const item=records.find(r=>r.outage===q('stateOutage').value&&String(r.unit_id)===q('stateUnit').value&&r.thimble_id===Number(q('stateThimble').value));if(item)this.edit(item)}};
  rule();render();stateScopeSummary();
})();
