import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), `notification-modal-${Date.now()}`);
fs.mkdirSync(output, {recursive:true});
const runtime = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron} = await import(pathToFileURL(runtime).href);
const port = process.env.THIMBLE_TEST_PORT || String(19200 + Math.floor(Math.random() * 500));
const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
const app = await _electron.launch({
  timeout:60000, executablePath:packaged || path.join(root, 'node_modules/electron/dist/electron.exe'),
  args:packaged ? ['--disable-gpu'] : [root, '--disable-gpu'], cwd:root,
  env:{
    ...process.env, THIMBLE_ALLOW_MULTI_INSTANCE:'1',
    THIMBLE_PORT:port,
    THIMBLE_PYTHON:path.join(root, '.venv/Scripts/python.exe'),
    THIMBLE_DB_PATH:path.join(output, 'test.db'), THIMBLE_USER_DATA_DIR:path.join(output, 'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output, 'exports'), THIMBLE_LOG_PATH:path.join(output, 'service.log'),
  },
});
const evidence = {checks:[], errors:[]};
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
let page;
async function check(name, run) {
  await run(); evidence.checks.push(name); console.log('PASS', name);
}
async function settled() {
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
async function resize(width, height) {
  await app.evaluate(({BrowserWindow}, size) => {
    const win = BrowserWindow.getAllWindows()[0];
    win.unmaximize(); win.setContentSize(size.width, size.height);
  }, {width, height});
  await page.waitForFunction(size => innerWidth === size.width && innerHeight === size.height, {width, height});
  await settled();
}
async function show(message = '请核对当前大修批次后继续操作。') {
  await page.evaluate(message => window.appFeedback.notify(message, {type:'warning', duration:60000}), message);
  await settled();
}
async function assertPlacement(dialogId) {
  const geometry = await page.locator('#toast').evaluate((host, id) => {
    const dialog = document.getElementById(id), box = host.getBoundingClientRect();
    const modal = dialog.getBoundingClientRect(), actions = dialog.querySelector('.dialog-actions').getBoundingClientRect();
    return {
      parent:host.closest('dialog')?.id, open:host.matches(':popover-open'),
      viewport:box.left >= 0 && box.top >= 0 && box.right <= innerWidth + 1 && box.bottom <= innerHeight + 1,
      withinModal:box.left >= modal.left && box.right <= modal.right + 1 && box.top >= modal.top && box.bottom <= modal.bottom + 1,
      clearActions:box.bottom <= actions.top,
      textFits:host.querySelector('span').getBoundingClientRect().bottom <= box.bottom,
      left:box.left, top:box.top, right:box.right, bottom:box.bottom,
    };
  }, dialogId);
  assert.equal(geometry.parent, dialogId, JSON.stringify(geometry));
  assert(geometry.open && geometry.viewport && geometry.withinModal && geometry.clearActions && geometry.textFits, JSON.stringify(geometry));
  return geometry;
}
try {
  page = await app.firstWindow();
  await ensureLocalLogin(page);
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => evidence.errors.push(error.message));
  await page.waitForFunction(() => window.appFeedback && window.__thimbleState);
  await resize(1440, 960);
  await check('Success and error notifications default to three seconds and retain history', async () => {
    await page.mouse.move(0,0);
    await page.evaluate(() => localStorage.removeItem('thimbleNotificationDuration'));
    assert.equal(await page.evaluate(() => window.appFeedback.notificationDuration()),3000);
    for (const type of ['success','error']) {
      await page.evaluate(type => {
        document.activeElement?.blur();
        const host=document.querySelector('#toast');
        window.notificationTiming={started:performance.now(),elapsed:null};
        const observer=new MutationObserver(()=>{
          if(!host.classList.contains('show')){
            window.notificationTiming.elapsed=performance.now()-window.notificationTiming.started;
            observer.disconnect();
          }
        });
        observer.observe(host,{attributes:true,attributeFilter:['class']});
        window.appFeedback.notify(`默认三秒隐藏：${type}`, {type});
      },type);
      await page.waitForFunction(() => document.querySelector('#toast').matches(':popover-open'));
      await page.waitForTimeout(1000);
      assert(await page.locator('#toast').evaluate(host=>host.matches(':popover-open')));
      await page.waitForFunction(() => !document.querySelector('#toast').matches(':popover-open'));
      const elapsed=await page.evaluate(()=>window.notificationTiming.elapsed);
      assert(elapsed>=2800 && elapsed<5000,`${type} notification remained visible for ${elapsed} ms`);
      assert.match(await page.locator('#feedbackHistory').textContent(),new RegExp(`默认三秒隐藏：${type}`));
    }
  });
  await check('Notification sound obeys the saved setting', async () => {
    const result=await page.evaluate(() => {
      const original=AudioContext.prototype.createOscillator;
      let calls=0;
      AudioContext.prototype.createOscillator=function(...args){calls++;return original.apply(this,args)};
      try{
        localStorage.setItem('thimbleNotificationSound','false');
        window.appFeedback.notify('静音通知',{historyOnly:true});
        const muted=calls;
        localStorage.setItem('thimbleNotificationSound','true');
        window.appFeedback.notify('声音通知',{historyOnly:true});
        return {muted,enabled:calls};
      }finally{AudioContext.prototype.createOscillator=original}
    });
    assert.equal(result.muted,0);
    assert.equal(result.enabled,1);
  });
  await check('Notification drawer close control renders exactly one icon', async () => {
    await page.locator('#feedbackToggle').click();
    const icon = await page.locator('#feedbackClose').evaluate(button => ({
      imageCount:button.querySelectorAll('img').length,
      imageVisible:[...button.querySelectorAll('img')].every(image=>getComputedStyle(image).display!=='none'&&image.getBoundingClientRect().width>0),
      before:getComputedStyle(button,'::before').content,
      after:getComputedStyle(button,'::after').content,
    }));
    assert.equal(icon.imageCount,1,JSON.stringify(icon));
    assert(icon.imageVisible,JSON.stringify(icon));
    assert.equal(icon.before,'none',JSON.stringify(icon));
    assert.equal(icon.after,'none',JSON.stringify(icon));
    await page.locator('#feedbackClose').click();
  });
  await check('Notification follows an open import dialog when the desktop window is resized', async () => {
    await page.locator('#importDialog').evaluate(dialog => dialog.showModal());
    await show();
    await assertPlacement('importDialog');
    await resize(820, 600);
    await assertPlacement('importDialog');
  });
  await check('Long repeated messages stay scrollable above the action buttons', async () => {
    for (let index = 0; index < 12; index++) await show(`第 ${index + 1} 条核对提示：${'请核对基地、机组、大修编号及移位距离，确认后保存。'.repeat(100)}`);
    await assertPlacement('importDialog');
    assert(await page.locator('#toast > span').evaluate(text => text.scrollHeight > text.clientHeight));
    await page.screenshot({path:path.join(output, 'long-notification-small-window.png')});
    await page.locator('#toast button').click();
    assert.equal(await page.locator('#toast').evaluate(host => host.matches(':popover-open')), false);
  });
  await check('A new message in the same dialog resumes following content size changes after dismissal', async () => {
    await show();
    await page.locator('#importDialog').evaluate(dialog => { dialog.style.width = '500px'; });
    await page.waitForFunction(() => {
      const dialog = document.querySelector('#importDialog').getBoundingClientRect();
      const toast = document.querySelector('#toast').getBoundingClientRect();
      return toast.left >= dialog.left && toast.right <= dialog.right;
    });
    await assertPlacement('importDialog');
    await page.locator('#importDialog').evaluate(dialog => dialog.style.removeProperty('width'));
    await settled();
    await assertPlacement('importDialog');
  });
  await check('Nested dialogs follow opening order instead of DOM order and restore the parent notification', async () => {
    await page.evaluate(() => {
      const parent = document.querySelector('#importDialog');
      const child = document.createElement('dialog');
      child.id = 'notificationChild';
      child.innerHTML = '<form method="dialog"><h2>Nested check</h2><p>Confirmation</p><div class="dialog-actions"><button value="cancel">Close</button></div></form>';
      parent.before(child);
      child.showModal();
    });
    await show();
    await assertPlacement('notificationChild');
    await page.locator('#notificationChild button[value=cancel]').click();
    await settled();
    await assertPlacement('importDialog');
    await page.locator('#notificationChild').evaluate(dialog => dialog.remove());
  });
  await check('An existing notification moves into a newly opened dialog and back out on close', async () => {
    await page.locator('#importDialog').evaluate(dialog => dialog.close());
    await settled();
    assert.equal(await page.locator('#toast').evaluate(host => host.parentElement === document.body && host.matches(':popover-open')), true);
    assert.equal(await page.locator('#toast').evaluate(host => host.style.cssText), '');
    await page.locator('#importDialog').evaluate(dialog => dialog.showModal());
    await settled();
    await assertPlacement('importDialog');
    await page.locator('#importDialog').evaluate(dialog => dialog.close());
    await settled();
    await page.locator('#toast button').click();
    assert.equal(await page.locator('#toast').evaluate(host => host.matches(':popover-open')), false);
  });
  await check('Notification follows a scrollable modal and recovers when the modal is removed', async () => {
    await page.evaluate(() => {
      const dialog = document.createElement('dialog');
      dialog.id = 'notificationScroll';
      dialog.style.cssText = 'width:600px;max-height:300px;overflow:auto';
      dialog.innerHTML = '<form method="dialog"><h2>Scrollable check</h2><div style="height:600px"></div><div class="dialog-actions"><button value="close">Close</button></div></form>';
      document.body.append(dialog); dialog.showModal();
      dialog.scrollTop = 0;
    });
    await show();
    await assertPlacement('notificationScroll');
    await page.locator('#notificationScroll').evaluate(dialog => { dialog.scrollTop = dialog.scrollHeight; });
    await settled();
    await assertPlacement('notificationScroll');
    await page.locator('#notificationScroll').evaluate(dialog => dialog.remove());
    await settled();
    assert.equal(await page.locator('#toast').evaluate(host => host.parentElement === document.body && host.matches(':popover-open')), true);
    await page.locator('#toast button').click();
    await page.locator('#importDialog').evaluate(dialog => dialog.showModal());
    await settled();
    assert.equal(await page.locator('#toast').evaluate(host => host.matches(':popover-open')), false, 'dismissed messages must stay dismissed');
    await page.locator('#importDialog').evaluate(dialog => dialog.close());
  });
  await check('Notification severity, accessible labels and keyboard dismissal work without submitting the dialog', async () => {
    await page.locator('#importDialog').evaluate(dialog => dialog.showModal());
    for (const [type, mark, role] of [['success', '✓', 'status'], ['warning', '!', 'status'], ['error', '×', 'alert'], ['info', 'i', 'status']]) {
      const message = `通知类型核验：${type}`;
      await page.evaluate(({message, type}) => window.appFeedback.notify(message, {type, duration:60000}), {message, type});
      await settled();
      await assertPlacement('importDialog');
      assert.equal(await page.locator('#toast').getAttribute('data-type'), type);
      assert.equal(await page.locator('#toast').getAttribute('role'), role);
      assert.equal(await page.locator('#toast').getAttribute('aria-live'), type === 'error' ? 'assertive' : 'polite');
      assert.equal(await page.locator('#toast .feedback-mark').textContent(), mark);
      assert.equal(await page.locator('#feedbackHistory li').first().locator('span').textContent(), message);
      await page.locator('#toast button[aria-label="关闭通知"]').focus();
      await page.keyboard.press('Enter');
      assert.equal(await page.locator('#toast').evaluate(host => host.matches(':popover-open')), false);
      assert.equal(await page.locator('#importDialog').evaluate(dialog => dialog.matches(':modal')), true);
    }
    await page.locator('#importDialog').evaluate(dialog => dialog.close());
  });
  await check('Operation dismissals preserve history and cannot close a newer notification', async () => {
    const result = await page.evaluate(() => {
      const dismissEarlier = window.appFeedback.notify('先前操作失败', {type:'error', duration:60000});
      const dismissCurrent = window.appFeedback.notify('后续操作已完成', {type:'success', duration:60000});
      dismissEarlier();
      const host = document.querySelector('#toast');
      const currentVisible = host.matches(':popover-open') && host.textContent.includes('后续操作已完成');
      dismissCurrent();
      return {
        currentVisible,
        dismissed:!host.matches(':popover-open') && !host.classList.contains('show'),
        retained:document.querySelector('#feedbackHistory').textContent.includes('先前操作失败'),
      };
    });
    assert(result.currentVisible && result.dismissed && result.retained, JSON.stringify(result));
    await page.locator('#importDialog').evaluate(dialog => dialog.showModal());
    await settled();
    assert.equal(await page.locator('#toast').evaluate(host => host.matches(':popover-open')), false);
    await page.locator('#importDialog').evaluate(dialog => dialog.close());
  });
  await check('Expired notifications remain hidden across subsequent dialog openings', async () => {
    await page.mouse.move(0, 0);
    await page.evaluate(() => {
      document.activeElement?.blur();
      window.appFeedback.notify('本条提示自动关闭。', {type:'info', duration:350});
    });
    await page.waitForFunction(() => document.querySelector('#toast').matches(':popover-open'));
    await page.waitForFunction(() => !document.querySelector('#toast').matches(':popover-open'));
    assert.equal(await page.locator('#toast').evaluate(host => host.classList.contains('show')), false);
    await page.locator('#importDialog').evaluate(dialog => dialog.showModal());
    await settled();
    assert.equal(await page.locator('#toast').evaluate(host => host.matches(':popover-open')), false);
    await page.locator('#importDialog').evaluate(dialog => dialog.close());
  });
  await check('Focused messages pause expiry and stale focus callbacks cannot cancel a new timer', async () => {
    await page.mouse.move(0,0);
    await page.evaluate(() => {
      window.appFeedback.notify('正在核对的通知', {type:'info',duration:250});
      document.querySelector('#toast button').focus();
    });
    await page.waitForTimeout(400);
    assert(await page.locator('#toast').evaluate(host => host.matches(':popover-open')));
    await page.locator('#toast button').evaluate(button => button.blur());
    await page.waitForFunction(() => !document.querySelector('#toast').matches(':popover-open'));
    await page.evaluate(() => {
      window.appFeedback.notify('旧通知', {duration:60000});
      const earlierSchedule = document.querySelector('#toast').onmouseleave;
      queueMicrotask(earlierSchedule);
      window.appFeedback.notify('新通知', {duration:250});
    });
    await page.waitForFunction(() => !document.querySelector('#toast').matches(':popover-open'));
    await page.evaluate(() => window.appFeedback.notify('保留至手动关闭', {type:'info',duration:0}));
    await page.waitForTimeout(400);
    assert(await page.locator('#toast').evaluate(host => host.matches(':popover-open')));
    await page.locator('#toast button').click();
  });
  await check('Notification center groups duplicates, tracks unread, filters and clears records', async () => {
    await page.locator('#feedbackToggle').click();
    await page.locator('#feedbackClear').click();
    await page.locator('#feedbackClose').click();
    await page.evaluate(() => {
      window.appFeedback.notify('维护记录保存完成', {type:'success'});
      window.appFeedback.notify('维护记录保存完成', {type:'success'});
      window.appFeedback.notify('导入状态与当前记录不同，请核对', {type:'warning'});
      window.appFeedback.notify('保存失败，请重试', {type:'error'});
      window.appFeedback.notify('预览已更新', {type:'info'});
    });
    assert.equal(await page.locator('#feedbackHistory li').count(), 4);
    assert.equal(await page.locator('#feedbackCount').textContent(), '4');
    assert.equal(await page.locator('.feedback-repeat').textContent(), '×2');
    await page.locator('#toast button').click();
    await page.locator('#feedbackToggle').click();
    assert.equal(await page.locator('#feedbackCount').isVisible(), false);
    for (const type of ['error','warning','success','info']) {
      await page.locator(`[data-feedback-filter=${type}]`).click();
      assert.equal(await page.locator('#feedbackHistory li').count(), 1);
      assert.equal(await page.locator('#feedbackHistory li').getAttribute('data-type'), type);
      assert.equal(await page.locator(`[data-feedback-filter=${type}]`).getAttribute('aria-pressed'), 'true');
    }
    await page.locator('[data-feedback-filter=all]').click();
    for (const theme of ['light','dark']) {
      await page.evaluate(theme => window.appAppearance.setTheme(theme, {persist:false}), theme);
      for (const [width,height] of [[820,600],[1440,960]]) {
        await resize(width,height);
        const box = await page.locator('#feedbackDrawer').boundingBox();
        assert(box.x >= 0 && box.y >= 0 && box.x + box.width <= width && box.y + box.height <= height);
        await page.screenshot({path:path.join(output, `notification-center-${theme}-${width}.png`)});
      }
    }
    await page.locator('#feedbackClear').click();
    assert.equal(await page.locator('.feedback-empty').textContent(), '暂无操作通知');
    assert(await page.locator('#feedbackClear').isDisabled());
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#feedbackDrawer').isVisible(), false);
    assert.equal(await page.locator('#feedbackToggle').evaluate(button => button === document.activeElement), true);
  });
  await check('Undo notifications remain compact with one history entry and no duplicate popup', async () => {
    await resize(820,600);
    for (const theme of ['light','dark']) {
      await page.evaluate(theme => {
        window.appAppearance.setTheme(theme, {persist:false});
        window.dataDeleteMgr.showResultToast({deletedCount:12,batchId:'notification-layout-test'}, true);
      }, theme);
      assert.equal(await page.locator('.ddm-toast').count(), 1);
      assert.equal(await page.locator('#toast').evaluate(host => host.matches(':popover-open')), false);
      const box = await page.locator('.ddm-toast').boundingBox();
      assert(box.height < 100 && box.y + box.height <= 600 && box.x >= 0);
      await page.screenshot({path:path.join(output, `notification-undo-${theme}.png`)});
      await page.locator('.ddm-toast-close').click();
    }
  });
  await check('Undo failure offers retry and successful retry updates the existing notice', async () => {
    let attempts = 0;
    await page.route('**/api/recycle-bin/restore', route => {
      attempts++;
      return route.fulfill({status:attempts === 1 ? 503 : 200,contentType:'application/json',
        body:JSON.stringify(attempts === 1 ? {error:'恢复失败，请重试'} : {restoredCount:12})});
    });
    await page.evaluate(() => {
      window.notificationRestore = null;
      window.addEventListener('data-restored', event => { window.notificationRestore = event.detail; }, {once:true});
      window.dataDeleteMgr.showResultToast({deletedCount:12,batchId:'notification-layout-test'}, true);
    });
    await page.locator('.ddm-toast-undo').click();
    await page.waitForFunction(() => document.querySelector('.ddm-toast-undo')?.textContent === '重试恢复');
    assert.equal(await page.locator('.ddm-toast-undo').isDisabled(), false);
    const errorBox = await page.locator('#toast').boundingBox(), undoBox = await page.locator('.ddm-toast').boundingBox();
    assert(errorBox.y + errorBox.height <= undoBox.y);
    await page.locator('#toast button').click();
    await page.locator('.ddm-toast-undo').click();
    await page.waitForFunction(() => document.querySelector('.ddm-toast-text').textContent === '已恢复 12 条记录');
    assert.equal(await page.locator('.ddm-toast-undo').count(), 0);
    assert.equal(await page.locator('#toast').evaluate(host => host.matches(':popover-open')), false);
    assert.equal(await page.evaluate(() => window.notificationRestore.restoredCount), 12);
    assert.equal(attempts, 2);
    await page.locator('.ddm-toast-close').click();
    await page.unroute('**/api/recycle-bin/restore');
  });
  await check('Confirmation keeps typed safeguards and notification actions reachable in both themes', async () => {
    for (const theme of ['light','dark']) {
      await page.evaluate(theme => {
        window.appAppearance.setTheme(theme, {persist:false});
        window.notificationConfirmation = window.appFeedback.confirm('将永久删除所选记录。请核对范围后确认。', {title:'永久删除记录',danger:true,phrase:'永久删除'});
      }, theme);
      assert(await page.locator('.interaction-confirm [value=ok]').isDisabled());
      await page.locator('#confirmPhrase').fill('永久删除');
      assert.equal(await page.locator('.interaction-confirm [value=ok]').isDisabled(), false);
      await page.locator('.interaction-confirm').evaluate(dialog => dialog.id = 'notificationConfirmation');
      await show('请核对所选记录和删除范围。');
      await assertPlacement('notificationConfirmation');
      await page.screenshot({path:path.join(output, `notification-confirm-${theme}.png`)});
      await page.locator('#toast button').click();
      await page.locator('.interaction-confirm [value=cancel]').click();
      assert.equal(await page.evaluate(() => window.notificationConfirmation), false);
    }
  });
  assert.deepEqual(evidence.errors, []);
  console.log('NOTIFICATION_MODAL PASS', output);
} catch (error) {
  evidence.failure = error.stack;
  if (page && !page.isClosed()) await page.screenshot({path:path.join(output, 'failure.png')}).catch(() => {});
  throw error;
} finally {
  fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2));
  await app.close();
  assert.equal(await fetch(`http://127.0.0.1:${port}/api/health`, {signal:AbortSignal.timeout(2000)}).then(() => true, () => false), false, 'test backend must stop with the desktop application');
}
