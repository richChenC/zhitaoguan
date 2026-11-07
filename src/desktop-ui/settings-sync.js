(() => {
  'use strict';
  const revisionKey='thimble-settings-update';
  const backendEvents=new Set(['analysis-rules-changed','data-source-settings-changed',
    'backup-policy-changed','local-accounts-changed']);
  const preferenceKeys=new Set(['thimbleAppearance','thimbleUiDensity','thimbleReduceMotion',
    'thimbleStartupView','thimbleRememberView','thimbleNotificationDuration','thimbleNotificationSound']);
  const number=(key,fallback)=>{
    const raw=localStorage.getItem(key),value=raw==null||raw.trim()===''?NaN:Number(raw);
    return Number.isFinite(value)?Math.max(0,Math.min(100,value)):fallback;
  };
  function severity(){
    const color=(name,fallback)=>{
      const value=localStorage.getItem('thimbleSeverity'+name);
      return /^#[0-9a-f]{6}$/i.test(value||'')?value:fallback;
    };
    const midThreshold=number('thimbleSeverityMidThreshold',30);
    return {none:color('NoneColor','#a6afb7'),low:color('LowColor','#79b98c'),
      mid:color('MidColor','#e5a83b'),high:color('HighColor','#df4b45'),
      midThreshold,highThreshold:Math.max(midThreshold,number('thimbleSeverityHighThreshold',50)),
      pointLabels:localStorage.getItem('thimbleSeverityPointLabels')==='1'};
  }
  function applyRuntime(){
    const density=localStorage.getItem('thimbleUiDensity')==='compact'?'compact':'standard';
    const motion=localStorage.getItem('thimbleReduceMotion')==='true'?'true':'false';
    for(const node of [document.documentElement,document.body].filter(Boolean)){
      node.dataset.uiDensity=density;node.dataset.reduceMotion=motion;
    }
    const palette=severity();
    for(const key of ['none','low','mid','high'])document.documentElement.style.setProperty('--severity-'+key,palette[key]);
    window.dispatchEvent(new Event('software-runtime-settings-changed'));
  }
  window.appSettings={severity,applyRuntime};
  for(const type of backendEvents)window.addEventListener(type,event=>{
    if(event.detail?.settingsRemote)return;
    // Persist only an invalidation notice. Each window reloads authoritative
    // local service values; no credentials or draft form data are broadcast.
    localStorage.setItem(revisionKey,JSON.stringify({type,id:crypto.randomUUID()}));
  });
  let severityFrame=0;
  window.addEventListener('storage',event=>{
    if(event.key===revisionKey){
      try{
        const message=JSON.parse(event.newValue);
        if(backendEvents.has(message.type))window.dispatchEvent(new CustomEvent(message.type,{detail:{settingsRemote:true}}));
      }catch{}
    }
    if(event.key===null||preferenceKeys.has(event.key))applyRuntime();
    if(event.key===null||event.key?.startsWith('thimbleSeverity')){
      if(!severityFrame)severityFrame=requestAnimationFrame(()=>{
        severityFrame=0;applyRuntime();window.dispatchEvent(new Event('severity-settings-changed'));
      });
    }
  });
  window.addEventListener('software-preferences-changed',applyRuntime);
  window.addEventListener('severity-settings-changed',()=>{
    const palette=severity();
    for(const key of ['none','low','mid','high'])document.documentElement.style.setProperty('--severity-'+key,palette[key]);
  });
  applyRuntime();
  document.addEventListener('DOMContentLoaded',applyRuntime,{once:true});
})();
