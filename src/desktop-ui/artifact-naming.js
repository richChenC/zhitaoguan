(() => {
  'use strict';
  const siteCode = value => ({P:'HZ', C:'CN', HZ:'HZ', CN:'CN'}[value] || String(value || ''));
  const unitCode = value => String(value || '').replace(/^([A-Za-z]+)(?=\d)/, code => siteCode(code));
  const segment = value => String(value || '范围未指定').trim()
    .replace(/[<>:"/\\|?*\x00-\x1f\s]+/g, '-').replace(/-+/g, '-')
    .replace(/^[ ._-]+|[ ._-]+$/g, '').slice(0, 36).replace(/[ ._-]+$/g, '') || '范围未指定';
  function filename(kind, scope, extension) {
    const suffix = String(extension || '').replace(/^\./, '').toLowerCase();
    if (!/^[a-z0-9]{1,8}$/.test(suffix)) throw new Error('导出文件扩展名无效');
    const date = new Date(), pad = (value, size = 2) => String(value).padStart(size, '0');
    const stamp = `${date.getFullYear()}${pad(date.getMonth()+1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
    const token = crypto.randomUUID().replaceAll('-', '').slice(0, 8);
    const scopeLabel = String(scope || '范围未指定').replaceAll('全部基地_全部机组_全部大修', '全范围');
    return `TH_${segment(kind)}_${segment(scopeLabel)}_${stamp}_${token}.${suffix}`;
  }
  window.artifactNaming = Object.freeze({filename, siteCode, unitCode});
})();
