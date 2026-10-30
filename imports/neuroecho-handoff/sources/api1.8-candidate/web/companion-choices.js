/* A choice edits a draft only. The server applies an explicit request after sending. */
window.XinjiCompanionChoices = (() => {
  const inserted = new WeakMap();
  const choices = {listen: '先听我说，', reflect: '帮我梳理一下，', auto: '恢复自然聊天，'};
  function put(input, text) {
    if (!input || !text) return;
    let draft = input.value || '';
    const previous = inserted.get(input);
    // Only remove a prefix we inserted and that the user has not edited.
    if (previous && draft.startsWith(previous)) draft = draft.slice(previous.length);
    input.value = text + draft;
    inserted.set(input, text);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.focus();
    input.setSelectionRange?.(input.value.length, input.value.length);
  }
  function bind(root, input) {
    root.querySelectorAll('[data-response-choice]').forEach(button => {
      button.addEventListener('click', () => put(input, choices[button.dataset.responseChoice]));
    });
  }
  return {put, bind};
})();
