
export interface RectCache {
  get(): { left: number; top: number; width: number; height: number };
  invalidate(): void;
  dispose(): void;
}

export function createRectCache(el: Element, win: Window): RectCache {
  let rect: DOMRect | null = null;
  const drop = (): void => {
    rect = null;
  };
  win.addEventListener('scroll', drop, true);
  win.addEventListener('resize', drop);
  return {
    get() {
      rect ??= el.getBoundingClientRect();
      return rect;
    },
    invalidate: drop,
    dispose() {
      win.removeEventListener('scroll', drop, true);
      win.removeEventListener('resize', drop);
    },
  };
}
