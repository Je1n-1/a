export function resolvePageRenderer(page, renderers, fallback) {
  return Object.hasOwn(renderers, page) ? renderers[page] : fallback;
}
