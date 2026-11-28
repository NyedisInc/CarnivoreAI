import { isDismissTarget } from './task-manager-posts';

export interface CloseCue {
  readonly active: number | null;
  point: (id: number, event: Pick<PointerEvent, 'shiftKey' | 'target'>) => void;
  leave: (id: number) => void;
  key: (event: Pick<KeyboardEvent, 'shiftKey'>) => void;
  clear: () => void;
  attach: (win?: Window) => () => void;
}

export function createCloseCue(): CloseCue {
  let shift = $state(false);
  let over = $state<number | null>(null);
  let dismissable = $state(false);
  const clear = (): void => { shift = false; over = null; dismissable = false; };
  return {
    get active() { return shift && dismissable ? over : null; },
    point(id, event) { over = id; shift = event.shiftKey; dismissable = isDismissTarget(event.target as Element | null); },
    leave(id) { if (over === id) { over = null; dismissable = false; } },
    key(event) { shift = event.shiftKey; },
    clear,
    attach(win = window) {
      const onKey = (event: KeyboardEvent): void => { shift = event.shiftKey; };
      const onHide = (): void => { if (win.document.visibilityState === 'hidden') clear(); };
      win.addEventListener('keydown', onKey);
      win.addEventListener('keyup', onKey);
      win.addEventListener('blur', clear);
      win.document.addEventListener('visibilitychange', onHide);
      return () => {
        win.removeEventListener('keydown', onKey);
        win.removeEventListener('keyup', onKey);
        win.removeEventListener('blur', clear);
        win.document.removeEventListener('visibilitychange', onHide);
      };
    },
  };
}
