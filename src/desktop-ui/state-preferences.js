(() => {
  'use strict';
  const key='thimble-state-default-shift-direction',endpoint='/api/settings/state-direction';
  const request=window.fetch.bind(window);
  const valid=value=>['1','-1','pending'].includes(value);
  let writable=true;
  const read=()=>{const value=localStorage.getItem(key);return valid(value)?value:'1'};
  function publish(settings){
    writable=settings.writable;
    localStorage.setItem(key,settings.shift_direction);
    for(const id of ['settingsShiftDirection','stateDefaultShiftDirection']){
      const field=document.getElementById(id);
      if(field){field.value=settings.shift_direction;field.disabled=!writable}
    }
    window.dispatchEvent(new CustomEvent('state-direction-changed',{detail:settings}));
  }
  async function load(data){
    const response=await request(endpoint,data?{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)
    }:{});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'移位方向设置保存失败，请重试');
    return result;
  }
  const report=error=>window.toast?.(error.message,{type:'error'});
  // Migrate the existing browser preference once. Later windows and restarts
  // read the database, including preferences restored with a backup.
  let pending=(async()=>{
    let settings=await load();
    if(!settings.initialized)settings=await load({shift_direction:read(),initialize_only:true});
    publish(settings);
  })();
  pending.catch(report);
  function enqueue(action){
    pending=pending.then(action,action);
    pending.catch(report);
    return pending;
  }
  window.statePreferences={
    read,
    get writable(){return writable},
    settled:()=>pending,
    set(value){
      if(!valid(value))return Promise.reject(new Error('无符号移位默认方向无效'));
      return enqueue(async()=>{
        try{const settings=await load({shift_direction:value});publish(settings);return settings}
        catch(error){publish(await load());throw error}
      });
    }
  };
  window.addEventListener('storage',event=>{
    if(event.key===key||event.key===null)enqueue(async()=>publish(await load()));
  });
  document.addEventListener('DOMContentLoaded',()=>{
    for(const id of ['settingsShiftDirection','stateDefaultShiftDirection']){
      const field=document.getElementById(id);
      if(field){field.value=read();field.disabled=!writable}
    }
  });
})();
