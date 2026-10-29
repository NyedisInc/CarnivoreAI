
export interface ScrollAnchor {
  index: string;
  offset: number;
}

export function anchorOf(box: HTMLElement): ScrollAnchor | null {
  const top = box.getBoundingClientRect().top;
  for (const el of box.querySelectorAll<HTMLElement>('[data-message-index]')) {
    const rect = el.getBoundingClientRect();
    if (rect.bottom > top) return { index: el.dataset['messageIndex'] ?? '', offset: rect.top - top };
  }
  return null;
}

export function restoreAnchor(box: HTMLElement, anchor: ScrollAnchor): boolean {
  const el = box.querySelector<HTMLElement>(`[data-message-index="${anchor.index}"]`);
  if (!el) return false;
  const moved = el.getBoundingClientRect().top - box.getBoundingClientRect().top - anchor.offset;
  if (moved) box.scrollTop += moved;
  return true;
}
