/* Small, reusable dialog lifecycle. Opening never sends or changes a conversation. */
(() => {
  function create(options) {
    const {dialog, primaryButton, backgrounds = [], openers = [], closeButtons = []} = options;
    if (!dialog) throw new Error("A dialog element is required");
    const doc = dialog.ownerDocument || document;
    const key = options.storageKey === undefined ? "xinji_companion_welcome" : options.storageKey;
    const version = options.version || "companion-20261029-r4";
    let opened = false, dismissed = false, previousFocus = null, previousBackgrounds = [];
    const visible = (el) => !!el && el.isConnected !== false && !el.hidden && !el.closest?.(".is-hidden, [hidden], [inert]");
    const focusable = () => [...dialog.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')].filter(visible);
    function focusFirst() { (visible(primaryButton) ? primaryButton : focusable()[0] || dialog).focus(); }
    function onKey(event) {
      if (!opened) return;
      const nested = event.target?.closest?.('dialog[open]');
      if (nested && nested !== dialog) return;
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); return; }
      if (event.key !== "Tab") return;
      const nodes = focusable(), first = nodes[0], last = nodes[nodes.length - 1];
      if (!first) { event.preventDefault(); dialog.focus(); return; }
      if (!dialog.contains(doc.activeElement) || (event.shiftKey && doc.activeElement === first)) {
        event.preventDefault(); (event.shiftKey ? last : first).focus();
      } else if (!event.shiftKey && doc.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    function onFocus(event) { if (opened && !dialog.contains(event.target)) focusFirst(); }
    function open() {
      if (opened) return;
      opened = true;
      previousFocus = doc.activeElement;
      previousBackgrounds = backgrounds.filter(Boolean).map((element) => ({element, inert: element.inert, aria: element.getAttribute("aria-hidden")}));
      dialog.classList.remove("is-hidden");
      dialog.setAttribute("aria-hidden", "false");
      dialog.setAttribute("role", "dialog");
      dialog.setAttribute("aria-modal", "true");
      dialog.setAttribute("tabindex", "-1");
      focusFirst();
      for (const {element} of previousBackgrounds) { element.inert = true; element.setAttribute("aria-hidden", "true"); }
      doc.addEventListener("keydown", onKey, true);
      doc.addEventListener("focusin", onFocus, true);
    }
    function close({remember = true} = {}) {
      if (!opened) return;
      opened = false;
      doc.removeEventListener("keydown", onKey, true);
      doc.removeEventListener("focusin", onFocus, true);
      dialog.classList.add("is-hidden");
      dialog.setAttribute("aria-hidden", "true");
      for (const {element, inert, aria} of previousBackgrounds) {
        element.inert = inert;
        if (aria === null) element.removeAttribute("aria-hidden"); else element.setAttribute("aria-hidden", aria);
      }
      previousBackgrounds = [];
      if (remember && key) {
        dismissed = true;
        try { (options.storage || localStorage).setItem(key, version); } catch (_) {}
      }
      const fallback = typeof options.fallbackFocus === "function" ? options.fallbackFocus() : options.fallbackFocus;
      (visible(previousFocus) ? previousFocus : visible(fallback) ? fallback : null)?.focus();
      options.onClose?.();
    }
    function maybeShow({messages = []} = {}) {
      if (messages.some((message) => message.role === "user") || dismissed) return false;
      try { if (key && (options.storage || localStorage).getItem(key) === version) return false; } catch (_) {}
      open(); return true;
    }
    for (const opener of openers) opener?.addEventListener("click", open);
    for (const button of closeButtons) button?.addEventListener("click", () => close());
    primaryButton?.addEventListener("click", () => { close(); options.onPrimary?.(); });
    return {open, close, maybeShow, isOpen: () => opened};
  }
  const mascotMarkup = `<svg class="echo-companion" viewBox="0 0 120 112" fill="none" aria-hidden="true"><ellipse class="echo-shadow" cx="60" cy="102" rx="29" ry="5" fill="#687a65" opacity=".13"/><g class="echo-body"><path d="M27 62c-2-23 10-43 32-44 24-1 40 18 37 43-1 17-5 33-19 33H44C32 94 28 79 27 62Z" fill="#ead8b8"/><path d="M31 46c5-15 17-23 31-23 13 0 23 6 29 18" stroke="#fff7e9" stroke-width="4" stroke-linecap="round"/><path d="M40 88 36 97m43-9 5 9" stroke="#6c7964" stroke-width="5" stroke-linecap="round"/><path d="M27 63 18 68m77-5 8 5" stroke="#bf6b4d" stroke-width="5" stroke-linecap="round"/><g class="echo-eyes" fill="#4b4c3f"><ellipse cx="47" cy="56" rx="3" ry="4"/><ellipse cx="73" cy="56" rx="3" ry="4"/></g><path d="M54 66q6 5 12 0" stroke="#8b6348" stroke-width="2.5" stroke-linecap="round"/><ellipse cx="38" cy="65" rx="5" ry="2.5" fill="#d99d7b" opacity=".65"/><ellipse cx="82" cy="65" rx="5" ry="2.5" fill="#d99d7b" opacity=".65"/><path d="M61 21c-3-9 0-16 9-18 1 9-2 15-9 18Z" fill="#788a6c"/><path d="M60 22c-7-7-14-6-18-2 5 5 12 6 18 2Z" fill="#96a284"/></g></svg>`;
  window.XinjiWelcome = {create, mascotMarkup};
})();
