const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function loadWindowPage(window, url, { log = () => {}, timeout = 30000, pause = wait } = {}) {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    if (window.isDestroyed()) return false;
    let timer;
    let onDestroyed;
    const destroyed = new Promise(resolve => {
      onDestroyed = () => resolve(false);
      window.once('closed', onDestroyed);
    });
    try {
      const loaded = await Promise.race([
        window.loadURL(url),
        destroyed,
        new Promise((_, reject) => {
          timer = setTimeout(() => {
            if (!window.isDestroyed()) window.webContents.stop();
            reject(new Error('Page loading timed out'));
          }, timeout);
        })
      ]);
      return loaded === false ? false : !window.isDestroyed();
    } catch (error) {
      log(`load attempt ${attempt}: ${error.message}`);
      if (window.isDestroyed()) return false;
      if (attempt === 3) throw error;
    } finally {
      clearTimeout(timer);
      window.removeListener('closed', onDestroyed);
    }
    await pause(250 * attempt);
  }
  return false;
}

module.exports = { loadWindowPage };
