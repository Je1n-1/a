function focusedElementContext(root) {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || !root.contains(active)) return null;
  if (active.id) return {type:"id", value:active.id};
  const owner = active.closest("[data-ui-focus-key]");
  return owner?.dataset.uiFocusKey ? {type:"owner", value:owner.dataset.uiFocusKey} : null;
}

export function captureRenderContext(root) {
  return {
    scrollX:window.scrollX,
    scrollY:window.scrollY,
    focus:focusedElementContext(root),
    details:[...root.querySelectorAll("details[data-ui-state-key]")].map(element => ({key:element.dataset.uiStateKey, open:element.open})),
  };
}

export function restoreRenderContext(root, context, canRestore) {
  context.details.forEach(({key, open}) => {
    const element = root.querySelector(`[data-ui-state-key="${CSS.escape(key)}"]`);
    if (element instanceof HTMLDetailsElement) element.open = open;
  });
  window.requestAnimationFrame(() => {
    if (!canRestore()) return;
    if (Math.abs(window.scrollX - context.scrollX) < 4 && Math.abs(window.scrollY - context.scrollY) < 4) window.scrollTo(context.scrollX, context.scrollY);
    const current = document.activeElement;
    const canRestoreFocus = current === document.body || current === document.documentElement || root.contains(current);
    if (!canRestoreFocus || !context.focus) return;
    const target = context.focus.type === "id"
      ? document.getElementById(context.focus.value)
      : root.querySelector(`[data-ui-focus-key="${CSS.escape(context.focus.value)}"] summary`);
    target?.focus({preventScroll:true});
  });
}
