
import { untrack } from 'svelte';
import type { CellId, LayoutPage } from './types';

export const sizes: Record<string, { width: number; height: number }> = $state({});

let observer: ResizeObserver | undefined;
let frame = 0;
const pending = new Map<string, { width: number; height: number }>();
const keys = new WeakMap<Element, string>();

function flush(): void {
  frame = 0;
  for (const [key, box] of pending) {
    const current = sizes[key];
    if (current && Math.abs(current.width - box.width) < 1 && Math.abs(current.height - box.height) < 1) continue;
    sizes[key] = box;
  }
  pending.clear();
}

function ensure(): ResizeObserver {
  if (observer) return observer;
  observer = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const key = keys.get(entry.target);
      if (!key) continue;
      const rect = entry.contentRect;
      pending.set(key, { width: rect.width, height: rect.height });
    }
    if (!frame) frame = requestAnimationFrame(flush);
  });
  return observer;
}

export function observeCell(key: CellId | string) {
  return (node: Element) => {
    keys.set(node, key);
    const shared = ensure();
    shared.observe(node);
    const measure = (): void => {
      if (!node.isConnected || keys.get(node) !== key) return;
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return;
      const current = untrack(() => sizes[key]);
      if (current && current.width === rect.width && current.height === rect.height) return;
      sizes[key] = { width: rect.width, height: rect.height };
    };
    measure();
    queueMicrotask(measure);
    return () => {
      shared.unobserve(node);
      keys.delete(node);
    };
  };
}

export function surfaceKeyOf(page: LayoutPage): string {
  return page === 'home' ? 'surface' : `surface:${page}`;
}

export function sizeOf(key: CellId | string): { width: number; height: number } {
  return sizes[key] ?? { width: 0, height: 0 };
}
