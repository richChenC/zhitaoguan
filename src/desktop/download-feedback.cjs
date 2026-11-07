function observeDownloads(session) {
  session.on('will-download', (_event, item, contents) => {
    let interrupted = false;
    const notify = state => {
      if (!contents || contents.isDestroyed()) return;
      contents.send('desktop-download-status', {
        state,
        filename: item.getFilename(),
      });
    };
    item.on('updated', (_event, state) => {
      if (state === 'interrupted' && !interrupted) {
        interrupted = true;
        notify('interrupted');
      }
    });
    item.once('done', (_event, state) => {
      if (state === 'interrupted' && interrupted) return;
      if (['completed', 'cancelled', 'interrupted'].includes(state)) notify(state);
    });
  });
}

module.exports = {observeDownloads};
