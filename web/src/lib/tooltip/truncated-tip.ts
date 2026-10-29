
export function isClipped(el: HTMLElement): boolean {
  if (el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight) return true;
  if (el.clientWidth !== 0 || el.clientHeight !== 0) return false;
  for (let up = el.parentElement, hops = 0; up && hops < 3; up = up.parentElement, hops += 1) {
    const overflow = getComputedStyle(up).overflowX;
    if (overflow === 'hidden' || overflow === 'clip') return up.scrollWidth > up.clientWidth;
  }
  return false;
}

export function truncatedTip(node: HTMLElement, text: string): { update: (next: string) => void; destroy: () => void } {
  let full = text;
  const measure = (): void => {
    if (full && isClipped(node)) node.setAttribute('data-tooltip', full);
    else node.removeAttribute('data-tooltip');
  };
  node.addEventListener('pointerover', measure);
  node.setAttribute('data-tip-wired', '');
  return {
    update(next: string): void {
      full = next;
    },
    destroy(): void {
      node.removeEventListener('pointerover', measure);
      node.removeAttribute('data-tooltip');
      node.removeAttribute('data-tip-wired');
    },
  };
}
