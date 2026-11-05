
const FLAG_PREFIX = 'ps-';

const FLAG_ANCHORS = {
  'terminal-active': ['body'],
  'terminal-empty-active': ['body'],
  'drawer-open': ['body'],
  'grid-surface': ['body', '#terminal-grid'],
  'grid-focus': ['#terminal-grid'],
  'browser-screen': ['body'],
  'phone-tabs': ['body'],
  'page-back': ['body'],
  topbar: ['html'],
} as const satisfies Record<string, readonly string[]>;

export type PageFlag = keyof typeof FLAG_ANCHORS;

const claims = new Map<PageFlag, number>();

type FlagWriter = 'claim' | 'set' | 'observe';

const writers = new Map<PageFlag, FlagWriter>();

function ownFlag(flag: PageFlag, writer: FlagWriter): void {
  const owner = writers.get(flag);
  if (owner !== undefined && owner !== writer) {
    throw new Error(`page flag "${flag}" is written by ${owner} and now by ${writer}; use one`);
  }
  writers.set(flag, writer);
}

function anchorElement(key: string): Element | null {
  if (key === 'body') return document.body;
  if (key === 'html') return document.documentElement;
  return document.querySelector(key);
}

function paint(flag: PageFlag, on: boolean): void {
  for (const key of FLAG_ANCHORS[flag]) {
    anchorElement(key)?.classList.toggle(FLAG_PREFIX + flag, on);
  }
}

export function setFlag(flag: PageFlag, on: boolean): void {
  ownFlag(flag, 'set');
  paint(flag, on);
}

export function raiseFlag(flag: PageFlag): () => void {
  ownFlag(flag, 'claim');
  claims.set(flag, (claims.get(flag) ?? 0) + 1);
  paint(flag, true);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const left = (claims.get(flag) ?? 1) - 1;
    claims.set(flag, left);
    if (left <= 0) paint(flag, false);
  };
}

const TERMINAL_SCREEN_ID = 'terminal-screen';

export function installScreenFlags(): (() => void) | null {
  const screen = document.getElementById(TERMINAL_SCREEN_ID);
  if (!screen) return null;
  ownFlag('terminal-active', 'observe');
  ownFlag('terminal-empty-active', 'observe');
  const sync = (): void => {
    const active = screen.classList.contains('active');
    paint('terminal-active', active);
    paint('terminal-empty-active', active && screen.classList.contains('terminal-screen--empty'));
  };
  const observer = new MutationObserver(sync);
  observer.observe(screen, { attributes: true, attributeFilter: ['class'] });
  sync();
  return () => observer.disconnect();
}
