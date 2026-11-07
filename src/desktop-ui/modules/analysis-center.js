import { mountImportQuality } from './import-quality.js';
import { mountReportEditor } from './report-draft-editor.js';
import { historicalOutages, validateReportScope } from './report-scope.js';

const $ = (id) => document.getElementById(id);
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {D:'大亚湾',L:'岭澳',H:'红沿河',N:'宁德',F:'防城港',Y:'阳江',T:'台山',C:'苍南',P:'惠州',LF:'陆丰'};
const labels = {normal:'正常',plugged:'堵管',shifted:'移位',replaced:'换管',unknown:'未维护'};
const palette = ['#087f8c','#bc503e','#6b79a2','#b68924','#42834c','#885a87'];
const fmt = (n) => n == null || n === '' ? '/' : Number.isInteger(n) ? String(n) : Number(n).toFixed(1);
const tableValue = (value, header) => {
  if (/备注|来源|原始|说明|依据|路径|文件|工作表/.test(header)) return value ?? '';
  return value == null || String(value).trim() === '' || /^[-—–]$/.test(String(value).trim()) ? '/' : value;
};
const api = async (url, body, signal) => {
  return window.api(url, body === undefined ? {signal} : {method:'POST',body:JSON.stringify(body),signal});
};
const options = (el, values, placeholder, old = el.value) => {
  el.innerHTML = `<option value="">${escape(placeholder)}</option>` + values.map(x => {
    const value = typeof x === 'object' ? x.value : x;
    const label = typeof x === 'object' ? x.label : x;
    return `<option value="${escape(value)}">${escape(label)}</option>`;
  }).join('');
  if ([...el.options].some(x => x.value === String(old))) el.value = String(old);
};
const table = (headers, rows, empty = '当前范围没有数据') => `<div class="ac-table-wrap"><table><thead><tr>${headers.map(h=>`<th>${escape(h)}</th>`).join('')}</tr></thead><tbody>${rows.length ? rows.map(r=>`<tr>${r.map((v,i)=>`<td>${escape(tableValue(v,headers[i]||''))}</td>`).join('')}</tr>`).join('') : `<tr><td colspan="${headers.length}" class="ac-empty">${escape(empty)}</td></tr>`}</tbody></table></div>`;
const warningNotice = warnings => {
  const groups = new Map();
  for (const warning of warnings) {
    const tube = warning.thimble_id == null ? '范围' : `${warning.thimble_id}号管`;
    const group = groups.get(tube) || {tube, reasons:[], codes:new Set()};
    const reason = String(warning.reason || '请核对原始资料和导入记录');
    if (!group.reasons.includes(reason)) group.reasons.push(reason);
    if (warning.code) group.codes.add(warning.code);
    groups.set(tube, group);
  }
  const items = [...groups.values()].sort((a,b) => {
    if (a.tube === '范围') return -1;
    if (b.tube === '范围') return 1;
    return Number.parseInt(a.tube, 10) - Number.parseInt(b.tube, 10);
  });
  const rows = items.map(group => {
    const details = group.reasons.length > 1
      ? `<details class="ac-warning-detail"><summary>展开 ${group.reasons.length} 条具体提示</summary><ul>${group.reasons.map(reason => `<li>${escape(reason)}</li>`).join('')}</ul></details>`
      : '';
    return `<article class="ac-warning-item"><div class="ac-warning-item-head"><strong>${escape(group.tube)}</strong><span>${group.reasons.length} 条提示</span></div><p>${escape(group.reasons[0])}</p>${details}</article>`;
  }).join('');
  return `<details class="ac-notice ac-warning-groups" open><summary><span>需人工核查</span><b>${items.length} 个管号</b><em>${warnings.length} 条提示</em></summary><p class="ac-warning-intro">同一根管的多条历史记录已合并；请按管号展开核对原始报告，不代表出现了多根同号管。</p><div class="ac-warning-list">${rows}</div></details>`;
};

let overview = null, overviewLoading=null, overviewRequest=0, reportRequest=0, lastSnapshot=null, lastPayload=null, reportMode='inspection';
let exportBusy=false;
let workspaceRecords=[];
let reportAbort=null, reportTimer=0, mounted=false;
let reportTemplates=[], reportCatalogReady=false, reportCatalogError='', reportCatalogLoading=null, reportEditor=null, previewZoom=100, fitPreviewOnResize=false;
const reportHeaders = new Map();
let headerScope = '';
let importedHeaderFields = null;
const fieldDefinitions = [
  ['reportComponentNo','设备/部件编号'],['reportNo','报告单编码'],['reportPlant','电厂名称'],
  ['reportInspection','检查类型'],['reportComponent','设备/部件名称'],['reportSafety','安全等级'],
  ['reportRoom','房间号'],['reportScope','检验范围'],['reportMaterial','材料'],['reportSize','尺寸'],
  ['reportInstrumentModel','涡流仪型号'],['reportInstrumentSerial','涡流仪出厂编号'],['reportCalibrationNo','标定管编号'],
  ['reportProbeType','探头类型'],['reportProbeModel','探头型号'],['reportProbeSpec','探头规格'],
  ['reportSpeed','检验速度'],['reportSampleRate','采样率'],['reportFrequency','检验频率'],['reportProcedure','检验程序/版次']
];

function scopeControls(prefix, required=false) {
  return `<div class="ac-scope"><label>基地<select id="${prefix}Site" aria-label="基地"></select></label><label>机组<select id="${prefix}Unit" aria-label="机组"></select></label><label>本次大修<select id="${prefix}Outage" aria-label="本次大修"></select></label>${required?'':`<button id="${prefix}Refresh" type="button" title="刷新本机数据" aria-label="刷新本机数据">↻</button>`}</div>`;
}

function syncScope(prefix, changed='') {
  const list=overview?.combinations || [], site=$(prefix+'Site'), unit=$(prefix+'Unit'), outage=$(prefix+'Outage');
  if(changed==='site'){unit.value='';outage.value='';}
  if(changed==='unit')outage.value='';
  const sites=[...new Set(list.map(x=>x.site))].sort();
  options(site,sites.map(s=>({value:s,label:`${names[s]||s}（${({P:'HZ',C:'CN'}[s]||s)}）`})),prefix==='rc'?'选择基地':'全部基地');
  const units=[...new Set(list.filter(x=>!site.value||x.site===site.value).map(x=>x.unit_id))].sort((a,b)=>a-b);
  options(unit,units.map(u=>({value:u,label:u+'号机组'})),prefix==='rc'?'选择机组':'全部机组');
  const codes=list.filter(x=>(!site.value||x.site===site.value)&&(!unit.value||String(x.unit_id)===unit.value)).map(x=>x.outage).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  options(outage,[...new Set(codes)].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true})),prefix==='rc'?'选择本次大修':'全部大修');
  if(prefix==='rc') {
    unit.disabled=!site.value;
    outage.disabled=!site.value||!unit.value;
    if(unit.disabled)unit.value='';
    if(outage.disabled)outage.value='';
    const old=$('rcOld');
    const history=historicalOutages(codes,outage.value);
    options(old,history,'选择历史大修');
    old.disabled=!history.length;
    if(!history.length)old.options[0].textContent=outage.value?'当前机组没有更早的大修数据':'请先选择本次大修';
    $('rcLatest').disabled=outage.disabled||!codes.length;
    syncHeaderScope();
  }
}

function readScope(prefix) {return {site:$(prefix+'Site').value,unit:Number($(prefix+'Unit').value||0),outage:$(prefix+'Outage').value};}

function syncHeaderScope() {
  const scope=readScope('rc'), key=scope.site&&scope.unit&&scope.outage?JSON.stringify(scope):'';
  if(key===headerScope)return;
  if(headerScope)reportHeaders.set(headerScope,fieldDefinitions.map(([id])=>[id,$(id)?.value||'']));
  const saved=new Map(reportHeaders.get(key)||importedHeaderFields||[]);
  for(const [id] of fieldDefinitions)if($(id))$(id).value=saved.get(id)||(id==='reportComponent'?'指套管':'');
  headerScope=key;
}

async function loadOverview({force=false}={}) {
  if(overviewLoading&&!force)return overviewLoading;
  const request=++overviewRequest;
  const pending=(async()=>{
    try{
      const data=await api('/api/overview');
      if(request!==overviewRequest)return;
      overview=data;syncScope('rc');
    }catch(error){if(request===overviewRequest)throw error;}
  })();
  overviewLoading=pending;
  try{await pending;}finally{if(overviewLoading===pending)overviewLoading=null;}
}

function mountReports() {
  const root=$('reports'), form=document.createElement('form');
  form.id='reportForm';
  const headerGroups=[['报告与设备',fieldDefinitions.slice(0,10)],['仪器与探头',fieldDefinitions.slice(10,16)],['检验参数与规程',fieldDefinitions.slice(16)]];
  form.innerHTML=`<section id="reportHeaderTable" class="report-header-table">${headerGroups.map(([name,fields])=>`<fieldset class="rc-field-group"><legend>${name}</legend>${fields.map(([id,label])=>`<label class="report-header-cell"><span>${escape(label)}</span><input id="${id}" value="${id==='reportComponent'?'指套管':''}"></label>`).join('')}</fieldset>`).join('')}</section>`;
  const headerActions=document.createElement('div');
  headerActions.id='reportHeaderFileActions';
  headerActions.className='report-header-file-actions';
  headerActions.innerHTML='<span id="reportExportStatus" role="status"></span><button id="importReportHeader" type="button">导入设置文件</button><button id="exportReportHeader" type="button">保存设置文件</button><input id="reportHeaderFileInput" type="file" accept="application/json,.json" hidden>';
  const center=document.createElement('div');
  center.className='report-center rc-workspace';
  center.dataset.mode='inspection';
  center.innerHTML=`
    <div class="rc-topbar">
      <div id="reportModeTabs" class="rc-mode-tabs" role="tablist" aria-label="报告类型">
        <button id="rcInspectionTab" type="button" class="active" data-report-mode="result" role="tab" aria-selected="true" aria-controls="rcReportPanel">检验报告单</button>
        <button id="rcComparisonTab" type="button" data-report-mode="history" role="tab" aria-selected="false" aria-controls="rcReportPanel" tabindex="-1">检验结果比对表</button>
      </div>
      <div class="rc-scope-actions">
        <button id="rcUseWorkspace" type="button" title="带入数据工作台当前的基地、机组和大修"><i class="rc-icon rc-icon-database" aria-hidden="true"></i>工作台范围</button>
        <button id="rcRefresh" class="rc-icon-button" type="button" aria-label="刷新报告" title="刷新报告"></button>
      </div>
    </div>
    <div id="rcReportPanel" role="tabpanel" aria-labelledby="rcInspectionTab">
      <div class="ac-scope rc-toolbar">
        <div id="rcScopeHost"></div>
        <label id="rcOldLabel" hidden>历史大修<select id="rcOld" aria-label="历史大修"></select></label>
        <button id="rcLatest" type="button" title="选择当前机组已导入的最新大修" disabled>最新大修</button>
      </div>
      <div class="rc-context-line">
        <span id="rcStatus" role="status" aria-live="polite">请选择基地、机组和本次大修</span>
        <span id="rcCatalogStatus" class="rc-catalog-status" role="status" aria-live="polite">正在读取报告表式</span>
      </div>
      <div class="rc-options">
        <label id="rcSelectedLabel"><input type="checkbox" id="rcSelected">仅使用工作台勾选记录 <span id="rcSelectedCount">(0)</span></label>
        <span id="rcFullScope" hidden>完整比对 · 全部50根管</span>
        <details id="rcHeader"><summary>表头与设备信息</summary><div id="rcHeaderActions"></div><div id="rcHeaderForm"></div></details>
      </div>
      <div id="rcWarnings"></div>
      <div class="rc-preview-heading">
        <div class="rc-preview-label"><h2 id="rcPreviewTitle">检验报告单预览</h2><span id="rcSnapshot">预览待更新</span></div>
        <div class="rc-downloads">
          <select id="rcFormat" aria-label="导出格式"><option value="docx">Word (.docx)</option><option value="xlsx">Excel (.xlsx)</option></select>
          <button id="rcExport" class="primary" disabled><span id="rcExportLabel">导出检验报告单</span></button>
        </div>
      </div>
      <div class="rc-viewbar" role="group" aria-label="预览工具">
        <div class="rc-zoom-tools">
          <button id="rcScrollLeft" class="rc-icon-button" type="button" aria-label="向左查看报告" title="向左查看报告"><i class="rc-icon rc-icon-left" aria-hidden="true"></i></button>
          <button id="rcZoomOut" class="rc-icon-button" type="button" aria-label="缩小预览" title="缩小预览"><span aria-hidden="true">−</span></button>
          <span id="rcZoomValue">100%</span>
          <button id="rcZoomIn" class="rc-icon-button" type="button" aria-label="放大预览" title="放大预览"><span aria-hidden="true">+</span></button>
          <button id="rcZoomFit" type="button" aria-label="适合窗口宽度" title="适合窗口宽度">适宽</button>
          <button id="rcScrollRight" class="rc-icon-button" type="button" aria-label="向右查看报告" title="向右查看报告"><i class="rc-icon rc-icon-right" aria-hidden="true"></i></button>
        </div>
        <button id="rcToggleEditor" type="button" aria-pressed="false" aria-controls="rcEditor" title="显示或隐藏修改草稿">修改草稿</button>
      </div>
      <div id="rcDocumentLayout" class="rc-document-layout" data-editor="closed">
        <div id="rcPreview" class="rc-preview"><p class="ac-empty">请选择基地、机组和本次大修</p></div>
        <aside id="rcEditor" class="rc-editor" aria-label="报告修改草稿"></aside>
      </div>
      <div id="rcDownload" role="status"></div>
      <details id="rcSources"><summary>来源追溯</summary><div id="rcSourceRows"></div></details>
    </div>`;
  root.append(center);
  reportEditor=mountReportEditor({host:$('rcEditor'),preview:$('rcPreview'),onApply:()=>queueReport({preservePreview:true})});
  $('rcToggleEditor').onclick=()=>{const open=$('rcToggleEditor').getAttribute('aria-pressed')!=='true';$('rcToggleEditor').setAttribute('aria-pressed',String(open));$('rcToggleEditor').textContent=open?'收起草稿':'修改草稿';$('rcDocumentLayout').dataset.editor=open?'open':'closed';};
  const zoom=delta=>{fitPreviewOnResize=false;previewZoom=Math.min(150,Math.max(50,previewZoom+delta));applyPreviewZoom();};
  $('rcZoomOut').onclick=()=>zoom(-10);$('rcZoomIn').onclick=()=>zoom(10);
  $('rcZoomFit').onclick=fitPreviewWidth;
  $('rcScrollLeft').onclick=()=>scrollPreview(-1);
  $('rcScrollRight').onclick=()=>scrollPreview(1);
  if(window.ResizeObserver){
    const previewObserver=new ResizeObserver(()=>{if(fitPreviewOnResize)fitPreviewWidth({scroll:false});});
    previewObserver.observe($('rcPreview'));
  }
  $('rcSnapshot').textContent='预览待更新';
  for(const key of ['site','unit','outage']){const el=document.createElement('select'),label=document.createElement('label');label.textContent={site:'基地',unit:'机组',outage:'本次大修'}[key];el.id='rc'+key[0].toUpperCase()+key.slice(1);el.setAttribute('aria-label',label.textContent);label.append(el);$('rcScopeHost').append(label);}
  $('rcHeaderForm').append(form);form.hidden=false;
  if(headerActions){$('rcHeaderActions').append(headerActions);headerActions.querySelector('[type="submit"]')?.remove();headerActions.querySelector('#toggleReportHeader')?.remove();}
  form.querySelectorAll('button[type="submit"]').forEach(b=>b.remove());
  form.onsubmit=e=>e.preventDefault();
  for(const [id] of fieldDefinitions){const el=$(id);if(el && id!=='reportComponent')el.value='';}
  // Existing saved settings remain opt-in, never silently carried across units.
  const grid=$('reportHeaderTable');if(grid)grid.hidden=false;
  window.scheduleInlineReport=queueReport;window.refreshInlineReport=refreshReport;
  for(const type of ['Site','Unit','Outage'])$('rc'+type).addEventListener('change',()=>{syncScope('rc',type.toLowerCase());resetReportDraft();invalidateReport();queueReport();});
  $('rcLatest').onclick=()=>{
    const select=$('rcOutage'), latest=[...select.options].filter(option=>option.value).at(-1);
    if(latest&&select.value!==latest.value){select.value=latest.value;select.dispatchEvent(new Event('change'));}
  };
  $('rcUseWorkspace').onclick=async()=>{
    const button=$('rcUseWorkspace');
    if(button.disabled)return;
    button.disabled=true;
    try{
      if(!overview)await loadOverview();
      const context=await window.desktopAPI?.getWorkspaceReportScope?.();
      const scope=context?.scope||{site:$('site').value,unit:$('unit').value,outage:$('outage').value};
      workspaceRecords=context?.records||[];
      $('rcSelectedCount').textContent=`(${workspaceRecords.length})`;
      if(!scope.site||!scope.unit||!scope.outage){window.toast('请先在数据工作台选择基地、机组和大修');return;}
      $('rcSite').value=scope.site;syncScope('rc','site');
      $('rcUnit').value=scope.unit;syncScope('rc','unit');
      $('rcOutage').value=scope.outage;syncScope('rc');
      resetReportDraft();queueReport();
    }catch(error){window.toast(error.message,{type:'error'});}
    finally{button.disabled=false;}
  };
  const setReportMode = mode => {
    if(reportMode===(mode==='history'?'comparison':'inspection'))return;
    reportMode=mode==='history'?'comparison':'inspection';
    $('rcSelected').disabled=reportMode==='comparison';
    if(reportMode==='comparison')$('rcSelected').checked=false;
    center.dataset.mode=reportMode;
    $('rcSelectedLabel').hidden=reportMode==='comparison';
    $('rcFullScope').hidden=reportMode!=='comparison';
    resetReportDraft();
    $('rcOldLabel').hidden=reportMode!=='comparison';
    $('rcHeader').hidden=reportMode!=='inspection';
    $('rcFormat').querySelector('[value="docx"]').disabled=false;
    document.querySelectorAll('#rcModeTabs [data-report-mode], .rc-mode-tabs [data-report-mode]').forEach(button=>{
      const active=button.dataset.reportMode===mode;
      button.classList.toggle('active',active);
      button.setAttribute('aria-selected',String(active));
      button.tabIndex=active?0:-1;
    });
    $('rcReportPanel').setAttribute('aria-labelledby',mode==='history'?'rcComparisonTab':'rcInspectionTab');
    $('rcPreviewTitle').textContent=reportMode==='comparison'?'检验结果比对表预览':'检验报告单预览';
    $('rcExportLabel').textContent=reportMode==='comparison'?'导出检验结果比对表':'导出检验报告单';
    invalidateReport();
    queueReport();
  };
  document.querySelectorAll('.rc-mode-tabs [data-report-mode]').forEach(button=>button.onclick=()=>setReportMode(button.dataset.reportMode));
  $('reportModeTabs').onkeydown=event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const buttons=[...$('reportModeTabs').querySelectorAll('[role=tab]')];
    const index=event.key==='Home'?0:event.key==='End'?1:reportMode==='inspection'?1:0;
    setReportMode(buttons[index].dataset.reportMode);buttons[index].focus();
  };
  $('rcOld').onchange=()=>{resetReportDraft();queueReport();};$('rcSelected').onchange=()=>{resetReportDraft();queueReport();};
  $('rcRefresh').onclick=()=>{
    clearTimeout(reportTimer);reportRequest++;reportAbort?.abort();invalidateReport();
    $('rcStatus').textContent='正在刷新报告…';
    Promise.all([loadOverview({force:true}),loadReportTemplates(true)]).then(()=>refreshReport()).catch(e=>{$('rcStatus').textContent=e.message;});
  };
  $('rcExport').onclick=()=>exportReport().catch(error=>{window.toast(error.message);queueReport();});
  form.addEventListener('input',queueReport);form.addEventListener('change',queueReport);
  $('rcHeader').open=false;
  bindHeaderFiles();
}

function bindHeaderFiles(){
  const apply=raw=>{
    const config=JSON.parse(raw);
    if(config?.schema!=='thimble-report-header'||config.version!==1||!config.fields||Array.isArray(config.fields)||typeof config.fields!=='object')throw new Error('不是有效的指套管报告表头设置文件');
    importedHeaderFields=new Map(fieldDefinitions
      .filter(([id])=>Object.hasOwn(config.fields,id))
      .map(([id])=>[id,String(config.fields[id]??'')]));
    for(const [id] of fieldDefinitions)if(importedHeaderFields.has(id))$(id).value=importedHeaderFields.get(id);
    queueReport();window.toast('报告表头设置已导入');
  };
  const run=async(button,action)=>{button.disabled=true;try{await action();}catch(error){window.toast(error.message);}finally{button.disabled=false;}};
  $('importReportHeader').onclick=event=>run(event.currentTarget,async()=>{
    if(window.desktopAPI?.openReportHeader){const raw=await window.desktopAPI.openReportHeader();if(raw)apply(raw);}
    else $('reportHeaderFileInput').click();
  });
  $('reportHeaderFileInput').onchange=event=>{const file=event.target.files?.[0];event.target.value='';if(file)run($('importReportHeader'),async()=>{if(file.size>256*1024)throw new Error('设置文件过大');apply(await file.text());});};
  $('exportReportHeader').onclick=event=>run(event.currentTarget,async()=>{
    const content=JSON.stringify({schema:'thimble-report-header',version:1,updated_at:new Date().toISOString(),fields:Object.fromEntries(fieldDefinitions.map(([id])=>[id,$(id).value]))},null,2);
    const defaultName=window.exportArtifactName?.('报告表头设置',$('reportPlant').value||'指套管','json')||'TH_report-header.json';
    if(window.desktopAPI?.saveReportHeader){if(await window.desktopAPI.saveReportHeader({content,defaultName}))window.toast('报告表头设置已保存');}
    else {const url=URL.createObjectURL(new Blob([content],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download=defaultName;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  });
}

function resetReportDraft(){reportEditor?.reset();}
function applyPreviewZoom(){
  $('rcZoomValue').textContent=previewZoom+'%';
  $('rcPreview').querySelectorAll('.report-sheet').forEach(page=>{page.style.zoom=String(previewZoom/100);});
  $('rcZoomOut').disabled=previewZoom<=50;$('rcZoomIn').disabled=previewZoom>=150;
}
function scrollPreview(direction){
  const preview=$('rcPreview');
  preview.scrollBy({left:direction*Math.max(240,preview.clientWidth*.72),behavior:'smooth'});
}
function fitPreviewWidth({scroll=true}={}){
  fitPreviewOnResize=true;
  const preview=$('rcPreview'),page=preview.querySelector('.report-sheet');
  if(!page)return;
  const style=getComputedStyle(preview);
  const available=preview.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)-8;
  const pageWidth=page.offsetWidth||page.getBoundingClientRect().width/(previewZoom/100);
  if(pageWidth>0)previewZoom=Math.min(150,Math.max(50,Math.floor(available/pageWidth*100)));
  applyPreviewZoom();
  if(scroll)preview.scrollTo({left:0,behavior:'smooth'});
}
function syncReportFormats(){
  const selected=$('rcFormat').value;
  options($('rcFormat'),[
    {value:'docx',label:'Word (.docx)'},
    {value:'xlsx',label:'Excel (.xlsx)'}
  ],'选择格式',selected);
  if(!$('rcFormat').value)$('rcFormat').value='docx';
}
async function loadReportTemplates(force=false){
  if(reportCatalogLoading)return reportCatalogLoading;
  if(reportCatalogReady&&!force)return;
  reportCatalogLoading=(async()=>{
    $('rcCatalogStatus').textContent='正在读取报告模板';$('rcCatalogStatus').dataset.error='false';
    try{
      const data=await api('/api/reports/templates');
      if(!Array.isArray(data.templates)||!data.templates.length||data.templates.some(item=>!item.id||!item.title||!['inspection','comparison'].includes(item.mode)))throw new Error('报告模板目录不完整');
      const available=new Set(data.templates.map(item=>item.id));
      if(!available.has('inspection')||!available.has('comparison'))throw new Error('检验报告单或检验结果比对表表式缺失');
      reportTemplates=data.templates;reportCatalogReady=true;reportCatalogError='';
      syncReportFormats();
      $('rcCatalogStatus').textContent='表式已就绪';
    }catch(error){
      reportCatalogReady=false;reportCatalogError=`报告模板读取失败：${error.message}`;
      $('rcCatalogStatus').textContent=reportCatalogError;$('rcCatalogStatus').dataset.error='true';
      invalidateReport();
      throw error;
    }finally{reportCatalogLoading=null;}
  })();
  return reportCatalogLoading;
}
function invalidateReport({preservePreview=false}={}){
  clearTimeout(reportTimer);reportRequest++;reportAbort?.abort();
  lastSnapshot=null;lastPayload=null;$('rcExport').disabled=true;
  $('rcStatus').dataset.state='pending';
  $('rcStatus').textContent='预览待更新';
  if(preservePreview){
    $('rcSnapshot').textContent='草稿同步中';
    $('rcPreview').setAttribute('aria-busy','true');
  }else{
    $('rcPreview').removeAttribute('aria-busy');
    reportEditor?.pending();
    $('rcSnapshot').textContent='预览待更新';
    $('rcPreview').innerHTML='<p class="ac-empty">正在准备报告预览…</p>';
    $('rcSourceRows').replaceChildren();
    $('rcWarnings').replaceChildren();
    $('rcDownload').replaceChildren();
  }
}
function queueReport(options={}){
  if(!mounted)return;
  try{if(lastSnapshot&&JSON.stringify(reportPayload())===JSON.stringify(lastPayload))return;}catch{}
  invalidateReport({preservePreview:options?.preservePreview===true});reportTimer=setTimeout(refreshReport,260);
}
function reportPayload(){
  const scope=readScope('rc');
  if(reportMode==='comparison'){$('rcSelected').checked=false;$('rcSelected').disabled=true;}else{$('rcSelected').disabled=false;}
  if(!reportCatalogReady)throw new Error(reportCatalogError||'正在读取报告模板');
  if(!scope.site||!scope.unit||!scope.outage)throw new Error('请选择基地、机组和本次大修');
  if(reportMode==='comparison'&&!$('rcOld').value)throw new Error($('rcOld').disabled?'当前机组没有可对比的历史大修，请选择其他范围或导入历史数据':'请选择历史大修');
  validateReportScope(scope,reportMode==='comparison'?$('rcOld').value:'');
  const selected=workspaceRecords;
  $('rcSelectedCount').textContent=`(${selected.length})`;
  if($('rcSelected').checked && !selected.length)throw new Error('工作台尚未勾选记录');
  if($('rcSelected').checked && selected.some(r=>r.outage!==scope.outage||Number(r.unit_id)!==scope.unit||(r.site_code&&r.site_code!==scope.site)))throw new Error('工作台勾选记录与报告范围不同，请重新带入工作台范围');
  return {...scope,kind:reportMode,old:reportMode==='comparison'?$('rcOld').value:'',template_id:reportMode,draft_edits:reportEditor?.payload()||[],finding_ids:$('rcSelected').checked?selected.map(r=>r.id):[],metadata:reportMode==='comparison'?{}:Object.fromEntries([['机组',String(scope.unit)],...fieldDefinitions.map(([id,label])=>[label,$(id)?.value || ''])])};
}
async function refreshReport(){
  if(!mounted)return;
  invalidateReport();
  const request=reportRequest;reportAbort=new AbortController();
  $('rcPreview').setAttribute('aria-busy','true');
  try{
    const payload=reportPayload();$('rcStatus').textContent='正在生成可追溯预览…';
    const data=await api('/api/reports/preview',payload,reportAbort.signal);if(request!==reportRequest)return;
    lastPayload=payload;lastSnapshot=data;
    $('rcPreview').innerHTML=data.html;
    if(fitPreviewOnResize)fitPreviewWidth({scroll:false});else applyPreviewZoom();
    reportEditor.sync(data);$('rcSnapshot').textContent=`共 ${data.rows} 条记录${data.draft_audit?.length?` · 人工修改 ${data.draft_audit.length} 项`:''}`;
    $('rcStatus').dataset.state=data.coverage_complete===false?'error':'ready';
    $('rcStatus').textContent=`${names[data.site]||data.site} ${data.unit}号机组 · ${data.kind==='comparison'?`${data.old} → ${data.outage} · 全部50根管`:`${data.outage} · ${$('rcSelected').checked?'勾选记录':'全部记录'}`} · ${data.rows} 行`;
    const warnings=data.warnings||[],coverage=data.coverage||[];
    const coverageText=coverage.map(c=>`${escape(c.outage)}：实际记录 ${c.present}/50 根${c.missing.length?`，缺少通道 ${c.missing.join('、')}`:'，完整'}`).join('<br>');
    const historicalWarnings=warnings.filter(item=>item.code==='unmatched_history');
    const historicalTubeCount=new Set(historicalWarnings.map(item=>item.thimble_id)).size;
    $('rcWarnings').innerHTML=(data.kind==='comparison'?`<div class="${data.coverage_complete?'comparison-coverage complete':'rc-coverage-error'}" role="status"><strong>${data.coverage_complete?'50根管完整性检查通过':'50根管完整性检查未通过，禁止正式导出'}</strong><p>${coverageText}</p></div><div class="rc-comparison-summary"><span>原有显示 R <b>${data.summary?.R||0}</b><small>历史缺陷仍存在</small></span><span>新增显示 NI <b>${data.summary?.NI||0}</b><small>本次新出现</small></span><span>待确认 <b>${data.summary?.['待确认']||0}</b><small>需要人工判断</small></span><span>历史未匹配 <b>${data.summary?.historical_unmatched||0}</b><small>${historicalTubeCount?`涉及 ${historicalTubeCount} 个管号`:'历史记录条数'}</small></span><span>双方 NDD <b>${data.summary?.NDD||0}</b><small>两次均无显示</small></span></div>`:'')+(warnings.length?warningNotice(warnings):'');
    $('rcSourceRows').innerHTML=table(data.source_headers||[],data.sources||[]);
    $('rcExport').disabled=exportBusy||data.coverage_complete===false;
  }catch(error){if(request!==reportRequest||error.name==='AbortError')return;$('rcStatus').dataset.state='pending';$('rcStatus').textContent=error.message;$('rcPreview').innerHTML=`<p class="ac-empty">${escape(error.message)}</p>`;}
  finally{if(request===reportRequest)$('rcPreview').removeAttribute('aria-busy');}
}
async function exportReport(){
  if(exportBusy||!lastSnapshot||!lastPayload||lastSnapshot.coverage_complete===false)return;
  const payload=reportPayload();if(JSON.stringify(payload)!==JSON.stringify(lastPayload)){queueReport();return;}
  const snapshot=lastSnapshot,exportRequest=reportRequest;
  exportBusy=true;
  $('rcExport').disabled=true;$('rcExport').setAttribute('aria-busy','true');$('rcExportLabel').textContent='正在导出…';$('rcDownload').textContent='正在导出…';
  try{
    const data=await api('/api/reports/export',{...lastPayload,snapshot_id:snapshot.snapshot_id,format:$('rcFormat').value});
    if(exportRequest!==reportRequest)return;
    const anchor=document.createElement('a');anchor.href=data.download_url;anchor.download=data.filename;anchor.textContent=`${data.filename} · ${data.rows} 行`;$('rcDownload').replaceChildren(anchor);
    if(data.provenance_download_url){
      const evidence=document.createElement('a');evidence.href=data.provenance_download_url;evidence.download=data.provenance_filename;evidence.textContent='来源与核查凭证';
      let savingEvidence=false;
      evidence.onclick=async event=>{
        event.preventDefault();if(savingEvidence)return;savingEvidence=true;evidence.setAttribute('aria-disabled','true');
        try{const result=await window.saveGeneratedProvenance(data);window.toast(result.status==='saved'?`凭证已保存：${result.path}`:result.status==='cancelled'?'已取消保存凭证':'凭证已生成，正在下载',{type:result.status==='saved'?'success':'info'});}
        catch(error){window.toast(`凭证保存失败：${error.message}，可点击凭证重试。`,{type:'error'});}
        finally{savingEvidence=false;evidence.removeAttribute('aria-disabled');}
      };
      $('rcDownload').append(document.createTextNode(' · '),evidence);
    }
    let saveBusy=false;
    const save=async()=>{
      if(saveBusy)return;
      saveBusy=true;anchor.setAttribute('aria-disabled','true');
      try{const saved=await window.saveGeneratedOfficeFile(data);window.toast(saved.status==='saved'?`报告已保存：${saved.path}`:saved.status==='cancelled'?'已取消保存报告':'报告已生成，正在保存',{type:saved.status==='saved'?'success':'info'});}
      finally{saveBusy=false;anchor.removeAttribute('aria-disabled');}
    };
    anchor.addEventListener('click',event=>{event.preventDefault();save().catch(error=>window.toast(error.message,{type:'error'}));});
    await save();
  }catch(error){if(exportRequest===reportRequest){if(!$('rcDownload').querySelector('a'))$('rcDownload').textContent=error.message;window.toast(error.message,{type:'error'});if(error.message.includes('变化'))queueReport();}}
  finally{exportBusy=false;$('rcExport').removeAttribute('aria-busy');$('rcExportLabel').textContent=reportMode==='comparison'?'导出检验结果比对表':'导出检验报告单';$('rcExport').disabled=!lastSnapshot||lastSnapshot.coverage_complete===false;}
}

async function init(){
  if(mounted||document.body.dataset.window==='settings'||!$('reports'))return;
  mountReports();mounted=true;
  for(const event of ['database-cleared','data-imported','data-deleted','data-restored','workspace-data-changed']){
    window.addEventListener(event,()=>{overview=null;resetReportDraft();invalidateReport();
      const ready=loadOverview({force:true});
      ready.then(()=>queueReport()).catch(e=>{$('rcStatus').textContent=e.message;});});
  }
  window.addEventListener('tube-state-changed',()=>{resetReportDraft();invalidateReport();queueReport();});
  window.addEventListener('analysis-rules-changed',()=>{resetReportDraft();invalidateReport();queueReport();});
  workspaceRecords=[...(window.__thimbleState?.selectedRecords?.values()||[])];
  window.addEventListener('workspace-selection-settled',()=>{workspaceRecords=[...(window.__thimbleState?.selectedRecords?.values()||[])];$('rcSelectedCount').textContent=`(${workspaceRecords.length})`;if($('rcSelected').checked)queueReport();});
  try{await Promise.all([loadOverview(),loadReportTemplates()]);queueReport();}catch(e){$('rcStatus').textContent=e.message;}
}
function prepareSettings(){
  if(document.body.dataset.window==='settings')mountImportQuality($('settingsImportPane'));
  window.addEventListener('app-view-changed',event=>{if(event.detail?.view==='reports')init();});
  if($('reports')?.classList.contains('active'))init();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',prepareSettings,{once:true});else prepareSettings();
