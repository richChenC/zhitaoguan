const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
(()=>{
  const density=localStorage.getItem('thimbleUiDensity');
  const motion=localStorage.getItem('thimbleReduceMotion');
  document.documentElement.dataset.theme=localStorage.getItem('thimbleAppearance')==='dark'?'dark':'light';
  if(density==='compact'||density==='standard')document.body.dataset.uiDensity=density;
  document.body.dataset.reduceMotion=motion==='true'?'true':'false';
})();
// Presentation only: never use this formatter when persisting source notes.
function displayTableValue(value){
  return value==null||String(value).trim()===''||/^[-—–]+$/.test(String(value).trim())?'/':String(value);
}
const displayDateTime=value=>window.formatDateTime?window.formatDateTime(value):displayTableValue(value);
function displayTableCell(value){
  return displayTableValue(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function displayPercent(value){const text=displayTableValue(value);return text==='/'?text:`${text}%`}
function measurementCell(value,suffix=''){const text=displayTableValue(value);return `<td${text==='/'?' class="empty-value"':''}>${displayTableCell(value)}${text==='/'?'':suffix}</td>`}
function editableCell(value,field,suffix=''){const text=displayTableValue(value);return `<td class="ledger-editable" data-edit-field="${field}" title="${displayTableCell(text)}">${displayTableCell(text)}${text==='/'?'':suffix}</td>`}
// Expose shared helpers for late-loaded UI enhancement modules.
const state={page:1,pages:1,size:100,items:[],coreItems:[],selected:null,selectedIds:new Set(),selectedRecords:new Map(),selectionScope:'',overview:null};
const workspaceColumnFilters={};
// 稳层防护：主窗口关闭前由主进程查询此函数；有未提交的行内编辑时先弹确认，
// 避免直接关窗静默丢失修改。不用 beforeunload——Electron 中它只会让关闭“无反应”。
window.__thimbleUnsavedEdits=()=>Boolean(document.querySelector('.inline-finding-editor')||stateListDirty);
const api=async(url,options={})=>{const r=await fetch(url,{...options,headers:{'Content-Type':'application/json',...options.headers}});let data;try{data=await r.json()}catch{throw new Error(`本地服务未返回有效数据（${r.status}），请重试`)}if(!r.ok){const error=new Error(data.error||`请求失败（${r.status}），请重试`);error.details=data;error.batchId=data.batch_id;throw error}if(options.method==='POST'&&['/api/state','/api/state-delete'].includes(url))window.dispatchEvent(new CustomEvent('tube-state-changed'));if(options.method==='POST'&&url==='/api/import')window.dispatchEvent(new Event('data-imported'));return data};
let toastTimer;
const toast=(msg,options={})=>{if(window.appFeedback)return window.appFeedback.notify(msg,options);const e=$('#toast');clearTimeout(toastTimer);e.textContent=msg;e.setAttribute('role','status');e.classList.add('show');toastTimer=setTimeout(()=>e.classList.remove('show'),3000)};
function params(){const p=new URLSearchParams({page:state.page,size:state.size});['site','outage','unit','analyst','thimble'].forEach(id=>{const v=$('#'+id).value.trim();if(v)p.set(id,v)});Object.entries(workspaceColumnFilters).forEach(([field,value])=>p.set(`column_${field}`,value));return p}
function selectedRecords(){return [...state.selectedRecords.values()]}
const canonicalSite=value=>({H:'H',LHNP:'H',D:'D',CNPS:'D',L:'L',LNPS:'L',N:'N',NDNP:'N',Y:'Y',YJNP:'Y',F:'F',BLNP:'F',T:'T',TSNP:'T',P:'P',HENP:'P',C:'C',CNMP:'C',LF:'LF',LFNP:'LF'})[String(value??'').trim().toUpperCase()]||String(value??'').trim().toUpperCase()
function clearSelectionState(){state.selectedIds.clear();state.selectedRecords.clear();state.selected=null}
function selectionScopeKey(){return ['site','outage','unit','analyst','thimble'].map(id=>$('#'+id)?.value?.trim()||'').join('|')+'|'+JSON.stringify(workspaceColumnFilters)}
function selectionVisualization(){const records=selectedRecords(),sites=new Set(records.map(row=>canonicalSite(row.site_code||row.site||row.outage?.match?.(/^[A-Za-z]+/)?.[0]))),units=new Set(records.map(row=>String(row.unit_id))),outages=new Set(records.map(row=>String(row.outage)));return{records,sites,units,outages,ready:records.length>0&&sites.size===1&&units.size===1&&outages.size===1}}
function sameVisualizationScope(left,right){return canonicalSite(left?.site_code||left?.site||left?.outage?.match?.(/^[A-Za-z]+/)?.[0])===canonicalSite(right?.site_code||right?.site||right?.outage?.match?.(/^[A-Za-z]+/)?.[0])&&String(left?.unit_id||'')===String(right?.unit_id||'')&&String(left?.outage||'')===String(right?.outage||'')}
function visualSelectionRecords(){const selection=selectionVisualization();return selection.ready?selection.records:[]}
function notifyThreeView(){const selection=selectionVisualization();window.dispatchEvent(new CustomEvent('workspace-filter-changed',{detail:{site:$('#site').value,unit:$('#unit').value,outage:$('#outage').value,thimble:$('#thimble').value,items:state.items,selectedItems:selection.ready?selection.records:[],selectionBlocked:selection.records.length>0&&!selection.ready}}))}
let overviewRequest=0;
async function loadOverview({refreshStates=true}={}){
  const request=++overviewRequest;
  let data;
  try{data=await api('/api/overview')}catch(error){if(request===overviewRequest)throw error;return}
  if(request!==overviewRequest)return;
  state.overview=data;
  refill('site',data.sites,'全部基地');refreshMainFilters();
  if(window.stateMaintenance)window.stateMaintenance.overview();
  else{fill($('#stateOutage'),data.outages,'选择大修');fill($('#stateUnit'),data.units,'选择机组')}
  if(refreshStates)loadStates().catch(()=>{});
}
let stateListRequest=0;
let stateListItems=[],stateDeleting=false,stateMutationBusy=false,statePage=1,statePageSize=50,stateFilteredTotal=0,stateListDirty=false,stateFilterCommitted=null;
let stateSearchPending=false;
const stateSelected=new Map();
const stateRowKey=row=>[row.outage,row.unit_id,row.thimble_id].join('|');
function stateFilterValues(){
  return {
    site:$('#stateFilterSite')?.value||'',
    outage:$('#stateFilterOutage')?.value||'',
    unit:$('#stateFilterUnit')?.value||'',
    type:$('#stateFilterType')?.value||'',
    search:$('#stateFilterSearch')?.value||''
  };
}
function restoreStateFilterValues(values){
  if(!values)return;
  for(const [id,value] of Object.entries({
    stateFilterSite:values.site,stateFilterOutage:values.outage,stateFilterUnit:values.unit,
    stateFilterType:values.type
  })){const element=$('#'+id);if(element)element.value=value}
  window.stateTableFilterSync?.();
  const search=$('#stateFilterSearch');if(search)search.value=values.search||'';
}
function refreshStateListDirty(){
  stateListDirty=$$('#stateRows .inline-state,#stateRows .inline-offset,#stateRows .inline-note')
    .some(input=>input.value!==input.dataset.originalValue);
}
async function confirmStateListReload(reason='重新加载'){
  refreshStateListDirty();
  if(!stateListDirty)return true;
  const confirmed=await askConfirm(
    `当前状态维护表有未保存的修改。${reason}会丢弃这些修改，已保存的数据不受影响。`,
    {title:'未保存的维护修改',confirmLabel:'丢弃修改并继续'}
  );
  if(confirmed)stateListDirty=false;
  return confirmed;
}
function originalStateNote(input, original=input.dataset.originalNote){
  const raw=String(original??'');
  return input.value===raw.replace(/\r\n?/g,'\n')?raw:input.value;
}
function refreshStateSelection(){
  const total=stateListItems.length,count=stateSelected.size,all=$('#stateSelectAll'),button=$('#stateDeleteSelected');
  if(!button)return;
  const busy=stateSearchPending||stateDeleting||stateMutationBusy||$('#stateRows').getAttribute('aria-busy')==='true'||$('#stateRows').dataset.stale==='true';
  button.disabled=busy||!count;
  $('#stateSelectionCount').textContent=stateSearchPending?'正在应用搜索条件…':`筛选 ${stateFilteredTotal} 条 · 已选 ${count} 条`;
  $('#statePagePrev').disabled=busy||statePage<=1;
  $('#statePageNext').disabled=busy||statePage>=Math.max(1,Math.ceil(stateFilteredTotal/statePageSize));
  $('#statePageSize').disabled=busy;
  if(all){all.checked=total>0&&count===total;all.indeterminate=count>0&&count<total;all.disabled=busy||!total;}
  $$('#stateRows [data-state-select]').forEach(input=>{input.checked=stateSelected.has(input.dataset.key);input.disabled=busy;input.closest('tr').classList.toggle('state-row-selected',input.checked)});
}
async function deleteSelectedStates(){
  if(stateDeleting||!stateSelected.size)return;
  const preservedSelection=new Map(stateSelected);
  stateDeleting=true;refreshStateSelection();window.stateMaintenance?.setBusy(true);
  const rows=[...stateSelected.values()],outages=unique(rows.map(r=>r.outage));
  try{
    const range=outages.length<=6?outages.join('、'):`${outages.slice(0,6).join('、')}等 ${outages.length} 次大修`;
    if(!await askConfirm(`确认删除已勾选的 ${rows.length} 条管状态维护记录？\n范围：${range}。\n删除后对应管恢复为未维护；检测数据保留，删除过程记入状态审计记录。`,{title:'批量删除维护记录',danger:true,confirmLabel:`删除 ${rows.length} 条`})){
      stateSelected.clear();
      preservedSelection.forEach((value,key)=>stateSelected.set(key,value));
      $$('#stateRows [data-state-select]').forEach(input=>{
        const selected=stateSelected.has(input.dataset.key);
        input.checked=selected;
        input.closest('tr')?.classList.toggle('state-row-selected',selected);
      });
      refreshStateSelection();
      return;
    }
    const result=await api('/api/states/delete-batch',{method:'POST',body:JSON.stringify({rows,confirmed:true})});
    const refreshed=await loadStates({discardDraftKeys:rows.map(stateRowKey)});
    if(rows.some(row=>row.outage===$('#stateOutage').value&&String(row.unit_id)===$('#stateUnit').value&&String(row.thimble_id)===$('#stateThimble').value))window.stateMaintenance?.reset();
    window.dispatchEvent(new Event('tube-state-changed'));toast(refreshed?`已删除 ${result.deleted} 条维护记录`:`已删除 ${result.deleted} 条维护记录，但列表刷新失败。请重新加载，无需重复删除。`,{type:refreshed?'success':'warning'});
  }catch(error){toast(error.message,{type:'error'});await loadStates()}
  finally{stateDeleting=false;window.stateMaintenance?.setBusy(false);refreshStateSelection()}
}
function mountStateFilters(){
  if($('#stateFilterOutage')){
    syncStateTableFilters();
    return;
  }
  $('.state-table-panel .panel-title').insertAdjacentHTML('afterend','<div class="state-table-toolbar"><select id="stateFilterOutage" aria-label="筛选大修"></select><select id="stateFilterUnit" aria-label="筛选机组"></select><select id="stateFilterType" aria-label="筛选状态"><option value="">全部状态</option><option value="normal">正常</option><option value="plugged">堵管</option><option value="shifted">移位</option><option value="replaced">换管</option><option value="composite">复合处理</option></select><button id="statePickLatest" type="button" title="选择最新大修及对应机组">选最新</button><button id="stateFilterClear" type="button">清除</button></div>');
  $('.state-table-toolbar').insertAdjacentHTML('afterbegin','<select id="stateFilterSite" aria-label="筛选基地"></select>');
  $('.state-table-toolbar').insertAdjacentHTML('beforeend','<input id="stateFilterSearch" type="search" aria-label="搜索管号或备注" placeholder="管号 / 备注"><span id="stateSelectionCount" role="status"></span><button id="stateDeleteSelected" class="danger-outline" type="button" disabled>删除所选</button>');
  $('.state-table-toolbar').insertAdjacentHTML('afterend','<div class="state-category-tabs" role="group" aria-label="维护记录分类"><button type="button" data-state-category="">全部</button><button type="button" data-state-category="normal">正常</button><button type="button" data-state-category="plugged">堵管</button><button type="button" data-state-category="shifted">移位</button><button type="button" data-state-category="replaced">换管</button><button type="button" data-state-category="composite">复合处理</button></div>');
  const syncCategories=()=>document.querySelectorAll('[data-state-category]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.stateCategory===$('#stateFilterType').value)));
  $('.state-category-tabs').onclick=event=>{const button=event.target.closest('[data-state-category]');if(!button)return;$('#stateFilterType').value=button.dataset.stateCategory;$('#stateFilterType').dispatchEvent(new Event('change'))};
  $('.state-table-panel').insertAdjacentHTML('beforeend','<div class="state-list-pager" aria-label="维护记录分页"><label class="state-page-size">每页<select id="statePageSize" aria-label="每页条数"><option value="50">50</option><option value="100">100</option></select>条</label><button id="statePagePrev" type="button" aria-label="上一页">上一页</button><span id="statePageInfo" role="status">1 / 1</span><button id="statePageNext" type="button" aria-label="下一页">下一页</button></div>');
  const head=$('#stateRows').closest('table').querySelector('thead tr');
  const sourceHeading=document.createElement('th');sourceHeading.textContent='来源';head.children[6].before(sourceHeading);
  head.insertAdjacentHTML('afterbegin','<th class="state-select-cell"><input type="checkbox" id="stateSelectAll" aria-label="全选当前页" title="只选择当前页；翻页或筛选后清除选择"></th>');
  $('#stateSelectAll').onchange=event=>{stateSelected.clear();if(event.target.checked)stateListItems.forEach(item=>stateSelected.set(stateRowKey(item),item));refreshStateSelection()};
  $('#stateDeleteSelected').onclick=deleteSelectedStates;
  let searchTimer=0,searchRequest=0;$('#stateFilterSearch').oninput=()=>{
    clearTimeout(searchTimer);
    const request=++searchRequest;
    stateSearchPending=true;
    refreshStateSelection();
    const previous=stateFilterCommitted||stateFilterValues();
    searchTimer=setTimeout(async()=>{
      if(request!==searchRequest)return;
      if(!await confirmStateListReload('搜索')){restoreStateFilterValues(previous);stateSearchPending=false;refreshStateSelection();return}
      statePage=1;stateListRequest++;stateSelected.clear();stateListItems=[];$('#stateRows').setAttribute('aria-busy','true');refreshStateSelection();
      await loadStates({preserveDrafts:false});
      if(request===searchRequest){stateSearchPending=false;refreshStateSelection()}
    },160);
  };
  async function turnPage(page,size=statePageSize){
    if(stateListDirty&&!await askConfirm('当前页有未保存的行内修改。继续翻页将丢弃这些修改，已保存的数据不受影响。',{title:'离开当前页',confirmLabel:'丢弃修改并继续'})){$('#statePageSize').value=String(statePageSize);return}
    statePage=page;statePageSize=size;loadStates({preserveDrafts:false});
  }
  $('#statePageSize').onchange=()=>turnPage(1,Number($('#statePageSize').value)||50);
  $('#statePagePrev').onclick=()=>{if(statePage>1)turnPage(statePage-1)};
  $('#statePageNext').onclick=()=>{if(statePage<Math.max(1,Math.ceil(stateFilteredTotal/statePageSize)))turnPage(statePage+1)};
  $('#stateRows').addEventListener('input',event=>{if(event.target.matches('.inline-state,.inline-offset,.inline-note'))refreshStateListDirty()});
  $('#stateRows').addEventListener('change',event=>{if(event.target.matches('.inline-state,.inline-offset,.inline-note'))refreshStateListDirty()});
  function syncStateTableFilters(){
    const scopes=window.stateMaintenance?.scopes?.()||state.overview?.combinations||[];
    const siteSelect=$('#stateFilterSite'),unitSelect=$('#stateFilterUnit'),outageSelect=$('#stateFilterOutage');
    if(!siteSelect||!unitSelect||!outageSelect)return;
    const previous={site:siteSelect.value,unit:unitSelect.value,outage:outageSelect.value};
    const siteValues=unique(scopes.map(row=>row.site).filter(Boolean));
    fill(siteSelect,siteValues,'全部基地');
    siteSelect.value=siteValues.includes(previous.site)?previous.site:'';
    const scopedBySite=scopes.filter(row=>!siteSelect.value||String(row.site)===String(siteSelect.value));
    const unitValues=unique(scopedBySite.map(row=>row.unit_id).filter(value=>value!==''&&value!=null));
    fill(unitSelect,unitValues,'全部机组');
    unitSelect.value=unitValues.map(String).includes(String(previous.unit))?previous.unit:'';
    const scopedByUnit=scopedBySite.filter(row=>!unitSelect.value||String(row.unit_id)===String(unitSelect.value));
    const outageValues=unique(scopedByUnit.map(row=>row.outage).filter(Boolean));
    fill(outageSelect,outageValues,'全部大修');
    outageSelect.value=outageValues.includes(previous.outage)?previous.outage:'';
    for(const option of siteSelect.options)if(option.value)option.textContent=siteOptionLabel(option.value);
    for(const option of outageSelect.options)if(option.value){
      const match=option.value.match(/(\d{2})$/);
      option.textContent=match?`${option.value}（第${Number(match[1])}次大修）`:option.value;
    }
  }
  window.stateTableFilterSync=syncStateTableFilters;
  syncStateTableFilters();
  ['#stateFilterSite','#stateFilterOutage','#stateFilterUnit','#stateFilterType'].forEach(selector=>$(selector).onchange=async()=>{
    const previous=stateFilterCommitted||stateFilterValues();
    if(selector!=='#stateFilterType')syncStateTableFilters();
    if(!await confirmStateListReload('筛选')){restoreStateFilterValues(previous);syncCategories();return}
    syncCategories();
    statePage=1;
    loadStates({preserveDrafts:false});
  });
  $('#stateFilterClear').onclick=()=>{
    clearTimeout(searchTimer);searchRequest++;
    const previous=stateFilterCommitted||stateFilterValues();
    const clear=async()=>{
      if(!await confirmStateListReload('清除筛选')){restoreStateFilterValues(previous);return}
      ['#stateFilterSite','#stateFilterOutage','#stateFilterUnit','#stateFilterType'].forEach(selector=>$(selector).value='');
      $('#stateFilterSearch').value='';
      syncStateTableFilters();
      syncCategories();
      statePage=1;loadStates({preserveDrafts:false});
    };
    clear();
  };
  $('#statePickLatest').onclick=async()=>{
    const previous=stateFilterCommitted||stateFilterValues();
    if(!await confirmStateListReload('切换到最新大修')){restoreStateFilterValues(previous);return}
    const options=[...$('#stateOutage').options].filter(option=>option.value);
    const latest=options.at(-1)?.value;
    if(!latest)return;
    $('#stateOutage').value=latest;
    const scope=combinations().find(item=>item.outage===latest);
    if(scope)$('#stateUnit').value=String(scope.unit_id);
    if(scope)window.stateMaintenance?.edit({...scope,thimble_id:0});
    $('#stateFilterOutage').value=latest;
    $('#stateFilterUnit').value=scope?String(scope.unit_id):'';
    syncStateTableFilters();
    statePage=1;loadStates({preserveDrafts:false});
  };
  syncCategories();
}
async function loadStates({preserveDrafts=true,discardDraftKeys=[]}={}){
  const host=$('#stateRows');if(!host)return;
  mountStateFilters();
  const committedKeys=new Set(discardDraftKeys);
  const captureDrafts=()=>{
    const drafts=new Map();
    for(const row of preserveDrafts?host.querySelectorAll('tr[data-state-outage]'):[]){
      const key=[row.dataset.stateOutage,row.dataset.stateUnit,row.dataset.stateThimble].join('|');
      if(committedKeys.has(key))continue;
      const fields={};
      for(const input of row.querySelectorAll('.inline-state,.inline-offset,.inline-note')){
        if(input.value!==input.dataset.originalValue)fields[input.className.split(/\s+/).find(name=>name.startsWith('inline-'))]=input.value;
      }
      if(Object.keys(fields).length)drafts.set(key,fields);
    }
    return drafts;
  };
  const request=++stateListRequest;
  host.setAttribute('aria-busy','true');
  stateSelected.clear();stateListItems=[];refreshStateSelection();
  try{
    const data=await api('/api/states');
    if(request!==stateListRequest)return;
    window.stateMaintenance?.records(data.items,data.pending||[],data.scopes||[]);
    mountStateFilters();
    window.stateTableFilterSync?.();
    const outage=$('#stateFilterOutage').value,unit=$('#stateFilterUnit').value,type=$('#stateFilterType').value;
    const site=$('#stateFilterSite').value;
    const term=$('#stateFilterSearch').value.trim().toLowerCase();
    const items=data.items.filter(row=>(!site||row.outage.match(/^[A-Z]+/)?.[0]===site)&&(!outage||String(row.outage)===outage)&&(!unit||String(row.unit_id)===unit)&&(!type||(type==='composite'?(row.events||[]).length>1:row.state===type||(row.events||[]).includes(type)))&&(!term||[row.outage,`#${row.thimble_id}`,row.position,row.note,row.source,row.event_label].some(value=>String(value||'').toLowerCase().includes(term))));
    stateFilteredTotal=items.length;
    const pageCount=Math.max(1,Math.ceil(stateFilteredTotal/statePageSize));
    statePage=Math.min(statePage,pageCount);
    stateListItems=items.slice((statePage-1)*statePageSize,statePage*statePageSize);
    const drafts=captureDrafts(),visibleKeys=new Set(stateListItems.map(stateRowKey));
    if([...drafts.keys()].some(key=>!visibleKeys.has(key))){
      const error=new Error('部分未保存修改对应的记录已不存在或不在当前页');
      error.code='DRAFT_NOT_VISIBLE';throw error;
    }
    stateFilterCommitted=stateFilterValues();
    $('#statePageInfo').textContent=`${statePage} / ${pageCount}`;
    $('#statePagePrev').disabled=statePage<=1;
    $('#statePageNext').disabled=statePage>=pageCount;
    delete host.dataset.stale;host.replaceChildren();
    if(!items.length){
      const row=host.insertRow(),cell=row.insertCell();cell.colSpan=10;cell.className='empty';
      cell.textContent='暂无符合条件的管状态记录';
    }
    for(const item of stateListItems){
      const row=host.insertRow();
      row.dataset.stateOutage=item.outage;row.dataset.stateUnit=item.unit_id;row.dataset.stateThimble=item.thimble_id;
      const selection=row.insertCell(),checkbox=document.createElement('input');selection.className='state-select-cell';checkbox.type='checkbox';checkbox.dataset.stateSelect='';checkbox.dataset.key=stateRowKey(item);checkbox.setAttribute('aria-label',`选择 ${item.outage} 通道${item.thimble_id}`);
      checkbox.onchange=()=>{if(checkbox.checked)stateSelected.set(stateRowKey(item),item);else stateSelected.delete(stateRowKey(item));refreshStateSelection()};selection.append(checkbox);
      [item.outage,item.unit_id,`#${item.thimble_id}${item.position?` · ${item.position}`:''}`].forEach(value=>row.insertCell().textContent=value);
      const select=document.createElement('select');select.className='inline-state';select.setAttribute('aria-label',`${item.outage} 通道${item.thimble_id}状态`);
      for(const [value,label] of Object.entries({normal:'正常',plugged:'堵管',shifted:'移位',replaced:'换管'}))select.add(new Option(label,value));
      select.value=item.state;select.dataset.originalValue=select.value;const stateCell=row.insertCell();stateCell.append(select);
      if((item.events||[]).length>1){
        select.hidden=true;
        const edit=document.createElement('button');edit.type='button';edit.className='state-composite';
        edit.textContent=item.event_label;edit.dataset.events=(item.events||[]).join(',');
        const paint=window.thimbleStateColors;
        if(paint){
          edit.style.background=paint.background(item.events);
          edit.style.borderColor=paint.edge(item.events);
          edit.style.color=paint.ink(item.events);
        }
        edit.onclick=()=>{if(host.dataset.stale==='true')return;window.stateMaintenance?.edit(item);$('#stateForm').scrollIntoView({block:'center',behavior:'smooth'})};
        stateCell.append(edit);
      }
      const offset=document.createElement('input');offset.type='number';offset.step='0.1';offset.min='-1000';offset.max='1000';offset.value=item.offset_mm??'';offset.dataset.originalValue=offset.value;offset.className='inline-offset';offset.setAttribute('aria-label','位移量（mm）');offset.placeholder=item.unsigned_offset_mm!=null?`${item.unsigned_offset_mm}（方向未注明）`:'未注明';offset.title=item.unsigned_offset_mm!=null?`原表距离 ${item.unsigned_offset_mm} mm，方向未注明`:'距离可空；明确方向时填写有符号毫米值';row.insertCell().append(offset);
      const hasShift=()=>select.value===item.state?(item.events||[]).includes('shifted'):select.value==='shifted';
      const updateOffset=()=>{offset.disabled=!hasShift();offset.required=false};select.onchange=updateOffset;updateOffset();
      const note=document.createElement('textarea');note.rows=2;note.className='inline-note';note.value=item.note||'';note.dataset.originalValue=note.value;note.title=note.value;note.setAttribute('aria-label','状态备注');row.insertCell().append(note);
      const sourceCell=row.insertCell();sourceCell.className='state-source-cell';sourceCell.textContent=item.source||'';sourceCell.title=item.source||'';
      row.insertCell().textContent=displayDateTime(item.updated_at);
      const actions=row.insertCell(),save=document.createElement('button'),remove=document.createElement('button');
      save.type=remove.type='button';save.className='state-save';save.dataset.stateSave='';save.textContent='保存';
      remove.className='state-delete danger-outline';remove.dataset.stateDelete='';remove.textContent='撤销';actions.append(save,remove);
      row.onclick=event=>{
        if(host.dataset.stale==='true'||event.target.closest('button,input,select,textarea'))return;
        $('#stateOutage').value=item.outage;$('#stateUnit').value=String(item.unit_id);$('#stateThimble').value=item.thimble_id;
        $('#stateType').value=item.state;$('#stateOffset').value=item.offset_mm??'';$('#stateNote').value=item.note||'';
        window.stateMaintenance?.edit(item);
      };
      const persist=async deleting=>{
        if(deleting&&!await askConfirm('撤销这条维护记录后，将不再作为当前管状态。检测数据和修改审计不会删除。',{title:'撤销管状态维护',confirmLabel:'撤销记录'}))return;
        if(!deleting&&!offset.reportValidity())return;
        stateMutationBusy=true;save.disabled=remove.disabled=true;host.setAttribute('aria-busy','true');refreshStateSelection();window.stateMaintenance?.setBusy(true);
        try{
          const result=await api(deleting?'/api/state-delete':'/api/state',{method:'POST',body:JSON.stringify({
            outage:item.outage,unit_id:item.unit_id,thimble_id:item.thimble_id,expected_updated_at:item.updated_at,
            ...(deleting?{}:{state:select.value,events:select.value===item.state?item.events:(select.value==='normal'?[]:[select.value]),replacement_stage:item.replacement_stage,offset_mm:hasShift()?(offset.value===''?null:Number(offset.value)):0,unsigned_offset_mm:hasShift()&&offset.value===''?item.unsigned_offset_mm:null,note:originalStateNote(note,item.note),source:item.source||''})
          })});
          const refreshed=await loadStates({discardDraftKeys:[stateRowKey(item)]});
          if(deleting&&item.outage===$('#stateOutage').value&&String(item.unit_id)===$('#stateUnit').value&&String(item.thimble_id)===$('#stateThimble').value)window.stateMaintenance?.reset();
          toast(!refreshed?deleting?'维护记录已撤销，但列表刷新失败。请重新加载，无需重复撤销。':'维护记录已保存，但列表刷新失败。请重新加载，无需重复保存。':deleting?'维护记录已撤销':result?.warnings?.length?'管状态已保存，仍有待核对项':'管状态已更新',{type:!refreshed||result?.warnings?.length?'warning':'success'});
        }catch(error){toast(error.message,{type:'error'})}
        finally{save.disabled=remove.disabled=host.dataset.stale==='true';stateMutationBusy=false;host.setAttribute('aria-busy','false');window.stateMaintenance?.setBusy(false);refreshStateSelection()}
      };
      save.title=`保存 ${item.outage} 通道${item.thimble_id} 的修改`;remove.title=`撤销 ${item.outage} 通道${item.thimble_id} 的维护记录`;save.setAttribute('aria-label',save.title);remove.setAttribute('aria-label',remove.title);
      save.onclick=()=>persist(false);remove.onclick=()=>persist(true);
    }
    for(const row of host.querySelectorAll('tr[data-state-outage]')){
      const fields=drafts.get([row.dataset.stateOutage,row.dataset.stateUnit,row.dataset.stateThimble].join('|'));
      if(!fields)continue;
      for(const [className,value] of Object.entries(fields)){
        const input=row.querySelector(`.${className}`);
        if(input)input.value=value;
      }
      if(Object.hasOwn(fields,'inline-state'))row.querySelector('.inline-state')?.dispatchEvent(new Event('change',{bubbles:true}));
    }
    refreshStateListDirty();
    return true;
  }catch(error){
    if(request!==stateListRequest)return;
    const row=document.createElement('tr'),cell=row.insertCell(),retry=document.createElement('button');
    cell.colSpan=10;cell.className='state-load-error';cell.setAttribute('role','status');
    const retained=captureDrafts().size>0;
    const message=document.createElement('span');message.textContent=`状态加载失败：${error.message}`+(retained?'。未保存的修改仍保留，请先记录需要的内容。':'。');
    retry.type='button';retry.textContent=error.code==='DRAFT_NOT_VISIBLE'?'重新加载并放弃修改':'重新加载';retry.onclick=async()=>{
      if(error.code==='DRAFT_NOT_VISIBLE'&&!await confirmStateListReload('重新加载状态'))return;
      if(await loadStates({preserveDrafts:error.code!=='DRAFT_NOT_VISIBLE'})){
        window.stateMaintenance?.saved();
        if($('#stateBulkHint'))$('#stateBulkHint').textContent='状态记录已刷新，可继续修改。';
        toast('状态记录已重新加载',{type:'success'});
      }
    };cell.append(message,retry);
    if(retained){
      host.querySelectorAll('.state-load-error,.state-remote-warning').forEach(cell=>cell.closest('tr')?.remove());
      host.dataset.stale='true';
      host.querySelectorAll('[data-state-save],[data-state-delete],.state-composite').forEach(button=>button.disabled=true);
      host.prepend(row);
    }else{delete host.dataset.stale;host.replaceChildren(row)}
    return false;
  }finally{if(request===stateListRequest){host.setAttribute('aria-busy','false');refreshStateSelection()}}
}
function renderHistoryOverview(items){const chart=$('#historyOverviewChart'),empty=$('#historyOverviewEmpty');if(!chart||!empty)return;const max=Math.max(1,...items.map(item=>item.findings));empty.hidden=items.length>0;chart.hidden=!items.length;chart.innerHTML=items.map(item=>`<button type="button" class="history-bar" data-site="${displayTableCell(item.site)}" data-unit="${displayTableCell(item.unit_id)}" data-outage="${displayTableCell(item.outage)}" title="${displayTableCell(item.outage)} · ${displayTableCell(item.unit_id)}号机：${item.findings}条记录，${item.tubes}根管，${item.analysts}位分析人员"><i style="--level:${Math.max(.08,item.findings/max)}"></i><b>${displayTableCell(item.outage)}</b><small>${item.findings}</small></button>`).join('');$$('#historyOverviewChart .history-bar').forEach(button=>button.onclick=()=>{$('#site').value=button.dataset.site;refreshMainFilters();$('#unit').value=button.dataset.unit;refreshMainFilters();$('#outage').value=button.dataset.outage;state.page=1;loadRows();$$('#historyOverviewChart .history-bar').forEach(x=>x.classList.toggle('active',x===button))})}
const SITE_NAMES={D:'大亚湾',L:'岭澳',N:'宁德',H:'红沿河',F:'防城港',Y:'阳江',T:'台山',P:'惠州',LF:'陆丰',C:'苍南'};
const SITE_DISPLAY_CODES={P:'HZ',C:'CN'};
function siteOptionLabel(value){const code=String(value??'');return `${SITE_NAMES[code]||code}（${SITE_DISPLAY_CODES[code]||code}）`}
function fill(el,values,first){const siteSelector=['site','compareSite','reportSite','stateSite','stateFilterSite'].includes(el?.id);el.innerHTML=(first!==null?`<option value="">${first}</option>`:'')+values.map(v=>{const value=String(v),label=siteSelector?siteOptionLabel(value):value;return `<option value="${displayTableCell(value)}">${displayTableCell(label)}</option>`}).join('')}
function combinations(){return state.overview?.combinations||[]}
function unique(values){return [...new Set(values)].sort((a,b)=>String(a).localeCompare(String(b),'zh-CN',{numeric:true}))}
function refill(id,values,label,preferred){const el=$('#'+id),value=preferred??el.value;fill(el,unique(values),label);if([...el.options].some(option=>String(option.value)===String(value)))el.value=value;return el.value}
function refreshMainFilters(){const site=$('#site').value,unit=$('#unit').value,available=combinations().filter(x=>!site||x.site===site);const selectedUnit=refill('unit',available.map(x=>x.unit_id),'全部机组',unit);refill('outage',available.filter(x=>!selectedUnit||String(x.unit_id)===selectedUnit).map(x=>x.outage),'全部大修')}


function showWorkspaceNotice(title,message,actionLabel,action){
  $('#workspace .split').classList.add('workspace-notice');
  const notice=document.createElement('div');
  notice.className='workspace-feedback';notice.setAttribute('role','status');
  const heading=document.createElement('strong'),description=document.createElement('p');
  heading.textContent=title;description.textContent=message;notice.append(heading,description);
  if(action){const button=document.createElement('button');button.type='button';button.className='primary';button.textContent=actionLabel;button.onclick=action;notice.append(button)}
  const row=document.createElement('tr'),cell=document.createElement('td');
  cell.colSpan=18;cell.className='empty';cell.textContent=title;row.append(cell);
  $('#rows').replaceChildren(row);$('#workspaceEmptyNotice')?.remove();
  notice.id='workspaceEmptyNotice';$('.table-panel .table-wrap').append(notice);
}
function resetWorkspaceFilters(){
  clearTimeout(filterTimer);
  ['site','unit','outage','analyst','thimble'].forEach(id=>$('#'+id).value='');
  Object.keys(workspaceColumnFilters).forEach(key=>delete workspaceColumnFilters[key]);
  updateColumnFilterButtons();
  refreshMainFilters();state.page=1;loadRows().catch(error=>toast(error.message));
}
window.locateMappingRecords=async hint=>{
  clearTimeout(filterTimer);
  Object.keys(workspaceColumnFilters).forEach(key=>delete workspaceColumnFilters[key]);
  updateColumnFilterButtons();
  ['site','unit','outage','analyst','thimble'].forEach(id=>$('#'+id).value='');
  refreshMainFilters();
  const unit=String(hint.unit),outage=String(hint.outage||'');
  if(![...$('#unit').options].some(option=>option.value===unit))throw new Error('当前记录中没有对应机组，请检查导入结果');
  $('#unit').value=unit;refreshMainFilters();
  if(![...$('#outage').options].some(option=>option.value===outage))throw new Error('当前记录中没有对应大修，请检查导入结果');
  $('#outage').value=outage;$('#thimble').value=String(hint.tube);state.page=1;
  document.querySelector('nav [data-view="workspace"]').click();
  await loadRows();
  toast('已筛选同大修、机组和通道的记录，请对照来源逐条核对。');
};
function updateWorkspaceActions(busy=$('#rows').getAttribute('aria-busy')==='true'){
  $('#prevBtn').disabled=busy||state.page<=1;
  $('#nextBtn').disabled=busy||state.page>=state.pages;
  if($('#selectAllRows'))$('#selectAllRows').disabled=busy||!state.items.length;
  if($('#clearPageSelection'))$('#clearPageSelection').disabled=busy||!state.selectedIds.size;
}
async function reloadWorkspace(){try{await loadOverview();await loadRows()}catch(error){toast(error.message)}}
let rowsRequest=0,rowsController,rowsPrefetchController,loadedRowsScope='',loadedRowsPage=1;
const rowsPageCache=new Map();
function cacheRowsPage(key,data){
  rowsPageCache.set(key,data);
  while(rowsPageCache.size>6)rowsPageCache.delete(rowsPageCache.keys().next().value);
}
async function loadRows({pageOnly=false,requireValidFilter=false}={}){
  const tube=$('#thimble'),invalidFilter=Boolean(tube.value&&!tube.checkValidity());
  if(invalidFilter&&!requireValidFilter){tube.reportValidity();return}
  const request=++rowsRequest,host=$('#rows'),scope=selectionScopeKey();
  const keepCore=pageOnly&&loadedRowsScope===scope&&state.items.length>0,previousPage=loadedRowsPage;
  if(!keepCore)rowsPageCache.clear();
  if(state.selectionScope!==scope){clearSelectionState();state.selectionScope=scope}
  rowsController?.abort();rowsPrefetchController?.abort();rowsController=new AbortController();
  const controller=rowsController,timeout=setTimeout(()=>controller.abort(new DOMException('读取检测记录超时，请重试','TimeoutError')),30000);
  cancelAnimationFrame(selectionFrame);
  if(!keepCore){state.items=[];state.coreItems=[];drawCore([]);renderSelectedDetails();syncCoreAvailability();notifyThreeView()}
  updateWorkspaceActions(true);
  $('#workspace .split').classList.remove('workspace-notice');$('#workspaceEmptyNotice')?.remove();
  host.setAttribute('aria-busy','true');if(!keepCore)host.innerHTML='<tr><td colspan="18" class="empty">正在加载检测记录...</td></tr>';
  const query=params(),cacheKey=query.toString();if(keepCore)query.set('core','0');
  try{
    if(invalidFilter)throw new Error('通道编号筛选无效，请输入 1–50 的整数或清空筛选');
    const cached=keepCore&&rowsPageCache.get(cacheKey);
    const d=await(cached||api('/api/findings?'+query,{signal:controller.signal}));if(request!==rowsRequest)return;
    cacheRowsPage(cacheKey,d);
    state.items=d.items;if(!keepCore)state.coreItems=d.core_items||[];state.page=d.page;state.size=d.size;
    loadedRowsScope=scope;loadedRowsPage=d.page;if(d.total===0)clearSelectionState();
    if(!keepCore)coreMode=document.querySelector('#unit').value?(Number(document.querySelector('#unit').value)%2?'odd':'even'):'combined';state.pages=d.pages;
    coreSwitch?.querySelectorAll('[data-core-mode]').forEach(button=>button.classList.toggle('active',button.dataset.coreMode===coreMode));
    $('.split').classList.remove('empty-results');$('#resultInfo').textContent=`共 ${d.total} 条`;$(`#pageInfo`).textContent=`${d.page} / ${d.pages}`;
    $('#prevBtn').disabled=d.page<=1;$('#nextBtn').disabled=d.page>=d.pages;const pageSize=$('#pageSize');if(pageSize)pageSize.value=String(d.size);
    const pageRange=$('#workspacePageRange');if(pageRange)pageRange.textContent=d.total?`第 ${(d.page-1)*d.size+1}–${Math.min(d.page*d.size,d.total)} 条，共 ${d.total} 条`:'共 0 条';
    host.innerHTML=d.items.map((r,i)=>{const effective=isEffectiveFinding(r),number=(d.page-1)*d.size+i+1,checked=state.selectedIds.has(r.id);return `<tr data-i="${i}" class="${effective?'':'no-defect'}${checked?' selected':''}"><td><input type="checkbox" aria-label="选择第${number}条记录" ${checked?'checked':''}></td><td class="row-number">${number}</td><td>${displayTableCell(r.outage)}</td><td>${displayTableCell(r.unit_id)}</td>${editableCell(r.thimble_id,'thimble_id')}${editableCell(r.position,'position')}${editableCell(displayFindingCode(r),'indication')}${editableCell(r.volts,'volts')}${editableCell(r.degrees,'degrees')}${editableCell(r.percent,'percent','%')}${editableCell(r.location,'location')}${editableCell(r.channel,'channel')}${editableCell(r.probe,'probe')}${editableCell(r.analyst,'analyst')}${editableCell(r.filename,'filename')}${editableCell(r.calgroup,'calgroup')}${editableCell(r.analysis,'analysis')}${editableCell(r.maintenance_text,'maintenance_text')}</tr>`}).join('');
    if(!d.items.length){
      if(state.overview?.stats?.findings===0||(!Object.keys(workspaceColumnFilters).length&&!['site','unit','outage','analyst','thimble'].some(id=>$('#'+id).value.trim())))showWorkspaceNotice('尚未导入检测记录','选择检测文件夹或 Excel，确认后即可在此查询记录。','导入数据',()=>$('#openImportFlow').click());
      else showWorkspaceNotice('没有匹配的检测记录','请调整基地、机组、大修、分析人员或通道编号。','清除筛选',resetWorkspaceFilters);
    }
    if(!keepCore){
      if(state.selectedIds.size)refreshSelectionViews();
      else{drawCore($('#unit').value?state.coreItems:[]);$('#detail').className='detail empty';$('#detail').textContent=d.items.length?'勾选任意记录查看详情；只有有效缺陷参与管板着色':'当前没有可显示的检测记录';syncCoreAvailability();notifyThreeView()}
    }
    $$('#rows tr[data-i]').forEach(tr=>{
      const input=tr.querySelector('input[type="checkbox"]');
      input.onchange=()=>selectRow(+tr.dataset.i,tr,input.checked);
      input.onclick=event=>event.stopPropagation();
      tr.onclick=event=>{
        if(event.target.closest('.inline-finding-editor')||event.detail>1)return;
        const selection=getSelection();
        if(selection&&!selection.isCollapsed&&tr.contains(selection.anchorNode)&&tr.contains(selection.focusNode))return;
        input.checked=!input.checked;
        selectRow(+tr.dataset.i,tr,input.checked);
      };
    });
    if(d.page<d.pages){
      const nextQuery=params();nextQuery.set('page',String(d.page+1));const nextKey=nextQuery.toString();
      if(!rowsPageCache.has(nextKey)){
        nextQuery.set('core','0');
        const prefetchController=new AbortController();rowsPrefetchController=prefetchController;
        const prefetchTimeout=setTimeout(()=>prefetchController.abort(),15000);
        api('/api/findings?'+nextQuery,{signal:prefetchController.signal})
          .then(result=>{if(request===rowsRequest&&!prefetchController.signal.aborted)cacheRowsPage(nextKey,result)})
          .catch(()=>{})
          .finally(()=>{clearTimeout(prefetchTimeout);if(rowsPrefetchController===prefetchController)rowsPrefetchController=null});
      }
    }
  }catch(error){
    if(request!==rowsRequest||error.name==='AbortError')return;
    if(keepCore){rowsPageCache.delete(cacheKey);state.page=previousPage;throw error}
    clearSelectionState();state.page=1;state.pages=1;$('#resultInfo').textContent=invalidFilter?'筛选无效':'加载失败';$('#pageInfo').textContent=invalidFilter?'筛选无效':'加载失败';
    if($('#workspacePageRange'))$('#workspacePageRange').textContent=invalidFilter?'请修正通道编号筛选':'记录读取失败';
    drawCore([]);renderSelectedDetails();syncCoreAvailability();notifyThreeView();
    if(invalidFilter)showWorkspaceNotice('请修正筛选',error.message,'修正筛选',()=>tube.focus());
    else showWorkspaceNotice('检测记录加载失败','请确认本地服务已启动，然后重试。','重新加载',reloadWorkspace);
    throw error;
  }finally{clearTimeout(timeout);if(request===rowsRequest){rowsController=null;host.removeAttribute('aria-busy');updateWorkspaceActions()}}
}
function stateLabel(s){return({normal:'正常',plugged:'堵管',replaced:'换管',shifted:'移位'})[s]||s}
let coreMode='combined';
function isEmptySourceValue(value){
  if(value===null||value===undefined)return true;
  return typeof value==='string'&&['','/','NONE','NO DATA','NO DEFECT','N/A','NA','NULL','-','—','–'].includes(value.normalize('NFKC').trim().toUpperCase());
}
function hasWearInformation(row){
  if(['volts','degrees','percent','location_raw','location']
    .some(key=>!isEmptySourceValue(row?.[key])))return true;
  const channel=String(row?.channel??'').normalize('NFKC').trim().toUpperCase();
  if(!isEmptySourceValue(row?.channel)&&!/^CH[-_ ]?\d+$/.test(channel))return true;
  const measurement=String(row?.measurement_type??'').trim().toUpperCase();
  return !isEmptySourceValue(row?.measurement_type)&&!['POINT','VMAX'].includes(measurement);
}
function isNoDefect(row){
  const indication=String(row.indication||'').trim().toUpperCase();
  if(['NDD','NONE','NO DEFECT'].includes(indication))return true;
  return ['', '/'].includes(indication)&&!hasWearInformation(row);
}
function isEffectiveFinding(row){const percent=Number(row.percent);return !isNoDefect(row)&&Number.isFinite(percent)&&percent>0}
function displayFindingCode(row){return isNoDefect(row)?'NDD':(String(row.indication||'').trim()||'未标注')}
function severitySettings(){
  if(window.appSettings)return window.appSettings.severity();
  const color=(key,fallback)=>/^#[0-9a-f]{6}$/i.test(localStorage.getItem(key)||'')?localStorage.getItem(key):fallback;
  // 显示分级默认值与台账业务水位一致（关注 30% / 极限 50%），可在软件设置中调整。
  const mid=Math.max(0,Math.min(100,Number(localStorage.getItem('thimbleSeverityMidThreshold')||30)));
  const high=Math.max(mid,Math.min(100,Number(localStorage.getItem('thimbleSeverityHighThreshold')||50)));
  return {none:color('thimbleSeverityNoneColor','#a6afb7'),low:color('thimbleSeverityLowColor','#79b98c'),mid:color('thimbleSeverityMidColor','#e5a83b'),high:color('thimbleSeverityHighColor','#df4b45'),midThreshold:mid,highThreshold:high};
}
function severityHex(value,settings=severitySettings()){return value>0?(value>=settings.highThreshold?settings.high:value>=settings.midThreshold?settings.mid:settings.low):'#ffffff'}
function selectedFindingStats(){
  const selectedRows=selectedRecords(),defects=selectedRows.filter(isEffectiveFinding),tubeMaximums=new Map(),zones=new Map();
  defects.forEach(row=>{const key=`${row.unit_id}|${row.thimble_id}`,value=Number(row.percent);tubeMaximums.set(key,Math.max(tubeMaximums.get(key)||0,value));const zone=String(row.location||'').match(/P[1-6]/i)?.[0]?.toUpperCase()||'未标注';zones.set(zone,(zones.get(zone)||0)+1)});
  const densest=[...zones.entries()].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))[0];
  return {selectedRows,defects,tubeMaximums,maxPercent:Math.max(0,...tubeMaximums.values()),densestZone:densest?.[0]||'/',densestCount:densest?.[1]||0};
}
function updateCoreStats(){
  const host=$('#coreStats');if(!host)return;const stats=selectedFindingStats(),selection=selectionVisualization();
  if(!stats.selectedRows.length){host.className='core-stats empty';host.textContent='勾选检测记录后统计缺陷分布';return}
  if(!selection.ready){host.className='core-stats empty';host.textContent=`已选 ${selection.records.length} 条记录，包含 ${selection.units.size} 个机组、${selection.outages.size} 个大修；表格选择已保留，二维和三维需筛选到单一机组、单一大修后显示`;return}
  host.className='core-stats';host.innerHTML=`<span><small>已选记录</small><b>${stats.selectedRows.length}</b></span><span><small>缺陷管</small><b>${stats.tubeMaximums.size}</b></span><span><small>最大磨损</small><b>${stats.maxPercent>0?displayPercent(stats.maxPercent):'/'}</b></span><span><small>密集区域</small><b>${displayTableCell(stats.densestZone)}${stats.densestCount?` · ${stats.densestCount}条`:''}</b></span>`;
}
function createCoreSnapshot(){
  const stats=selectedFindingStats();if(!stats.selectedRows.length)throw new Error('请先勾选需要导出的检测记录');
  const units=[...new Set(stats.selectedRows.map(row=>Number(row.unit_id)))];if(units.length!==1)throw new Error('缺陷分布图只能导出同一机组的数据');
  const outages=[...new Set(stats.selectedRows.map(row=>String(row.outage)))];if(outages.length!==1)throw new Error('缺陷分布图只能导出同一次大修的数据');
  const unit=units[0],positions=unit%2?ODD_POSITIONS:EVEN_POSITIONS,settings=severitySettings(),canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
  canvas.width=1500;canvas.height=1390;ctx.fillStyle='#ffffff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.textBaseline='middle';ctx.fillStyle='#1d2b31';ctx.font='700 42px "Microsoft YaHei",sans-serif';ctx.fillText('指套管缺陷分布图',90,70);
  const site=$('#site').value||stats.selectedRows[0].site_code||'/',outage=$('#outage').value||[...new Set(stats.selectedRows.map(row=>row.outage))].join('、')||'/';ctx.font='24px "Microsoft YaHei",sans-serif';ctx.fillStyle='#5b6971';ctx.fillText(`${site}基地 · ${unit}号机组 · ${outage} · 当前勾选 ${stats.selectedRows.length} 条记录`,90,120);
  const {columns,rowWidths}=window.plateGeometry,cell=62,left=260,top=190;
  ctx.lineWidth=1;ctx.strokeStyle='#9aa5ad';rowWidths.forEach((width,row)=>{const start=Math.floor((15-width)/2);for(let col=start;col<start+width;col++){ctx.fillStyle='#fbfcfc';ctx.fillRect(left+col*cell,top+row*cell,cell,cell);ctx.strokeRect(left+col*cell,top+row*cell,cell,cell)}});
  ctx.fillStyle='#52616c';ctx.font='700 18px "Microsoft YaHei",sans-serif';ctx.textAlign='center';columns.forEach((label,col)=>ctx.fillText(label,left+(col+.5)*cell,top-24));ctx.textAlign='right';Array.from({length:15},(_,row)=>ctx.fillText(String(row+1).padStart(2,'0'),left-18,top+(row+.5)*cell));
  const maximumByTube=new Map();stats.defects.forEach(row=>{const id=Number(row.thimble_id),value=Number(row.percent);maximumByTube.set(id,Math.max(maximumByTube.get(id)||0,value))});
  positions.forEach((position,index)=>{const match=position.match(/([A-Z])(\d+)/),col=columns.indexOf(match[1]),row=Number(match[2])-1,x=left+(col+.5)*cell,y=top+(row+.5)*cell,value=maximumByTube.get(index+1)||0;ctx.beginPath();ctx.arc(x,y,21,0,Math.PI*2);ctx.fillStyle=severityHex(value,settings);ctx.fill();ctx.lineWidth=value>0?4:2;ctx.strokeStyle=value>0?'#24313a':'#6f7b82';ctx.stroke();ctx.fillStyle='#17252c';ctx.font='700 15px "Microsoft YaHei",sans-serif';ctx.textAlign='center';ctx.fillText(String(index+1),x,y+1)});
const centerX=left+7.5*cell,centerY=top+7*cell,drawArrow=(startX,startY,endX,endY)=>{const angle=Math.atan2(endY-startY,endX-startX);ctx.beginPath();ctx.moveTo(startX,startY);ctx.lineTo(endX,endY);ctx.stroke();ctx.beginPath();ctx.moveTo(endX,endY);ctx.lineTo(endX-16*Math.cos(angle-Math.PI/6),endY-16*Math.sin(angle-Math.PI/6));ctx.lineTo(endX-16*Math.cos(angle+Math.PI/6),endY-16*Math.sin(angle+Math.PI/6));ctx.closePath();ctx.fill()};ctx.fillStyle='#263a43';ctx.strokeStyle='#263a43';ctx.lineWidth=4;ctx.textAlign='center';ctx.font='700 18px "Microsoft YaHei",sans-serif';ctx.fillText('180°',centerX,top-58);drawArrow(left-150,centerY,left-60,centerY);ctx.fillText('90°',left-105,centerY+29);ctx.fillText('OUTLET',left+15*cell+105,centerY-29);drawArrow(left+15*cell+60,centerY,left+15*cell+150,centerY);ctx.fillText('270°',left+15*cell+105,centerY+29);ctx.fillText('INLET',left+13.15*cell,top+6);drawArrow(left+12.7*cell,top+2,left+11.8*cell,top+50);drawArrow(left+3.2*cell,top+50,left+2.3*cell,top+2);drawArrow(left+3.2*cell,top+15*cell-50,left+2.3*cell,top+15*cell-2);drawArrow(left+12.7*cell,top+15*cell-2,left+11.8*cell,top+15*cell-50);ctx.fillText('0°',centerX,top+15*cell+72);
  const summaryY=1260;ctx.fillStyle='#eef2f3';ctx.fillRect(90,summaryY-40,1320,92);ctx.fillStyle='#263840';ctx.font='700 22px "Microsoft YaHei",sans-serif';ctx.textAlign='left';ctx.fillText(`缺陷管 ${stats.tubeMaximums.size} 根`,125,summaryY);ctx.fillText(`最大磨损 ${stats.maxPercent>0?displayPercent(stats.maxPercent):'/'}`,440,summaryY);ctx.fillText(`密集区域 ${stats.densestZone}${stats.densestCount?`（${stats.densestCount}条）`:''}`,790,summaryY);ctx.font='16px "Microsoft YaHei",sans-serif';ctx.fillStyle='#68767f';ctx.fillText(`分级：一级 < ${settings.midThreshold}% · 二级 ${settings.midThreshold}-${settings.highThreshold}% · 三级 ≥ ${settings.highThreshold}%`,125,summaryY+34);
  return {canvas,unit,outage};
}
async function exportCoreSnapshot(){
  const button=$('#exportCorePng');if(button.disabled)return;button.disabled=true;
  try{const {canvas,unit,outage}=createCoreSnapshot(),dataUrl=canvas.toDataURL('image/png'),site=canonicalSite(selectedRecords()[0]?.site_code||selectedRecords()[0]?.site||outage.match(/^[A-Za-z]+/)?.[0]),defaultName=exportArtifactName('管板缺陷分布',`${window.artifactNaming.siteCode(site)}_${unit}号机组_${window.artifactNaming.unitCode(outage)}`,'png');if(window.desktopAPI?.saveCoreImage){const saved=await window.desktopAPI.saveCoreImage({dataUrl,defaultName});if(saved)toast(`管板图片已保存：${saved}`)}else{const link=document.createElement('a');link.href=dataUrl;link.download=defaultName;link.click();toast('管板图片已导出')}}catch(error){toast(error.message)}finally{button.disabled=false;syncCoreAvailability()}
}
function exportArtifactName(kind,scope,extension){
  return window.artifactNaming.filename(kind,scope,extension);
}
function drawCore(items){
  const {columns,rowWidths}=window.plateGeometry,oddCounts={},evenCounts={},oddNdd=new Set(),evenNdd=new Set();
  // Severity is an explicit selection state. A filter scopes the available
  // rows, but must not paint the whole board until the operator selects data.
  const colorRows=visualSelectionRecords();
  colorRows.forEach(r=>{const odd=Number(r.unit_id)%2===1;if(displayFindingCode(r)==='NDD'){(odd?oddNdd:evenNdd).add(r.position);return}const value=Number(r.percent);if(!Number.isFinite(value)||value<=0)return;const target=odd?oddCounts:evenCounts;target[r.position]=Math.max(target[r.position]||0,value)});
  const max=100,{midThreshold,highThreshold}=severitySettings(),severityColor=value=>value>0?(value>=highThreshold?'var(--severity-high)':value>=midThreshold?'var(--severity-mid)':'var(--severity-low)'):'#ffffff';
  const cells=rowWidths.map((width,row)=>{const start=Math.floor((15-width)/2);return Array.from({length:width},(_,offset)=>`<span class="grid-cell" style="--col:${start+offset};--row:${row}"></span>`).join('')}).join('');
  const labels='<div class="ref-axis ref-letters">'+columns.map((x,i)=>`<span style="--col:${i}">${x}</span>`).join('')+'</div><div class="ref-axis ref-numbers">'+Array.from({length:15},(_,i)=>`<span style="--row:${i}">${String(i+1).padStart(2,'0')}</span>`).join('')+'</div>';
  const pairs=ODD_POSITIONS.map((oddPos,index)=>({oddPos,oddId:index+1,evenPos:null,evenId:null}));
  EVEN_POSITIONS.forEach((evenPos,index)=>{const pair=pairs.find(item=>item.oddPos===evenPos);if(!pair)throw new Error(`管板映射不一致：${evenPos}`);pair.evenPos=evenPos;pair.evenId=index+1});
  const tubes=pairs.map(pair=>{const oddMatch=pair.oddPos.match(/([A-Z])(\d+)/),evenMatch=pair.evenPos.match(/([A-Z])(\d+)/),x=(columns.indexOf(oddMatch[1])+columns.indexOf(evenMatch[1]))/2,y=(+oddMatch[2]+ +evenMatch[2])/2-1,oc=oddCounts[pair.oddPos]||0,ec=evenCounts[pair.evenPos]||0,severity=coreMode==='odd'?oc:coreMode==='even'?ec:Math.max(oc,ec),color=severityColor(severity),label=coreMode==='odd'?pair.oddId:coreMode==='even'?pair.evenId:`${pair.oddId}/${pair.evenId}`,oddClass=oddNdd.has(pair.oddPos)?' is-ndd':'',evenClass=evenNdd.has(pair.evenPos)?' is-ndd':'';return `<button class="path-marker mode-${coreMode} ${severity>0?'has-severity':''}" data-odd-pos="${pair.oddPos}" data-even-pos="${pair.evenPos}" title="奇数 ${pair.oddId}:${pair.oddPos} · 偶数 ${pair.evenId}:${pair.evenPos}" style="--col:${x};--row:${y};--odd-hit:${oc/max};--even-hit:${ec/max};--severity:${severity/max};--tube-color:${color};--odd-color:${severityColor(oc)};--even-color:${severityColor(ec)}"><span class="path-half combined-path" data-path="combined">${label}</span><span class="path-half odd-path${oddClass}" data-path="odd">${pair.oddId}</span><span class="path-half even-path${evenClass}" data-path="even">${pair.evenId}</span></button>`}).join('');
  $('#coreMap').innerHTML=`<div class="reference-grid">${cells}${labels}${tubes}<div class="flow-mark one-eighty">180°</div><div class="flow-mark side-left"><i></i><span>90°</span></div><div class="flow-mark side-right"><b>OUTLET</b><i></i><span>270°</span></div><div class="flow-mark corner top-left"><i></i></div><div class="flow-mark corner top-right"><b>INLET</b><i></i></div><div class="flow-mark corner bottom-left"><i></i></div><div class="flow-mark corner bottom-right"><i></i></div><div class="flow-mark zero">0°</div></div>`;
  const selectedOdd=new Set(),selectedEven=new Set();
  for(const row of colorRows){
    const odd=Number(row.unit_id)%2===1,position=(odd?ODD_POSITIONS:EVEN_POSITIONS)[Number(row.thimble_id)-1];
    if(position)(odd?selectedOdd:selectedEven).add(position);
  }
  $$('#coreMap .path-marker').forEach(marker=>{
    const selected=(coreMode!=='even'&&selectedOdd.has(marker.dataset.oddPos))||(coreMode!=='odd'&&selectedEven.has(marker.dataset.evenPos));
    marker.classList.toggle('focused',selected);marker.setAttribute('aria-pressed',String(selected));
  });
  updateCoreStats();
  $$('#coreMap .path-half').forEach(part=>part.onclick=event=>{event.stopPropagation();const marker=part.closest('.path-marker');let path=part.dataset.path;if(path==='combined'){const selectedUnit=Number($('#unit').value||0);path=selectedUnit?(selectedUnit%2?'odd':'even'):'odd'}const pos=path==='odd'?marker.dataset.oddPos:marker.dataset.evenPos,id=path==='odd'?Number(marker.querySelector('.odd-path').textContent):Number(marker.querySelector('.even-path').textContent),count=(path==='odd'?oddCounts:evenCounts)[pos]||0;$('#detail').className='detail';$('#detail').innerHTML=`<div class="path-detail"><b>${path==='odd'?'奇数':'偶数'}机组 · ${id}号指套管</b><span>堆芯坐标 ${pos}</span><strong>${count} 条缺陷记录</strong><button id="showPathRows">查看记录</button><button id="showTubeHistory">查看演变</button></div>`;const unit=(state.overview?.units||[]).find(value=>(value%2===1)===(path==='odd'));$('#showPathRows').onclick=()=>{coreMode=path;coreSwitch.querySelector(`[data-core-mode="${path}"]`).click();$('#unit').value=unit||'';$('#thimble').value=id;state.page=1;loadRows()};$('#showTubeHistory').onclick=async()=>{const site=$('#site').value||String((state.overview?.sites||[])[0]||'');const history=await api(`/api/tube-history?site=${encodeURIComponent(site)}&unit=${unit||''}&thimble=${id}`);$('#detail').innerHTML=`<div class="path-detail"><b>${id}号管历史演变</b>${history.items.length?history.items.map(row=>`<p>${displayTableCell(row.outage)} · ${displayTableCell(row.location)} · ${displayTableCell(displayFindingCode(row))} · ${displayPercent(row.percent)} · ${displayTableCell(stateLabel(row.state))}</p>`).join(''):'<p>暂无历史记录</p>'}</div>`}})
}
const ODD_POSITIONS="L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9".split(' '),EVEN_POSITIONS="B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 N5 R8 N7 N8 N10 L5 L8 L6 L4".split(' ');
const coreSwitch=document.createElement('div');coreSwitch.className='core-switch segmented';coreSwitch.innerHTML='<button class="active" data-core-mode="combined">综合显示</button><button data-core-mode="odd">奇数机组</button><button data-core-mode="even">偶数机组</button>';$('.core-panel .panel-title span').textContent='筛选后按单管最大磨损着色 · 左奇数 / 右偶数';$('#coreMap').before(coreSwitch);coreSwitch.querySelectorAll('button').forEach(button=>button.onclick=()=>{coreSwitch.querySelectorAll('button').forEach(x=>x.classList.remove('active'));button.classList.add('active');coreMode=button.dataset.coreMode;drawCore($('#unit').value?state.coreItems:[])});
$('#exportCorePng').onclick=exportCoreSnapshot;
$('#coreMap').addEventListener('click',async event=>{const half=event.target.closest('.path-half');if(!half)return;event.stopImmediatePropagation();const marker=half.closest('.path-marker'),selection=selectionVisualization(),selectedUnit=+($('#unit').value||(selection.ready?[...selection.units][0]:0)),unit=selectedUnit;if(!selectedUnit)return toast('请先筛选机组或勾选同一机组、同一次大修的数据');const isOdd=half.dataset.path==='combined'?Boolean(selectedUnit%2):half.dataset.path==='odd';if(Boolean(selectedUnit%2)!==isOdd)return toast('当前机组奇偶与所选管板不匹配');const thimble=Number(marker.querySelector(isOdd?'.odd-path':'.even-path').textContent),site=$('#site').value||(selection.ready?[...selection.sites][0]:''),outage=$('#outage').value||(selection.ready?[...selection.outages][0]:'');$$('#coreMap .path-marker').forEach(item=>item.classList.remove('focused'));marker.classList.add('focused');const p=new URLSearchParams({page:'1',size:'200',unit:String(unit),thimble:String(thimble)});if(site)p.set('site',site);if(outage)p.set('outage',outage);try{const data=await api('/api/findings?'+p);const records=data.items;$('#detail').className='detail';$('#detail').innerHTML=`<div class="path-detail records-detail"><b>${unit}号机 · ${thimble}号指套管</b><span>${isOdd?'奇数机组左半圆':'偶数机组右半圆'} · ${marker.dataset[isOdd?'oddPos':'evenPos']}</span><strong>${records.length} 条当前筛选记录</strong><button id="focusTubeFromCore">三维定位</button><div class="tube-records">${records.length?records.map(row=>`<p><b>${displayTableCell(row.outage)}</b><span>${displayTableCell(row.location)} · ${displayTableCell(displayFindingCode(row))} · ${displayPercent(row.percent)}</span></p>`).join(''):'<p>当前筛选范围内无记录</p>'}</div></div>`;$('#focusTubeFromCore').onclick=()=>{document.querySelector('[data-view="threeD"]').click();window.dispatchEvent(new CustomEvent('three-focus-tube',{detail:{thimble,unit,outage}}))}}catch(error){toast(error.message)}} ,true);
  function renderSelectedDetails(){const records=selectedRecords(),selection=selectionVisualization(),host=$('#detail');if(!records.length){host.className='detail empty';host.textContent='勾选记录后在此逐条显示检测详情';return}const warning=selection.ready?'':`<p class="selection-scope-warning">当前选择包含 ${selection.units.size} 个机组、${selection.outages.size} 个大修。表格记录已全部保留；二维和三维需缩小到单一机组、单一大修后显示。</p>`;host.className='detail selection-details';host.innerHTML=`<div class="selection-detail-head"><b>已勾选 ${records.length} 条记录</b><span>${new Set(records.map(row=>row.thimble_id)).size} 根指套管</span></div>${warning}<div class="selected-record-list">${records.map((row,index)=>`<article><i>${index+1}</i><div><b>#${row.thimble_id} · ${displayTableCell(row.position)}</b><span>${displayTableCell(row.outage)} / ${displayTableCell(row.unit_id)}号机 · ${displayTableCell(row.analyst)}</span></div><div><strong>${displayTableCell(displayFindingCode(row))} · ${displayPercent(row.percent)}</strong><span>${displayTableCell(row.location)} · ${displayTableCell(row.channel)}</span></div></article>`).join('')}</div>`}
  function refreshSelectionViews(){const selection=selectionVisualization(),selectedUnit=$('#unit').value||(selection.ready?[...selection.units][0]:'');if(selection.ready){coreMode=Number(selectedUnit)%2?'odd':'even';coreSwitch?.querySelectorAll('[data-core-mode]').forEach(button=>button.classList.toggle('active',button.dataset.coreMode===coreMode))}const coreRows=state.coreItems.filter(item=>!selectedUnit||String(item.unit_id)===String(selectedUnit));drawCore(coreRows.length?coreRows:state.items.filter(item=>!selectedUnit||String(item.unit_id)===String(selectedUnit)));renderSelectedDetails();syncCoreAvailability();notifyThreeView();updateWorkspaceActions();return selection}
  let selectionFrame;
  function selectRow(i,tr,checked){const r=state.items[i],input=tr.querySelector('input[type="checkbox"]');if(!r)return false;if(checked){const anchor=selectedRecords()[0];if(anchor&&!sameVisualizationScope(anchor,r)){if(input)input.checked=false;tr.classList.remove('selected');tr.setAttribute('aria-selected','false');toast(`不能同时选择不同基地、机组或大修的数据；当前范围为 ${anchor.outage} · ${anchor.unit_id}号机`);return false}state.selectedIds.add(r.id);state.selectedRecords.set(r.id,r)}else{state.selectedIds.delete(r.id);state.selectedRecords.delete(r.id)}tr.classList.toggle('selected',checked);tr.setAttribute('aria-selected',String(checked));state.selected=checked?r:null;cancelAnimationFrame(selectionFrame);selectionFrame=requestAnimationFrame(refreshSelectionViews);return true}

const settingsWindowMode=new URLSearchParams(location.search).get('window')==='settings';
if(settingsWindowMode){
  document.body.dataset.window='settings';
  // The settings window must never briefly render the workbench while the
  // renderer is starting or while a stored startup view is being restored.
  $$('nav button[data-view],main>.view').forEach(element=>element.classList.remove('active'));
  $('#settings').classList.add('active');
  document.body.dataset.settingsReady='true';
}
$$('nav button[data-view]').forEach(b=>b.onclick=()=>{if(b.dataset.openSettings)return;$$('nav button[data-view],.view').forEach(x=>x.classList.remove('active'));b.classList.add('active');$('#'+b.dataset.view).classList.add('active');if(!settingsWindowMode&&!new URLSearchParams(location.search).has('visualization')&&localStorage.getItem('thimbleRememberView')!=='false')localStorage.setItem('thimbleLastView',b.dataset.view);if(b.dataset.view==='threeD')notifyThreeView();window.dispatchEvent(new CustomEvent('app-view-changed',{detail:{view:b.dataset.view}}))});
document.querySelector('[data-open-settings]')?.addEventListener('click',()=>window.desktopAPI?.openSettingsWindow(document.querySelector('[data-open-settings]').dataset.openSettings));
if(settingsWindowMode){
  document.querySelectorAll('.app-nav,.view:not(#settings)').forEach(element=>element.hidden=true);
}
function installSplitResizer(){
  const split=document.querySelector('#workspace .split');
  if(!split||split.dataset.resizerInstalled)return;
  split.dataset.resizerInstalled='1';
  const table=split.querySelector('.table-panel'), core=split.querySelector('.core-panel');
  if(!table||!core)return;
  const divider=document.createElement('div');
  divider.className='split-divider';divider.setAttribute('role','separator');divider.setAttribute('aria-orientation','vertical');
  divider.tabIndex=0;divider.title='拖动调整表格与管板宽度';
  divider.setAttribute('aria-label','表格与管板宽度');
  table.after(divider);
  const saved=Number(localStorage.getItem('thimbleWorkspaceSplit')||'62');
  divider.setAttribute('aria-valuemin','38');divider.setAttribute('aria-valuemax','70');
  const apply=ratio=>{const value=Math.max(38,Math.min(70,ratio));split.style.setProperty('--split-ratio',`${value}%`);localStorage.setItem('thimbleWorkspaceSplit',String(value));divider.setAttribute('aria-valuenow',String(Math.round(value)));divider.setAttribute('aria-valuetext',`检测记录 ${Math.round(value)}%，堆芯分布 ${100-Math.round(value)}%`);};
  apply(Number.isFinite(saved)?saved:62);
  let dragging=false;
  const move=event=>{if(!dragging)return;const rect=split.getBoundingClientRect();apply((event.clientX-rect.left)/rect.width*100);};
  divider.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();dragging=true;divider.setPointerCapture(event.pointerId);document.body.classList.add('resizing-split');});
  divider.addEventListener('pointermove',move);
  const stop=event=>{dragging=false;if(divider.hasPointerCapture(event.pointerId))divider.releasePointerCapture(event.pointerId);document.body.classList.remove('resizing-split');};
  for(const event of ['pointerup','pointercancel','lostpointercapture'])divider.addEventListener(event,stop);
  divider.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();apply(Number(split.style.getPropertyValue('--split-ratio').replace('%','')||62)+(event.key==='ArrowRight'?2:-2));}});
}
installSplitResizer();
window.addEventListener('storage',event=>{
  if(event.key==='thimbleAppearance')document.documentElement.dataset.theme=event.newValue==='dark'?'dark':'light';
  if(event.key==='thimbleUiDensity'&&(event.newValue==='compact'||event.newValue==='standard'))document.body.dataset.uiDensity=event.newValue;
  if(event.key==='thimbleReduceMotion')document.body.dataset.reduceMotion=event.newValue==='true'?'true':'false';
  if(event.key==='thimbleRememberView'&&event.newValue==='true'&&!settingsWindowMode&&!new URLSearchParams(location.search).has('visualization')){
    const view=document.querySelector('.app-nav [aria-current="page"]')?.dataset.view;
    if(view)localStorage.setItem('thimbleLastView',view);
  }
});
window.addEventListener('severity-settings-changed',()=>drawCore(state.coreItems.length?state.coreItems:state.items));
$('.app-nav').addEventListener('click',event=>{
  const button=event.target.closest('button[data-view]');if(!button||button.dataset.openSettings)return;
  $('.app-nav [aria-current]')?.removeAttribute('aria-current');
  button.setAttribute('aria-current','page');
},true);
$('.app-nav button.active')?.setAttribute('aria-current','page');
/* 三维 → 表格回跳：在三维视图点击缺陷标记（带 recordIds 的选中通知）时，
   自动切回数据工作台，按三维当前范围筛选到该管并勾选对应检测记录。
   仅点管体（无具体记录）不跳转，避免浏览模型时被打断。
   检索面板内点记录行（jump:false）只聚焦模型，同样不跳转。 */
window.addEventListener('three-tube-selected', async event => {
  const detail = event.detail || {}, thimble = Number(detail.thimble), ids = new Set((detail.recordIds || []).map(Number));
  if (!Number.isInteger(thimble) || thimble < 1 || thimble > 50 || !ids.size) return;
  if (detail.jump === false) return;
  document.querySelector('[data-view="workspace"]')?.click();
  const scope = detail.scope || {};
  if (scope.site) { $('#site').value = String(scope.site); refreshMainFilters(); }
  if (scope.unit) { $('#unit').value = String(scope.unit); refreshMainFilters(); }
  if (scope.outage) $('#outage').value = String(scope.outage);
  if ($('#thimble').checkValidity()) $('#thimble').value = String(thimble);
  state.page = 1;
  try { await loadRows(); } catch (error) { toast(error.message); return; }
  $$('#rows tr[data-i]').forEach(tr => {
    const row = state.items[+tr.dataset.i], input = tr.querySelector('input[type="checkbox"]');
    // selectRow 只改状态不改勾选框，先补上视觉勾选（与 input.onchange 的行为一致）
    if (row && ids.has(Number(row.id)) && input && !input.checked) { input.checked = true; selectRow(+tr.dataset.i, tr, true); }
  });
  if (![...ids].some(id => state.items.some(row => Number(row.id) === Number(id)))) toast('该管记录较多，已定位到第一页，请翻页查看其余记录');
});
$('#searchBtn').onclick=()=>{clearTimeout(filterTimer);state.page=1;loadRows().catch(e=>toast(e.message))};$('#resetBtn').onclick=resetWorkspaceFilters;$('#prevBtn').onclick=()=>window.workspaceMovePage(-1);$('#nextBtn').onclick=()=>window.workspaceMovePage(1);
window.workspaceMovePage=delta=>{if($('#rows').getAttribute('aria-busy')==='true')return;const next=Math.max(1,Math.min(state.pages,state.page+delta));if(next!==state.page){state.page=next;loadRows({pageOnly:true}).catch(e=>toast(e.message))}};
const importProgressState={startedAt:0,timer:0,percent:null,label:'正在处理',meta:'',timing:''};
const formatDuration=seconds=>{if(!Number.isFinite(seconds)||seconds<0)return '';const whole=Math.ceil(seconds);return whole<60?`${whole}秒`:whole<3600?`${Math.floor(whole/60)}分${whole%60}秒`:`${Math.floor(whole/3600)}小时${Math.floor(whole%3600/60)}分`};
function progress(active,percent,label='',meta='',timing=''){
  const panel=$('#importProgressPanel'),bar=$('#parseProgress'),track=$('#importProgressTrack');
  if(!panel||!bar||!track)return;
  if(active&&!importProgressState.startedAt){importProgressState.startedAt=Date.now();importProgressState.percent=null;importProgressState.timer=window.setInterval(()=>progress(true,importProgressState.percent,importProgressState.label,importProgressState.meta,importProgressState.timing),1000)}
  if(active){if(label)importProgressState.label=label;if(meta)importProgressState.meta=meta}
  if(active)importProgressState.timing=timing;
  if(!active&&importProgressState.timer){clearInterval(importProgressState.timer);importProgressState.timer=0;importProgressState.startedAt=0;importProgressState.percent=null;importProgressState.label='正在处理';importProgressState.meta='';importProgressState.timing=''}
  panel.hidden=!active;track.classList.toggle('indeterminate',active&&!Number.isFinite(percent));track.setAttribute('aria-busy',String(active));
  $('#importProgressLabel').textContent=label||'正在处理';
  $('#importProgressMeta').textContent=meta;
  const percentage=$('#importProgressPercent'),value=Number.isFinite(percent)?Math.max(0,Math.min(100,percent)):null;
  importProgressState.percent=value;
  percentage.hidden=!active||value===null;percentage.textContent=value===null?'':`${Math.floor(value)}%`;
  const eta=$('#importProgressEta');
  if(active&&timing){eta.hidden=false;eta.textContent=timing}
  else if(active&&value!==null&&value>0){const elapsed=(Date.now()-importProgressState.startedAt)/1000;eta.hidden=false;eta.textContent=`已用 ${formatDuration(elapsed)} · 预计剩余 ${formatDuration(elapsed*(100-value)/value)}`}
  else if(active){eta.hidden=false;eta.textContent='已用 '+formatDuration((Date.now()-importProgressState.startedAt)/1000)+' · 正在估算剩余时间'}
  else{eta.hidden=true;eta.textContent=''}
  bar.style.width=active&&Number.isFinite(percent)?`${Math.max(0,Math.min(100,percent))}%`:active?'35%':'0%';
  if(active&&value!==null){track.setAttribute('aria-valuenow',String(value));track.setAttribute('aria-valuetext',`${Math.floor(value)}%`)}
  else{track.removeAttribute('aria-valuenow');track.setAttribute('aria-valuetext',active?'正在处理中':'等待开始')}
}
function startImportProgress(status,label,details={}){if(status){status.hidden=false;status.textContent=`${label}…`}progress(true,details.percent,label,details.meta)}
window.startImportProgress=startImportProgress;
window.updateImportProgress=(label,details={})=>progress(true,details.percent,label,details.meta,details.timing);
window.stopImportProgress=()=>progress(false);
$('#stateForm').onsubmit=async e=>{
  e.preventDefault();
  const form=e.target,button=form.querySelector('[type="submit"]');
  if($('#lifecycleBatchMode')?.checked){
    toast('当前处于批量选择模式；请先关闭批量选择，再保存单管状态。批量操作请使用“批量处理”。',{type:'warning'});
    $('#lifecycleBatchMode').focus();
    return;
  }
  if(!$('#stateSite').value||!$('#stateOutage').value||!$('#stateUnit').value||!Number($('#stateThimble').value)){toast('请先选择基地、机组、大修和管号',{type:'warning'});return}
  const validation=window.tubeLifecycle?.validate();if(validation){toast(validation,{type:'warning'});return}
  const hasShift=window.tubeLifecycle?.hasShift()??$('#stateType').value==='shifted';
  if(hasShift&&!$('#stateOffset').reportValidity())return;
  window.stateMaintenance?.setBusy(true);
  if($('#stateBulkHint'))$('#stateBulkHint').textContent=`正在保存 ${$('#stateThimble').value} 号管的单管状态；批量选择已锁定。`;
  button.disabled=true;button.setAttribute('aria-busy','true');button.textContent='正在保存…';
  let finalHint='';
  try{
    const result=await api('/api/state',{method:'POST',body:JSON.stringify({outage:$('#stateOutage').value,unit_id:+$('#stateUnit').value,thimble_id:+$('#stateThimble').value,state:$('#stateType').value,offset_mm:hasShift?($('#stateOffset').value===''?null:+$('#stateOffset').value):0,unsigned_offset_mm:hasShift&&$('#stateOffset').value===''&&$('#stateOffset').dataset.unsignedOffset?Number($('#stateOffset').dataset.unsignedOffset):null,note:originalStateNote($('#stateNote')),source:$('#stateSource')?originalStateNote($('#stateSource')):'',...window.tubeLifecycle?.payload()})});
    if(!await loadStates()){
      const message='管状态已保存，但列表刷新失败。请点击“重新加载”，无需重复保存。';
      finalHint=message;
      toast(message,{type:'warning'});
      return;
    }
    window.stateMaintenance?.saved();
    if(window.tubeLifecycle&&!await window.tubeLifecycle.refresh(true)){
      finalHint='管状态已保存，但历史有效状态刷新失败。请点击“重新读取”，无需重复保存。';
      toast(finalHint,{type:'warning'});
      return;
    }
    toast(result.effective?.inherited_plug?'已保存；历史堵管持续有效':result.warnings?.length?'已保存；特殊处理顺序或移位距离待核对':'管状态已保存',{type:result.warnings?.length?'warning':'success'});finalHint='单管状态已保存；可继续选择另一根管。';if(!window.stateMaintenance)form.reset();
  }catch(error){finalHint=`单管保存失败：${error.message}；可修改后重试。`;toast(error.message,{type:'error'})}
  finally{button.disabled=false;button.removeAttribute('aria-busy');button.textContent='保存状态';window.stateMaintenance?.setBusy(false);if($('#stateBulkHint'))$('#stateBulkHint').textContent=finalHint}
};
loadOverview().catch(error=>{
  showWorkspaceNotice('数据总览加载失败','请确认本地服务已启动，然后重试。','重新加载',reloadWorkspace);
  $('#resultInfo').textContent='加载失败';updateWorkspaceActions(true);toast(error.message);
}).then(()=>{if(state.overview)return loadRows().catch(error=>toast(error.message))});

const reportPicker=document.createElement('section');
reportPicker.id='reportPicker';
reportPicker.className='report-picker';
reportPicker.innerHTML='<div class="report-picker-head"><b>Report 版本</b><button id="scanReports" type="button">扫描并确认</button></div><div id="reportOptions" class="report-options empty">选择文件夹后扫描</div>';
$('#reportOptionsMount').append(reportPicker);
// software-settings.js owns the confirmed Report wizard and import queue.

const clearButton=$('#clearRecordsBtn');
function askConfirm(message,options={}){if(window.appFeedback)return window.appFeedback.confirm(message,options);return new Promise(resolve=>{const dialog=document.createElement('dialog');dialog.className='app-confirm';dialog.innerHTML='<form method="dialog"><h3>请确认操作</h3><p></p><div><button value="cancel" autofocus>取消</button><button value="ok" class="primary">确定</button></div></form>';dialog.querySelector('p').textContent=message;document.body.append(dialog);dialog.addEventListener('close',()=>{resolve(dialog.returnValue==='ok');dialog.remove()},{once:true});dialog.showModal()})}
window.resolveIndicationWarnings=data=>new Promise(resolve=>{const warning=data.blank_indication||{},dialog=document.createElement('dialog'),escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),rows=warning.items||[],nddCount=warning.ndd_count||0;dialog.className='indication-warning-dialog';dialog.innerHTML=`<form method="dialog"><div class="wizard-head"><div><span>导入数据质量校验</span><h2>发现 ${warning.count||0} 条三字符缺失记录</h2></div></div><div class="indication-warning-summary"><b>可处理 WAR ${warning.count||0} 条 · 自动判定 NDD ${nddCount} 条 · 涉及 ${warning.tubes||0} 根管、${warning.sources||0} 个来源文件</b><p>只有包含幅值、相位、磨损深度、测量通道或磨损位置等有效信息的记录，才会进入 WAR 处理；全部为空或 / 的记录会保存为 NDD，不会被批量改成 WAR。</p></div><div class="indication-warning-table"><table><thead><tr><th>序号</th><th>大修</th><th>机组</th><th>通道</th><th>堆芯位置</th><th>三字符</th><th>幅值(V)</th><th>相位(°)</th><th>深度</th><th>磨损位置</th><th>测量通道</th><th>数据文件</th><th>数据组</th><th>分析人员</th><th>RPT来源 / 文件地址</th></tr></thead><tbody>${rows.map((row,index)=>`<tr><td>${index+1}</td><td>${displayTableCell(row.outage)}</td><td>${displayTableCell(row.unit_id)}</td><td>#${displayTableCell(row.thimble_id)}</td><td>${displayTableCell(row.position)}</td><td>未标注</td><td>${displayTableCell(row.volts)}</td><td>${displayTableCell(row.degrees)}</td><td>${escape(displayPercent(row.percent))}</td><td>${displayTableCell(row.location)}</td><td>${displayTableCell(row.channel)}</td><td>${row.filename==null||row.filename===''?'/':escape(row.filename)}</td><td>${displayTableCell(row.calgroup)}</td><td>${displayTableCell(row.analyst)}</td><td class="source-path" title="${escape(row.source||'')}">${row.source==null||row.source===''?'/':escape(row.source)}</td></tr>`).join('')}</tbody></table></div><div class="indication-warning-actions"><button class="export-warning-table" type="button">导出完整表格</button><span></span><button value="cancel">取消本次导入</button><button value="review">保留空值，待人工确认</button><button value="fill_war" class="primary">一键将本批次缺失项设为 WAR</button></div></form>`;document.body.append(dialog);
dialog.querySelector('.export-warning-table').onclick=async event=>{
  const button=event.currentTarget,slot=button.closest('.indication-warning-actions').querySelector('span');
  button.disabled=true;button.textContent='正在生成…';
  try{
    const file=await api('/api/export-indication-warnings',{method:'POST',body:JSON.stringify({items:rows})});
    if(!dialog.isConnected)return;
    const link=document.createElement('a');link.href=file.download_url;link.download=file.filename;link.textContent='重新保存清单';
    let saving=false;
    const save=async()=>{
      if(saving)return;saving=true;
      try{
        const result=await window.saveGeneratedOfficeFile(file);
        if(!dialog.isConnected)return;
        const message=result.status==='saved'?`已保存 ${file.rows} 条记录。`:result.status==='cancelled'?'已取消保存清单。':'已发起清单下载。';
        status.textContent=message;
      }catch(error){if(dialog.isConnected)status.textContent=`清单保存失败：${error.message}。`;}
      finally{saving=false;}
    };
    const status=document.createElement('span');status.setAttribute('role','status');
    link.onclick=event=>{event.preventDefault();save();};
    slot.replaceChildren(status,document.createTextNode(' '),link);
    if(file.provenance_download_url){
      const evidence=document.createElement('a');evidence.href=file.provenance_download_url;evidence.download=file.provenance_filename;evidence.textContent='保存来源凭证';
      let savingEvidence=false;
      evidence.onclick=async event=>{
        event.preventDefault();if(savingEvidence)return;savingEvidence=true;
        try{
          const result=await window.saveGeneratedProvenance(file);
          if(dialog.isConnected)status.textContent=result.status==='saved'?'来源凭证已保存。':result.status==='cancelled'?'已取消保存来源凭证。':'已发起凭证下载。';
        }catch(error){if(dialog.isConnected)status.textContent=`来源凭证保存失败：${error.message}。`;}
        finally{savingEvidence=false;}
      };
      slot.append(document.createTextNode(' · '),evidence);
    }
    await save();
  }catch(error){if(dialog.isConnected)slot.textContent=`生成清单失败：${error.message}。`;}
  finally{button.disabled=false;button.textContent='导出完整表格';}
};
dialog.addEventListener('close',()=>{resolve(dialog.returnValue||'cancel');dialog.remove()},{once:true});dialog.showModal()});
clearButton.onclick=async()=>{
  if(!await askConfirm('将清空本机检测记录、管状态、导入历史和报告记录。保留账户、安全审计、操作日志与恢复备份；清空前自动备份，历史业务数据需通过备份恢复。',{title:'清空业务数据',danger:true,phrase:'清空全部数据',confirmLabel:'清空业务数据'}))return;
  clearButton.disabled=true;
  try{
    try{await api('/api/clear',{method:'POST',body:JSON.stringify({confirmed:true})})}
    catch(error){toast(error.message,{type:'error'});return}
    clearTimeout(filterTimer);clearSelectionState();state.page=1;++overviewRequest;state.overview=null;
    ++rowsRequest;rowsController?.abort();rowsPrefetchController?.abort();rowsPageCache.clear();
    state.items=[];state.coreItems=[];drawCore([]);renderSelectedDetails();syncCoreAvailability();notifyThreeView();
    stateListDirty=false;statePage=1;window.stateMaintenance?.records([],[],[]);window.stateMaintenance?.reset();
    showWorkspaceNotice('业务数据已清空','正在刷新显示。');
    // The committed clear invalidates every window, even if subsequent reads fail.
    window.dispatchEvent(new Event('database-cleared'));
    if(await refreshCommittedWorkspace({cleared:true}))toast('业务数据已清空；账户、日志与恢复备份已保留');
  }finally{clearButton.disabled=false}
};
let filterTimer;$$('#workspace .toolbar select').forEach(control=>control.addEventListener('change',()=>{clearTimeout(filterTimer);if(control.id==='site'||control.id==='unit')refreshMainFilters();state.page=1;loadRows().catch(error=>toast(error.message))}));$$('#workspace .toolbar input').forEach(control=>{control.addEventListener('keydown',event=>{if(event.key==='Enter'){clearTimeout(filterTimer);state.page=1;loadRows().catch(error=>toast(error.message))}});control.addEventListener('input',()=>{clearTimeout(filterTimer);filterTimer=setTimeout(()=>{state.page=1;loadRows().catch(error=>toast(error.message))},350)})});

$('#reportPicker').hidden=false;
const excelPicker=document.createElement('section');
excelPicker.className='excel-picker import-step-card';
excelPicker.innerHTML='<div class="import-source-actions"><button id="selectExcelBtn" class="primary" type="button">选择 Excel 文件</button><button id="selectExcelFolderBtn" type="button">添加文件夹内 Excel</button><span class="import-format-hint">支持 .xls / .xlsx / .xlsm</span></div><input id="excelImportPath" class="import-path-hint" placeholder="尚未选择 Excel 文件" readonly>';
$('#excelImportMount').append(excelPicker);
const importStatusObserver=new MutationObserver(()=>{const status=$('#importStatus');if(!status)return;if(status.textContent.trim())status.hidden=false;const duplicateCount=Number(status.textContent.match(/跳过重复\s*(\d+)/)?.[1]||0);if(!duplicateCount||status.querySelector('[data-open-dedup]'))return;const button=document.createElement('button');button.type='button';button.dataset.openDedup='1';button.textContent='查看去重详情';button.onclick=()=>{window.openSoftwareSettings?.('maintenance');setTimeout(()=>document.querySelector('#databaseDedup')?.scrollIntoView({behavior:'smooth',block:'center'}),120)};status.append(' ',button)});importStatusObserver.observe($('#importStatus'),{childList:true,subtree:true,characterData:true});


$('#openImportFlow')?.addEventListener('click',()=>$('#importDialog').showModal());$('#openImportFlowCard')?.addEventListener('click',()=>$('#importDialog').showModal());$$('[data-go-view]').forEach(button=>button.onclick=()=>document.querySelector(`nav [data-view="${button.dataset.goView}"]`)?.click());

window.workspaceSetPageSize=size=>{state.size=size;state.page=1;loadRows().catch(error=>toast(error.message))};
document.addEventListener('workspace-selection-settled',notifyThreeView);
const requestedView=new URLSearchParams(location.search).get('view');
const storedView=localStorage.getItem('thimbleRememberView')==='false'?null:localStorage.getItem('thimbleLastView');
const startupView=[requestedView,storedView,localStorage.getItem('thimbleStartupView'),'workspace']
  .find(view=>['workspace','threeD','analytics','reports','states'].includes(view));
if(!settingsWindowMode&&startupView)document.querySelector(`nav [data-view="${CSS.escape(startupView)}"]`)?.click();
if(window.localAccount?.user)document.documentElement.removeAttribute('data-startup-pending');
else window.addEventListener('local-account-ready',()=>document.documentElement.removeAttribute('data-startup-pending'),{once:true});
window.api=api; window.toast=toast; window.__thimbleState=state; window.__thimbleLoadRows=loadRows;
window.saveGeneratedOfficeFile=async(file)=>{
  if(!window.desktopAPI?.saveOfficeFile){
    const link=document.createElement('a');link.href=file.download_url;link.download=file.filename;link.click();
    return {status:'pending'};
  }
  const url=new URL(file.download_url,location.href);
  if(url.origin!==location.origin||!['/api/download-excel','/api/download-report'].includes(url.pathname))throw new Error('导出文件地址无效，请重新生成。');
  const response=await fetch(url);
  if(!response.ok)throw new Error('读取导出文件失败，请重新生成。');
  if(Number(response.headers.get('content-length'))>50*1024*1024)throw new Error('导出文件超过 50 MB，请缩小筛选范围后重试。');
  const bytes=new Uint8Array(await response.arrayBuffer());
  const path=await window.desktopAPI.saveOfficeFile({bytes,defaultName:file.filename});
  return path?{status:'saved',path}:{status:'cancelled'};
};
window.saveGeneratedProvenance=async(file)=>{
  if(!window.desktopAPI?.saveProvenance){
    const link=document.createElement('a');link.href=file.provenance_download_url;link.download=file.provenance_filename;link.click();
    return {status:'pending'};
  }
  const url=new URL(file.provenance_download_url,location.href);
  if(url.origin!==location.origin||!['/api/download-excel','/api/download-report'].includes(url.pathname)||
     !String(file.provenance_filename||'').toLowerCase().endsWith('.provenance.json'))throw new Error('来源凭证地址无效，请重新生成。');
  const response=await fetch(url);
  if(!response.ok)throw new Error('读取来源凭证失败，请重新生成。');
  if(Number(response.headers.get('content-length'))>50*1024*1024)throw new Error('来源凭证超过 50 MB，请缩小筛选范围后重试。');
  const bytes=new Uint8Array(await response.arrayBuffer());
  const path=await window.desktopAPI.saveProvenance({bytes,defaultName:file.provenance_filename});
  return path?{status:'saved',path}:{status:'cancelled'};
};
window.desktopAPI?.onDownloadStatus?.(({state,filename})=>{
  if(state==='completed')toast(`文件已保存：${filename}`);
  else if(state==='interrupted')toast(`文件保存中断：${filename}。请检查磁盘空间和保存位置后重试。`,{type:'error',duration:10000});
  else if(state==='cancelled')toast(`已取消保存：${filename}`);
});
window.__thimbleWindowInstanceId ||= globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random()}`;
const visualizationChanges=typeof BroadcastChannel==='function'?new BroadcastChannel('thimble-visualization-data'):null;
window.workspaceRefresh=async()=>{
  clearSelectionState();state.page=1;
  window.dispatchEvent(new Event('workspace-data-changed'));
  await loadOverview();await loadRows();await loadStates();
  window.dispatchEvent(new CustomEvent('tube-state-changed',{detail:{workspaceLoaded:true}}));
};
window.addEventListener('tube-state-changed',event=>{if(!event.detail?.workspaceLoaded)loadRows({requireValidFilter:true}).catch(error=>toast(`管状态已变更，工作台刷新失败：${error.message}`,{type:'warning'}))});
window.addEventListener('cross-group-reviewed',async()=>{
  clearSelectionState();
  try{await loadOverview();await loadRows();}catch(error){toast(error.message)}
});
const refreshDeletedData=async event=>{
  if(event.detail?.workspaceLoaded)return;
  clearSelectionState();state.page=1;
  try{await loadOverview();await loadRows();}catch(error){toast(`数据已变更，刷新失败：${error.message}`,{type:'error'})}
};
for(const event of ['data-deleted','data-restored'])window.addEventListener(event,refreshDeletedData);
const broadcastWorkspaceChange=event=>{
  if(event.detail?.settingsRemote&&(event.detail.visualizationNotified||settingsWindowMode||new URLSearchParams(location.search).has('visualization')))return;
  if(event.detail?.workspaceLoaded&&event.type==='tube-state-changed')return;
  visualizationChanges?.postMessage({type:event.type});
};
for(const event of ['tube-state-changed','data-imported','database-cleared','data-deleted','data-restored','workspace-data-changed','cross-group-reviewed'])
  window.addEventListener(event,broadcastWorkspaceChange);
window.addEventListener('beforeunload',()=>visualizationChanges?.close(),{once:true});
if(typeof BroadcastChannel==='function'){
  const legacyDataChanges=new BroadcastChannel('thimble-local-data-changes');
  legacyDataChanges.onmessage=event=>{
    if(event.data?.sourceId===window.__thimbleWindowInstanceId)return;
    if(!['database-cleared','cross-group-reviewed','data-imported','data-deleted','data-restored','workspace-data-changed'].includes(event.data?.type))return;
    if(['database-cleared','data-imported','data-deleted','data-restored','workspace-data-changed'].includes(event.data.type)){
      clearSelectionState();state.page=1;++overviewRequest;state.overview=null;
      ++rowsRequest;rowsController?.abort();rowsPrefetchController?.abort();rowsPageCache.clear();
      state.items=[];state.coreItems=[];drawCore([]);renderSelectedDetails();syncCoreAvailability();notifyThreeView();
      showWorkspaceNotice('数据已更改','正在重新读取检测记录。');
      window.dispatchEvent(new CustomEvent(event.data.type,{detail:{workspaceLoaded:true,settingsRemote:true,visualizationNotified:event.data.visualizationNotified===true}}));
      void refreshCommittedWorkspace({external:true});
      return;
    }
    window.dispatchEvent(new Event(event.data.type));
  };
}
window.drawCore=drawCore;
window.workspaceApplyScope=async scope=>{const site=$('#site'),unit=$('#unit'),outage=$('#outage');site.value=[...site.options].some(option=>option.value===String(scope.site||''))?String(scope.site||''):'';refreshMainFilters();unit.value=[...unit.options].some(option=>option.value===String(scope.unit||''))?String(scope.unit||''):'';refreshMainFilters();outage.value=[...outage.options].some(option=>option.value===String(scope.outage||''))?String(scope.outage||''):'';$('#thimble').value='';state.page=1;await loadRows()};
window.workspaceSelectTube=async thimble=>{if(!Number.isInteger(Number(thimble))||Number(thimble)<1||Number(thimble)>50)return;$('#thimble').value=String(thimble);state.page=1;await loadRows()};

const DISPLAY_PAGE_SIZES=[20,50,100,200,500];
function normalizeWorkstationTable(){
  const table=$('#workspace table'); if(!table)return;
  [...table.querySelectorAll('thead th')].forEach(th=>{if(/套管|濂楃/.test(th.textContent))th.textContent='通道编号';if(/数据点|鏁版嵁鐐/.test(th.textContent))th.remove()});
  const select=$('#pageSize'); if(select){select.innerHTML=DISPLAY_PAGE_SIZES.map(n=>`<option value="${n}">${n}</option>`).join('');select.value=String(state.size)}
}
normalizeWorkstationTable(); document.addEventListener('DOMContentLoaded',normalizeWorkstationTable);
function installSelectionTools(){const title=$('#workspace .table-panel .panel-title');if(!title||$('#selectAllRows'))return;const actions=document.createElement('div');actions.className='selection-tools';actions.innerHTML='<button id="selectAllRows" type="button" class="secondary">全选本页</button><button id="clearPageSelection" type="button">清除勾选</button>';title.append(actions);$('#selectAllRows').onclick=()=>{const rows=$$('#rows tr[data-i]'),existing=selectedRecords()[0],anchor=existing||state.items[+rows[0]?.dataset.i],eligible=rows.filter(row=>sameVisualizationScope(anchor,state.items[+row.dataset.i]));eligible.forEach(row=>{const record=state.items[+row.dataset.i],input=row.querySelector('input[type="checkbox"]');if(!record||!input)return;state.selectedIds.add(record.id);state.selectedRecords.set(record.id,record);input.checked=true;row.classList.add('selected')});refreshSelectionViews();const skipped=rows.length-eligible.length;toast(skipped?`已选择同一大修 ${eligible.length} 条，已跳过其他机组或大修 ${skipped} 条`:`已选中本页 ${eligible.length} 条记录`)};$('#clearPageSelection').onclick=()=>{clearSelectionState();$$('#rows input[type="checkbox"]').forEach(input=>{input.checked=false;input.closest('tr')?.classList.remove('selected')});drawCore(state.coreItems.length?state.coreItems:state.items);$('#detail').className='detail empty';$('#detail').textContent='已清除勾选，请选择检测记录查看详情';syncCoreAvailability();notifyThreeView();updateWorkspaceActions();toast('已清除全部勾选记录')}}
async function refreshCommittedWorkspace({cleared=false,external=false}={}){
  const errors=[];
  if(cleared&&!await loadStates({preserveDrafts:false}))errors.push('状态列表刷新失败');
  if(external){
    refreshStateListDirty();
    if(stateListDirty){
      const host=$('#stateRows');
      host.querySelector('.state-remote-warning')?.remove();
      const row=document.createElement('tr'),cell=row.insertCell(),retry=document.createElement('button');
      row.className='state-remote-warning';cell.colSpan=10;cell.setAttribute('role','status');
      cell.append('其他窗口的数据已更改，当前未保存的修改仍保留；重新加载前请先记录需要的内容。 ');
      retry.type='button';retry.textContent='重新加载状态';retry.onclick=async()=>{
        if(await confirmStateListReload('重新加载状态'))await loadStates({preserveDrafts:false});
      };
      cell.append(retry);host.prepend(row);
      host.dataset.stale='true';
      host.querySelectorAll('[data-state-save],[data-state-delete],[data-state-select],.state-composite').forEach(button=>button.disabled=true);
      $('#stateDeleteSelected').disabled=true;$('#stateSelectAll').disabled=true;
      errors.push('状态列表有未保存修改，请到状态处理页面核对');
    }else if(!await loadStates())errors.push('状态列表刷新失败');
  }
  try{await loadOverview({refreshStates:!external})}catch(error){errors.push(`统计刷新失败：${error.message}`)}
  // A failed overview must not prevent reading the committed records.
  try{await loadRows({requireValidFilter:true})}catch(error){errors.push(`记录刷新失败：${error.message}`)}
  $('#workspaceSaveNotice')?.remove();
  if(!errors.length)return true;
  const headingText=external?'其他窗口的数据已更改':cleared?'业务数据已清空':'记录已保存';
  const message=`${errors.join('；')}。请重新加载，无需重复${external?'操作':cleared?'清空':'保存'}。`;
  const notice=document.createElement('div'),text=document.createElement('div');
  const heading=document.createElement('strong'),description=document.createElement('span'),button=document.createElement('button');
  notice.id='workspaceSaveNotice';notice.setAttribute('role','status');
  heading.textContent=headingText;description.textContent=message;text.append(heading,description);
  button.type='button';button.textContent='重新加载';
  button.onclick=async()=>{
    button.disabled=true;notice.setAttribute('aria-busy','true');
    try{if(await refreshCommittedWorkspace({cleared,external}))toast('显示已更新')}
    finally{button.disabled=false;notice.removeAttribute('aria-busy')}
  };
  notice.append(text,button);$('#workspace .table-panel .table-wrap').before(notice);
  toast(`${headingText}，${message}`,{type:'warning'});
  return false;
}
function installInlineFindingEditors(){
  const host=$('#rows');if(!host||host.dataset.editReady)return;host.dataset.editReady='1';
  host.addEventListener('dblclick',event=>{
    const cell=event.target.closest('[data-edit-field]'),rowEl=event.target.closest('tr[data-i]');
    if(!cell||!rowEl||cell.querySelector('.inline-finding-editor'))return;
    const record=state.items[Number(rowEl.dataset.i)],field=cell.dataset.editField;if(!record)return;
    const original=field==='location'?(record.location_raw??record.location):record[field];
    const multiline=['analysis','maintenance_text'].includes(field),input=document.createElement(multiline?'textarea':'input');
    const previousHtml=cell.innerHTML,originalText=String(original??'');
    input.className='inline-finding-editor';input.value=originalText;input.rows=3;
    input.setAttribute('aria-label',cell.closest('table').querySelectorAll('thead th')[cell.cellIndex]?.textContent||field);
    input.title=multiline?'Ctrl+Enter 保存，Esc 取消':'Enter 保存，Esc 取消';
    cell.classList.add('ledger-editing');cell.replaceChildren(input);input.focus();input.select?.();
    const baseline=input.value;let done=false;
    const restore=()=>{cell.classList.remove('ledger-editing','ledger-saving');cell.removeAttribute('aria-busy');cell.innerHTML=previousHtml};
    const save=async(cancel=false)=>{
      if(done)return;done=true;
      if(cancel||input.value===baseline){restore();return}
      const value=input.value;input.disabled=true;cell.classList.add('ledger-saving');cell.setAttribute('aria-busy','true');
      let result;
      try{result=await api('/api/findings/edit',{method:'POST',body:JSON.stringify({id:record.id,field,value,expected_value:original??null})})}
      catch(error){restore();toast(error.message,{type:'error'});return}
      state.selectedRecords.delete(record.id);state.selectedIds.delete(record.id);
      cell.classList.remove('ledger-editing');cell.textContent='已保存，正在刷新…';delete cell.dataset.editField;
      // Notify all consumers at commit time, even when a following read fails.
      window.dispatchEvent(new Event('data-imported'));
      if(result.state_recognition)window.dispatchEvent(new CustomEvent('tube-state-changed',{detail:{workspaceLoaded:true}}));
      if(await refreshCommittedWorkspace()){
        const review=result.state_recognition?.pending;
        toast(review?'记录已保存，维护信息已加入待核对':'记录已保存');
      }
    };
    input.addEventListener('keydown',event=>{
      if(event.isComposing)return;
      if(event.key==='Escape'){event.preventDefault();save(true)}
      else if(event.key==='Enter'&&(!multiline||event.ctrlKey)){event.preventDefault();save(false)}
    });
    input.addEventListener('blur',()=>save(false),{once:true});
  });
}
function updateColumnFilterButtons(){
  $$('#workspace [data-column-filter]').forEach(button=>{
    const active=Boolean(workspaceColumnFilters[button.dataset.columnFilter]);
    button.classList.toggle('active',active);
    button.setAttribute('aria-pressed',String(active));
  });
}
function installColumnFilters(){
  const table=$('#workspace .table-panel table');
  const fields=[null,null,'outage','unit_id','thimble_id','position','indication','volts','degrees','percent','location','channel','probe','analyst','filename','calgroup','analysis','maintenance_text'];
  table.querySelectorAll('thead th').forEach((th,index)=>{
    const field=fields[index];if(!field||th.querySelector('[data-column-filter]'))return;
    const label=th.textContent.trim(),button=document.createElement('button');
    button.type='button';button.className='column-filter-button';button.dataset.columnFilter=field;
    button.title=`筛选${label}`;button.setAttribute('aria-label',button.title);
    button.innerHTML='<span aria-hidden="true">⌄</span>';th.append(button);
    button.onclick=()=>{
      document.querySelector('#workspaceColumnFilter')?.remove();
      const dialog=document.createElement('dialog');dialog.id='workspaceColumnFilter';
      const form=document.createElement('form');form.method='dialog';
      const heading=document.createElement('h3');heading.textContent=`筛选${label}`;
      const input=document.createElement('input');input.type='search';input.value=workspaceColumnFilters[field]||'';
      input.setAttribute('aria-label',`筛选${label}`);input.placeholder='输入包含的内容';
      const actions=document.createElement('div');actions.className='column-filter-actions';
      const clear=document.createElement('button');clear.type='button';clear.textContent='清除此列';
      const cancel=document.createElement('button');cancel.type='button';cancel.textContent='取消';
      const apply=document.createElement('button');apply.type='submit';apply.className='primary';apply.textContent='应用';
      const commit=value=>{
        if(value)workspaceColumnFilters[field]=value;else delete workspaceColumnFilters[field];
        updateColumnFilterButtons();dialog.close();state.page=1;loadRows().catch(error=>toast(error.message));
      };
      clear.onclick=()=>commit('');cancel.onclick=()=>dialog.close();
      form.onsubmit=event=>{event.preventDefault();commit(input.value.trim())};
      actions.append(clear,cancel,apply);form.append(heading,input,actions);dialog.append(form);
      dialog.addEventListener('close',()=>{dialog.remove();button.focus()},{once:true});
      document.body.append(dialog);dialog.showModal();input.focus();
    };
  });
  updateColumnFilterButtons();
}
installSelectionTools();installInlineFindingEditors();installColumnFilters();updateWorkspaceActions(!state.overview);document.addEventListener('DOMContentLoaded',()=>{installSelectionTools();installInlineFindingEditors();installColumnFilters()});
// 综合台账导出：全量数据在服务端生成表格可能持续 40–60 秒，期间按钮保持可点击；
// 第二次点击用 AbortController 中止请求，并始终显示“当前阶段 + 已用时间”，避免被误认为界面卡死。
// 服务端已开始的 Excel 生成不会随连接中断立即停止，但客户端不会再保存任何文件。
let ledgerExport=null;
function ledgerExportScopeText(){
  const values=[];
  const site=$('#site')?.value.trim(),unit=$('#unit')?.value.trim(),outage=$('#outage')?.value.trim(),analyst=$('#analyst')?.value.trim(),thimble=$('#thimble')?.value.trim();
  if(site)values.push(site);
  if(unit)values.push(`${unit} 号机组`);
  if(outage)values.push(outage);
  if(analyst)values.push(`分析：${analyst}`);
  if(thimble)values.push(`#${thimble} 通道`);
  const columns=Object.keys(workspaceColumnFilters);
  if(columns.length)values.push(`列筛选 ${columns.length} 项`);
  return values.join(' · ')||'全部检测记录';
}
function ledgerExportStatus(text,{state='busy'}={}){
  const host=$('#workspace .workspace-commands');
  if(!host)return;
  let status=$('#ledgerExportStatus');
  if(!status){
    status=document.createElement('span');
    status.id='ledgerExportStatus';
    status.className='workspace-export-status';
    status.setAttribute('role','status');
    status.setAttribute('aria-live','polite');
    host.append(status);
  }
  status.hidden=!text;
  status.dataset.state=state;
  status.title=text||'';
  status.textContent=text||'';
}
$('#exportLedgerBtn')?.addEventListener('click',async()=>{
  const button=$('#exportLedgerBtn');if(!button)return;
  // 导出中再次点击 = 取消；原生保存窗口打开时忽略，避免把“保存中”误判成可取消。
  if(ledgerExport){
    if(ledgerExport.phase!=='saving')ledgerExport.controller.abort();
    return;
  }
  const controller=new AbortController();
  const exportState=ledgerExport={controller,phase:'request',startedAt:Date.now()};
  const scope=ledgerExportScopeText();
  button.disabled=false;
  button.setAttribute('aria-busy','true');
  button.textContent='正在导出…点击取消';
  const tick=()=>{
    if(ledgerExport!==exportState)return;
    const elapsed=Math.max(0,Math.round((Date.now()-exportState.startedAt)/1000));
    if(exportState.phase==='request')ledgerExportStatus(`正在准备数据 · 已用 ${elapsed} 秒 · ${scope}`);
    else if(exportState.phase==='render')ledgerExportStatus(`正在生成表格 · 已用 ${elapsed} 秒 · ${scope}`);
  };
  tick();
  const timer=window.setInterval(tick,1000);
  // 请求阶段同时包含取数与表格生成；1.5 秒后切到“生成表格”，让等待过程有阶段感。
  const phaseTimer=window.setTimeout(()=>{if(ledgerExport===exportState&&exportState.phase==='request'){exportState.phase='render';tick()}},1500);
  try{
    const data=await api('/api/data-ledger/export',{method:'POST',body:JSON.stringify(Object.fromEntries(params())),signal:controller.signal});
    if(controller.signal.aborted)throw new DOMException('已取消','AbortError');
    exportState.phase='write';
    ledgerExportStatus(`正在写入文件 · ${data.rows} 条检测记录`);
    if(window.desktopAPI?.saveLedger){
      const response=await fetch(data.download_url,{signal:controller.signal});
      if(!response.ok)throw new Error('获取台账文件失败，请重新导出。');
      if(Number(response.headers.get('content-length'))>50*1024*1024)throw new Error('台账文件超过 50 MB，无法保存，请缩小筛选范围后重试。');
      const bytes=new Uint8Array(await response.arrayBuffer());
      if(controller.signal.aborted)throw new DOMException('已取消','AbortError');
      exportState.phase='saving';
      button.textContent='等待保存位置';
      ledgerExportStatus('请在保存窗口中选择台账保存位置');
      const saved=await window.desktopAPI.saveLedger({bytes,defaultName:data.filename});
      ledgerExportStatus('');
      toast(saved?`综合台账已保存：${saved}`:'已取消保存综合台账',{type:saved?'success':'info'});
    }else{
      const link=document.createElement('a');link.href=data.download_url;link.download=data.filename;link.click();
      ledgerExportStatus('');
      toast(`已生成 ${data.rows} 条检测记录，正在保存台账`,{type:'info'});
    }
  }catch(error){
    const aborted=controller.signal.aborted||error?.name==='AbortError';
    ledgerExportStatus('');
    toast(aborted?'已取消，未保存':error.message,{type:aborted?'info':'error'});
  }finally{
    window.clearInterval(timer);window.clearTimeout(phaseTimer);
    if(ledgerExport===exportState)ledgerExport=null;
    button.removeAttribute('aria-busy');
    button.textContent='导出综合台账';
  }
});
function syncCoreAvailability(){const map=$('#coreMap'),unit=$('#unit');if(!map||!unit)return;map.style.pointerEvents=unit.value||selectionVisualization().ready?'':'none';}
syncCoreAvailability(); $('#unit')?.addEventListener('change',syncCoreAvailability); document.addEventListener('DOMContentLoaded',syncCoreAvailability);

// Keep filter controls synchronized with the latest imported dataset.
const rebuildMainFilters = () => {
  const site = $('#site').value;
  const unit = $('#unit').value;
  const outage = $('#outage').value;
  const available = combinations().filter(item => !site || String(item.site) === String(site));
  const selectedUnit = refill('unit', available.map(item => item.unit_id), '全部机组', unit);
  refill('outage', available.filter(item => !selectedUnit || String(item.unit_id) === String(selectedUnit)).map(item => item.outage), '全部大修', outage);
};
$('#selectServerRoot').onclick=async()=>{
  const button=$('#selectServerRoot'),status=$('#serverStatus');
  if(!window.desktopAPI?.selectDirectory)return toast('请在本地桌面软件中选择检测来源文件夹');
  if(button.disabled)return;
  button.disabled=true;
  button.setAttribute('aria-busy','true');
  try{
    const selected=await window.desktopAPI.selectDirectory();
    if(selected){
      const input=$('#serverRoot');
      input.value=selected;
      input.dispatchEvent(new Event('input',{bubbles:true}));
      input.dispatchEvent(new Event('change',{bubbles:true}));
      status.textContent='已选择来源文件夹，可保存配置或扫描目录';
    }
  }catch(error){status.textContent=error.message||'无法打开文件夹选择窗口'}
  finally{button.disabled=false;button.removeAttribute('aria-busy')}
};
const scanServerButton=$('#scanServerBtn');
scanServerButton.onclick=async()=>{
  const root=$('#serverRoot').value.trim(),status=$('#serverStatus'),box=$('#serverSources');
  if(!root)return toast('请填写或选择检测来源文件夹');
  if(scanServerButton.disabled)return;
  const browseButton=$('#selectServerRoot');
  scanServerButton.disabled=true;browseButton.disabled=true;
  scanServerButton.setAttribute('aria-busy','true');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  scanServerButton.textContent='正在扫描...';status.textContent='正在识别检测来源目录...';
  box.className='server-sources empty';box.textContent='正在扫描本地或共享文件夹...';
  try{
    const data=await api('/api/discover-server',{method:'POST',body:JSON.stringify({path:root})});
    status.textContent=`已扫描 ${data.scanned_directories} 个目录，发现 ${data.items.length} 个指套管大修`;
    box.className='server-sources';
    box.innerHTML=data.items.length?data.items.map(item=>`<button type="button" data-source="${encodeURIComponent(item.path)}"><b>${displayTableCell(item.station||item.site)} · ${displayTableCell(item.outage)}</b><span>${displayTableCell(item.project)} · ${displayTableCell(item.unit_folder||'')} · ${displayTableCell(item.folder)}</span><small>${displayTableCell(item.path)}</small></button>`).join(''):'<div class="empty">未发现包含 TH 数据组的指套管目录</div>';
    $$('#serverSources [data-source]').forEach(button=>button.onclick=()=>{
      $('#importPath').value=decodeURIComponent(button.dataset.source);
      const dialog=$('#importDialog');
      if(!dialog.open)dialog.showModal();
      $('#rptImportTab').click();
      // Use the active confirmation wizard, not the retired report checkbox list.
      $('#scanReports').click();
    });
  }catch(error){
    status.textContent='扫描失败，可修改路径后重试';
    box.className='server-sources empty';box.textContent=error.message;
  }finally{
    scanServerButton.disabled=false;browseButton.disabled=false;
    scanServerButton.removeAttribute('aria-busy');scanServerButton.textContent='扫描指套管目录';
  }
};

const stateHeader=$('#stateRows')?.closest('table')?.querySelector('thead tr');
if(stateHeader&&!stateHeader.querySelector('.state-actions-head'))stateHeader.insertAdjacentHTML('beforeend','<th class="state-actions-head">操作</th>');

// Candidate reports are deliberately filtered in the dialog, while the server
// remains authoritative for parsing and duplicate/version validation.
(function installReportCandidateFilters(){
  const host=$('#reportOptions');if(!host)return;
  const toolbar=document.createElement('div');toolbar.className='report-option-filters';toolbar.hidden=true;toolbar.innerHTML='<input id="reportOptionAnalyst" type="search" aria-label="筛选已选分析人员或报告" placeholder="筛选已选分析人员或报告">';
  host.parentElement.insertBefore(toolbar,host);
  const filter=()=>{const term=String($('#reportOptionAnalyst')?.value||'').trim().toLowerCase(),rows=$$('#reportOptions .report-option, #reportOptions .report-summary-row');toolbar.hidden=!rows.length;rows.forEach(option=>{option.hidden=!!term&&!option.textContent.toLowerCase().includes(term)})};
  toolbar.addEventListener('input',filter);new MutationObserver(filter).observe(host,{childList:true});
})();
