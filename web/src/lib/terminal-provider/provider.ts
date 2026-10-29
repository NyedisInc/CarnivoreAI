
export interface Disposable { dispose(): void }

export type TerminalEvent = 'data' | 'resize' | 'scroll' | 'selection' | 'bell';

export interface TerminalHandle {
  attach(host: HTMLElement): void;
  write(data: string | Uint8Array, done?: () => void): void;
  resize(cols: number, rows: number): void;
  dispose(): void;
  on(event: TerminalEvent, fn: (payload: unknown) => void): Disposable;
  cellSize(): { width: number; height: number } | undefined;
  scrollBarWidth(): number;
  mouseEventsActive(): boolean;
  mouseService(): Record<string, unknown> | undefined;
  syncInputTextarea(): void;
  clearRenderer(): void;
  quiesceViewport(): void;
}

type Xterm = Record<string, any> | null | undefined; // eslint-disable-line @typescript-eslint/no-explicit-any

const EVENT_METHOD: Record<TerminalEvent, string> = {
  data: 'onData', resize: 'onResize', scroll: 'onScroll', selection: 'onSelectionChange', bell: 'onBell',
};

const handles = new WeakMap<object, TerminalHandle>();

function build(term: Xterm): TerminalHandle {
  const core = (): Record<string, any> | undefined => term?._core; // eslint-disable-line @typescript-eslint/no-explicit-any
  return {
    attach: (host) => { term!.open(host); },
    write: (data, done) => { term!.write(data, done); },
    resize: (cols, rows) => { term!.resize(cols, rows); },
    dispose: () => { term!.dispose(); },
    on: (event, fn) => term![EVENT_METHOD[event]](fn),
    cellSize: () => core()?._renderService?.dimensions?.css?.cell,
    scrollBarWidth: () => { const c = term!._core; return c.viewport ? c.viewport.scrollBarWidth : 0; },
    mouseEventsActive: () => !!(core()?.coreMouseService?.areMouseEventsActive),
    mouseService: () => core()?._mouseService,
    syncInputTextarea: () => { const c = core(); if (c && typeof c._syncTextArea === 'function') c._syncTextArea(); },
    clearRenderer: () => { const r = core()?._renderService; if (r && typeof r.clear === 'function') r.clear(); },
    quiesceViewport: () => {
      const v = core()?.viewport;
      if (v) { v.syncScrollArea = () => {}; v._innerRefresh = () => {}; }
    },
  };
}

export function wrap(term: unknown): TerminalHandle {
  if (term === null || term === undefined || typeof term !== 'object') return build(null);
  let h = handles.get(term);
  if (!h) { h = build(term as Xterm); handles.set(term, h); }
  return h;
}

export const TerminalProvider = { wrap };
