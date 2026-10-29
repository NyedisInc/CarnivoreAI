
/* padding */
export function fitHeight(box: HTMLTextAreaElement): number {
  const css = getComputedStyle(box);
  const padding = (parseFloat(css.paddingTop) || 0) + (parseFloat(css.paddingBottom) || 0);
  const border = (parseFloat(css.borderTopWidth) || 0) + (parseFloat(css.borderBottomWidth) || 0);
  box.style.height = 'auto';
  // padding
  const content = box.value === '' ? 0 : box.scrollHeight + (css.boxSizing === 'border-box' ? border : 0);
  const min = parseFloat(css.minHeight) || 0;
  const max = parseFloat(css.maxHeight);
  const wanted = Math.max(content, min);
  const height = Number.isFinite(max) ? Math.min(wanted, max) : wanted;
  box.style.overflowY = wanted > height ? 'auto' : 'hidden';
  // padding
  const inner = css.boxSizing === 'border-box' ? height : height - padding;
  box.style.height = `${Math.max(0, inner)}px`;
  return height;
}

export function autogrow(box: HTMLTextAreaElement): () => void {
  let width = box.clientWidth;
  fitHeight(box);
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
    if (box.clientWidth === width) return;
    width = box.clientWidth;
    fitHeight(box);
  });
  observer?.observe(box);
  return () => observer?.disconnect();
}
