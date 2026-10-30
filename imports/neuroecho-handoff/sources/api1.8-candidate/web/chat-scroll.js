/* Preserve the reader's position when messages arrive while reading history. */
((root) => {
  function createChatScroll(view, button) {
    const nearBottom = () => view.scrollHeight - view.clientHeight - view.scrollTop <= 48;
    const hideNotice = () => button.classList.add("is-hidden");
    const toBottom = () => { view.scrollTop = view.scrollHeight; hideNotice(); };
    view.addEventListener("scroll", () => { if (nearBottom()) hideNotice(); });
    button.addEventListener("click", toBottom);
    return {
      render(update, { forceBottom = false, newMessage = false } = {}) {
        const follow = forceBottom || nearBottom();
        const previousTop = view.scrollTop;
        update();
        if (follow) toBottom();
        else {
          view.scrollTop = previousTop;
          if (newMessage) button.classList.remove("is-hidden");
        }
      },
    };
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { createChatScroll };
  else root.createChatScroll = createChatScroll;
})(typeof window === "undefined" ? globalThis : window);
