function createWindowCloseGuard({ isDirty, confirmDiscard, close }) {
  let closeAllowed = false;
  let closePending = false;

  return async function handleClose(event) {
    if (closeAllowed) return true;
    event.preventDefault();
    if (closePending) return false;

    closePending = true;
    try {
      if (await isDirty()) {
        try {
          if (!(await confirmDiscard())) return false;
        } catch (_) { return false; }
      }
      closeAllowed = true;
      close();
      return false;
    } finally {
      closePending = false;
    }
  };
}

module.exports = { createWindowCloseGuard };
