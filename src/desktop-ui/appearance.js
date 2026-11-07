(() => {
  if(!localStorage.getItem('thimbleNddGrayDefault')){
    const old=localStorage.getItem('thimbleSeverityNoneColor');
    if(!old||old.toLowerCase()==='#ffffff')localStorage.setItem('thimbleSeverityNoneColor','#a6afb7');
    localStorage.setItem('thimbleNddGrayDefault','1');
  }
  const key = 'thimbleAppearance';
  const channelName = 'thimble-appearance';
  const normalize = value => value === 'dark' ? 'dark' : 'light';
  const root = document.documentElement;
  let channel = null;

  try {
    channel = new BroadcastChannel(channelName);
    channel.addEventListener('message', event => {
      if (event.data?.type !== 'theme') return;
      apply(event.data.theme, false);
    });
  } catch {}

  function apply(value, persist = false) {
    const theme = normalize(value);
    if (root.dataset.theme === theme && !persist) return;
    root.classList.add('theme-switching');
    root.dataset.theme = theme;
    if (persist) {
      localStorage.setItem(key, theme);
      try { channel?.postMessage({type:'theme', theme}); } catch {}
    }
    window.dispatchEvent(new CustomEvent('appearance-theme-changed', {detail:{theme}}));
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('theme-switching')));
  }

  window.appAppearance = {
    getTheme: () => normalize(root.dataset.theme || localStorage.getItem(key)),
    setTheme: (value, options = {}) => apply(value, options.persist !== false),
  };
  apply(localStorage.getItem(key), false);
  window.addEventListener('storage', event => {
    if (event.key === key) apply(event.newValue, false);
  });
})();
