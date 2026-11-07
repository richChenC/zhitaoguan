const assert = require('node:assert/strict');
const {allowedURL} = require('../src/desktop/offline-policy.cjs');
const base='http://127.0.0.1:18767';
for (const url of [base+'/',base+'/api/health','data:image/png;base64,AAAA','blob:'+base+'/image','about:blank']) assert.equal(allowedURL(url,base),true,url);
for (const url of ['http://127.0.0.1:18768/','http://localhost:18767/','http://127.0.0.1.evil.test:18767/','https://example.com/','file:///C:/Windows/win.ini','javascript:alert(1)','blob:https://example.com/image']) assert.equal(allowedURL(url,base),false,url);
console.log('PASS offline URL allowlist');
