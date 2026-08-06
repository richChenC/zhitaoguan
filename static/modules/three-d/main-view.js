const section=document.querySelector('#threeD');
const frame=document.createElement('iframe');
frame.id='threeModelFrame';
frame.className='three-model-frame';
frame.src='/visualizations/thimble/index.html?embedded=1&v=20260806f';
frame.title='指套管三维结构与缺陷模型';
frame.setAttribute('allow','fullscreen');

const scopeTools=document.createElement('div');
scopeTools.className='three-scope-controls';
scopeTools.innerHTML='<label>基地<select id="threeSite"><option value="">全部基地</option></select></label><label>机组<select id="threeUnit"><option value="">全部机组</option></select></label><label>大修<select id="threeOutage"><option value="">全部大修</option></select></label><button id="applyThreeScope" type="button">应用到三维</button>';
section.replaceChildren(frame,scopeTools);
const style=document.createElement('style');
style.textContent=`#threeD{height:calc(100vh - 88px);min-height:680px;padding:0!important;background:#080b0c;overflow:hidden;position:relative}.three-model-frame{display:block;width:100%;height:100%;border:0;background:#080b0c}.three-scope-controls{position:absolute;top:12px;right:18px;z-index:4;display:flex;align-items:end;gap:8px;padding:9px 10px;background:#101817e8;border:1px solid #41534d;box-shadow:0 4px 16px #0005}.three-scope-controls label{display:grid;gap:4px;color:#c4d0ca;font-size:10px}.three-scope-controls select{height:30px;min-width:110px;border:1px solid #5a6c65;border-radius:3px;background:#18231f;color:#eef2ed;padding:0 7px}.three-scope-controls button{height:30px;border:1px solid #d7ef4a;background:#d7ef4a;color:#151a0c;border-radius:3px;font-size:11px;font-weight:700;padding:0 10px}@media(max-width:900px){#threeD{height:calc(100vh - 72px);min-height:620px}.three-scope-controls{left:10px;right:10px;top:10px;flex-wrap:wrap}.three-scope-controls label{flex:1;min-width:100px}.three-scope-controls select{width:100%;min-width:0}}`;
section.append(style);

let latestScope={};
function readScope(){return{site:document.querySelector('#site')?.value||'',unit:document.querySelector('#unit')?.value||'',outage:document.querySelector('#outage')?.value||'',selectedItems:[]}}
function fillScopeControls(scope={}){const overview=window.__thimbleState?.overview||{};const site=document.querySelector('#threeSite'),unit=document.querySelector('#threeUnit'),outage=document.querySelector('#threeOutage');if(!site||!unit||!outage)return;const sites=overview.sites||[],units=overview.units||[],outages=overview.outages||[];site.innerHTML='<option value="">全部基地</option>'+sites.map(v=>`<option value="${v}">${v}</option>`).join('');unit.innerHTML='<option value="">全部机组</option>'+units.map(v=>`<option value="${v}">${v}</option>`).join('');outage.innerHTML='<option value="">全部大修</option>'+outages.map(v=>`<option value="${v}">${v}</option>`).join('');site.value=scope.site||'';unit.value=scope.unit||'';outage.value=scope.outage||''}
function send(type,payload={}){if(frame.contentWindow)frame.contentWindow.postMessage({type,...payload},location.origin)}
function sync(scope){latestScope=scope||readScope();send('thimble-scope',{scope:latestScope})}

frame.addEventListener('load',()=>{fillScopeControls(latestScope);sync(latestScope)});
window.addEventListener('workspace-filter-changed',event=>sync(event.detail||readScope()));
window.addEventListener('three-focus-tube',event=>{const detail=event.detail||{};latestScope={...latestScope,...detail};sync(latestScope);send('thimble-focus',{thimble:Number(detail.thimble||1)})});
window.addEventListener('message',event=>{if(event.origin===location.origin&&event.data?.type==='thimble-selected')window.dispatchEvent(new CustomEvent('three-tube-selected',{detail:event.data}))});
document.querySelector('[data-view="threeD"]')?.addEventListener('click',()=>requestAnimationFrame(()=>sync(latestScope.site!==undefined?latestScope:readScope())));
document.querySelector('#applyThreeScope')?.addEventListener('click',()=>{const site=document.querySelector('#threeSite')?.value||'',unit=document.querySelector('#threeUnit')?.value||'',outage=document.querySelector('#threeOutage')?.value||'';const set=(id,value)=>{const el=document.querySelector('#'+id);if(el){el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}))}};set('site',site);set('unit',unit);set('outage',outage);window.__thimbleLoadRows?.();latestScope={...readScope(),site,unit,outage};sync(latestScope)});
