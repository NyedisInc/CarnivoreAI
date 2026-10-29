/*  hidden  overflow: hidden */

const watched = new WeakMap<Element, () => void>();

const shared: ResizeObserver | null =
  typeof ResizeObserver === 'undefined'
    ? null
    : new ResizeObserver((entries) => {
        for (const entry of entries) watched.get(entry.target)?.();
      });

const TOLERANCE_PX = 1;

export function isTruncated(el: HTMLElement): boolean {
  return el.scrollWidth - el.clientWidth > TOLERANCE_PX;
}

/* <button use:titleWhenTruncated={'.oc-ptab__label'}> */
export function titleWhenTruncated(node: HTMLElement, selector?: string): { destroy: () => void } {
  const label = (): HTMLElement => {
    const found = node.querySelector<HTMLElement>(selector ?? ':scope > [data-btn-label]');
    if (found) return found;
    if (selector !== undefined || !isTruncated(node)) return node;
    const span = document.createElement('span');
    span.setAttribute('data-btn-label', '');
    span.append(...Array.from(node.childNodes));
    node.append(span);
    return span;
  };
  let ours = false;
  let authored: string | null = null;

  const sync = (): void => {
    const el = label();
    if (isTruncated(el)) {
      const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim();
      if (!ours) authored = node.getAttribute('title');
      ours = true;
      if (text && node.getAttribute('title') !== text) node.setAttribute('title', text);
    } else if (ours) {
      ours = false;
      if (authored === null) node.removeAttribute('title');
      else node.setAttribute('title', authored);
    }
  };

  sync();
  watched.set(node, sync);
  shared?.observe(node);
  const mutation = typeof MutationObserver === 'undefined' ? null : new MutationObserver(sync);
  mutation?.observe(node, { childList: true, characterData: true, subtree: true });

  return {
    destroy(): void {
      shared?.unobserve(node);
      watched.delete(node);
      mutation?.disconnect();
    },
  };
}
