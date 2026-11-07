(() => {
  'use strict';
  const q = selector => document.querySelector(selector);
  let setup = false;
  const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('thimble-local-session'):null;
  function enterWorkspace(){
    const next=new URLSearchParams(location.search).get('next')||'/';
    const destination=new URL(next,location.origin);
    location.replace(destination.origin===location.origin&&!destination.pathname.includes('login')?destination.href:'/');
  }
  const reason=new URLSearchParams(location.search).get('reason');
  if(reason==='restore'||reason==='expired'){
    q('#loginMessage').textContent=reason==='restore'?'数据库已恢复，请重新登录。':'登录已失效，请重新登录。';
    q('#loginMessage').dataset.state='info';
  }
  channel?.addEventListener('message',async event=>{
    if(event.data!=='login')return;
    try{await api('/api/auth/me');enterWorkspace()}catch{}
  });
  window.addEventListener('beforeunload',()=>channel?.close(),{once:true});
  async function api(path, data) {
    const response = await fetch(path, data ? {method:'POST',headers:{'Content-Type':'application/json','X-Thimble-Request':'1'},body:JSON.stringify(data)} : {});
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || '本地服务暂不可用');
    return value;
  }
  async function initialize() {
    const status = await api('/api/auth/status');
    setup = !status.initialized;
    q('#loginMode').textContent = setup ? '首次使用 · 管理员初始化' : '本地账户 · 身份验证';
    q('#loginTitle').textContent = setup ? '建立管理员账户' : '登录本地工作区';
    q('#loginHint').textContent = setup ? '设置首个管理员身份，用于账户管理、权限分配和系统维护。' : '使用管理员分配的账户凭据继续工作。';
    q('#confirmPasswordField').hidden = !setup;
    q('#loginConfirmPassword').required = setup;
    q('#loginPassword').autocomplete = setup ? 'new-password' : 'current-password';
    q('#loginPassword').minLength = setup ? 6 : 1;
    q('#loginUsername').placeholder = setup ? '请输入姓名完整拼音，例如 zhangsan' : '请输入用户名';
    q('#loginPassword').placeholder = setup ? '至少 6 位' : '请输入密码';
    q('#loginSubmit').textContent = setup ? '创建管理员并进入系统' : '登录';
    q('#loginSecurityState').textContent = status.offline ? '本地服务已连接' : '连接状态未知';
    q('#loginSubmit').disabled = false;
    q('#loginUsername').focus();
  }
  q('#localLoginForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = q('#loginSubmit');button.disabled = true;
    q('#loginMessage').textContent = '';
    q('#loginMessage').dataset.state = '';
    button.textContent = setup ? '正在创建…' : '正在验证…';
    try {
      const username=q('#loginUsername').value.trim();
      const data = {username,password:q('#loginPassword').value,display_name:setup?username.toLowerCase():''};
      if (setup) {
        if (data.password !== q('#loginConfirmPassword').value) throw new Error('两次输入的密码不一致');
        await api('/api/auth/setup', data);
        setup = false;
      }
      await api('/api/auth/login', data);
      q('#loginPassword').value = q('#loginConfirmPassword').value = '';
      channel?.postMessage('login');enterWorkspace();
    } catch (error) {
      q('#loginMessage').textContent = error.message;
      q('#loginMessage').dataset.state = 'error';
      button.disabled = false;
      button.textContent = setup ? '创建管理员并进入系统' : '登录';
    }
  });
  initialize().catch(error => {
    q('#loginMessage').textContent = `无法读取本地账户状态：${error.message}。请检查本机服务与数据目录。`;
    q('#loginMessage').dataset.state = 'error';
    q('#loginSecurityState').textContent = '本地服务未就绪';
  });
})();
