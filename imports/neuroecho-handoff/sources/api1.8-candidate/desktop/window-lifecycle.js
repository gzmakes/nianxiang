// Keep a reopened desktop window visible, including a previously minimized one.
function revealWindow(window) {
  if (!window || window.isDestroyed()) return false;
  if (window.isMinimized()) window.restore();
  window.show();
  window.focus();
  return true;
}
module.exports = {revealWindow};
