/* Keep bulk tools with the right-side editor, where actions and fields are
   operated together instead of making the tube picker carry a second toolbar. */
(() => {
  const controls = document.querySelector('#states .state-controls');
  const editor = document.querySelector('#states .state-panel');
  const actions = controls?.querySelector('.state-bulk-actions');
  const title = editor?.querySelector('.panel-title');
  if (actions && editor && title) {
    actions.classList.add('state-action-dock');
    title.after(actions);
  }
})();
