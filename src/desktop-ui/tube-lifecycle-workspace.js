(()=>{
  const q=id=>document.getElementById(id),root=q('states'),form=q('stateForm'),grid=q('stateTubeGrid');
  if(!form||!grid)return;
  const labels={normal:'正常',plugged:'堵管',shifted:'移位',replaced:'换管'};
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const request=(url,data)=>window.api(url,data?{method:'POST',body:JSON.stringify(data)}:{});
  let original=null,scopeItems=[],scopeKey='',requestId=0,busy=false,gridView='effective',previewNotice,dragSelection=null,suppressPointerClick=false,batchOffsetTouched=false;
  let scopeStatus='idle',scopeError='',scopeController=null,scopePromise=null;
  const selected=new Set(),view=document.createElement('div'),mode=document.createElement('div'),batch=document.createElement('div');
  const editorPanel=form.closest('.state-panel');
  view.className='state-grid-view';
  view.innerHTML='<span>管位显示</span><div role="group" aria-label="管位状态显示方式"><button type="button" data-grid-view="current" aria-pressed="false" title="只看当前大修是否已维护及本次处理">本次记录</button><button type="button" data-grid-view="effective" aria-pressed="true" title="查看历次大修延续到当前的有效状态">截至本次有效</button></div><small id="stateGridCaption">历史堵管延续至明确换管；无记录不视为正常。</small>';
  mode.className='lifecycle-batch-toolbar';
  mode.innerHTML='<label class="lifecycle-batch-toggle" title="开启后点击或拖动管号卡片选择多根管；再次点击可取消"><input type="checkbox" id="lifecycleBatchMode">批量选择</label><span id="lifecycleSelected" role="status" aria-live="polite">已选0根</span><button type="button" id="lifecycleClear" title="清除当前已选管号">清除</button><button type="button" class="primary" id="lifecyclePreview" disabled title="先选择需要处理的管；下一步会先预览，不会立即保存">批量处理</button><button type="button" id="lifecycleSelectAll" title="选择当前范围内全部50根管；涉及历史异常时建议先逐管核对">全选50根</button>';
  batch.className='lifecycle-batch-settings';batch.hidden=true;
  batch.innerHTML='<div id="lifecycleBatchSelectionSummary" class="lifecycle-batch-selection-summary" role="status">已选管号：—</div><label>统一处理状态<select id="lifecycleBatchState"><option value="normal">正常</option><option value="plugged">堵管</option><option value="shifted">移位</option><option value="replaced">换管</option><option value="composite">复合处理</option></select></label><fieldset id="lifecycleBatchEvents" hidden><legend>本次同时发生</legend><div class="lifecycle-event-options"><label><input type="checkbox" data-batch-event value="plugged">堵管</label><label><input type="checkbox" data-batch-event value="shifted">移位</label><label><input type="checkbox" data-batch-event value="replaced">换管</label></div></fieldset><label id="lifecycleBatchOffsetLabel" hidden>移位距离（mm）<input id="lifecycleBatchOffset" type="number" min="-1000" max="1000" step="any" placeholder="正数正向，负数反向；未知可留空" aria-describedby="lifecycleBatchOffsetHint"></label><p id="lifecycleBatchOffsetHint" class="lifecycle-batch-offset-hint" role="status" hidden></p><label id="lifecycleBatchStageLabel" hidden>与换管的先后顺序<select id="lifecycleBatchStage"><option value="unknown">未确认，标记待核对</option><option value="before_replacement">其他处理在换管前</option><option value="after_replacement">其他处理在换管后</option></select></label><label class="lifecycle-batch-note-label">统一追加备注<textarea id="lifecycleBatchNote" rows="3" maxlength="2000" placeholder="填写本批处理依据或维护说明；原有备注和来源会保留"></textarea></label><p id="lifecycleBatchRule" role="status"></p>';
  grid.before(view);
  if(editorPanel){
    const actionDock=editorPanel.querySelector('.state-action-dock');
    if(actionDock)actionDock.before(mode,batch);else editorPanel.querySelector('.panel-title')?.after(mode,batch);
  }else grid.before(mode,batch);
  const fields=document.createElement('fieldset');fields.className='lifecycle-events';fields.hidden=true;
  fields.innerHTML='<legend>本次检查后处理（可多选）</legend><div class="lifecycle-event-options"><label><input type="checkbox" data-maintenance-event value="plugged">堵管</label><label><input type="checkbox" data-maintenance-event value="shifted">移位</label><label><input type="checkbox" data-maintenance-event value="replaced">换管</label></div><label id="lifecycleStageLabel" hidden>同次其他处理发生在<select id="lifecycleStage"><option value="unknown">顺序未确认，保留待核对</option><option value="before_replacement">换管前，作用于旧管</option><option value="after_replacement">换管后，作用于新管</option></select></label><p id="lifecycleRule" role="status"></p>';
  q('stateType').closest('label').hidden=false;
  q('stateType').closest('label').querySelector('select').setAttribute('aria-label','单管处理状态');
  q('stateType').add(new Option('复合处理（多选）','composite'));
  q('stateType').querySelector('option[value="shifted"]').textContent='移位';
  q('stateType').closest('label').after(fields);
  const summary=document.createElement('div');summary.id='lifecycleSummary';summary.className='lifecycle-summary';summary.setAttribute('role','status');
  fields.before(summary);
  const scopeNotice=document.createElement('div');scopeNotice.className='lifecycle-summary';scopeNotice.hidden=true;scopeNotice.dataset.warning='true';
  scopeNotice.setAttribute('role','status');grid.before(scopeNotice);
  const history=document.createElement('button');history.type='button';history.id='lifecycleHistory';history.textContent='查看单管历次维护';
  form.querySelector('.state-form-actions').prepend(history);
  scopeNotice.addEventListener('click',event=>{if(event.target.closest('#lifecycleRetry'))refresh(true)});
  const names=()=>[...fields.querySelectorAll('[data-maintenance-event]:checked')].map(input=>input.value);
  const singleEvents=()=>{const value=q('stateType').value;return value==='normal'?[]:value==='composite'?names():[value]};
  const batchEvents=()=>{const value=q('lifecycleBatchState').value;return value==='normal'?[]:value==='composite'?[...batch.querySelectorAll('[data-batch-event]:checked')].map(input=>input.value):[value]};
  function syncBatchOffsetFromSelection(force=false){
    const input=q('lifecycleBatchOffset'),hint=q('lifecycleBatchOffsetHint'),label=q('lifecycleBatchOffsetLabel');
    if(!input||!hint||!label)return;
    const events=batchEvents(),shifted=events.includes('shifted');
    hint.hidden=!shifted;input.removeAttribute('data-mixed');label.removeAttribute('data-mixed');
    if(!shifted){hint.textContent='';return}
    const selectedItems=[...selected].map(tube=>scopeItems.find(item=>Number(item.thimble_id)===tube)).filter(Boolean);
    const shiftedItems=selectedItems.filter(item=>Array.isArray(item.current_events)&&item.current_events.includes('shifted'));
    const values=shiftedItems.map(item=>{
      const value=item.maintenance_offset_mm;
      if(value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value)))return {value:Number(value),uncertain:false};
      const unsigned=item.maintenance_unsigned_offset_mm;
      if(unsigned!==null&&unsigned!==undefined&&unsigned!==''&&Number.isFinite(Number(unsigned)))return {value:Number(unsigned),uncertain:true};
      return null;
    }).filter(Boolean);
    const unique=[...new Set(values.filter(item=>!item.uncertain).map(item=>item.value))];
    const hasUnknown=values.some(item=>item.uncertain)||shiftedItems.length>values.length;
    const hasUnshiftedSelection=selectedItems.length>shiftedItems.length;
    const mixed=unique.length>1||(unique.length>0&&hasUnknown)||hasUnshiftedSelection;
    if(!force&&batchOffsetTouched){
      if(mixed){input.dataset.mixed='true';label.dataset.mixed='true';hint.textContent='已选移位管的距离不一致；已保留你手动填写的统一距离，请确认适用于全部所选管。'}
      else hint.textContent='已保留你手动填写的统一距离。';
      return;
    }
    if(!values.length){
      input.value='';input.placeholder='正数正向，负数反向；未知可留空';
      hint.textContent=shiftedItems.length?'选中的移位记录没有可直接套用的有符号距离，请按原始依据填写。':'';
    }else if(mixed&&hasUnshiftedSelection&&unique.length<=1&&!hasUnknown){
      input.value='';input.placeholder='请确认并填写本批统一移位距离';input.dataset.mixed='true';label.dataset.mixed='true';
      hint.textContent='选中管中包含没有本次移位距离的管子；为避免把已有距离误用到其他管，请确认并填写统一距离。';
    }else if(mixed){
      input.value='';input.placeholder='选中管子的移位距离不一致，请填写统一距离';input.dataset.mixed='true';label.dataset.mixed='true';
      hint.textContent='已选移位管的距离不一致，当前不会自动带入任何一个值；请填写本批统一距离，或留空标记待核对。';
    }else if(unique.length===1&&!hasUnknown){
      input.value=String(unique[0]);input.placeholder='已同步选中管的共同移位距离';
      hint.textContent=`已同步共同距离 ${unique[0]>0?'+':''}${unique[0]} mm；如需统一改写可直接编辑。`;
    }else{
      input.value='';input.placeholder='选中管子的距离待核对，请填写统一距离';input.dataset.mixed='true';label.dataset.mixed='true';
      hint.textContent='选中管包含方向未确认或缺少距离的记录，请按原始依据填写统一距离。';
    }
  }
  const ruleText=events=>events.includes('replaced')&&events.length>1?'换管与其他处理同次发生，请确认发生在换管前还是换管后；未知时标记待核对。':events.includes('replaced')?'换管是独立状态，将建立新的管子代次并保留历史。':events.includes('plugged')?'堵管与移位不同，会持续到明确换管；正常不会解除历史堵管。':events.includes('shifted')?'移位请按原始依据填写距离和方向，正数为正向、负数为反向，未知可留空并标记待核对。':'正常表示本次有明确依据确认正常；未维护不等于正常，历史堵管不会因此解除。';
  function updateSingle(){
    const events=singleEvents(),shifted=events.includes('shifted');
    fields.hidden=q('stateType').value!=='composite';
    q('stateOffsetLabel').hidden=!shifted;q('stateOffset').disabled=!shifted;
    q('stateOffsetLabel').firstChild.textContent='移位距离（mm，正数正向 / 负数反向）';
    q('stateOffset').placeholder=shifted?(q('stateOffset').dataset.unsignedOffset?`${q('stateOffset').dataset.unsignedOffset} mm（方向未注明）`:'请填写距离和方向；未知可留空'):'' ;
    q('lifecycleStageLabel').hidden=!(events.includes('replaced')&&events.length>1);
    q('lifecycleRule').textContent=ruleText(events);
    q('stateRule').hidden=!fields.hidden;q('stateRule').textContent=ruleText(events);
  }
  function update(){
    const active=q('lifecycleBatchMode').checked,events=batchEvents(),locked=busy||q('states').getAttribute('aria-busy')==='true';
    const currentTube=Number(q('stateThimble').value);
    batch.hidden=!active;q('lifecycleBatchEvents').hidden=q('lifecycleBatchState').value!=='composite';
    q('lifecycleBatchOffsetLabel').hidden=!events.includes('shifted');
    q('lifecycleBatchStageLabel').hidden=!(events.includes('replaced')&&events.length>1);
    syncBatchOffsetFromSelection(false);
    const offsetHint=q('lifecycleBatchOffsetHint');
    q('lifecycleBatchRule').textContent=ruleText(events)+(events.length?' 保存时追加本次处理并保留原备注和来源。':' 仅处理本次未维护且无历史堵管、待核对问题的管。');
    if(offsetHint&&!offsetHint.hidden&&offsetHint.textContent)q('lifecycleBatchRule').textContent+=` ${offsetHint.textContent}`;
    root.classList.toggle('batch-edit-active',active);
    if(editorPanel){
      const heading=editorPanel.querySelector('.panel-title h2'),subheading=editorPanel.querySelector('.panel-title span');
      if(heading)heading.textContent=active?'批量处理':'管状态处理';
      if(subheading)subheading.textContent=active?`已选 ${selected.size} 根`:'选择管号后编辑并保存';
    }
    const selectionSummary=q('lifecycleBatchSelectionSummary');
    if(selectionSummary)selectionSummary.textContent=selected.size?`已选管号：${[...selected].sort((a,b)=>a-b).map(t=>String(t).padStart(2,'0')).join('、')}`:'已选管号：—';
    q('lifecycleSelected').textContent=`已选${selected.size}根`;
    grid.dataset.batchActive=String(active);
    const canUseCurrent=active&&currentTube>=1&&currentTube<=50;
    q('lifecyclePreview').disabled=!active||!selected.size||locked;
    const actionCount=active?selected.size:0;
    const actionLabel=actionCount?`处理所选（${actionCount}）`:'处理所选';
    q('lifecyclePreview').textContent=actionLabel;
    q('lifecyclePreview').setAttribute('aria-label',actionCount?`${actionLabel}；下一步先预览影响，确认后保存`:'执行批量处理；请先开启批量选择并选中管子');
    q('lifecyclePreview').title=locked?'当前正在读取或保存，请稍候':active?'处理所选管号；下一步先预览影响，确认后保存':'请先开启批量选择；单管请使用下方“保存状态”';
    q('lifecycleClear').disabled=!selected.size||locked;
    for(const control of batch.querySelectorAll('input,select,textarea'))control.disabled=locked;
    grid.querySelectorAll('[data-tube]').forEach(button=>{
      const chosen=active&&selected.has(Number(button.dataset.tube));button.classList.toggle('batch-selected',chosen);
      button.setAttribute('aria-pressed',String(active?chosen:Number(button.dataset.tube)===Number(q('stateThimble').value)));
    });
    drawSummary();
  }
  function drawSummary(){
    scopeNotice.hidden=scopeStatus!=='error';
    if(scopeStatus==='error')scopeNotice.innerHTML=`<span>历史有效状态读取失败：${escape(scopeError)}</span> <button type="button" id="lifecycleRetry">重新读取</button>`;
    else scopeNotice.replaceChildren();
    summary.setAttribute('aria-busy',String(scopeStatus==='loading'));
    summary.dataset.warning=String(scopeStatus==='error');
    if(scopeStatus==='loading'){summary.textContent='正在读取历史有效状态…';return}
    if(scopeStatus==='error'){
      summary.textContent=`历史有效状态读取失败：${scopeError}`;
      return;
    }
    const item=scopeItems.find(row=>row.thimble_id===Number(q('stateThimble').value));
    const facts=item?[
      ['本次处理',item.maintained?(item.current_events.map(event=>labels[event]).join(' · ')||'正常'):'未维护'],
      ['截至本次有效',item.state_label],
      ['管子代次',`第${item.generation}代管`],
      ['本代累计位移',item.cumulative_offset_mm==null?'待核对':`${item.cumulative_offset_mm>0?'+':''}${item.cumulative_offset_mm} mm`]
    ]:[];
    summary.innerHTML=item?`<dl class="lifecycle-facts">${facts.map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>
      ${item.plug_since?`<p class="lifecycle-plug-since">自 ${escape(item.plug_since)} 堵管</p>`:''}
      ${item.warnings.length?`<ul class="lifecycle-fact-warnings">${item.warnings.map(warning=>`<li>${escape(warning)}</li>`).join('')}</ul>`:''}`:'请选择管号';
    summary.dataset.warning=String(!!(item?.plugged||item?.needs_review));
  }
  function paintScope(){
    grid.dataset.historyStatus=scopeStatus;
    grid.setAttribute('aria-busy',String(scopeStatus==='loading'));
    for(const button of grid.querySelectorAll('[data-tube]')){
      if(scopeStatus==='loading'||scopeStatus==='error'){
        const message=scopeStatus==='loading'?'读取中':'读取失败';
        button.dataset.state='unknown';button.dataset.review='false';
        button.querySelector('small').textContent=message;
        button.title=`${button.dataset.tube}号管 · 历史有效状态${message}`;
        button.setAttribute('aria-label',button.title);
        const tooltip=button.querySelector('.state-tube-tooltip');if(tooltip)tooltip.textContent=button.title;
        continue;
      }
      const item=scopeItems.find(row=>row.thimble_id===Number(button.dataset.tube));if(!item)continue;
      const events=item.current_events,current=item.maintained?(events.map(event=>labels[event]).join(' · ')||'正常'):'未维护';
      const currentState=item.maintained?(events.includes('plugged')?'plugged':events.includes('replaced')?'replaced':events.includes('shifted')?'shifted':'normal'):'unknown';
      button.dataset.state=gridView==='current'?currentState:item.state;
      button.dataset.review=String(item.needs_review&&(gridView==='effective'||item.maintained));
      button.querySelector('small').textContent=gridView==='current'?current:item.state_label;
      button.title=`${item.thimble_id}号管 · 本次：${current} · 截至本次：${item.state_label} · 第${item.generation}代${item.plug_since?` · 自${item.plug_since}堵管`:''}${item.cumulative_offset_mm==null?' · 累计位移待核对':` · 累计位移${item.cumulative_offset_mm} mm`}`;
      if(item.warnings.length)button.title+=` · ${item.warnings.join('；')}`;
      button.setAttribute('aria-label',button.title);
      const tooltip=button.querySelector('.state-tube-tooltip');if(tooltip)tooltip.textContent=button.title;
    }
    update();
  }
  async function refresh(force=false){
    const key=[q('stateOutage').value,q('stateUnit').value].join('|');
    if(key!==scopeKey){selected.clear();scopeItems=[]}
    if(!q('stateOutage').value||!q('stateUnit').value){
      scopeController?.abort();scopeController=null;scopePromise=null;
      scopeKey=key;requestId++;scopeStatus='idle';scopeError='';paintScope();return false;
    }
    if(!force&&key===scopeKey){paintScope();return scopePromise||scopeStatus==='ready'}
    scopeController?.abort();
    scopeKey=key;const id=++requestId;
    const controller=new AbortController();scopeController=controller;
    scopeItems=[];scopeStatus='loading';scopeError='';paintScope();
    const timeout=setTimeout(()=>controller.abort(),20000);
    const pending=(async()=>{
      try{
        const data=await window.api(`/api/states/scope?outage=${encodeURIComponent(q('stateOutage').value)}&unit_id=${q('stateUnit').value}&details=maintenance`,{signal:controller.signal});
        if(id!==requestId||key!==scopeKey)return false;
        scopeItems=data.items;scopeStatus='ready';paintScope();return true;
      }catch(error){
        if(id!==requestId||key!==scopeKey)return false;
        scopeItems=[];scopeStatus='error';
        scopeError=controller.signal.aborted?'读取超时，请重试':error.message;
        paintScope();return false;
      }finally{
        clearTimeout(timeout);
        if(id===requestId){scopeController=null;scopePromise=null}
      }
    })();
    scopePromise=pending;return pending;
  }
  view.addEventListener('click',event=>{
    const button=event.target.closest('[data-grid-view]');if(!button)return;gridView=button.dataset.gridView;
    view.querySelectorAll('[data-grid-view]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
    q('stateGridCaption').textContent=gridView==='current'?'仅本次维护记录；未维护不代表正常。':'历史堵管延续至明确换管；无记录不视为正常。';paintScope();
  });
  fields.onchange=updateSingle;
  batch.onchange=event=>{if(event.target.matches('#lifecycleBatchState,[data-batch-event]'))batchOffsetTouched=false;update()};
  q('lifecycleBatchOffset').addEventListener('input',()=>{batchOffsetTouched=true;q('lifecycleBatchOffset').removeAttribute('data-mixed');q('lifecycleBatchOffsetLabel').removeAttribute('data-mixed')});
  q('stateType').addEventListener('change',()=>{
    const value=q('stateType').value;
    if(value!=='composite')fields.querySelectorAll('[data-maintenance-event]').forEach(input=>input.checked=input.value===value);
    q('lifecycleStage').value='unknown';updateSingle();
  });
  function edit(record){
    original=record||null;
    const values=record?.events||(record?.state&&record.state!=='normal'?[record.state]:[]);
    q('stateType').value=values.length>1?'composite':values[0]||'normal';
    fields.querySelectorAll('[data-maintenance-event]').forEach(input=>input.checked=values.includes(input.value));
    q('lifecycleStage').value=record?.replacement_stage||'unknown';updateSingle();drawSummary();
  }
  function payload(){
    const events=singleEvents();
    return {events,replacement_stage:q('lifecycleStage').value,
      state:events.includes('plugged')?'plugged':events.includes('replaced')?'replaced':events.includes('shifted')?'shifted':'normal',
      offset_mm:events.includes('shifted')?(q('stateOffset').value===''?null:Number(q('stateOffset').value)):0,
      expected_updated_at:original?.updated_at??null};
  }
  function validateSingle(){
    if(q('stateType').value==='composite'&&singleEvents().length<2)return '复合处理请至少选择两项；单项处理请直接选择对应状态。';
    return '';
  }
  const applyDragTube=button=>{
    const tube=Number(button.dataset.tube);
    if(!dragSelection||dragSelection.lastTube===tube)return;
    dragSelection.moved=dragSelection.moved||tube!==dragSelection.startTube;
    dragSelection.lastTube=tube;
    if(dragSelection.add)selected.add(tube);else selected.delete(tube);
    update();
  };
  grid.addEventListener('pointerdown',event=>{
    const button=event.target.closest('[data-tube]');
    if(!button||!q('lifecycleBatchMode').checked||event.button!==0)return;
    const tube=Number(button.dataset.tube);
    dragSelection={pointerId:event.pointerId,startTube:tube,lastTube:tube,add:!selected.has(tube),moved:false};
    suppressPointerClick=false;
    button.focus({preventScroll:true});
    event.preventDefault();
    if(dragSelection.add)selected.add(tube);else selected.delete(tube);
    update();
  });
  grid.addEventListener('pointerover',event=>{
    if(!dragSelection||event.pointerId!==dragSelection.pointerId||!(event.buttons&1))return;
    const button=event.target.closest('[data-tube]');
    if(button)applyDragTube(button);
  });
  document.addEventListener('pointerup',event=>{
    if(!dragSelection||event.pointerId!==dragSelection.pointerId)return;
    suppressPointerClick=true;
    dragSelection=null;
  });
  document.addEventListener('pointercancel',event=>{
    if(dragSelection?.pointerId===event.pointerId)dragSelection=null;
  });
  grid.addEventListener('click',event=>{
    if(!q('lifecycleBatchMode').checked)return;
    if(suppressPointerClick&&event.detail>0){
      suppressPointerClick=false;event.preventDefault();event.stopImmediatePropagation();return;
    }
    const button=event.target.closest('[data-tube]');if(!button)return;
    event.preventDefault();event.stopImmediatePropagation();
    const tube=Number(button.dataset.tube);selected.has(tube)?selected.delete(tube):selected.add(tube);update();
  },true);
  q('lifecycleBatchMode').onchange=()=>{
    if(q('lifecycleBatchMode').checked){
      const current=Number(q('stateThimble').value);
      if(current>=1&&current<=50)selected.add(current);
    }else {selected.clear();batchOffsetTouched=false}
    update();
    window.dispatchEvent(new Event('tube-edit-mode-changed'));
  };
  q('lifecycleSelectAll').onclick=()=>{
    const wasActive=q('lifecycleBatchMode').checked;
    q('lifecycleBatchMode').checked=true;
    for(let i=1;i<=50;i++)selected.add(i);
    update();
    if(!wasActive)window.dispatchEvent(new Event('tube-edit-mode-changed'));
  };
  q('lifecycleClear').onclick=()=>{selected.clear();update()};
  q('lifecyclePreview').onclick=async()=>{
    if(busy||q('states').getAttribute('aria-busy')==='true')return;
    const previewButton=q('lifecyclePreview'),previewLabel=previewButton.textContent;
    let refreshWarning='';
    try{
      if(!q('stateOutage').value||!q('stateUnit').value)throw Error('请先选择基地、机组和大修');
      if(!q('lifecycleBatchMode').checked)throw Error('请先开启“批量选择”；单管编辑请使用下方“保存状态”。');
      if(!selected.size)throw Error('请先选择需要处理的管号');
      const events=batchEvents();
      if(q('lifecycleBatchState').value==='composite'&&events.length<2)throw Error('复合处理请至少选择两项；单项处理请直接选择对应状态。');
      if(events.includes('shifted')&&!q('lifecycleBatchOffset').reportValidity())return;
      const rows=[...selected].sort((a,b)=>a-b).map(thimble_id=>({
        outage:q('stateOutage').value,unit_id:Number(q('stateUnit').value),thimble_id,
        events,state:events.includes('plugged')?'plugged':events.includes('replaced')?'replaced':events.includes('shifted')?'shifted':'normal',
        replacement_stage:q('lifecycleBatchStage').value,
        offset_mm:events.includes('shifted')?(q('lifecycleBatchOffset').value===''?null:Number(q('lifecycleBatchOffset').value)):0,unsigned_offset_mm:null,note:''}));
      // Explicit batch editing is different from the "补齐未维护" action:
      // existing rows may be updated, while history and original evidence remain protected.
      const options={mode:'append',only_unmaintained:false,bulk_edit:true};
      previewNotice?.();previewNotice=null;
      busy=true;window.stateMaintenance?.setBusy(true);update();
      if(q('stateBulkHint'))q('stateBulkHint').textContent=`正在生成批量预览：${rows.length} 根管；单管保存已锁定。`;
      previewButton.textContent='正在读取预览…';previewButton.setAttribute('aria-busy','true');
      const data=await request('/api/states/batch-preview',{rows,...options});
      previewButton.textContent=previewLabel;previewButton.removeAttribute('aria-busy');
      const dialog=document.createElement('dialog');dialog.className='lifecycle-dialog';dialog.dataset.kind='batch';dialog.setAttribute('aria-label','批量维护影响预览');
      const affectedRows=data.rows.map(row=>`<tr><td>${row.thimble_id}</td><td>${escape(row.before.state_label)} · 第${row.before.generation}代</td><td>${escape(row.after.state_label)} · 第${row.after.generation}代</td><td>${row.after.cumulative_offset_mm??'待核对'}</td><td>${escape(row.after.warnings.join('；')||(row.after.inherited_plug?'历史堵管继续有效':''))}</td></tr>`).join('');
      const skippedRows=(data.skipped_rows||[]).map(row=>`<tr class="lifecycle-skipped"><td>${row.thimble_id}</td><td colspan="3">跳过，不修改</td><td>${escape(row.reason)}</td></tr>`).join('');
      dialog.innerHTML=`<form method="dialog"><h2>批量维护影响预览</h2><p>${escape(rows[0].outage)} · ${rows[0].unit_id}号机 · 已选 ${rows.length} 根 · 可保存 ${data.affected} 根 · 跳过 ${data.skipped} 根。确认后更新本次记录；原备注、来源和历史审计保留。</p><div class="lifecycle-preview-summary"><b>统一处理：</b>${escape(labels[rows[0].state]||'复合处理')}${rows[0].offset_mm!=null&&rows[0].events.includes('shifted')?` · ${rows[0].offset_mm>0?'+':''}${rows[0].offset_mm} mm`:''}${q('lifecycleBatchNote')?.value?' · 已填写统一备注':''}</div><div class="lifecycle-table"><table><thead><tr><th>管号</th><th>当前有效状态</th><th>保存后有效状态</th><th>本代累计位移(mm)</th><th>提示</th></tr></thead><tbody>${affectedRows}${skippedRows}</tbody></table></div><p class="lifecycle-dialog-error" role="status">${data.affected?'':'没有可保存的管，请核对跳过原因。'}</p><div class="dialog-actions"><button value="cancel" autofocus>返回修改</button><button type="button" class="primary" id="lifecycleCommit" ${data.affected?'':'disabled'}>确认保存${data.affected}根</button></div></form>`;
      document.body.append(dialog);
      let saving=false;
      const status=dialog.querySelector('.lifecycle-dialog-error'),noteInput=q('lifecycleBatchNote'),cancel=dialog.querySelector('[value=cancel]');
      dialog.addEventListener('cancel',event=>{if(saving)event.preventDefault()});
      dialog.querySelector('#lifecycleCommit').onclick=async event=>{
        if(saving)return;
        const button=event.currentTarget,label=button.textContent;
        saving=true;dialog.setAttribute('aria-busy','true');
        button.disabled=true;cancel.disabled=true;noteInput.disabled=true;button.textContent='正在保存…';
        status.dataset.kind='progress';status.textContent='正在保存维护记录，请稍候…';
        let result;
        try{
          result=await request('/api/states/batch',{rows:rows.map(row=>({...row,note:noteInput?.value||''})),...options,confirmed:true,revision:data.revision});
        }catch(error){
          saving=false;dialog.setAttribute('aria-busy','false');
          status.dataset.kind='error';status.textContent=`保存未完成：${error.message}`;
          button.disabled=false;cancel.disabled=false;noteInput.disabled=false;button.textContent=label;button.focus();
          return;
        }
        selected.clear();status.textContent='维护记录已保存，正在刷新显示…';
        window.dispatchEvent(new Event('tube-state-changed'));
        if(q('stateBulkHint'))q('stateBulkHint').textContent=`批量维护已保存 ${result.changed} 根，跳过 ${result.skipped} 根；正在刷新当前范围。`;
        try{
          const refreshed=await window.loadStates(),historyRefreshed=await refresh(true);
          if(!refreshed)throw new Error('状态列表加载失败');
          if(!historyRefreshed)throw new Error(scopeError||'历史有效状态加载失败');
          window.toast(`已保存 ${result.changed} 根，跳过 ${result.skipped} 根；${data.warnings?'仍有待核对项，请查看管位提示':'历史记录已保留'}`,{type:data.warnings?'warning':'success'});
        }catch(error){refreshWarning=`批量维护已保存，但刷新失败：${error.message}；无需重复保存，请重新加载。`;if(q('stateBulkHint'))q('stateBulkHint').textContent=refreshWarning;window.toast(`维护记录已保存，刷新显示失败：${error.message}。请重新加载记录，无需重复保存。`,{type:'warning'})}
        finally{dialog.close('saved')}
      };
      await new Promise(resolve=>{dialog.addEventListener('close',resolve,{once:true});dialog.showModal()});dialog.remove();
    }catch(error){if(q('stateBulkHint'))q('stateBulkHint').textContent=`批量操作未完成：${error.message}；可修改后重试。`;previewNotice=window.toast(error.message,{type:busy?'error':'warning'})}
    finally{
      if(busy){busy=false;window.stateMaintenance?.setBusy(false)}
      previewButton.textContent=previewLabel;previewButton.removeAttribute('aria-busy');update();
      if(refreshWarning&&q('stateBulkHint'))q('stateBulkHint').textContent=refreshWarning;
    }
  };
  history.onclick=async()=>{
    try{
      const tube=Number(q('stateThimble').value),outage=q('stateOutage').value,unit=q('stateUnit').value;
      if(!tube||!outage)throw Error('请先选择管号');
      const site=outage.match(/^[A-Z]+/)[0],data=await request(`/api/state-history?site=${site}&unit_id=${unit}&thimble_id=${tube}`);
      const describe=raw=>{
        if(!raw)return '无记录';const row=JSON.parse(raw),events=row.events_json==null?(row.state==='normal'?[]:[row.state]):JSON.parse(row.events_json);
        return `${row.is_deleted?'已撤销 · ':''}${events.map(event=>labels[event]).join(' · ')||'正常'}${events.includes('shifted')?` · ${row.offset_confirmed===0?'距离或方向待核对':`${row.offset_mm} mm`}`:''}${row.replacement_stage==='before_replacement'?' · 其他处理在换管前':row.replacement_stage==='after_replacement'?' · 其他处理在换管后':''}${row.note?` · ${row.note}`:''}${row.source?` · 来源：${row.source}`:''}`;
      };
      const dialog=document.createElement('dialog');dialog.className='lifecycle-dialog';dialog.setAttribute('aria-label','单管维护历史');
      dialog.innerHTML=`<form method="dialog"><h2>${escape(site)} · ${unit}号机 · ${tube}号管维护历史</h2><p>按大修顺序展示处理后的状态；无新处理时堵管、位移继续沿用。原始检测记录保留。</p><div class="lifecycle-table"><table><thead><tr><th>大修</th><th>本次处理</th><th>处理后状态</th><th>管子代次</th><th>累计位移(mm)</th><th>原始备注 / 提示</th></tr></thead><tbody>${(data.timeline||[]).map(row=>`<tr><td>${escape(row.outage)}</td><td>${escape(row.event_label)}</td><td>${escape(row.effective.state_label)}</td><td>第${row.effective.generation}代</td><td>${row.effective.cumulative_offset_mm??'待核对'}</td><td>${escape([row.note,...row.effective.warnings].filter(Boolean).join('；'))}</td></tr>`).join('')||'<tr><td colspan="6">暂无有效维护记录</td></tr>'}</tbody></table></div><details><summary>修改与撤销明细（最近200次）</summary><div class="lifecycle-table"><table><thead><tr><th>维护时间</th><th>大修</th><th>操作者</th><th>修改前</th><th>修改后</th></tr></thead><tbody>${data.items.map(row=>`<tr><td>${escape(window.formatDateTime?.(row.created_at)||row.created_at)}</td><td>${escape(row.outage)}</td><td>${escape(row.operator)}</td><td>${escape(describe(row.before_json))}</td><td>${escape(describe(row.after_json))}</td></tr>`).join('')||'<tr><td colspan="5">暂无修改记录</td></tr>'}</tbody></table></div></details><div class="dialog-actions"><button value="close">关闭</button></div></form>`;
      document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
    }catch(error){window.toast(error.message)}
  };
  window.tubeLifecycle={payload,edit,refresh,validate:validateSingle,hasShift:()=>singleEvents().includes('shifted'),sync:updateSingle};
  window.addEventListener('tube-state-changed',()=>refresh(true));
  q('stateThimble').addEventListener('input',()=>{drawSummary();update()});
  edit(null);refresh();
})();
