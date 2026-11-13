async page => {
  const samples = [];
  const capture = async (state, width, height, theme) => {
    await page.setViewportSize({width, height});
    await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
    await page.waitForTimeout(100);
    samples.push(await page.evaluate(({state, width, height, theme}) => {
      const controls = {};
      for (const selector of ['.login-shell', '.login-product', '.login-mark', '.login-product strong',
        '.login-card', '#loginTitle', '#localLoginForm', '#displayNameField', '#loginDisplayName',
        '#loginUsername', '#loginPassword', '#loginReveal', '#confirmPasswordField',
        '#loginConfirmPassword', '#loginConfirmReveal', '#loginPasswordMeter',
        '.login-options', '#loginRemember', '#loginMessage', '#loginSubmit', '.login-card-footer']) {
        const node = document.querySelector(selector), style = getComputedStyle(node);
        const visible = Boolean(node.getClientRects().length);
        controls[selector] = {visible, rect: node.getBoundingClientRect().toJSON(), text: node.textContent.trim(),
          value: 'value' in node && !selector.toLowerCase().includes('password') ? node.value : undefined,
          placeholder: node.getAttribute('placeholder'),
          style: Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'color',
            'backgroundColor', 'borderColor', 'borderTopWidth', 'paddingTop', 'paddingRight', 'paddingBottom',
            'paddingLeft', 'marginTop', 'marginBottom', 'gap'].map(key => [key, style[key]]))};
      }
      return {state, width, height, theme, controls};
    }, {state, width, height, theme}));
    await page.screenshot({path: `reference-login-${state}-${width}-${theme}.png`});
  };
  await page.waitForFunction(() => !document.querySelector('#loginSubmit').disabled);
  for (const theme of ['light', 'dark'])
    for (const [width, height] of [[1080, 760], [521, 760], [520, 760], [460, 640]])
      await capture('setup', width, height, theme);
  const strengths = [];
  for (const value of ['', 'abc', 'abcdef', 'abc123', 'abc1234567', 'SecretPass@2026']) {
    await page.locator('#loginPassword').fill(value);
    strengths.push({length: value.length, text: await page.locator('#loginPasswordMeterText').textContent(),
      width: await page.locator('#loginPasswordMeterBar').evaluate(node => node.style.width),
      color: await page.locator('#loginPasswordMeterBar').evaluate(node => node.style.background)});
  }
  await page.locator('#loginDisplayName').fill('Login Probe');
  await page.locator('#loginUsername').fill('loginprobe');
  await page.locator('#loginPassword').fill('LoginProbe@2026');
  await page.locator('#loginConfirmPassword').fill('Mismatch@2026');
  await page.locator('#loginSubmit').click();
  await page.waitForFunction(() => document.querySelector('#loginMessage').textContent.includes('不一致'));
  await capture('mismatch', 1080, 760, 'light');
  await page.locator('#loginConfirmPassword').fill('LoginProbe@2026');
  await page.locator('#loginSubmit').click();
  await page.waitForURL(url => url.pathname === '/');
  await page.goto('http://127.0.0.1:18886/login.html');
  await page.waitForFunction(() => document.querySelector('#loginTitle').textContent === '登录' &&
    !document.querySelector('#loginSubmit').disabled);
  for (const theme of ['light', 'dark'])
    for (const [width, height] of [[1080, 760], [521, 760], [520, 760], [460, 640]])
      await capture('login', width, height, theme);
  await page.locator('#loginUsername').fill('loginprobe');
  await page.locator('#loginPassword').fill('WrongPassword@2026');
  await page.locator('#loginSubmit').click();
  await page.waitForFunction(() => document.querySelector('#loginMessage').textContent.length > 0);
  await capture('wrong-password', 1080, 760, 'light');
  await page.locator('#loginPassword').fill('LoginProbe@2026');
  await page.locator('#loginReveal').click();
  const reveal = {type: await page.locator('#loginPassword').getAttribute('type'),
    label: await page.locator('#loginReveal').getAttribute('aria-label'),
    focused: await page.evaluate(() => document.activeElement.id)};
  await page.locator('#loginReveal').click();
  await page.locator('#loginRemember').check();
  await page.locator('#loginSubmit').click();
  await page.waitForURL(url => url.pathname === '/');
  await page.goto('http://127.0.0.1:18886/login.html');
  await page.waitForFunction(() => !document.querySelector('#loginSubmit').disabled);
  return {samples, strengths, reveal,
    remembered: await page.locator('#loginUsername').inputValue(),
    passwordAfter: await page.locator('#loginPassword').inputValue()};
}
