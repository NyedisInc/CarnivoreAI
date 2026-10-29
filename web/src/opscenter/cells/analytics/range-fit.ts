
export const RANGE_STAGES = ['full', 'short', 'none'] as const;

export type RangeStage = (typeof RANGE_STAGES)[number];

export function chooseRangeStage(show: (stage: RangeStage) => boolean): RangeStage {
  for (const stage of RANGE_STAGES) if (!show(stage)) return stage;
  return 'none';
}

export function isCut(name: Element): boolean {
  return [name, ...Array.from(name.querySelectorAll('span'))].some((box) => box.clientWidth > 0 && box.scrollWidth > box.clientWidth);
}

export function fitRange(node: HTMLElement, text: string): { update: (next: string) => void; destroy: () => void } {
  const header = node.closest('.oc-frame-title');
  const name = header?.querySelector('.oc-frame-name') ?? null;
  let words = text;
  let hinted = false;

  function fit(): void {
    if (!header || !name) return;
    const stage = chooseRangeStage((next) => {
      node.dataset.fit = next;
      return isCut(name);
    });
    node.dataset.fit = stage;
    if (stage === 'none') {
      name.setAttribute('title', `${name.textContent?.trim() ?? ''}, ${words}`);
      hinted = true;
    } else if (hinted) {
      name.removeAttribute('title');
      hinted = false;
    }
  }

  const watcher = header && typeof ResizeObserver !== 'undefined' ? new ResizeObserver(fit) : null;
  if (header) watcher?.observe(header);
  const texts = name && typeof MutationObserver !== 'undefined' ? new MutationObserver(fit) : null;
  if (name) texts?.observe(name, { childList: true, characterData: true, subtree: true });
  fit();
  return {
    update(next: string): void { words = next; fit(); },
    destroy(): void { watcher?.disconnect(); texts?.disconnect(); if (hinted) name?.removeAttribute('title'); },
  };
}
