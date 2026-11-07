// Test runner only: authenticates through the same setup/login UI as a user.
import {randomBytes} from 'node:crypto';
const username='release-test-admin';
const password=randomBytes(24).toString('base64url');
const cookies=new Map();
const originalFetch=globalThis.fetch;
globalThis.fetch=async(input,options={})=>{
  const url=new URL(input instanceof Request?input.url:String(input));
  const cookie=cookies.get(url.origin);
  if(cookie&&url.pathname.startsWith('/api/')){
    const headers=new Headers(options.headers||(input instanceof Request?input.headers:{}));
    headers.set('Cookie',cookie);headers.set('X-Thimble-Request','1');
    options={...options,headers};
  }
  return originalFetch(input,options);
};

export async function ensureLocalLogin(page,credentials={username,password}){
  await page.waitForURL(url=>url.hostname==='127.0.0.1',{timeout:90000});
  await page.waitForFunction(()=>{
    const submit=document.querySelector('#loginSubmit');
    return (submit&&!submit.disabled)||document.querySelector('nav [data-view="workspace"]');
  },{timeout:30000});
  if(new URL(page.url()).pathname==='/login.html'){
    await page.locator('#loginSubmit:not([disabled])').waitFor({timeout:30000});
    await page.locator('#loginUsername').fill(credentials.username);await page.locator('#loginPassword').fill(credentials.password);
    const setupRequired=await page.locator('#confirmPasswordField').isVisible();
    if(setupRequired){
      await page.locator('#loginConfirmPassword').fill(credentials.password);
    }
    await page.locator('#loginSubmit').click();
    await page.waitForFunction(()=>!!window.localAccount?.user,{timeout:30000});
  }
  await page.waitForURL(url=>url.pathname!=='/login.html',{timeout:30000});
  await page.locator('nav').waitFor({state:'attached',timeout:30000});
  const values=await page.context().cookies(page.url());
  const cookie=values.filter(item=>item.name==='thimble_session').map(item=>`${item.name}=${item.value}`).join('; ');
  if(!cookie)throw new Error('The isolated release test could not establish its local session');
  cookies.set(new URL(page.url()).origin,cookie);
}

export async function ensureDesktopReady(page){
  await ensureLocalLogin(page);
  if(new URL(page.url()).pathname==='/login.html')throw new Error('Desktop login did not return to the main workspace');
  await page.locator('nav [data-view="workspace"]').waitFor({state:'attached'});
}
