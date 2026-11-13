async page => {
  const samples = [];
  const read = node => {
    const style = getComputedStyle(node);
    return {text: node.innerText, rect: node.getBoundingClientRect().toJSON(),
      style: Object.fromEntries(['fontFamily', 'fontSize', 'fontWeight', 'lineHeight',
        'color', 'backgroundColor', 'borderColor', 'padding', 'gap', 'gridTemplateColumns',
        'alignItems', 'justifyContent', 'boxShadow', 'whiteSpace', 'wordBreak', 'overflowWrap',
        'fontStretch', 'letterSpacing'].map(key => [key, style[key]]))};
  };
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => window.appAppearance.setTheme(theme, {persist:false}), theme);
    for (const width of [1180, 1001, 1000, 901, 900, 820]) {
      await page.setViewportSize({width, height:820});
      await page.locator('#settingsPreferencesTab').click();
      await page.evaluate(() => document.querySelector('main').scrollTop = 0);
      const sample = await page.evaluate(readText => {
        const read = eval('(' + readText + ')');
        const panel = document.querySelector('#settingsPreferencesPane');
        return {controls:Object.fromEntries(['.preferences-panel', '.panel-title', '.panel-title h2',
          '.panel-title > div > span', '#preferencesSaved', '.software-settings-body',
          '#preferencesStatus', '#resetPreferences', '.settings-action-row',
          '#settingsDensity', '#settingsMotion', '#settingsNotificationDuration',
          '#settingsNotificationSound', '#settingsStartupView', '#settingsRememberView',
          '#settingsShiftDirection', '#settingsImportPolicy', '.theme-switch']
          .map(selector => [selector, read(panel.querySelector(selector))])),
          groups:[...panel.querySelectorAll('fieldset')].map(node=>({
            ...read(node), legend:read(node.querySelector('legend'))})),
          rows:[...panel.querySelectorAll('.setting-row')].map(node=>({
            ...read(node), title:read(node.querySelector('b')), hint:read(node.querySelector('small')),
            control:read(node.lastElementChild)})),
          themeButtons:[...panel.querySelectorAll('[data-theme-choice]')].map(read)};
      }, read.toString());
      samples.push({theme,width,...sample});
      if ([1180,900,820].includes(width))
        await page.screenshot({path:`reference-preferences-${width}-${theme}.png`});
    }
  }
  return {samples};
}
