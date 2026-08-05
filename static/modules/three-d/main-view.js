const section=document.querySelector('#threeD');
const frame=document.createElement('iframe');
frame.id='threeModelFrame';
frame.className='three-model-frame';
frame.src='/visualizations/thimble/index.html?embedded=1&v=20260806a';
frame.title='指套管三维结构与缺陷模型';
frame.setAttribute('allow','fullscreen');

section.replaceChildren(frame);
const style=document.createElement('style');
style.textContent=`#threeD{height:calc(100vh - 88px);min-height:680px;padding:0!important;background:#080b0c;overflow:hidden}.three-model-frame{display:block;width:100%;height:100%;border:0;background:#080b0c}@media(max-width:900px){#threeD{height:calc(100vh - 72px);min-height:620px}}`;
section.append(style);

let latestScope={};
function readScope(){return{site:document.querySelector('#site')?.value||'',unit:document.querySelector('#unit')?.value||'',outage:document.querySelector('#outage')?.value||'',selectedItems:[]}}
function send(type,payload={}){if(frame.contentWindow)frame.contentWindow.postMessage({type,...payload},location.origin)}
function sync(scope){latestScope=scope||readScope();send('thimble-scope',{scope:latestScope})}

frame.addEventListener('load',()=>sync(latestScope));
window.addEventListener('workspace-filter-changed',event=>sync(event.detail||readScope()));
window.addEventListener('three-focus-tube',event=>{const detail=event.detail||{};latestScope={...latestScope,...detail};sync(latestScope);send('thimble-focus',{thimble:Number(detail.thimble||1)})});
window.addEventListener('message',event=>{if(event.origin===location.origin&&event.data?.type==='thimble-selected')window.dispatchEvent(new CustomEvent('three-tube-selected',{detail:event.data}))});
document.querySelector('[data-view="threeD"]')?.addEventListener('click',()=>requestAnimationFrame(()=>sync(latestScope.site!==undefined?latestScope:readScope())));
